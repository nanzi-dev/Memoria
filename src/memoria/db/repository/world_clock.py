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
# player world clock
# =========================
def get_or_create_player_world_clock(
    player_id: str,
    timezone_name: str,
    real_now_iso: str,
) -> dict:
    """Return a player's clock row, creating a real-time 1x clock if absent."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO player_world_clock
            (player_id, timezone, timezone_mode, anchor_real_utc, anchor_world_utc,
             time_scale, clock_revision, updated_at)
            VALUES (?, ?, 'fixed', ?, ?, 1, 1, ?)
            ON CONFLICT(player_id) DO NOTHING
            """,
            (player_id, timezone_name, real_now_iso, real_now_iso, real_now_iso),
        )
        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return dict(row)


def get_player_world_clock(player_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return _row_to_dict(row)


class ClockRevisionConflictError(RuntimeError):
    pass


class ClockScheduleBusyError(RuntimeError):
    pass


def update_player_world_clock_and_schedules(
    *,
    player_id: str,
    expected_revision: int,
    timezone_name: str,
    timezone_mode: str,
    anchor_real_utc: str,
    anchor_world_utc: str,
    time_scale: int,
    updated_at: str,
    resolve_schedule: Callable[[dict], tuple[str | None, str | None]],
) -> dict:
    """Atomically update a clock and all active schedules derived from it."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_world_clock
            SET timezone = ?, timezone_mode = ?, anchor_real_utc = ?,
                anchor_world_utc = ?, time_scale = ?,
                clock_revision = clock_revision + 1, updated_at = ?
            WHERE player_id = ? AND clock_revision = ?
            """,
            (
                timezone_name,
                timezone_mode,
                anchor_real_utc,
                anchor_world_utc,
                time_scale,
                updated_at,
                player_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ClockRevisionConflictError("world clock revision is stale")

        schedules = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE player_id = ? AND status = 'active'
              AND next_run_at IS NOT NULL
            """,
            (player_id,),
        ).fetchall()
        for raw_schedule in schedules:
            schedule = dict(raw_schedule)
            lease_expires_at = schedule.get("lease_expires_at")
            if lease_expires_at and lease_expires_at > updated_at:
                raise ClockScheduleBusyError("a scheduled event is currently executing")
            next_run_at, next_due_real_at = resolve_schedule(schedule)
            conn.execute(
                """
                UPDATE event_schedule_state
                SET next_run_at = ?, next_due_real_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (
                    next_run_at,
                    next_due_real_at,
                    updated_at,
                    schedule["event_id"],
                    schedule["character_id"],
                    player_id,
                ),
            )

        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return dict(row)


