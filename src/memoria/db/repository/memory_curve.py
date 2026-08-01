"""Persistence for the memory-curve side projection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from memoria.core import memory_curve as curve
from memoria.db.repository._common import *  # noqa: F403
from memoria.db.repository import _common as _common_mod
from memoria.db.repository._common import _lock_sqlite_write, db_session


for _name, _value in vars(_common_mod).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)
del _name, _value, _common_mod


def _memory_curve_key(
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
) -> tuple[str, str, str, str]:
    values = tuple(
        str(value or "").strip()
        for value in (owner_user_id, character_id, memory_type, memory_id)
    )
    if not all(values):
        raise ValueError("memory curve identity fields must not be blank")
    return values


def _get_memory_curve_state_in_transaction(
    conn,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
) -> dict | None:
    row = conn.execute(
        text("""
        SELECT * FROM memory_curve_state
        WHERE owner_user_id = :owner_user_id AND character_id = :character_id
          AND memory_type = :memory_type AND memory_id = :memory_id
        """),
        {
            "owner_user_id": owner_user_id,
            "character_id": character_id,
            "memory_type": memory_type,
            "memory_id": memory_id,
        },
    ).mappings().fetchone()
    return dict(row) if row else None


def _initialize_memory_curve_state_in_transaction(
    conn,
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
    world_occurred_at: str,
    source_kind: str,
    importance: float,
) -> bool:
    key = _memory_curve_key(
        owner_user_id, character_id, memory_type, memory_id
    )
    now = _now()
    cursor = conn.execute(
        text("""
        INSERT INTO memory_curve_state (
            owner_user_id, character_id, memory_type, memory_id,
            anchor_strength, stability_days, anchor_elapsed_seconds,
            elapsed_decay_seconds, world_time_watermark,
            reinforcement_count, source_kind, importance,
            created_at, updated_at
        ) VALUES (:owner_user_id, :character_id, :memory_type, :memory_id,
                  1.0, :stability_days, 0.0, 0.0, :world_watermark, 0,
                  :source_kind, :importance, :created_at, :updated_at)
        ON CONFLICT(owner_user_id, character_id, memory_type, memory_id)
        DO NOTHING
        """),
        {
            "owner_user_id": key[0],
            "character_id": key[1],
            "memory_type": key[2],
            "memory_id": key[3],
            "stability_days": curve.initial_stability_days(
                importance, source_kind
            ),
            "world_watermark": curve.as_utc(world_occurred_at).isoformat(),
            "source_kind": source_kind,
            "importance": curve.normalized_importance(importance),
            "created_at": now,
            "updated_at": now,
        },
    )
    return cursor.rowcount == 1


def initialize_memory_curve_state(
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
    world_occurred_at: str,
    source_kind: str,
    importance: float,
) -> dict:
    with db_session() as session:
        _lock_sqlite_write(session)
        _initialize_memory_curve_state_in_transaction(
            session,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_occurred_at,
            source_kind=source_kind,
            importance=importance,
        )
        return _get_memory_curve_state_in_transaction(
            session, owner_user_id, character_id, memory_type, memory_id
        )


def get_memory_curve_state(
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
) -> dict | None:
    key = _memory_curve_key(
        owner_user_id, character_id, memory_type, memory_id
    )
    with db_session() as session:
        return _get_memory_curve_state_in_transaction(session, *key)


def _advance_memory_curve_state_in_transaction(
    conn,
    state: dict,
    world_now: str,
) -> dict:
    watermark = curve.as_utc(state["world_time_watermark"])
    current_world = curve.as_utc(world_now)
    delta = max(0.0, (current_world - watermark).total_seconds())
    if delta <= 0:
        return state
    elapsed = float(state["elapsed_decay_seconds"]) + delta
    conn.execute(
        text("""
        UPDATE memory_curve_state
        SET elapsed_decay_seconds = :elapsed_decay_seconds,
            world_time_watermark = :world_time_watermark,
            updated_at = :updated_at
        WHERE owner_user_id = :owner_user_id AND character_id = :character_id
          AND memory_type = :memory_type AND memory_id = :memory_id
        """),
        {
            "elapsed_decay_seconds": elapsed,
            "world_time_watermark": current_world.isoformat(),
            "updated_at": _now(),
            "owner_user_id": state["owner_user_id"],
            "character_id": state["character_id"],
            "memory_type": state["memory_type"],
            "memory_id": state["memory_id"],
        },
    )
    state = dict(state)
    state["elapsed_decay_seconds"] = elapsed
    state["world_time_watermark"] = current_world.isoformat()
    return state


def advance_or_initialize_memory_curve_state(
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
    world_now: str,
    source_kind: str,
    importance: float,
) -> dict:
    key = _memory_curve_key(
        owner_user_id, character_id, memory_type, memory_id
    )
    with db_session() as session:
        _lock_sqlite_write(session)
        _initialize_memory_curve_state_in_transaction(
            session,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_now,
            source_kind=source_kind,
            importance=importance,
        )
        if _is_postgres_enabled():
            session.execute(
                text("""
                SELECT 1 FROM memory_curve_state
                WHERE owner_user_id = :owner_user_id
                  AND character_id = :character_id
                  AND memory_type = :memory_type
                  AND memory_id = :memory_id FOR UPDATE
                """),
                {
                    "owner_user_id": owner_user_id,
                    "character_id": character_id,
                    "memory_type": memory_type,
                    "memory_id": memory_id,
                },
            ).fetchone()
        state = _get_memory_curve_state_in_transaction(session, *key)
        return _advance_memory_curve_state_in_transaction(
            session, state, world_now
        )


def record_memory_curve_evidence(
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    memory_id: str,
    evidence_id: str,
    world_occurred_at: str,
    source_kind: str,
    importance: float,
) -> dict:
    """Initialize on first formation; idempotently reinforce later evidence."""
    key = _memory_curve_key(
        owner_user_id, character_id, memory_type, memory_id
    )
    evidence_id = str(evidence_id or "").strip()
    if not evidence_id:
        raise ValueError("evidence_id must not be blank")
    with db_session() as session:
        _lock_sqlite_write(session)
        initialized = _initialize_memory_curve_state_in_transaction(
            session,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_occurred_at,
            source_kind=source_kind,
            importance=importance,
        )
        if _is_postgres_enabled():
            session.execute(
                text("""
                SELECT 1 FROM memory_curve_state
                WHERE owner_user_id = :owner_user_id
                  AND character_id = :character_id
                  AND memory_type = :memory_type
                  AND memory_id = :memory_id FOR UPDATE
                """),
                {
                    "owner_user_id": owner_user_id,
                    "character_id": character_id,
                    "memory_type": memory_type,
                    "memory_id": memory_id,
                },
            ).fetchone()
        evidence_cursor = session.execute(
            text("""
            INSERT INTO memory_curve_reinforcement (
                owner_user_id, character_id, memory_type, memory_id,
                evidence_id, world_occurred_at, created_at
            ) VALUES (:owner_user_id, :character_id, :memory_type, :memory_id,
                      :evidence_id, :world_occurred_at, :created_at)
            ON CONFLICT(owner_user_id, character_id, memory_type, memory_id,
                        evidence_id) DO NOTHING
            """),
            {
                "owner_user_id": key[0],
                "character_id": key[1],
                "memory_type": key[2],
                "memory_id": key[3],
                "evidence_id": evidence_id,
                "world_occurred_at": curve.as_utc(
                    world_occurred_at
                ).isoformat(),
                "created_at": _now(),
            },
        )
        state = _get_memory_curve_state_in_transaction(session, *key)
        if initialized or evidence_cursor.rowcount != 1:
            return state

        state = _advance_memory_curve_state_in_transaction(
            session, state, world_occurred_at
        )
        current = curve.state_retention(state, world_occurred_at)
        strength, stability = curve.reinforce(
            current, state["stability_days"]
        )
        session.execute(
            text("""
            UPDATE memory_curve_state
            SET anchor_strength = :anchor_strength,
                stability_days = :stability_days,
                anchor_elapsed_seconds = elapsed_decay_seconds,
                reinforcement_count = reinforcement_count + 1,
                importance = :importance,
                updated_at = :updated_at
            WHERE owner_user_id = :owner_user_id
              AND character_id = :character_id
              AND memory_type = :memory_type
              AND memory_id = :memory_id
            """),
            {
                "anchor_strength": strength,
                "stability_days": stability,
                "importance": max(
                    float(state.get("importance") or 0.0),
                    curve.normalized_importance(importance),
                ),
                "updated_at": _now(),
                "owner_user_id": key[0],
                "character_id": key[1],
                "memory_type": key[2],
                "memory_id": key[3],
            },
        )
        return _get_memory_curve_state_in_transaction(session, *key)


def list_memory_curve_states(
    owner_user_id: str,
    character_id: str,
    *,
    memory_type: str | None = None,
) -> list[dict]:
    where = "owner_user_id = :owner_user_id AND character_id = :character_id"
    params: dict = {
        "owner_user_id": owner_user_id,
        "character_id": character_id,
    }
    if memory_type:
        where += " AND memory_type = :memory_type"
        params["memory_type"] = memory_type
    with db_session() as session:
        rows = session.execute(
            text(f"SELECT * FROM memory_curve_state WHERE {where} "
            "ORDER BY memory_type, memory_id",
            ),
            params,
        ).mappings().fetchall()
    return [dict(row) for row in rows]


def list_memory_curve_states_for_memory(
    owner_user_id: str,
    memory_type: str,
    memory_id: str,
) -> list[dict]:
    """Return every witness state for one tenant-scoped memory."""
    owner_user_id = str(owner_user_id or "").strip()
    memory_type = str(memory_type or "").strip()
    memory_id = str(memory_id or "").strip()
    if not owner_user_id or not memory_type or not memory_id:
        raise ValueError("memory curve lookup fields must not be blank")
    with db_session() as session:
        rows = session.execute(
            text("""
            SELECT * FROM memory_curve_state
            WHERE owner_user_id = :owner_user_id
              AND memory_type = :memory_type
              AND memory_id = :memory_id
            ORDER BY character_id
            """),
            {
                "owner_user_id": owner_user_id,
                "memory_type": memory_type,
                "memory_id": memory_id,
            },
        ).mappings().fetchall()
    return [dict(row) for row in rows]


# ──────────────────────────────────────────────────────────────
# Fix 1: batch advance or initialize in a single transaction
# ──────────────────────────────────────────────────────────────
def batch_advance_or_initialize_memory_curve_states(
    *,
    owner_user_id: str,
    character_id: str,
    memory_type: str,
    items: list[dict],
) -> dict[str, dict]:
    """Advance or initialize curve states for multiple memory IDs in one transaction.

    Each item in *items* must have keys: memory_id, world_now, source_kind, importance.
    Returns a dict mapping memory_id -> state row.
    """
    if not items:
        return {}

    key_prefix = (str(owner_user_id), str(character_id), str(memory_type))
    results: dict[str, dict] = {}

    with db_session() as session:
        _lock_sqlite_write(session)

        for item in items:
            memory_id = str(item["memory_id"] or "").strip()
            if not memory_id:
                continue
            world_now = item["world_now"]
            source_kind = item["source_kind"]
            importance = float(item["importance"])

            key = (*key_prefix, memory_id)
            state = _get_memory_curve_state_in_transaction(session, *key)

            if state is None:
                _initialize_memory_curve_state_in_transaction(
                    session,
                    owner_user_id=owner_user_id,
                    character_id=character_id,
                    memory_type=memory_type,
                    memory_id=memory_id,
                    world_occurred_at=world_now,
                    source_kind=source_kind,
                    importance=importance,
                )
                state = _get_memory_curve_state_in_transaction(session, *key)
            else:
                state = _advance_memory_curve_state_in_transaction(
                    session, state, world_now
                )
            results[memory_id] = state

    return results


# ──────────────────────────────────────────────────────────────
# Fix 5: cleanup forgotten curve states
# ──────────────────────────────────────────────────────────────
def cleanup_forgotten_memory_curve_states(
    *,
    owner_user_id: str | None = None,
    forgotten_threshold_days: float = 30.0,
    clarity_fragment_threshold: float = 0.15,
) -> int:
    """Delete curve states whose retention has been below the forgotten
    threshold for longer than *forgotten_threshold_days* world-time days.

    Only deletes states whose current retention is below *clarity_fragment_threshold*
    AND whose updated_at is older than the threshold.
    """
    from memoria.core import memory_curve as curve

    if forgotten_threshold_days <= 0:
        return 0

    cutoff_iso = (
        datetime.now(timezone.utc)
        - timedelta(days=forgotten_threshold_days)
    ).isoformat()

    with db_session() as session:
        # Find candidates: states updated long ago with very low retention
        where = "updated_at < :cutoff_iso AND elapsed_decay_seconds > 0"
        params: dict = {"cutoff_iso": cutoff_iso}
        if owner_user_id:
            where += " AND owner_user_id = :owner_user_id"
            params["owner_user_id"] = owner_user_id

        rows = session.execute(
            text(f"SELECT * FROM memory_curve_state WHERE {where}"),
            params,
        ).mappings().fetchall()

        to_delete = []
        for row in rows:
            state = dict(row)
            # Approximate current retention using the stored state
            # (conservative: use a point well past the watermark to simulate decay)
            approx_now_iso = (
                curve.as_utc(state["world_time_watermark"])
                + timedelta(days=forgotten_threshold_days)
            ).isoformat()
            r = curve.state_retention(state, approx_now_iso)
            if r < clarity_fragment_threshold:
                to_delete.append((
                    state["owner_user_id"],
                    state["character_id"],
                    state["memory_type"],
                    state["memory_id"],
                ))

        deleted = 0
        for key in to_delete:
            # Explicitly delete reinforcement rows first (SQLite doesn't enforce FK cascades)
            session.execute(
                text(
                    "DELETE FROM memory_curve_reinforcement "
                    "WHERE owner_user_id = :owner_user_id "
                    "AND character_id = :character_id "
                    "AND memory_type = :memory_type "
                    "AND memory_id = :memory_id"
                ),
                {
                    "owner_user_id": key[0],
                    "character_id": key[1],
                    "memory_type": key[2],
                    "memory_id": key[3],
                },
            )
            session.execute(
                text(
                    "DELETE FROM memory_curve_state "
                    "WHERE owner_user_id = :owner_user_id "
                    "AND character_id = :character_id "
                    "AND memory_type = :memory_type "
                    "AND memory_id = :memory_id"
                ),
                {
                    "owner_user_id": key[0],
                    "character_id": key[1],
                    "memory_type": key[2],
                    "memory_id": key[3],
                },
            )
            deleted += 1

    return deleted
