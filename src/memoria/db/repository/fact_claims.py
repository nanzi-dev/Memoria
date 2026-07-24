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
# fact claim projection
# =========================
class FactClaimConcurrencyError(RuntimeError):
    """Fact claim projection version or status changed concurrently."""


def _decode_fact_claim_row(row) -> dict | None:
    if row is None:
        return None
    claim = dict(row)
    for field_name, default in (
        ("provenance", {}),
        ("source_ids", []),
    ):
        raw_value = claim.get(field_name)
        if isinstance(raw_value, str):
            try:
                claim[field_name] = json.loads(raw_value)
            except (TypeError, ValueError):
                claim[field_name] = default
        elif raw_value is None:
            claim[field_name] = default
    return claim


def _get_fact_claim_in_transaction(
    conn,
    owner_user_id: str,
    claim_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM fact_claim
        WHERE owner_user_id = ? AND claim_id = ?
        """,
        (owner_user_id, claim_id),
    ).fetchone()
    return _decode_fact_claim_row(row)


def _begin_fact_claim_write(conn) -> None:
    if isinstance(conn, sqlite3.Connection) and not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _lock_fact_claim_for_write(conn, claim_id: str) -> None:
    if _is_postgres_enabled():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (claim_id,),
        )


def _fact_claim_event_id(event_type: str, *identity_parts: str) -> str:
    identity = "\0".join((event_type, *identity_parts))
    return uuid.uuid5(uuid.NAMESPACE_URL, identity).hex


def _new_fact_claim_event(
    *,
    owner_user_id: str,
    claim_id: str,
    event_type: str,
    payload: dict[str, Any],
    identity_parts: tuple[str, ...] = (),
    event_context: dict[str, Any] | None = None,
) -> NewDomainEvent:
    event_context = event_context or {}
    return NewDomainEvent(
        event_id=_fact_claim_event_id(
            event_type,
            owner_user_id,
            claim_id,
            *identity_parts,
        ),
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=claim_id,
        event_type=event_type,
        payload=payload,
        metadata={
            "producer": "memoria.core.fact_claims",
            **dict(event_context.get("metadata") or {}),
        },
        correlation_id=event_context.get("correlation_id"),
        causation_id=event_context.get("causation_id"),
        session_id=event_context.get("session_id"),
        group_thread_id=event_context.get("group_thread_id"),
        source_turn_id=event_context.get("source_turn_id"),
        source_message_id=event_context.get("source_message_id"),
        world_occurred_at=event_context.get("world_occurred_at"),
    )


def _canonical_fact_claim_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fact_claim_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_evidence_entry({
        "source_kind": payload["source_kind"],
        "source_ids": payload["source_ids"],
        "direct_support": payload["direct_support"],
        "details": dict(payload.get("provenance") or {}),
    })


def _guard_fact_claim_update(cursor, message: str) -> None:
    if cursor.rowcount != 1:
        raise FactClaimConcurrencyError(message)


def _insert_fact_claim_from_event(
    conn,
    event: StoredDomainEvent,
    payload: dict[str, Any],
) -> dict:
    evidence = _fact_claim_evidence(payload)
    encoded_provenance = json.dumps(
        {"evidence": [evidence]},
        ensure_ascii=False,
        allow_nan=False,
    )
    encoded_source_ids = json.dumps(
        evidence["source_ids"],
        ensure_ascii=False,
        allow_nan=False,
    )
    cursor = conn.execute(
        """
        INSERT INTO fact_claim (
            claim_id,
            owner_user_id,
            scope_type,
            scope_id,
            fact_text,
            normalized_fact_text,
            content_hash,
            normalized_content_hash,
            status,
            source_kind,
            provenance,
            source_ids,
            supersedes_claim_id,
            superseded_by_claim_id,
            ledger_version,
            created_at,
            updated_at,
            verified_at,
            retracted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, NULL)
        ON CONFLICT DO NOTHING
        """,
        (
            payload["claim_id"],
            payload["owner_user_id"],
            payload["scope_type"],
            payload["scope_id"],
            payload["fact_text"],
            payload["normalized_fact_text"],
            payload["content_hash"],
            payload["normalized_content_hash"],
            payload["source_kind"],
            encoded_provenance,
            encoded_source_ids,
            event.aggregate_version,
            event.recorded_at,
            event.recorded_at,
        ),
    )
    if cursor.rowcount == 1:
        return _get_fact_claim_in_transaction(
            conn,
            event.owner_user_id,
            event.aggregate_id,
        )
    concurrent = _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if (
        concurrent is not None
        and concurrent["ledger_version"] >= event.aggregate_version
    ):
        return concurrent
    raise FactClaimConcurrencyError(
        "fact claim initial projection conflict"
    )


def _validate_fact_claim_event(event: StoredDomainEvent) -> dict[str, Any]:
    if not isinstance(event, StoredDomainEvent):
        raise TypeError("fact claim projector requires StoredDomainEvent")
    if event.aggregate_type != "fact_claim":
        raise ValueError("fact claim projector received another aggregate type")
    payload = event.model_dump()["payload"]
    if payload.get("claim_id") != event.aggregate_id:
        raise ValueError("fact claim event payload identity mismatch")
    if payload.get("owner_user_id", event.owner_user_id) != event.owner_user_id:
        raise ValueError("fact claim event tenant identity mismatch")
    if event.event_type == "fact.claimed.v1":
        source_kind = payload.get("source_kind")
        if source_kind not in (
            CLAIM_SOURCE_KINDS | {ADMIN_VERIFICATION_SOURCE_KIND}
        ):
            raise ValueError(
                f"unsupported fact claim source_kind: {source_kind}"
            )
        clean_source_ids(payload.get("source_ids"))
        if not isinstance(payload.get("direct_support"), bool):
            raise ValueError("direct_support must be a boolean")
        if type(payload.get("provenance", {})) is not dict:
            raise ValueError("fact claim provenance must be an object")
        expected_identity = derive_fact_claim_identity(
            event.owner_user_id,
            payload["scope_type"],
            payload["scope_id"],
            payload["fact_text"],
        )
        for field_name in (
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
            "claim_id",
        ):
            if payload[field_name] != expected_identity[field_name]:
                raise ValueError(
                    f"fact claim {field_name} identity mismatch"
                )
    return payload


def _project_fact_claim_event_in_transaction(
    conn,
    event: StoredDomainEvent,
) -> dict:
    payload = _validate_fact_claim_event(event)
    claim = _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if claim is not None and event.aggregate_version <= claim["ledger_version"]:
        return claim
    if claim is None:
        if (
            event.event_type != "fact.claimed.v1"
            or event.aggregate_version != 1
        ):
            raise FactClaimConcurrencyError(
                "fact claim projection version gap before initial event"
            )
        if payload["source_kind"] == ADMIN_VERIFICATION_SOURCE_KIND:
            raise ValueError(
                "admin verification requires an existing fact claim"
            )
        return _insert_fact_claim_from_event(conn, event, payload)
    if event.aggregate_version != claim["ledger_version"] + 1:
        raise FactClaimConcurrencyError(
            "fact claim projection version conflict: "
            f"expected {claim['ledger_version'] + 1}, "
            f"found {event.aggregate_version}"
        )

    if event.event_type == "fact.claimed.v1":
        if claim["status"] in {"retracted", "superseded"}:
            raise FactClaimConcurrencyError(
                "fact claim terminal status rejects evidence"
            )
        identity_fields = (
            "owner_user_id",
            "claim_id",
            "scope_type",
            "scope_id",
            "fact_text",
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
        )
        if any(
            payload[field_name] != claim[field_name]
            for field_name in identity_fields
        ):
            raise ValueError("fact claim evidence identity mismatch")
        evidence_entries = list(
            (claim.get("provenance") or {}).get("evidence") or []
        )
        evidence = _fact_claim_evidence(payload)
        if evidence not in evidence_entries:
            evidence_entries.append(evidence)
        source_ids = sorted({
            source_id
            for item in evidence_entries
            for source_id in item.get("source_ids") or []
        })
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET provenance = ?,
                source_ids = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
            """,
            (
                json.dumps(
                    {"evidence": evidence_entries},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                json.dumps(
                    source_ids,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim evidence projection changed concurrently",
        )
    elif event.event_type == "fact.verified.v1":
        if claim["status"] != "candidate":
            raise FactClaimConcurrencyError(
                "fact claim verification status changed concurrently"
            )
        raw_snapshot = payload["verification_snapshot"]
        if not isinstance(raw_snapshot, dict):
            raise ValueError(
                "fact claim verification_snapshot must be an object"
            )
        snapshot = dict(raw_snapshot)
        evidence_entries = [
            normalize_evidence_entry(item)
            for item in snapshot.get("evidence") or []
        ]
        current_evidence = [
            normalize_evidence_entry(item)
            for item in (
                (claim.get("provenance") or {}).get("evidence") or []
            )
        ]
        if (
            _canonical_fact_claim_json(evidence_entries)
            != _canonical_fact_claim_json(current_evidence)
        ):
            raise ValueError(
                "fact claim verification evidence does not match claimed events"
            )
        decision = evaluate_verification(
            claim["normalized_fact_text"],
            evidence_entries,
        )
        for field_name, expected_value in decision.items():
            if field_name == "source_ids":
                continue
            if (
                _canonical_fact_claim_json(snapshot.get(field_name))
                != _canonical_fact_claim_json(expected_value)
            ):
                raise ValueError(
                    "fact claim verification decision mismatch: "
                    f"{field_name}"
                )
        if not decision["verified"]:
            raise ValueError(
                "fact claim verification policy is not satisfied"
            )
        source_ids = clean_source_ids(snapshot.get("source_ids"))
        if source_ids != decision["source_ids"]:
            raise ValueError(
                "fact claim verification source_ids do not match evidence"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'verified',
                provenance = ?,
                source_ids = ?,
                ledger_version = ?,
                updated_at = ?,
                verified_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status = 'candidate'
            """,
            (
                json.dumps(
                    {"evidence": evidence_entries},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                json.dumps(
                    source_ids,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim verification projection changed concurrently",
        )
    elif event.event_type == "fact.retracted.v1":
        if claim["status"] not in {"candidate", "verified"}:
            raise FactClaimConcurrencyError(
                "fact claim retraction status changed concurrently"
            )
        if claim["supersedes_claim_id"] is not None:
            raise FactClaimConcurrencyError(
                "fact claim replacement cannot be retracted"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'retracted',
                ledger_version = ?,
                updated_at = ?,
                retracted_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND supersedes_claim_id IS NULL
            """,
            (
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim retraction projection changed concurrently",
        )
    elif event.event_type == "fact.superseded.v1":
        if claim["status"] not in {"candidate", "verified"}:
            raise FactClaimConcurrencyError(
                "fact claim supersede status changed concurrently"
            )
        replacement_id = payload["superseded_by_claim_id"]
        replacement = _get_fact_claim_in_transaction(
            conn,
            event.owner_user_id,
            replacement_id,
        )
        if replacement is None:
            raise FactClaimConcurrencyError(
                "fact claim replacement projection is missing"
            )
        if (
            claim["scope_type"] != replacement["scope_type"]
            or claim["scope_id"] != replacement["scope_id"]
        ):
            raise ValueError("superseding claims must share a scope")
        if replacement["status"] in {"retracted", "superseded"}:
            raise FactClaimConcurrencyError(
                "fact claim replacement is terminal"
            )
        if (
            replacement["ledger_version"]
            != payload["replacement_ledger_version"]
        ):
            raise FactClaimConcurrencyError(
                "fact claim replacement version conflict"
            )
        if replacement["supersedes_claim_id"] not in {
            None,
            event.aggregate_id,
        }:
            raise FactClaimConcurrencyError(
                "fact claim replacement already supersedes another claim"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'superseded',
                superseded_by_claim_id = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND superseded_by_claim_id IS NULL
            """,
            (
                replacement_id,
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim supersede projection changed concurrently",
        )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET supersedes_claim_id = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND (
                    supersedes_claim_id IS NULL
                    OR supersedes_claim_id = ?
              )
            """,
            (
                event.aggregate_id,
                event.recorded_at,
                event.owner_user_id,
                replacement_id,
                replacement["ledger_version"],
                event.aggregate_id,
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim replacement projection changed concurrently",
        )
    else:
        raise ValueError(
            f"unsupported fact claim event type: {event.event_type}"
        )
    return _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )


def _project_fact_claim_event(
    event: StoredDomainEvent,
    *,
    conn=None,
) -> dict:
    if conn is not None:
        return _project_fact_claim_event_in_transaction(conn, event)
    with get_conn() as transaction:
        _begin_fact_claim_write(transaction)
        _lock_fact_claim_for_write(transaction, event.aggregate_id)
        return _project_fact_claim_event_in_transaction(transaction, event)


def _domain_event_major_version(event_type: str) -> int:
    match = re.fullmatch(r".+\.v([1-9][0-9]*)", event_type)
    if match is None:
        raise UnsupportedDomainEventVersionError(
            f"domain event type has no supported major version: {event_type}"
        )
    return int(match.group(1))


def _validate_projector_event_version(event: StoredDomainEvent) -> None:
    major_version = _domain_event_major_version(event.event_type)
    if major_version != 1:
        raise UnsupportedDomainEventVersionError(
            f"unsupported domain event {event.event_type}: "
            f"major version {major_version}"
        )


def _get_projection_checkpoint_in_transaction(
    conn,
    projector_name: str,
    owner_user_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT projector_name, owner_user_id, last_sequence, updated_at
        FROM projection_checkpoint
        WHERE projector_name = ? AND owner_user_id = ?
        """,
        (projector_name, owner_user_id),
    ).fetchone()
    if row is None:
        return None
    checkpoint = dict(row)
    checkpoint["last_sequence"] = int(checkpoint["last_sequence"])
    return checkpoint


def get_projection_checkpoint(
    projector_name: str,
    owner_user_id: str,
) -> dict | None:
    """读取租户内单个投影器的全局序列检查点。"""
    projector_name = str(projector_name or "").strip()
    owner_user_id = str(owner_user_id or "").strip()
    if not projector_name or not owner_user_id:
        raise ValueError("projector_name and owner_user_id must not be blank")
    with get_conn() as conn:
        return _get_projection_checkpoint_in_transaction(
            conn,
            projector_name,
            owner_user_id,
        )


def _save_projection_checkpoint_in_transaction(
    conn,
    projector_name: str,
    owner_user_id: str,
    last_sequence: int,
) -> None:
    conn.execute(
        """
        INSERT INTO projection_checkpoint (
            projector_name,
            owner_user_id,
            last_sequence,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(projector_name, owner_user_id)
        DO UPDATE SET
            last_sequence=excluded.last_sequence,
            updated_at=excluded.updated_at
        """,
        (
            projector_name,
            owner_user_id,
            int(last_sequence),
            _now(),
        ),
    )


def rebuild_domain_projections(owner_user_id: str) -> dict:
    """从不可变账本原子重建指定租户的事实与剧情投影。"""
    owner_user_id = str(owner_user_id or "").strip()
    if not owner_user_id:
        raise ValueError("owner_user_id must not be blank")

    projectors = {
        "fact_claim": (
            FACT_CLAIM_PROJECTOR,
            _project_fact_claim_event_in_transaction,
        ),
        "story": (
            STORY_STATE_PROJECTOR,
            _project_story_event_in_transaction,
        ),
    }
    progress = {
        projector_name: {
            "processed_events": 0,
            "last_sequence": 0,
        }
        for projector_name, _project in projectors.values()
    }

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ?",
            (owner_user_id,),
        )
        conn.execute(
            "DELETE FROM story_state WHERE owner_user_id = ?",
            (owner_user_id,),
        )
        conn.execute(
            """
            DELETE FROM projection_checkpoint
            WHERE owner_user_id = ?
              AND projector_name IN (?, ?)
            """,
            (
                owner_user_id,
                FACT_CLAIM_PROJECTOR,
                STORY_STATE_PROJECTOR,
            ),
        )
        rows = conn.execute(
            """
            SELECT *
            FROM domain_event
            WHERE owner_user_id = ?
            ORDER BY sequence ASC
            """,
            (owner_user_id,),
        ).fetchall()

        for row in rows:
            event = _domain_event_from_row(row)
            projector_spec = projectors.get(event.aggregate_type)
            if projector_spec is None:
                continue
            projector_name, projector = projector_spec
            _validate_projector_event_version(event)
            projector(conn, event)
            progress[projector_name]["processed_events"] += 1
            progress[projector_name]["last_sequence"] = event.sequence

        for projector_name, projector_progress in progress.items():
            _save_projection_checkpoint_in_transaction(
                conn,
                projector_name,
                owner_user_id,
                projector_progress["last_sequence"],
            )

    return {
        "owner_user_id": owner_user_id,
        "projectors": progress,
    }


def _record_fact_claim_in_transaction(
    conn,
    *,
    claim_id: str,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
    normalized_fact_text: str,
    content_hash: str,
    normalized_content_hash: str,
    source_kind: str,
    source_ids: list[str],
    provenance: dict[str, Any],
    direct_support: bool,
    verification_policy: Callable[[list[dict[str, Any]]], dict[str, Any]],
    event_context: dict[str, Any] | None = None,
) -> dict:
    _begin_fact_claim_write(conn)
    _lock_fact_claim_for_write(conn, claim_id)
    existing = _get_fact_claim_in_transaction(
        conn,
        owner_user_id,
        claim_id,
    )
    if (
        existing is not None
        and existing["status"] in {"retracted", "superseded"}
    ):
        raise ValueError("terminal fact claim cannot accept evidence")

    identity = existing or {
        "owner_user_id": owner_user_id,
        "claim_id": claim_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "fact_text": fact_text,
        "normalized_fact_text": normalized_fact_text,
        "content_hash": content_hash,
        "normalized_content_hash": normalized_content_hash,
    }
    evidence_payload = {
        "source_kind": source_kind,
        "source_ids": sorted(set(source_ids)),
        "direct_support": bool(direct_support),
        "provenance": provenance,
    }
    claimed_payload = {
        field_name: identity[field_name]
        for field_name in (
            "owner_user_id",
            "claim_id",
            "scope_type",
            "scope_id",
            "fact_text",
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
        )
    }
    claimed_payload.update(evidence_payload)
    evidence_identity = _canonical_fact_claim_json(evidence_payload)
    claimed_event = append_domain_event(
        _new_fact_claim_event(
            owner_user_id=owner_user_id,
            claim_id=claim_id,
            event_type="fact.claimed.v1",
            payload=claimed_payload,
            identity_parts=(evidence_identity,),
            event_context=event_context,
        ),
        expected_version=(
            existing["ledger_version"] if existing is not None else 0
        ),
        conn=conn,
    )
    projected = _project_fact_claim_event_in_transaction(
        conn,
        claimed_event,
    )
    evidence_entries = list(
        (projected.get("provenance") or {}).get("evidence") or []
    )
    decision = verification_policy(evidence_entries)
    if projected["status"] == "candidate" and decision["verified"]:
        snapshot = {
            **decision,
            "evidence": evidence_entries,
            "source_ids": projected["source_ids"],
        }
        verified_event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.verified.v1",
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "reason": "deterministic_policy",
                    "verification_snapshot": snapshot,
                },
                event_context=event_context,
            ),
            expected_version=projected["ledger_version"],
            conn=conn,
        )
        projected = _project_fact_claim_event_in_transaction(
            conn,
            verified_event,
        )
    return projected


def _record_fact_claim(
    *,
    claim_id: str,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
    normalized_fact_text: str,
    content_hash: str,
    normalized_content_hash: str,
    source_kind: str,
    source_ids: list[str],
    provenance: dict[str, Any],
    direct_support: bool,
    verification_policy: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict:
    """Append claim lifecycle events and update the projection atomically."""
    with get_conn() as conn:
        return _record_fact_claim_in_transaction(
            conn,
            claim_id=claim_id,
            owner_user_id=owner_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            fact_text=fact_text,
            normalized_fact_text=normalized_fact_text,
            content_hash=content_hash,
            normalized_content_hash=normalized_content_hash,
            source_kind=source_kind,
            source_ids=source_ids,
            provenance=provenance,
            direct_support=direct_support,
            verification_policy=verification_policy,
        )


def get_fact_claim(
    owner_user_id: str,
    claim_id: str,
) -> dict | None:
    with get_conn() as conn:
        return _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )


def _retract_fact_claim(
    owner_user_id: str,
    claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        _lock_fact_claim_for_write(conn, claim_id)
        claim = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )
        if claim is None:
            raise KeyError(f"fact claim not found: {claim_id}")
        if claim["supersedes_claim_id"] is not None:
            raise ValueError("fact claim replacement cannot be retracted")
        if claim["status"] == "retracted":
            return claim
        if claim["status"] == "superseded":
            raise ValueError("terminal fact claim cannot be retracted")

        event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.retracted.v1",
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "reason": reason,
                },
            ),
            expected_version=claim["ledger_version"],
            conn=conn,
        )
        return _project_fact_claim_event_in_transaction(conn, event)


def _supersede_fact_claim(
    owner_user_id: str,
    claim_id: str,
    superseded_by_claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        for locked_claim_id in sorted((claim_id, superseded_by_claim_id)):
            _lock_fact_claim_for_write(conn, locked_claim_id)
        claim = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )
        replacement = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            superseded_by_claim_id,
        )
        if claim is None or replacement is None:
            raise KeyError("fact claim or replacement not found")
        if claim["scope_type"] != replacement["scope_type"] or (
            claim["scope_id"] != replacement["scope_id"]
        ):
            raise ValueError("superseding claims must share a scope")
        if (
            claim["status"] == "superseded"
            and claim["superseded_by_claim_id"] == superseded_by_claim_id
        ):
            return claim
        if claim["status"] == "superseded":
            raise ValueError("fact claim replacement cannot be changed")
        if claim["status"] == "retracted":
            raise ValueError("terminal fact claim cannot be superseded")
        if replacement["status"] in {"retracted", "superseded"}:
            raise ValueError("replacement fact claim is terminal")

        event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.superseded.v1",
                identity_parts=(superseded_by_claim_id,),
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "superseded_by_claim_id": superseded_by_claim_id,
                    "replacement_ledger_version": (
                        replacement["ledger_version"]
                    ),
                    "reason": reason,
                },
            ),
            expected_version=claim["ledger_version"],
            conn=conn,
        )
        return _project_fact_claim_event_in_transaction(conn, event)


def list_fact_claims(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM fact_claim
            WHERE owner_user_id = ?
              AND scope_type = ?
              AND scope_id = ?
            ORDER BY created_at ASC, claim_id ASC
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchall()
    return [_decode_fact_claim_row(row) for row in rows]


def list_verified_fact_claims(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM fact_claim
            WHERE owner_user_id = ?
              AND scope_type = ?
              AND scope_id = ?
              AND status = 'verified'
            ORDER BY created_at ASC, claim_id ASC
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchall()
    return [_decode_fact_claim_row(row) for row in rows]


LONG_TERM_FACT_BACKFILL_MIGRATION = (
    "2026-07-15-long-term-fact-event-backfill"
)


def has_data_migration(migration_key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM data_migration
            WHERE migration_key = ?
            """,
            (migration_key,),
        ).fetchone()
    return row is not None


def _legacy_long_term_fact_claim_event(row: dict) -> NewDomainEvent:
    legacy_fact_id = int(row["id"])
    owner_user_id = str(row["player_id"]).strip()
    scope_id = str(row["character_id"]).strip()
    fact_text = str(row["fact_text"])
    identity = derive_fact_claim_identity(
        owner_user_id,
        "character",
        scope_id,
        fact_text,
    )
    source_id = f"long_term_fact:{legacy_fact_id}"
    return NewDomainEvent(
        event_id=f"legacy-long-term-fact-{legacy_fact_id}",
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=identity["claim_id"],
        event_type="fact.claimed.v1",
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": identity["claim_id"],
            "scope_type": "character",
            "scope_id": scope_id,
            "fact_text": fact_text,
            "normalized_fact_text": identity["normalized_fact_text"],
            "content_hash": identity["content_hash"],
            "normalized_content_hash": identity["normalized_content_hash"],
            "source_kind": "legacy",
            "source_ids": [source_id],
            "provenance": {
                "legacy_backfill": True,
                "legacy_fact_id": legacy_fact_id,
                "importance": row.get("importance"),
                "created_at": row.get("created_at"),
                "last_referenced": row.get("last_referenced"),
            },
            "direct_support": False,
        },
        metadata={
            "producer": "memoria.db.repository",
            "legacy_backfill": True,
            "legacy_fact_id": legacy_fact_id,
        },
    )


def backfill_legacy_long_term_fact_events() -> dict:
    """Backfill legacy facts into candidate claim events without deleting sources."""
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        existing = conn.execute(
            """
            SELECT metadata, applied_at
            FROM data_migration
            WHERE migration_key = ?
            """,
            (LONG_TERM_FACT_BACKFILL_MIGRATION,),
        ).fetchone()
        if existing is not None:
            metadata = json.loads(existing["metadata"])
            return {
                **metadata,
                "applied_at": existing["applied_at"],
                "already_applied": True,
            }

        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, character_id, player_id, fact_text, importance,
                       created_at, last_referenced
                FROM long_term_fact
                ORDER BY id ASC
                """
            ).fetchall()
        ]
        for row in rows:
            stored_event = append_domain_event(
                _legacy_long_term_fact_claim_event(row),
                conn=conn,
            )
            _project_fact_claim_event_in_transaction(
                conn,
                stored_event,
            )

        applied_at = _now()
        metadata = {
            "legacy_fact_count": len(rows),
            "event_count": len(rows),
        }
        conn.execute(
            """
            INSERT INTO data_migration (migration_key, metadata, applied_at)
            VALUES (?, ?, ?)
            """,
            (
                LONG_TERM_FACT_BACKFILL_MIGRATION,
                json.dumps(metadata, ensure_ascii=False, allow_nan=False),
                applied_at,
            ),
        )
        return {
            **metadata,
            "applied_at": applied_at,
            "already_applied": False,
        }


