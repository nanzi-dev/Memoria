"""Domain repository functions (split from monolith)."""
from __future__ import annotations

from typing import Callable

from sqlalchemy import select, text

from memoria.db.models import EventScheduleState, PlayerWorldClock
from memoria.db.repository._common import _row_to_dict, db_session

# =========================
# player world clock
# =========================
def get_or_create_player_world_clock(
    player_id: str,
    timezone_name: str,
    real_now_iso: str,
) -> dict:
    """Return a player's clock row, creating a real-time 1x clock if absent."""
    with db_session() as session:
        session.execute(
            text("""
                INSERT INTO player_world_clock
                (player_id, timezone, timezone_mode, anchor_real_utc, anchor_world_utc,
                 time_scale, clock_revision, updated_at)
                VALUES (:pid, :tz, 'fixed', :anchor_r, :anchor_w, 1, 1, :now)
                ON CONFLICT(player_id) DO NOTHING
            """),
            {
                "pid": player_id,
                "tz": timezone_name,
                "anchor_r": real_now_iso,
                "anchor_w": real_now_iso,
                "now": real_now_iso,
            },
        )
        row = session.execute(
            select(PlayerWorldClock).where(PlayerWorldClock.player_id == player_id)
        ).scalar_one()
    return _row_to_dict(row)


def get_player_world_clock(player_id: str) -> dict | None:
    with db_session() as session:
        row = session.execute(
            select(PlayerWorldClock).where(PlayerWorldClock.player_id == player_id)
        ).scalar_one_or_none()
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
    with db_session() as session:
        result = session.execute(
            text("""
                UPDATE player_world_clock
                SET timezone = :tz, timezone_mode = :tz_mode, anchor_real_utc = :anchor_r,
                    anchor_world_utc = :anchor_w, time_scale = :scale,
                    clock_revision = clock_revision + 1, updated_at = :updated_at
                WHERE player_id = :pid AND clock_revision = :rev
            """),
            {
                "tz": timezone_name,
                "tz_mode": timezone_mode,
                "anchor_r": anchor_real_utc,
                "anchor_w": anchor_world_utc,
                "scale": time_scale,
                "updated_at": updated_at,
                "pid": player_id,
                "rev": expected_revision,
            },
        )
        if result.rowcount != 1:
            raise ClockRevisionConflictError("world clock revision is stale")

        schedules = session.execute(
            text("""
                SELECT * FROM event_schedule_state
                WHERE player_id = :pid AND status = 'active'
                  AND next_run_at IS NOT NULL
            """),
            {"pid": player_id},
        ).mappings().all()
        for schedule in schedules:
            schedule = dict(schedule)
            lease_expires_at = schedule.get("lease_expires_at")
            if lease_expires_at and lease_expires_at > updated_at:
                raise ClockScheduleBusyError("a scheduled event is currently executing")
            next_run_at, next_due_real_at = resolve_schedule(schedule)
            session.execute(
                text("""
                    UPDATE event_schedule_state
                    SET next_run_at = :next_run, next_due_real_at = :next_due,
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = :updated_at
                    WHERE event_id = :eid AND character_id = :cid AND player_id = :pid
                """),
                {
                    "next_run": next_run_at,
                    "next_due": next_due_real_at,
                    "updated_at": updated_at,
                    "eid": schedule["event_id"],
                    "cid": schedule["character_id"],
                    "pid": player_id,
                },
            )

        row = session.execute(
            select(PlayerWorldClock).where(PlayerWorldClock.player_id == player_id)
        ).scalar_one()
    return _row_to_dict(row)
