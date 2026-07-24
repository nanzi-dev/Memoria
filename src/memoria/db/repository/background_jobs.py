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
# 持久化后台任务
# =========================
def _background_job_time(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decode_background_job(row) -> dict | None:
    job = _row_to_dict(row)
    if job is None:
        return None
    try:
        job["payload"] = json.loads(job["payload"])
    except (TypeError, ValueError):
        job["payload"] = {}
    return job


def _lock_background_job_write(conn) -> None:
    if isinstance(conn, sqlite3.Connection):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")


def _enqueue_background_job_in_transaction(
    conn,
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    available_at: datetime | str | None = None,
    now: datetime | str | None = None,
) -> dict:
    if not job_type or not dedupe_key:
        raise ValueError("job_type and dedupe_key are required")
    if not isinstance(payload, dict):
        raise TypeError("background job payload must be a dict")

    queued_at = _background_job_time(now)
    now_iso = queued_at.isoformat()
    available_at_iso = _background_job_time(available_at or queued_at).isoformat()
    job_id = f"job_{uuid.uuid4().hex}"
    encoded_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    _lock_background_job_write(conn)
    conn.execute(
        """
        INSERT INTO background_job (
            job_id, job_type, dedupe_key, payload, status, attempts,
            available_at, lease_owner, lease_expires_at, last_error,
            created_at, updated_at, completed_at
        )
        VALUES (?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?, NULL)
        ON CONFLICT(dedupe_key) DO NOTHING
        """,
        (
            job_id,
            job_type,
            dedupe_key,
            encoded_payload,
            available_at_iso,
            now_iso,
            now_iso,
        ),
    )
    row = conn.execute(
        "SELECT * FROM background_job WHERE dedupe_key = ?",
        (dedupe_key,),
    ).fetchone()
    if row["job_type"] != job_type:
        raise ValueError("dedupe_key is already used by another job type")
    return _decode_background_job(row)


def enqueue_background_job(
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    available_at: datetime | str | None = None,
) -> dict:
    """Persist one immutable job payload, deduplicated by caller-provided key."""
    now = _background_job_time()
    with get_conn() as conn:
        return _enqueue_background_job_in_transaction(
            conn,
            job_type=job_type,
            dedupe_key=dedupe_key,
            payload=payload,
            available_at=available_at,
            now=now,
        )


def get_background_job(job_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _decode_background_job(row)


def claim_background_job(
    *,
    lease_owner: str,
    lease_seconds: int = 60,
    now: datetime | str | None = None,
) -> dict | None:
    """Atomically claim one due or expired job and increment its attempt count."""
    if not lease_owner:
        raise ValueError("lease_owner is required")
    claimed_at = _background_job_time(now)
    claimed_at_iso = claimed_at.isoformat()
    lease_expires_at = (
        claimed_at + timedelta(seconds=max(1, int(lease_seconds)))
    ).isoformat()

    with get_conn() as conn:
        _lock_background_job_write(conn)
        select_sql = """
            SELECT *
            FROM background_job
            WHERE (
                status IN ('pending', 'retry')
                AND available_at <= ?
            ) OR (
                status = 'running'
                AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            )
            ORDER BY available_at ASC, created_at ASC, job_id ASC
            LIMIT 1
        """
        if _is_postgres_enabled():
            select_sql = _append_postgres_clause(
                select_sql,
                "FOR UPDATE SKIP LOCKED",
            )
        candidate = conn.execute(
            select_sql,
            (claimed_at_iso, claimed_at_iso),
        ).fetchone()
        if candidate is None:
            return None

        updated = conn.execute(
            """
            UPDATE background_job
            SET status = 'running',
                attempts = attempts + 1,
                lease_owner = ?,
                lease_expires_at = ?,
                last_error = NULL,
                updated_at = ?,
                completed_at = NULL
            WHERE job_id = ?
              AND (
                    (
                        status IN ('pending', 'retry')
                        AND available_at <= ?
                    ) OR (
                        status = 'running'
                        AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                    )
              )
            """,
            (
                lease_owner,
                lease_expires_at,
                claimed_at_iso,
                candidate["job_id"],
                claimed_at_iso,
                claimed_at_iso,
            ),
        )
        if updated.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (candidate["job_id"],),
        ).fetchone()
        return _decode_background_job(row)


def complete_background_job(
    job_id: str,
    *,
    lease_owner: str,
    now: datetime | str | None = None,
) -> bool:
    """Complete a job only while the caller still owns its active lease."""
    completed_at = _background_job_time(now).isoformat()
    with get_conn() as conn:
        updated = conn.execute(
            """
            UPDATE background_job
            SET status = 'completed',
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error = NULL,
                updated_at = ?,
                completed_at = ?
            WHERE job_id = ?
              AND status = 'running'
              AND lease_owner = ?
              AND lease_expires_at > ?
            """,
            (
                completed_at,
                completed_at,
                job_id,
                lease_owner,
                completed_at,
            ),
        )
        return updated.rowcount == 1


def record_background_job_failure(
    job_id: str,
    *,
    lease_owner: str,
    error: str,
    max_attempts: int,
    retry_delay_seconds: float = 0,
    now: datetime | str | None = None,
) -> dict | None:
    """Release a failed attempt for retry, or mark it terminal at the limit."""
    failed_at = _background_job_time(now)
    failed_at_iso = failed_at.isoformat()
    max_attempts = max(1, int(max_attempts))
    retry_at = (
        failed_at + timedelta(seconds=max(0.0, float(retry_delay_seconds)))
    ).isoformat()

    with get_conn() as conn:
        _lock_background_job_write(conn)
        if _is_postgres_enabled():
            row = conn.execute(
                """
                SELECT * FROM background_job
                WHERE job_id = ?
                FOR UPDATE
                """,
                (job_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM background_job WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if (
            row is None
            or row["status"] != "running"
            or row["lease_owner"] != lease_owner
            or not row["lease_expires_at"]
            or row["lease_expires_at"] <= failed_at_iso
        ):
            return None

        terminal = int(row["attempts"]) >= max_attempts
        status = "failed" if terminal else "retry"
        available_at = row["available_at"] if terminal else retry_at
        completed_at = failed_at_iso if terminal else None
        conn.execute(
            """
            UPDATE background_job
            SET status = ?,
                available_at = ?,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error = ?,
                updated_at = ?,
                completed_at = ?
            WHERE job_id = ? AND status = 'running' AND lease_owner = ?
            """,
            (
                status,
                available_at,
                str(error)[:4000],
                failed_at_iso,
                completed_at,
                job_id,
                lease_owner,
            ),
        )
        updated = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _decode_background_job(updated)


