"""Domain repository functions (split from monolith)."""
from __future__ import annotations

# Standard/third-party imports used across repository domains.
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import sqlite3
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit
import re
from difflib import SequenceMatcher

from memoria.core.config import configs
from memoria.core import performance, tracing
from memoria.core.domain_events import NewDomainEvent, StoredDomainEvent
from memoria.core.fact_claim_policy import (
    ADMIN_VERIFICATION_SOURCE_KIND,
    CLAIM_SOURCE_KINDS,
    clean_source_ids,
    derive_fact_claim_identity,
    evaluate_verification,
    normalize_evidence_entry,
    normalize_fact_text,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

logger = logging.getLogger(__name__)

# Import shared helpers / connection / schema. Private names included.
from memoria.db.repository._common import *  # noqa: F403
from memoria.db.repository import _common as _common_mod

# Ensure private helpers from _common are visible as bare names.
for _name, _value in vars(_common_mod).items():
    if _name.startswith('__'):
        continue
    globals().setdefault(_name, _value)
del _name, _value, _common_mod

# =========================
# story state projection
# =========================
class StoryStateTransitionError(ValueError):
    """剧情事件违反聚合状态转换规则。"""


_STORY_EVENT_TYPES = {
    "story.started.v1",
    "story.progressed.v1",
    "story.completed.v1",
    "story.failed.v1",
}
_TERMINAL_STORY_STATUSES = {"completed", "failed"}


def _decode_story_state_row(row) -> dict | None:
    if row is None:
        return None
    state = dict(row)
    state["progress"] = float(state["progress"])
    state["ledger_version"] = int(state["ledger_version"])
    return state


def _get_story_state_in_transaction(
    conn,
    owner_user_id: str,
    story_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM story_state
        WHERE owner_user_id = ? AND story_id = ?
        """,
        (owner_user_id, story_id),
    ).fetchone()
    return _decode_story_state_row(row)


def _clamp_story_progress(value: Any) -> float:
    try:
        progress = float(value)
    except (TypeError, ValueError) as exc:
        raise StoryStateTransitionError(
            "story progress must be numeric"
        ) from exc
    return max(0.0, min(1.0, progress))


def _project_story_event_in_transaction(
    conn,
    event: StoredDomainEvent,
) -> dict:
    if event.aggregate_type != "story":
        raise ValueError("story projector received another aggregate type")
    if event.event_type not in _STORY_EVENT_TYPES:
        raise ValueError(f"unsupported story event type: {event.event_type}")

    state = _get_story_state_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if state is not None and event.aggregate_version == state["ledger_version"]:
        return state

    expected_version = 1 if state is None else state["ledger_version"] + 1
    if event.aggregate_version != expected_version:
        raise DomainEventConcurrencyError(
            "story projection version conflict: "
            f"expected {expected_version}, found {event.aggregate_version}"
        )

    payload = event.model_dump()["payload"]
    if event.event_type == "story.started.v1":
        if state is not None:
            raise StoryStateTransitionError("story has already started")
        progress = _clamp_story_progress(payload.get("progress", 0.0))
        conn.execute(
            """
            INSERT INTO story_state (
                owner_user_id,
                story_id,
                status,
                progress,
                terminal_reason,
                ledger_version,
                started_at,
                updated_at,
                completed_at,
                failed_at
            )
            VALUES (?, ?, 'active', ?, NULL, ?, ?, ?, NULL, NULL)
            """,
            (
                event.owner_user_id,
                event.aggregate_id,
                progress,
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
            ),
        )
    elif event.event_type == "story.progressed.v1":
        if state is None:
            raise StoryStateTransitionError("story must be started before progress")
        if state["status"] in _TERMINAL_STORY_STATUSES:
            raise StoryStateTransitionError(
                "story progress cannot change after terminal state"
            )
        if "progress" in payload:
            progress = _clamp_story_progress(payload["progress"])
        else:
            progress = _clamp_story_progress(
                state["progress"] + float(payload.get("progress_delta", 0.0))
            )
        conn.execute(
            """
            UPDATE story_state
            SET progress = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND story_id = ?
              AND ledger_version = ?
            """,
            (
                progress,
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                state["ledger_version"],
            ),
        )
    else:
        if state is None:
            raise StoryStateTransitionError(
                "story must be started before reaching a terminal state"
            )
        if state["status"] in _TERMINAL_STORY_STATUSES:
            raise StoryStateTransitionError("story is already terminal")
        status = (
            "completed"
            if event.event_type == "story.completed.v1"
            else "failed"
        )
        progress = (
            1.0
            if status == "completed"
            else _clamp_story_progress(payload.get("progress", state["progress"]))
        )
        reason = str(payload.get("reason") or "").strip() or None
        conn.execute(
            """
            UPDATE story_state
            SET status = ?,
                progress = ?,
                terminal_reason = ?,
                ledger_version = ?,
                updated_at = ?,
                completed_at = ?,
                failed_at = ?
            WHERE owner_user_id = ?
              AND story_id = ?
              AND ledger_version = ?
            """,
            (
                status,
                progress,
                reason,
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at if status == "completed" else None,
                event.recorded_at if status == "failed" else None,
                event.owner_user_id,
                event.aggregate_id,
                state["ledger_version"],
            ),
        )

    projected = _get_story_state_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if projected is None or projected["ledger_version"] != event.aggregate_version:
        raise DomainEventConcurrencyError(
            "story projection changed concurrently"
        )
    return projected


def append_story_event(
    owner_user_id: str,
    story_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    session_id: str | None = None,
    group_thread_id: str | None = None,
    source_turn_id: str | None = None,
    source_message_id: int | None = None,
    world_occurred_at: str | None = None,
) -> dict:
    """追加剧情事件并在同一事务内更新规范化剧情状态。"""
    event_values = {
        "owner_user_id": owner_user_id,
        "aggregate_type": "story",
        "aggregate_id": story_id,
        "event_type": event_type,
        "payload": payload or {},
        "metadata": metadata or {},
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "session_id": session_id,
        "group_thread_id": group_thread_id,
        "source_turn_id": source_turn_id,
        "source_message_id": source_message_id,
        "world_occurred_at": world_occurred_at,
    }
    if event_id is not None:
        event_values["event_id"] = event_id
    event = NewDomainEvent(**event_values)
    with get_conn() as conn:
        return _append_and_project_story_event_in_transaction(conn, event)


def _append_and_project_story_event_in_transaction(
    conn,
    event: NewDomainEvent,
) -> dict:
    stored = append_domain_event(event, conn=conn)
    return _project_story_event_in_transaction(conn, stored)


def _event_execution_domain_event_id(
    execution_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
) -> str:
    identity = "\0".join(
        (
            "event_execution",
            execution_id,
            aggregate_type,
            aggregate_id,
            event_type,
        )
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, identity).hex


def _apply_story_update_in_transaction(
    conn,
    owner_user_id: str,
    update: dict[str, Any],
) -> dict:
    story_id = str(update.get("story_id") or "").strip()
    execution_id = str(update.get("execution_id") or "").strip()
    source_event_id = str(update.get("source_event_id") or "").strip()
    if not story_id or not execution_id or not source_event_id:
        raise ValueError("story update requires story_id, execution_id, and source_event_id")

    event_context = {
        "correlation_id": execution_id,
        "causation_id": source_event_id,
        "session_id": update.get("session_id"),
        "world_occurred_at": update.get("world_occurred_at"),
        "metadata": {
            "producer": "memoria.core.event_executor",
            "source_event_id": source_event_id,
            "source_event_name": update.get("source_event_name"),
        },
    }
    state = _get_story_state_in_transaction(conn, owner_user_id, story_id)
    if state is None:
        started = NewDomainEvent(
            event_id=_event_execution_domain_event_id(
                execution_id,
                "story",
                story_id,
                "story.started.v1",
            ),
            owner_user_id=owner_user_id,
            aggregate_type="story",
            aggregate_id=story_id,
            event_type="story.started.v1",
            payload={"progress": 0.0},
            **event_context,
        )
        state = _append_and_project_story_event_in_transaction(conn, started)

    requested_status = update.get("status")
    if requested_status == "completed":
        event_type = "story.completed.v1"
        payload = {
            "reason": f"event:{source_event_id}",
            "progress": 1.0,
        }
    elif requested_status == "failed":
        event_type = "story.failed.v1"
        payload = {
            "reason": f"event:{source_event_id}",
        }
        if update.get("progress") is not None:
            payload["progress"] = update["progress"]
    else:
        has_progress = (
            update.get("progress") is not None
            or update.get("progress_delta") is not None
        )
        if not has_progress and requested_status not in {"active", "pending"}:
            return state
        event_type = "story.progressed.v1"
        payload = {}
        if update.get("progress") is not None:
            payload["progress"] = update["progress"]
        if update.get("progress_delta") is not None:
            payload["progress_delta"] = update["progress_delta"]

    domain_event = NewDomainEvent(
        event_id=_event_execution_domain_event_id(
            execution_id,
            "story",
            story_id,
            event_type,
        ),
        owner_user_id=owner_user_id,
        aggregate_type="story",
        aggregate_id=story_id,
        event_type=event_type,
        payload=payload,
        **event_context,
    )
    return _append_and_project_story_event_in_transaction(conn, domain_event)


def get_story_state(
    owner_user_id: str,
    story_id: str,
) -> dict | None:
    """在租户边界内读取规范化剧情状态。"""
    with get_conn() as conn:
        return _get_story_state_in_transaction(
            conn,
            owner_user_id,
            story_id,
        )


