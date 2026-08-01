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

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError as _IntegrityError

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
from memoria.db.repository._common import _lock_sqlite_write, db_session

# Ensure private helpers from _common are visible as bare names.
for _name, _value in vars(_common_mod).items():
    if _name.startswith('__'):
        continue
    globals().setdefault(_name, _value)
del _name, _value, _common_mod

# =========================
# 权威领域事件账本
# =========================
class DomainEventConcurrencyError(RuntimeError):
    """聚合版本与调用方预期不一致。"""


class DomainEventIdempotencyConflictError(DomainEventConcurrencyError):
    """同一 event_id 被用于不同的不可变事件内容。"""


class UnsupportedDomainEventVersionError(ValueError):
    """投影器无法安全处理事件的主版本。"""


FACT_CLAIM_PROJECTOR = "fact_claim.v1"
STORY_STATE_PROJECTOR = "story_state.v1"


_DOMAIN_EVENT_IMMUTABLE_FIELDS = (
    "owner_user_id",
    "aggregate_type",
    "aggregate_id",
    "event_type",
    "payload",
    "metadata",
    "correlation_id",
    "causation_id",
    "session_id",
    "group_thread_id",
    "source_turn_id",
    "source_message_id",
    "world_occurred_at",
)


def _domain_event_from_row(row) -> StoredDomainEvent | None:
    if row is None:
        return None
    values = dict(row)
    values["payload"] = json.loads(values["payload"])
    values["metadata"] = json.loads(values["metadata"])
    return StoredDomainEvent(**values)


def _get_domain_event_by_id_in_transaction(
    conn,
    event_id: str,
) -> StoredDomainEvent | None:
    row = conn.execute(
        text("""
        SELECT *
        FROM domain_event
        WHERE event_id = :event_id
        """),
        {"event_id": event_id},
    ).mappings().fetchone()
    return _domain_event_from_row(row)


def _get_domain_event_in_transaction(
    conn,
    event_id: str,
    owner_user_id: str,
) -> StoredDomainEvent | None:
    row = conn.execute(
        text("""
        SELECT *
        FROM domain_event
        WHERE event_id = :event_id AND owner_user_id = :owner_user_id
        """),
        {"event_id": event_id, "owner_user_id": owner_user_id},
    ).mappings().fetchone()
    return _domain_event_from_row(row)


def _canonical_domain_event_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_domain_event_retry(
    event: NewDomainEvent,
    existing: StoredDomainEvent,
) -> StoredDomainEvent:
    submitted = event.model_dump()
    stored = existing.model_dump()
    mismatched_fields = []
    for field_name in _DOMAIN_EVENT_IMMUTABLE_FIELDS:
        submitted_value = submitted[field_name]
        stored_value = stored[field_name]
        if field_name in {"payload", "metadata"}:
            matches = (
                _canonical_domain_event_json(submitted_value)
                == _canonical_domain_event_json(stored_value)
            )
        else:
            matches = submitted_value == stored_value
        if not matches:
            mismatched_fields.append(field_name)
    if mismatched_fields:
        raise DomainEventIdempotencyConflictError(
            "domain event idempotency conflict for "
            f"event_id {event.event_id!r}: immutable fields differ: "
            + ", ".join(mismatched_fields)
        )
    return existing


def _current_domain_event_version(
    conn,
    aggregate_key: tuple[str, str, str],
) -> int:
    row = conn.execute(
        text("""
        SELECT COALESCE(MAX(aggregate_version), 0) AS aggregate_version
        FROM domain_event
        WHERE owner_user_id = :owner_user_id
          AND aggregate_type = :aggregate_type
          AND aggregate_id = :aggregate_id
        """),
        {
            "owner_user_id": aggregate_key[0],
            "aggregate_type": aggregate_key[1],
            "aggregate_id": aggregate_key[2],
        },
    ).mappings().fetchone()
    return int(row["aggregate_version"] or 0)


def _is_unique_constraint_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    if isinstance(getattr(exc, "orig", None), sqlite3.IntegrityError):
        return True
    if isinstance(exc, _IntegrityError):
        return True
    return getattr(exc, "sqlstate", None) == "23505"


