"""Persistence for the memory-curve side projection."""

from __future__ import annotations

import sqlite3

from memoria.core import memory_curve as curve
from memoria.db.repository._common import *  # noqa: F403
from memoria.db.repository import _common as _common_mod


for _name, _value in vars(_common_mod).items():
    if not _name.startswith("__"):
        globals().setdefault(_name, _value)
del _name, _value, _common_mod


def _begin_memory_curve_write(conn) -> None:
    if isinstance(conn, sqlite3.Connection) and not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


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
        """
        SELECT * FROM memory_curve_state
        WHERE owner_user_id = ? AND character_id = ?
          AND memory_type = ? AND memory_id = ?
        """,
        (owner_user_id, character_id, memory_type, memory_id),
    ).fetchone()
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
        """
        INSERT INTO memory_curve_state (
            owner_user_id, character_id, memory_type, memory_id,
            anchor_strength, stability_days, anchor_elapsed_seconds,
            elapsed_decay_seconds, world_time_watermark,
            reinforcement_count, source_kind, importance,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, 1.0, ?, 0.0, 0.0, ?, 0, ?, ?, ?, ?)
        ON CONFLICT(owner_user_id, character_id, memory_type, memory_id)
        DO NOTHING
        """,
        (
            *key,
            curve.initial_stability_days(importance, source_kind),
            curve.as_utc(world_occurred_at).isoformat(),
            source_kind,
            curve.normalized_importance(importance),
            now,
            now,
        ),
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
    with get_conn() as conn:
        _begin_memory_curve_write(conn)
        _initialize_memory_curve_state_in_transaction(
            conn,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_occurred_at,
            source_kind=source_kind,
            importance=importance,
        )
        return _get_memory_curve_state_in_transaction(
            conn, owner_user_id, character_id, memory_type, memory_id
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
    with get_conn() as conn:
        return _get_memory_curve_state_in_transaction(conn, *key)


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
        """
        UPDATE memory_curve_state
        SET elapsed_decay_seconds = ?, world_time_watermark = ?, updated_at = ?
        WHERE owner_user_id = ? AND character_id = ?
          AND memory_type = ? AND memory_id = ?
        """,
        (
            elapsed,
            current_world.isoformat(),
            _now(),
            state["owner_user_id"],
            state["character_id"],
            state["memory_type"],
            state["memory_id"],
        ),
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
    with get_conn() as conn:
        _begin_memory_curve_write(conn)
        _initialize_memory_curve_state_in_transaction(
            conn,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_now,
            source_kind=source_kind,
            importance=importance,
        )
        if _is_postgres_enabled():
            conn.execute(
                """
                SELECT 1 FROM memory_curve_state
                WHERE owner_user_id = ? AND character_id = ?
                  AND memory_type = ? AND memory_id = ? FOR UPDATE
                """,
                key,
            ).fetchone()
        state = _get_memory_curve_state_in_transaction(conn, *key)
        return _advance_memory_curve_state_in_transaction(conn, state, world_now)


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
    with get_conn() as conn:
        _begin_memory_curve_write(conn)
        initialized = _initialize_memory_curve_state_in_transaction(
            conn,
            owner_user_id=owner_user_id,
            character_id=character_id,
            memory_type=memory_type,
            memory_id=memory_id,
            world_occurred_at=world_occurred_at,
            source_kind=source_kind,
            importance=importance,
        )
        if _is_postgres_enabled():
            conn.execute(
                """
                SELECT 1 FROM memory_curve_state
                WHERE owner_user_id = ? AND character_id = ?
                  AND memory_type = ? AND memory_id = ? FOR UPDATE
                """,
                key,
            ).fetchone()
        evidence_cursor = conn.execute(
            """
            INSERT INTO memory_curve_reinforcement (
                owner_user_id, character_id, memory_type, memory_id,
                evidence_id, world_occurred_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(owner_user_id, character_id, memory_type, memory_id,
                        evidence_id) DO NOTHING
            """,
            (
                *key,
                evidence_id,
                curve.as_utc(world_occurred_at).isoformat(),
                _now(),
            ),
        )
        state = _get_memory_curve_state_in_transaction(conn, *key)
        if initialized or evidence_cursor.rowcount != 1:
            return state

        state = _advance_memory_curve_state_in_transaction(
            conn, state, world_occurred_at
        )
        current = curve.state_retention(state, world_occurred_at)
        strength, stability = curve.reinforce(
            current, state["stability_days"]
        )
        conn.execute(
            """
            UPDATE memory_curve_state
            SET anchor_strength = ?, stability_days = ?,
                anchor_elapsed_seconds = elapsed_decay_seconds,
                reinforcement_count = reinforcement_count + 1,
                importance = ?, updated_at = ?
            WHERE owner_user_id = ? AND character_id = ?
              AND memory_type = ? AND memory_id = ?
            """,
            (
                strength,
                stability,
                max(
                    float(state.get("importance") or 0.0),
                    curve.normalized_importance(importance),
                ),
                _now(),
                *key,
            ),
        )
        return _get_memory_curve_state_in_transaction(conn, *key)


def list_memory_curve_states(
    owner_user_id: str,
    character_id: str,
    *,
    memory_type: str | None = None,
) -> list[dict]:
    where = "owner_user_id = ? AND character_id = ?"
    params: list = [owner_user_id, character_id]
    if memory_type:
        where += " AND memory_type = ?"
        params.append(memory_type)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM memory_curve_state WHERE {where} "
            "ORDER BY memory_type, memory_id",
            tuple(params),
        ).fetchall()
    return [dict(row) for row in rows]