def _append_domain_events_in_transaction(
    conn,
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
) -> list[StoredDomainEvent]:
    expected_versions = expected_versions or {}
    current_versions: dict[tuple[str, str, str], int] = {}
    stored_events: list[StoredDomainEvent] = []

    for event_index, event in enumerate(events):
        existing = _get_domain_event_by_id_in_transaction(
            conn,
            event.event_id,
        )
        if existing is not None:
            stored_events.append(
                _validate_domain_event_retry(event, existing)
            )
            continue

        aggregate_key = (
            event.owner_user_id,
            event.aggregate_type,
            event.aggregate_id,
        )
        if aggregate_key not in current_versions:
            current_version = _current_domain_event_version(
                conn,
                aggregate_key,
            )
            expected_version = expected_versions.get(aggregate_key)
            if (
                expected_version is not None
                and current_version != expected_version
            ):
                raise DomainEventConcurrencyError(
                    "domain event aggregate version conflict: "
                    f"expected {expected_version}, found {current_version}"
                )
            current_versions[aggregate_key] = current_version

        aggregate_version = current_versions[aggregate_key] + 1
        recorded_at = _now()
        values = event.model_dump()
        insert_sql = """
            INSERT INTO domain_event (
                event_id,
                owner_user_id,
                aggregate_type,
                aggregate_id,
                aggregate_version,
                event_type,
                payload,
                metadata,
                correlation_id,
                causation_id,
                session_id,
                group_thread_id,
                source_turn_id,
                source_message_id,
                world_occurred_at,
                recorded_at
            )
            VALUES (:event_id, :owner_user_id, :aggregate_type, :aggregate_id,
                    :aggregate_version, :event_type, :payload, :metadata,
                    :correlation_id, :causation_id, :session_id,
                    :group_thread_id, :source_turn_id, :source_message_id,
                    :world_occurred_at, :recorded_at)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING sequence"
        savepoint_name = f"domain_event_append_{event_index}"
        use_savepoint = _is_postgres_enabled()
        if use_savepoint:
            conn.execute(text(f"SAVEPOINT {savepoint_name}"))
        try:
            cursor = conn.execute(
                text(insert_sql),
                {
                    "event_id": values["event_id"],
                    "owner_user_id": values["owner_user_id"],
                    "aggregate_type": values["aggregate_type"],
                    "aggregate_id": values["aggregate_id"],
                    "aggregate_version": aggregate_version,
                    "event_type": values["event_type"],
                    "payload": json.dumps(
                        values["payload"],
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    "metadata": json.dumps(
                        values["metadata"],
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    "correlation_id": values["correlation_id"],
                    "causation_id": values["causation_id"],
                    "session_id": values["session_id"],
                    "group_thread_id": values["group_thread_id"],
                    "source_turn_id": values["source_turn_id"],
                    "source_message_id": values["source_message_id"],
                    "world_occurred_at": values["world_occurred_at"],
                    "recorded_at": recorded_at,
                },
            )
            if _is_postgres_enabled():
                sequence = cursor.mappings().fetchone()["sequence"]
            else:
                sequence = cursor.lastrowid
        except Exception as exc:
            if use_savepoint:
                conn.execute(text(f"ROLLBACK TO SAVEPOINT {savepoint_name}"))
                conn.execute(text(f"RELEASE SAVEPOINT {savepoint_name}"))
            existing = _get_domain_event_by_id_in_transaction(
                conn,
                event.event_id,
            )
            if existing is not None:
                recovered = _validate_domain_event_retry(
                    event,
                    existing,
                )
                stored_events.append(recovered)
                current_versions[aggregate_key] = max(
                    current_versions[aggregate_key],
                    recovered.aggregate_version,
                )
                continue
            if _is_unique_constraint_error(exc):
                raise DomainEventConcurrencyError(
                    "domain event aggregate version conflict"
                ) from exc
            raise
        if use_savepoint:
            conn.execute(text(f"RELEASE SAVEPOINT {savepoint_name}"))
        stored = StoredDomainEvent(
            **values,
            sequence=sequence,
            aggregate_version=aggregate_version,
            recorded_at=recorded_at,
        )
        stored_events.append(stored)
        current_versions[aggregate_key] = aggregate_version

    return stored_events


def _append_domain_event_batch(
    conn,
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
) -> list[StoredDomainEvent]:
    if not events:
        return []

    _lock_sqlite_write(conn)

    savepoint_name = "domain_event_append_batch"
    conn.execute(text(f"SAVEPOINT {savepoint_name}"))
    try:
        stored_events = _append_domain_events_in_transaction(
            conn,
            events,
            expected_versions=expected_versions,
        )
    except Exception:
        conn.execute(text(f"ROLLBACK TO SAVEPOINT {savepoint_name}"))
        conn.execute(text(f"RELEASE SAVEPOINT {savepoint_name}"))
        raise
    conn.execute(text(f"RELEASE SAVEPOINT {savepoint_name}"))
    return stored_events


def append_domain_events(
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
    conn=None,
) -> list[StoredDomainEvent]:
    """原子追加一批领域事件；已有事务可通过 conn 复用。"""
    if conn is not None:
        return _append_domain_event_batch(
            conn,
            events,
            expected_versions=expected_versions,
        )
    with db_session() as session:
        return _append_domain_event_batch(
            session,
            events,
            expected_versions=expected_versions,
        )


def append_domain_event(
    event: NewDomainEvent,
    *,
    expected_version: int | None = None,
    conn=None,
) -> StoredDomainEvent:
    """追加单个领域事件。"""
    aggregate_key = (
        event.owner_user_id,
        event.aggregate_type,
        event.aggregate_id,
    )
    expected_versions = (
        {aggregate_key: expected_version}
        if expected_version is not None
        else None
    )
    return append_domain_events(
        [event],
        expected_versions=expected_versions,
        conn=conn,
    )[0]


def get_domain_event(
    event_id: str,
    *,
    owner_user_id: str,
) -> StoredDomainEvent | None:
    """在租户边界内按全局 event_id 获取事件。"""
    with db_session() as session:
        return _get_domain_event_in_transaction(
            session,
            event_id,
            owner_user_id,
        )


def list_domain_events(
    owner_user_id: str,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    *,
    after_sequence: int = 0,
    limit: int | None = None,
) -> list[StoredDomainEvent]:
    """按全局序列读取租户领域事件。"""
    if limit is not None and (
        isinstance(limit, bool)
        or limit < 0
    ):
        raise ValueError("limit must be a non-negative integer")

    clauses = ["owner_user_id = :owner_user_id", "sequence > :after_sequence"]
    params: dict[str, Any] = {
        "owner_user_id": owner_user_id,
        "after_sequence": after_sequence,
    }
    if aggregate_type is not None:
        clauses.append("aggregate_type = :aggregate_type")
        params["aggregate_type"] = aggregate_type
    if aggregate_id is not None:
        clauses.append("aggregate_id = :aggregate_id")
        params["aggregate_id"] = aggregate_id
    sql = (
        "SELECT * FROM domain_event WHERE "
        + " AND ".join(clauses)
        + " ORDER BY sequence ASC"
    )
    if limit is not None:
        sql += " LIMIT :limit"
        params["limit"] = limit
    with db_session() as session:
        rows = session.execute(text(sql), params).mappings().fetchall()
    return [_domain_event_from_row(row) for row in rows]

