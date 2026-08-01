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
from sqlalchemy import text

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
# 事件系统 - 事件定义
# =========================
def _save_event_definition_in_transaction(
    conn,
    *,
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> None:
    now = _now()
    conn.execute(text("""
        INSERT INTO event_definition
        (owner_user_id, event_id, event_name, description, character_id, story_id, trigger_config,
         effects_config, priority, exclusive_group, exclusive_scope, max_triggers_per_turn,
         stop_processing, is_active, created_at, updated_at, schedule, template_id)
        VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14, :p15, :p16, :p17)
        ON CONFLICT(owner_user_id, event_id)
        DO UPDATE SET
            event_name=excluded.event_name,
            description=excluded.description,
            character_id=excluded.character_id,
            story_id=excluded.story_id,
            trigger_config=excluded.trigger_config,
            effects_config=excluded.effects_config,
            priority=excluded.priority,
            exclusive_group=excluded.exclusive_group,
            exclusive_scope=excluded.exclusive_scope,
            max_triggers_per_turn=excluded.max_triggers_per_turn,
            stop_processing=excluded.stop_processing,
            is_active=excluded.is_active,
            updated_at=excluded.updated_at,
            schedule=excluded.schedule,
            template_id=excluded.template_id
        """), {"p0": owner_user_id, "p1": event_id, "p2": event_name, "p3": description, "p4": character_id, "p5": story_id, "p6": trigger_config, "p7": effects_config, "p8": priority, "p9": exclusive_group, "p10": exclusive_scope, "p11": max_triggers_per_turn, "p12": 1 if stop_processing else 0, "p13": 1 if is_active else 0, "p14": now, "p15": now, "p16": schedule, "p17": template_id})
    if exclusive_scope == "player" and exclusive_group:
        conn.execute(text("""
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = :p0 AND selected_event_id = :p1
              AND exclusive_group <> :p2
            """), {"p0": owner_user_id, "p1": event_id, "p2": exclusive_group})
    else:
        conn.execute(text("""
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = :p0 AND selected_event_id = :p1
            """), {"p0": owner_user_id, "p1": event_id})


def save_event_definition(
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> bool:
    """保存事件定义"""
    try:
        with db_session() as conn:
            _save_event_definition_in_transaction(
                conn,
                owner_user_id=owner_user_id,
                event_id=event_id,
                event_name=event_name,
                trigger_config=trigger_config,
                effects_config=effects_config,
                character_id=character_id,
                description=description,
                priority=priority,
                exclusive_group=exclusive_group,
                exclusive_scope=exclusive_scope,
                max_triggers_per_turn=max_triggers_per_turn,
                stop_processing=stop_processing,
                is_active=is_active,
                schedule=schedule,
                template_id=template_id,
                story_id=story_id,
            )
        return True
    except Exception as e:
        logger.error(f"保存事件定义失败: {e}")
        return False

def get_event_definition(owner_user_id: str, event_id: str) -> dict | None:
    """获取单个事件定义"""
    with db_session() as conn:
        row = conn.execute(text("""SELECT * FROM event_definition WHERE owner_user_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id}).mappings().fetchone()
    return _row_to_dict(row)

def list_event_definitions(
    owner_user_id: str,
    character_id: str = None,
    only_active: bool = True
) -> list[dict]:
    """列出事件定义"""
    with db_session() as conn:
        query = "SELECT * FROM event_definition WHERE owner_user_id = :owner_user_id"
        params = {"owner_user_id": owner_user_id}

        if character_id is not None:
            query += " AND (character_id = :character_id OR character_id IS NULL)"
            params["character_id"] = character_id

        if only_active:
            query += " AND is_active = 1"

        query += " ORDER BY priority DESC, created_at DESC"

        rows = conn.execute(text(query), params).mappings().fetchall()

    return [dict(r) for r in rows]

def delete_event_definition(owner_user_id: str, event_id: str) -> bool:
    """Delete an event definition and its operational trigger state."""
    try:
        with db_session() as conn:
            conn.execute(text("""DELETE FROM event_schedule_state WHERE player_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id})
            conn.execute(text("""DELETE FROM event_context_state WHERE player_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id})
            conn.execute(text("""DELETE FROM event_trigger_log WHERE player_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id})
            conn.execute(text("""DELETE FROM event_trigger_guard WHERE player_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id})
            conn.execute(text("""
                DELETE FROM event_exclusive_group_guard
                WHERE player_id = :p0 AND selected_event_id = :p1
                """), {"p0": owner_user_id, "p1": event_id})
            deleted = conn.execute(text("""DELETE FROM event_definition WHERE owner_user_id = :p0 AND event_id = :p1"""), {"p0": owner_user_id, "p1": event_id})
        return deleted.rowcount == 1
    except Exception as e:
        logger.error(f"删除事件定义失败: {e}")
        return False

def increment_event_trigger_count(owner_user_id: str, event_id: str):
    """增加事件触发计数"""
    with db_session() as conn:
        conn.execute(text("""
            UPDATE event_definition
            SET trigger_count = trigger_count + 1,
                last_triggered_at = :p0
            WHERE owner_user_id = :p1 AND event_id = :p2
            """), {"p0": _now(), "p1": owner_user_id, "p2": event_id})


# =========================
# 事件系统 - 触发记录
# =========================
def log_event_trigger(
    event_id: str,
    character_id: str,
    player_id: str,
    session_id: str,
    context_snapshot: str,
    effects_applied: str
):
    """记录事件触发"""
    with db_session() as conn:
        conn.execute(text("""
            INSERT INTO event_trigger_log
            (event_id, character_id, player_id, session_id, 
             triggered_at, context_snapshot, effects_applied)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6)
            """), {"p0": event_id, "p1": character_id, "p2": player_id, "p3": session_id, "p4": _now(), "p5": context_snapshot, "p6": effects_applied})

def get_event_trigger_history(
    event_id: str = None,
    character_id: str = None,
    player_id: str = None,
    limit: int = 50
) -> list[dict]:
    """获取事件触发历史"""
    with db_session() as conn:
        query = "SELECT * FROM event_trigger_log WHERE 1=1"
        params = {}
        
        if event_id:
            query += " AND event_id = :event_id"
            params["event_id"] = event_id
        
        if character_id:
            query += " AND character_id = :character_id"
            params["character_id"] = character_id
        
        if player_id:
            query += " AND player_id = :player_id"
            params["player_id"] = player_id
        
        query += " ORDER BY triggered_at DESC LIMIT :limit"
        params["limit"] = limit
        
        rows = conn.execute(text(query), params).mappings().fetchall()
    
    return [dict(r) for r in rows]

def get_last_trigger_time(event_id: str, character_id: str | None, player_id: str) -> str | None:
    """获取事件最后触发时间（用于冷却时间判断）"""
    with db_session() as conn:
        if character_id is None:
            row = conn.execute(text("""
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = :p0 AND player_id = :p1 AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """), {"p0": event_id, "p1": player_id}).mappings().fetchone()
        else:
            row = conn.execute(text("""
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = :p0 AND character_id = :p1 AND player_id = :p2
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """), {"p0": event_id, "p1": character_id, "p2": player_id}).mappings().fetchone()

    return row["triggered_at"] if row else None


def claim_event_trigger_guard(
    *,
    player_id: str,
    event_id: str,
    character_scope: str,
    cooldown_hours: int,
    claim_token: str,
    claimed_at: str,
    claim_expires_at: str,
) -> bool:
    """领取 once/cooldown 事件的持久化触发权。"""
    scope = character_scope or ""
    with db_session() as conn:
        if not _is_postgres_enabled():
            _lock_sqlite_write(conn)
        if scope:
            legacy = conn.execute(text("""
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = :p0 AND event_id = :p1 AND character_id = :p2
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """), {"p0": player_id, "p1": event_id, "p2": scope}).mappings().fetchone()
        else:
            legacy = conn.execute(text("""
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = :p0 AND event_id = :p1 AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """), {"p0": player_id, "p1": event_id}).mappings().fetchone()
        legacy_last_triggered_at = legacy["triggered_at"] if legacy else None
        conn.execute(text("""
            INSERT INTO event_trigger_guard
            (player_id, event_id, character_scope, last_triggered_at,
             claim_token, claim_expires_at, updated_at)
            VALUES (:p0, :p1, :p2, :p3, NULL, NULL, :p4)
            ON CONFLICT(player_id, event_id, character_scope) DO NOTHING
            """), {"p0": player_id, "p1": event_id, "p2": scope, "p3": legacy_last_triggered_at, "p4": claimed_at})
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(text("""
            SELECT last_triggered_at, claim_token, claim_expires_at
            FROM event_trigger_guard
            WHERE player_id = :player_id AND event_id = :event_id
              AND character_scope = :character_scope
            """ + lock_suffix), {
            "player_id": player_id,
            "event_id": event_id,
            "character_scope": scope,
        }).mappings().fetchone()
        last_triggered_at = row["last_triggered_at"] or legacy_last_triggered_at
        if not row["last_triggered_at"] and legacy_last_triggered_at:
            conn.execute(text("""
                UPDATE event_trigger_guard
                SET last_triggered_at = :p0, updated_at = :p1
                WHERE player_id = :p2 AND event_id = :p3 AND character_scope = :p4
                """), {"p0": legacy_last_triggered_at, "p1": claimed_at, "p2": player_id, "p3": event_id, "p4": scope})

        claimed_time = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
        if claimed_time.tzinfo is None:
            claimed_time = claimed_time.replace(tzinfo=timezone.utc)
        if last_triggered_at:
            last_time = datetime.fromisoformat(
                last_triggered_at.replace("Z", "+00:00")
            )
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            if cooldown_hours == 0:
                return False
            if claimed_time - last_time < timedelta(hours=cooldown_hours):
                return False

        existing_claim = row["claim_token"]
        existing_expiry = row["claim_expires_at"]
        if existing_claim and existing_claim != claim_token and existing_expiry:
            expires_at = datetime.fromisoformat(existing_expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > claimed_time:
                return False

        cursor = conn.execute(text("""
            UPDATE event_trigger_guard
            SET claim_token = :p0, claim_expires_at = :p1, updated_at = :p2
            WHERE player_id = :p3 AND event_id = :p4 AND character_scope = :p5
            """), {"p0": claim_token, "p1": claim_expires_at, "p2": claimed_at, "p3": player_id, "p4": event_id, "p5": scope})
        return cursor.rowcount == 1


def release_event_trigger_guard(
    *,
    player_id: str,
    event_id: str,
    character_scope: str,
    claim_token: str,
) -> bool:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_trigger_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = :p0
            WHERE player_id = :p1 AND event_id = :p2 AND character_scope = :p3
              AND claim_token = :p4
            """), {"p0": _now(), "p1": player_id, "p2": event_id, "p3": character_scope or "", "p4": claim_token})
    return cursor.rowcount == 1


def claim_event_exclusive_group(
    *,
    player_id: str,
    exclusive_group: str,
    claim_token: str,
    claimed_at: str,
    claim_expires_at: str,
) -> bool:
    """Claim a player-scoped exclusive group unless it is already selected."""
    with db_session() as conn:
        if not _is_postgres_enabled():
            _lock_sqlite_write(conn)
        conn.execute(text("""
            INSERT INTO event_exclusive_group_guard
            (player_id, exclusive_group, selected_event_id, claim_token,
             claim_expires_at, updated_at)
            VALUES (:p0, :p1, NULL, NULL, NULL, :p2)
            ON CONFLICT(player_id, exclusive_group) DO NOTHING
            """), {"p0": player_id, "p1": exclusive_group, "p2": claimed_at})
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(text("""
            SELECT selected_event_id, claim_token, claim_expires_at
            FROM event_exclusive_group_guard
            WHERE player_id = :player_id AND exclusive_group = :exclusive_group
            """ + lock_suffix), {
            "player_id": player_id,
            "exclusive_group": exclusive_group,
        }).mappings().fetchone()
        if row["selected_event_id"]:
            return False

        legacy_selection = conn.execute(text("""
            SELECT trigger_log.event_id
            FROM event_trigger_log AS trigger_log
            INNER JOIN event_definition AS definition
              ON definition.owner_user_id = trigger_log.player_id
             AND definition.event_id = trigger_log.event_id
            WHERE trigger_log.player_id = :p0
              AND trigger_log.status = 'succeeded'
              AND definition.exclusive_group = :p1
              AND definition.exclusive_scope = 'player'
            ORDER BY
              CASE WHEN trigger_log.triggered_at IS NULL THEN 1 ELSE 0 END,
              trigger_log.triggered_at ASC,
              trigger_log.id ASC
            LIMIT 1
            """), {"p0": player_id, "p1": exclusive_group}).mappings().fetchone()
        if legacy_selection:
            conn.execute(text("""
                UPDATE event_exclusive_group_guard
                SET selected_event_id = :p0, claim_token = NULL,
                    claim_expires_at = NULL, updated_at = :p1
                WHERE player_id = :p2 AND exclusive_group = :p3
                """), {"p0": legacy_selection["event_id"], "p1": claimed_at, "p2": player_id, "p3": exclusive_group})
            return False

        claimed_time = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
        if claimed_time.tzinfo is None:
            claimed_time = claimed_time.replace(tzinfo=timezone.utc)
        existing_claim = row["claim_token"]
        existing_expiry = row["claim_expires_at"]
        if existing_claim and existing_claim != claim_token and existing_expiry:
            expires_at = datetime.fromisoformat(existing_expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > claimed_time:
                return False

        cursor = conn.execute(text("""
            UPDATE event_exclusive_group_guard
            SET claim_token = :p0, claim_expires_at = :p1, updated_at = :p2
            WHERE player_id = :p3 AND exclusive_group = :p4
              AND selected_event_id IS NULL
            """), {"p0": claim_token, "p1": claim_expires_at, "p2": claimed_at, "p3": player_id, "p4": exclusive_group})
        return cursor.rowcount == 1


def release_event_exclusive_group(
    *,
    player_id: str,
    exclusive_group: str,
    claim_token: str,
) -> bool:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_exclusive_group_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = :p0
            WHERE player_id = :p1 AND exclusive_group = :p2
              AND selected_event_id IS NULL AND claim_token = :p3
            """), {"p0": _now(), "p1": player_id, "p2": exclusive_group, "p3": claim_token})
    return cursor.rowcount == 1


def get_event_exclusive_group_selection(
    player_id: str,
    exclusive_group: str,
) -> dict | None:
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT * FROM event_exclusive_group_guard
            WHERE player_id = :p0 AND exclusive_group = :p1
              AND selected_event_id IS NOT NULL
            """), {"p0": player_id, "p1": exclusive_group}).mappings().fetchone()
    return _row_to_dict(row)


def get_event_execution_batch(player_id: str, execution_key: str) -> dict | None:
    """读取已完成的事件批次，用于请求重放。"""
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT * FROM event_execution_batch
            WHERE player_id = :p0 AND execution_key = :p1
            """), {"p0": player_id, "p1": execution_key}).mappings().fetchone()
    return _row_to_dict(row)


def increment_event_execution_batch_deduplicated(
    player_id: str,
    execution_key: str,
) -> bool:
    """记录一次命中已完成批次的幂等重放。"""
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_execution_batch
            SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
            WHERE player_id = :p0 AND execution_key = :p1
            """), {"p0": player_id, "p1": execution_key})
    return cursor.rowcount == 1


def get_event_execution(
    owner_user_id: str,
    event_id: str,
    execution_key: str,
) -> dict | None:
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT * FROM event_execution
            WHERE owner_user_id = :p0 AND event_id = :p1 AND execution_key = :p2
            """), {"p0": owner_user_id, "p1": event_id, "p2": execution_key}).mappings().fetchone()
    return _row_to_dict(row)


def list_event_execution_history(
    owner_user_id: str,
    character_id: str | None = None,
    event_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent auditable event outcomes for condition evaluation."""
    with db_session() as conn:
        query = """
            SELECT execution_id, execution_key, event_id, character_id,
                   session_id, trigger_source, status, error, duration_ms,
                   created_at, completed_at
            FROM event_execution
            WHERE owner_user_id = :owner_user_id
        """
        params: dict[str, Any] = {"owner_user_id": owner_user_id}
        if character_id:
            query += " AND character_id = :character_id"
            params["character_id"] = character_id
        if event_id:
            query += " AND event_id = :event_id"
            params["event_id"] = event_id
        query += " ORDER BY completed_at DESC LIMIT :limit"
        params["limit"] = max(1, min(limit, 1000))
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(row) for row in rows]


def _insert_long_term_fact_in_transaction(conn, memory: dict) -> dict | None:
    fact_text = normalize_long_term_fact_text(memory.get("fact_text"))
    if not fact_text:
        return None
    character_id = memory["character_id"]
    player_id = memory["player_id"]
    importance = int(memory.get("importance") or 5)
    existing = _dedup_check(
        conn,
        "long_term_fact",
        "fact_text",
        fact_text,
        "character_id = :character_id AND player_id = :player_id",
        {"character_id": character_id, "player_id": player_id},
        threshold=0.75,
    )
    now = _now()
    if existing:
        conn.execute(
            text(
                "UPDATE long_term_fact SET importance = :importance, "
                "last_referenced = :last_referenced WHERE id = :id"
            ),
            {
                "importance": max(existing.get("importance", 0), importance),
                "last_referenced": now,
                "id": existing["id"],
            },
        )
        return None

    insert_sql = """
        INSERT INTO long_term_fact
        (character_id, player_id, fact_text, importance, created_at, last_referenced)
        VALUES (:character_id, :player_id, :fact_text, :importance,
                :created_at, :last_referenced)
    """
    if _is_postgres_enabled():
        insert_sql += " RETURNING id"
    cursor = conn.execute(
        text(insert_sql),
        {
            "character_id": character_id,
            "player_id": player_id,
            "fact_text": fact_text,
            "importance": importance,
            "created_at": now,
            "last_referenced": now,
        },
    )
    fact_id = cursor.mappings().fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
    return {
        "fact_id": fact_id,
        "character_id": character_id,
        "player_id": player_id,
        "fact_text": fact_text,
        "importance": importance,
    }


def _complete_event_schedule_in_transaction(
    conn,
    *,
    player_id: str,
    schedule_completion: dict,
    now: str,
) -> None:
    completed = conn.execute(text("""
        UPDATE event_schedule_state
        SET last_checked_at = :p0, last_run_at = :p1, next_run_at = :p2,
            next_due_real_at = :p3, missed_count = :p4,
            lease_owner = NULL, lease_expires_at = NULL,
            last_error = NULL, last_failed_at = NULL, updated_at = :p5
        WHERE event_id = :p6 AND character_id = :p7 AND player_id = :p8
          AND lease_owner = :p9
        """), {"p0": schedule_completion["last_checked_at"], "p1": schedule_completion["last_run_at"], "p2": schedule_completion["next_run_at"], "p3": schedule_completion.get("next_due_real_at"), "p4": int(schedule_completion.get("missed_count") or 0), "p5": now, "p6": schedule_completion["event_id"], "p7": schedule_completion["character_id"], "p8": player_id, "p9": schedule_completion["lease_owner"]})
    if completed.rowcount != 1:
        raise RuntimeError("schedule lease was lost before atomic completion")


class DialogueTurnConflictError(RuntimeError):
    """A session already has an active dialogue turn."""


def claim_dialogue_turn(
    *,
    session_id: str,
    request_id: str,
    player_id: str,
    turn_kind: str,
    lease_seconds: int = 240,
) -> dict:
    """Claim one idempotent turn, or return its completed response."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lease_owner = uuid.uuid4().hex
    lease_expires_at = (now + timedelta(seconds=max(30, lease_seconds))).isoformat()
    with db_session() as conn:
        if _is_postgres_enabled():
            conn.execute(text("""SELECT session_id FROM session WHERE session_id = :p0 FOR UPDATE"""), {"p0": session_id}).mappings().fetchone()
        else:
            _lock_sqlite_write(conn)

        existing = conn.execute(text("""
            SELECT * FROM dialogue_turn
            WHERE session_id = :p0 AND request_id = :p1
            """), {"p0": session_id, "p1": request_id}).mappings().fetchone()
        if existing and existing["status"] == "completed":
            return {
                "completed": True,
                "response": json.loads(existing["response_data"]),
            }
        if existing and (
            existing["player_id"] != player_id
            or existing["turn_kind"] != turn_kind
        ):
            raise DialogueTurnConflictError("request_id 已用于其他对话请求")
        if (
            existing
            and existing["status"] == "processing"
            and existing["lease_expires_at"]
            and existing["lease_expires_at"] > now_iso
        ):
            raise DialogueTurnConflictError("该请求正在处理中")

        active = conn.execute(text("""
            SELECT request_id
            FROM dialogue_turn
            WHERE session_id = :p0 AND status = 'processing'
              AND lease_expires_at > :p1 AND request_id <> :p2
            LIMIT 1
            """), {"p0": session_id, "p1": now_iso, "p2": request_id}).mappings().fetchone()
        if active:
            raise DialogueTurnConflictError("该会话已有消息正在处理中")

        conn.execute(text("""
            INSERT INTO dialogue_turn
            (session_id, request_id, player_id, turn_kind, status,
             lease_owner, lease_expires_at, response_data, error,
             created_at, updated_at, completed_at)
            VALUES (:p0, :p1, :p2, :p3, 'processing', :p4, :p5, NULL, NULL, :p6, :p7, NULL)
            ON CONFLICT(session_id, request_id)
            DO UPDATE SET
                status='processing',
                lease_owner=excluded.lease_owner,
                lease_expires_at=excluded.lease_expires_at,
                response_data=NULL,
                error=NULL,
                updated_at=excluded.updated_at,
                completed_at=NULL
            """), {"p0": session_id, "p1": request_id, "p2": player_id, "p3": turn_kind, "p4": lease_owner, "p5": lease_expires_at, "p6": now_iso, "p7": now_iso})
    return {
        "completed": False,
        "lease_owner": lease_owner,
        "request_id": request_id,
    }


def fail_dialogue_turn(
    session_id: str,
    request_id: str,
    lease_owner: str,
    error: str,
) -> None:
    with db_session() as conn:
        conn.execute(text("""
            UPDATE dialogue_turn
            SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                error = :p0, updated_at = :p1
            WHERE session_id = :p2 AND request_id = :p3
              AND status = 'processing' AND lease_owner = :p4
            """), {"p0": error[:1000], "p1": _now(), "p2": session_id, "p3": request_id, "p4": lease_owner})


def _save_runtime_states_in_transaction(
    conn,
    *,
    player_id: str,
    runtime_states: list[dict] | None,
    now: str,
) -> None:
    for state in runtime_states or []:
        _save_runtime_state_in_transaction(
            conn,
            character_id=state["character_id"],
            player_id=player_id,
            affection_level=state["affection_level"],
            trust_level=state["trust_level"],
            current_mood=state["current_mood"],
            now=now,
            insert_only=bool(state.get("insert_only")),
            state_changes=state.get("state_changes"),
        )


def _save_runtime_state_in_transaction(
    conn,
    *,
    character_id: str,
    player_id: str,
    affection_level: float,
    trust_level: float,
    current_mood: str,
    now: str,
    insert_only: bool = False,
    state_changes: list[dict] | None = None,
) -> None:
    if state_changes:
        conn.execute(text("""
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5)
            ON CONFLICT(character_id, player_id) DO NOTHING
            """), {"p0": character_id, "p1": player_id, "p2": affection_level, "p3": trust_level, "p4": current_mood, "p5": now})
        for changes in state_changes:
            assignments: list[str] = []
            parameters: dict[str, Any] = {}
            if "affection_level" in changes:
                delta = float(changes["affection_level"])
                parameters["affection_delta"] = delta
                assignments.append(
                    """
                    affection_level = CASE
                        WHEN affection_level + :affection_delta < -100 THEN -100
                        WHEN affection_level + :affection_delta > 100 THEN 100
                        ELSE affection_level + :affection_delta
                    END
                    """
                )
            if "trust_level" in changes:
                delta = float(changes["trust_level"])
                parameters["trust_delta"] = delta
                assignments.append(
                    """
                    trust_level = CASE
                        WHEN trust_level + :trust_delta < 0 THEN 0
                        WHEN trust_level + :trust_delta > 100 THEN 100
                        ELSE trust_level + :trust_delta
                    END
                    """
                )
            if "current_mood" in changes:
                assignments.append("current_mood = :current_mood")
                parameters["current_mood"] = str(changes["current_mood"])
            if not assignments:
                continue
            parameters["updated_at"] = now
            parameters["character_id"] = character_id
            parameters["player_id"] = player_id
            conn.execute(text(f"""
                UPDATE relationship_state
                SET {", ".join(assignments)}, updated_at = :updated_at
                WHERE character_id = :character_id AND player_id = :player_id
                """), parameters)
        row = conn.execute(text("""
            SELECT affection_level, trust_level, current_mood
            FROM relationship_state
            WHERE character_id = :p0 AND player_id = :p1
            """), {"p0": character_id, "p1": player_id}).mappings().fetchone()
        affection_level = row["affection_level"]
        trust_level = row["trust_level"]
        current_mood = row["current_mood"]
    else:
        relationship_state_conflict = (
            "DO NOTHING"
            if insert_only
            else """
            DO UPDATE SET
                affection_level=excluded.affection_level,
                trust_level=excluded.trust_level,
                current_mood=excluded.current_mood,
                updated_at=excluded.updated_at
            """
        )
        conn.execute(text(f"""
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5)
            ON CONFLICT(character_id, player_id)
            {relationship_state_conflict}
            """), {"p0": character_id, "p1": player_id, "p2": affection_level, "p3": trust_level, "p4": current_mood, "p5": now})
    player_id_node, character_id_node = _normalize_relationship_pair(
        player_node_id(player_id),
        character_id,
    )
    relationship_conflict = (
        "DO NOTHING"
        if insert_only
        else """
        DO UPDATE SET
            affinity=excluded.affinity,
            updated_at=excluded.updated_at
        """
    )
    conn.execute(text(f"""
        INSERT INTO character_relationship
        (owner_user_id, character_id_a, character_id_b, relationship_type,
         affinity, description, created_at, updated_at)
        VALUES (:p0, :p1, :p2, '相识', :p3, NULL, :p4, :p5)
        ON CONFLICT(owner_user_id, character_id_a, character_id_b)
        {relationship_conflict}
        """), {"p0": player_id, "p1": player_id_node, "p2": character_id_node, "p3": affection_level, "p4": now, "p5": now})


def _commit_dialogue_turn_in_transaction(
    conn,
    dialogue_turn: dict,
    *,
    now: str,
) -> dict | list:
    session_id = dialogue_turn["session_id"]
    request_id = dialogue_turn["request_id"]
    lease_owner = dialogue_turn["lease_owner"]
    row = conn.execute(text("""
        SELECT status, lease_owner, lease_expires_at, response_data
        FROM dialogue_turn
        WHERE session_id = :p0 AND request_id = :p1
        """), {"p0": session_id, "p1": request_id}).mappings().fetchone()
    if not row:
        raise RuntimeError("dialogue turn claim does not exist")
    if row["status"] == "completed":
        return json.loads(row["response_data"])
    if (
        row["status"] != "processing"
        or row["lease_owner"] != lease_owner
        or not row["lease_expires_at"]
        or row["lease_expires_at"] <= now
    ):
        raise DialogueTurnConflictError("对话轮次租约已失效")

    response = dialogue_turn["response"]
    temporary_ids: dict[int, int] = {}
    for message in dialogue_turn.get("messages") or []:
        reply_to_message_id = message.get("reply_to_message_id")
        if isinstance(reply_to_message_id, int) and reply_to_message_id < 0:
            reply_to_message_id = temporary_ids.get(reply_to_message_id)
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, character_id, character_name,
             action, affinity_delta, trust_delta, current_affinity,
             current_trust, current_mood, event_notification,
             knowledge_sources, reply_to_message_id, reply_to_character_id,
             intent, topic, trigger_source, created_at, world_created_at)
            VALUES (:session_id, :role, :content, :character_id, :character_name,
                    :action, :affinity_delta, :trust_delta, :current_affinity,
                    :current_trust, :current_mood, :event_notification,
                    :knowledge_sources, :reply_to_message_id,
                    :reply_to_character_id, :intent, :topic, :trigger_source,
                    :created_at, :world_created_at)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            text(insert_sql),
            {
                "session_id": session_id,
                "role": message["role"],
                "content": message["content"],
                "character_id": message.get("character_id"),
                "character_name": message.get("character_name"),
                "action": message.get("action"),
                "affinity_delta": message.get("affinity_delta"),
                "trust_delta": message.get("trust_delta"),
                "current_affinity": message.get("current_affinity"),
                "current_trust": message.get("current_trust"),
                "current_mood": message.get("current_mood"),
                "event_notification": message.get("event_notification"),
                "knowledge_sources": _encode_knowledge_sources(
                    message.get("knowledge_sources")
                ),
                "reply_to_message_id": reply_to_message_id,
                "reply_to_character_id": message.get("reply_to_character_id"),
                "intent": message.get("intent"),
                "topic": message.get("topic"),
                "trigger_source": message.get("trigger_source"),
                "created_at": now,
                "world_created_at": message.get("world_created_at"),
            },
        )
        message_id = cursor.mappings().fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
        temporary_id = message.get("temporary_id")
        if isinstance(temporary_id, int):
            temporary_ids[temporary_id] = message_id
        response_field = message.get("response_field")
        response_index = message.get("response_index")
        if response_field and response_index is None and isinstance(response, dict):
            response[response_field] = message_id
        elif (
            response_field
            and isinstance(response_index, int)
            and isinstance(response, list)
            and response_index < len(response)
        ):
            response[response_index][response_field] = message_id
        if message.get("character_id"):
            conn.execute(text("""
                UPDATE multi_session_participant
                SET last_spoke_at = :p0, message_count = message_count + 1
                WHERE session_id = :p1 AND character_id = :p2
                """), {"p0": now, "p1": session_id, "p2": message["character_id"]})

    if isinstance(response, list):
        for item in response:
            reply_to_message_id = item.get("reply_to_message_id")
            if isinstance(reply_to_message_id, int) and reply_to_message_id < 0:
                item["reply_to_message_id"] = temporary_ids.get(reply_to_message_id)

    group_state = dialogue_turn.get("group_state")
    if group_state:
        last_reply_to_message_id = group_state.get("last_reply_to_message_id")
        if isinstance(last_reply_to_message_id, int) and last_reply_to_message_id < 0:
            last_reply_to_message_id = temporary_ids.get(last_reply_to_message_id)
        unresolved_hooks = []
        for hook in group_state.get("unresolved_hooks") or []:
            mapped_hook = dict(hook)
            message_id = mapped_hook.get("message_id")
            if isinstance(message_id, int) and message_id < 0:
                mapped_hook["message_id"] = temporary_ids.get(message_id)
            unresolved_hooks.append(mapped_hook)
        conn.execute(text("""
            INSERT INTO group_dialogue_state
            (group_thread_id, player_id, current_topic, topic_source,
             last_reply_to_message_id, last_reply_to_character_id,
             last_speaker_id, waiting_for_player, unresolved_hooks,
             last_autonomous_pulse_at, last_autonomous_world_at,
             daily_message_date, daily_message_count, created_at, updated_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13, :p14)
            ON CONFLICT(group_thread_id)
            DO UPDATE SET
                current_topic=excluded.current_topic,
                topic_source=excluded.topic_source,
                last_reply_to_message_id=excluded.last_reply_to_message_id,
                last_reply_to_character_id=excluded.last_reply_to_character_id,
                last_speaker_id=excluded.last_speaker_id,
                waiting_for_player=excluded.waiting_for_player,
                unresolved_hooks=excluded.unresolved_hooks,
                last_autonomous_pulse_at=excluded.last_autonomous_pulse_at,
                last_autonomous_world_at=excluded.last_autonomous_world_at,
                daily_message_date=excluded.daily_message_date,
                daily_message_count=excluded.daily_message_count,
                updated_at=excluded.updated_at
            """), {"p0": group_state["group_thread_id"], "p1": dialogue_turn["player_id"], "p2": group_state.get("current_topic"), "p3": group_state.get("topic_source"), "p4": last_reply_to_message_id, "p5": group_state.get("last_reply_to_character_id"), "p6": group_state.get("last_speaker_id"), "p7": int(bool(group_state.get("waiting_for_player"))), "p8": json.dumps(unresolved_hooks, ensure_ascii=False), "p9": group_state.get("last_autonomous_pulse_at"), "p10": group_state.get("last_autonomous_world_at"), "p11": group_state.get("daily_message_date"), "p12": int(group_state.get("daily_message_count") or 0), "p13": now, "p14": now})

    for background_job in dialogue_turn.get("background_jobs") or []:
        _enqueue_background_job_in_transaction(
            conn,
            job_type=background_job["job_type"],
            dedupe_key=background_job["dedupe_key"],
            payload=background_job["payload"],
            available_at=background_job.get("available_at"),
            now=now,
        )

    response_data = json.dumps(response, ensure_ascii=False)
    completed = conn.execute(text("""
        UPDATE dialogue_turn
        SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL,
            response_data = :p0, error = NULL, updated_at = :p1, completed_at = :p2
        WHERE session_id = :p3 AND request_id = :p4
          AND status = 'processing' AND lease_owner = :p5
          AND lease_expires_at > :p6
        """), {"p0": response_data, "p1": now, "p2": now, "p3": session_id, "p4": request_id, "p5": lease_owner, "p6": now})
    if completed.rowcount != 1:
        raise DialogueTurnConflictError("对话轮次租约已失效")
    return response


def commit_dialogue_turn(
    *,
    dialogue_turn: dict,
    runtime_states: list[dict] | None = None,
) -> dict | list:
    """Atomically persist a turn without an event execution batch."""
    now = _now()
    with db_session() as conn:
        _save_runtime_states_in_transaction(
            conn,
            player_id=dialogue_turn["player_id"],
            runtime_states=runtime_states,
            now=now,
        )
        return _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)


def commit_event_execution_batch(
    *,
    player_id: str,
    execution_key: str,
    trigger_source: str,
    results_data: str,
    executions: list[dict],
    runtime_states: list[dict] | None = None,
    schedule_completion: dict | None = None,
    dialogue_turn: dict | None = None,
) -> dict:
    """在一个数据库事务中提交整轮事件执行及全部数据库副作用。"""
    inserted_memories: list[dict] = []
    memory_curve_evidence: list[dict] = []
    now = _now()
    statuses = {execution["status"] for execution in executions}
    if not executions or statuses <= {"succeeded", "skipped"}:
        batch_status = "succeeded"
    elif statuses == {"failed"}:
        batch_status = "failed"
    else:
        batch_status = "partial"
    with db_session() as conn:
        cursor = conn.execute(text("""
            INSERT INTO event_execution_batch
            (player_id, execution_key, trigger_source, status, results_data,
             deduplicated_count, created_at, completed_at)
            VALUES (:p0, :p1, :p2, :p3, :p4, 0, :p5, :p6)
            ON CONFLICT(player_id, execution_key) DO NOTHING
            """), {"p0": player_id, "p1": execution_key, "p2": trigger_source, "p3": batch_status, "p4": results_data, "p5": now, "p6": now})
        if cursor.rowcount == 0:
            conn.execute(text("""
                UPDATE event_execution_batch
                SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
                WHERE player_id = :p0 AND execution_key = :p1
                """), {"p0": player_id, "p1": execution_key})
            row = conn.execute(text("""
                SELECT * FROM event_execution_batch
                WHERE player_id = :p0 AND execution_key = :p1
                """), {"p0": player_id, "p1": execution_key}).mappings().fetchone()
            if schedule_completion:
                _complete_event_schedule_in_transaction(
                    conn,
                    player_id=player_id,
                    schedule_completion=schedule_completion,
                    now=now,
                )
            for execution in executions:
                claim_token = execution.get("trigger_claim_token")
                if claim_token:
                    conn.execute(text("""
                        UPDATE event_trigger_guard
                        SET claim_token = NULL, claim_expires_at = NULL, updated_at = :p0
                        WHERE player_id = :p1 AND event_id = :p2 AND character_scope = :p3
                          AND claim_token = :p4
                        """), {"p0": now, "p1": player_id, "p2": execution["event_id"], "p3": execution.get("trigger_character_scope") or "", "p4": claim_token})
                exclusive_claim_token = execution.get(
                    "exclusive_group_claim_token"
                )
                if exclusive_claim_token:
                    conn.execute(text("""
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = :p0
                        WHERE player_id = :p1 AND exclusive_group = :p2
                          AND selected_event_id IS NULL AND claim_token = :p3
                        """), {"p0": now, "p1": player_id, "p2": execution["exclusive_group"], "p3": exclusive_claim_token})
            dialogue_response = (
                _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)
                if dialogue_turn
                else None
            )
            return {
                "deduplicated": True,
                "batch": dict(row),
                "inserted_memories": [],
                "dialogue_response": dialogue_response,
            }

        for execution in executions:
            conn.execute(text("""
                INSERT INTO event_execution
                (execution_id, execution_key, owner_user_id, event_id, character_id,
                 session_id, trigger_source, status, effects_data, result_data,
                 error, duration_ms, created_at, completed_at)
                VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11, :p12, :p13)
                """), {"p0": execution["execution_id"], "p1": execution_key, "p2": player_id, "p3": execution["event_id"], "p4": execution["character_id"], "p5": execution["session_id"], "p6": trigger_source, "p7": execution["status"], "p8": execution["effects_data"], "p9": execution["result_data"], "p10": execution.get("error"), "p11": float(execution.get("duration_ms") or 0.0), "p12": now, "p13": now})

            if execution["status"] != "succeeded":
                continue

            claim_token = execution.get("trigger_claim_token")
            if claim_token:
                consumed = conn.execute(text("""
                    UPDATE event_trigger_guard
                    SET last_triggered_at = :p0, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = :p1
                    WHERE player_id = :p2 AND event_id = :p3 AND character_scope = :p4
                      AND claim_token = :p5
                    """), {"p0": now, "p1": now, "p2": player_id, "p3": execution["event_id"], "p4": execution.get("trigger_character_scope") or "", "p5": claim_token})
                if consumed.rowcount != 1:
                    raise RuntimeError(
                        "event trigger claim was lost before atomic completion"
                    )

            exclusive_claim_token = execution.get(
                "exclusive_group_claim_token"
            )
            if exclusive_claim_token:
                selected = conn.execute(text("""
                    UPDATE event_exclusive_group_guard
                    SET selected_event_id = :p0, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = :p1
                    WHERE player_id = :p2 AND exclusive_group = :p3
                      AND selected_event_id IS NULL AND claim_token = :p4
                      AND EXISTS (
                          SELECT 1
                          FROM event_definition
                          WHERE owner_user_id = :p5
                            AND event_id = :p6
                            AND exclusive_scope = 'player'
                            AND exclusive_group = :p7
                      )
                    """), {"p0": execution["event_id"], "p1": now, "p2": player_id, "p3": execution["exclusive_group"], "p4": exclusive_claim_token, "p5": player_id, "p6": execution["event_id"], "p7": execution["exclusive_group"]})
                if selected.rowcount != 1:
                    released_stale = conn.execute(text("""
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = :p0
                        WHERE player_id = :p1 AND exclusive_group = :p2
                          AND selected_event_id IS NULL AND claim_token = :p3
                          AND NOT EXISTS (
                              SELECT 1
                              FROM event_definition
                              WHERE owner_user_id = :p4
                                AND event_id = :p5
                                AND exclusive_scope = 'player'
                                AND exclusive_group = :p6
                          )
                        """), {"p0": now, "p1": player_id, "p2": execution["exclusive_group"], "p3": exclusive_claim_token, "p4": player_id, "p5": execution["event_id"], "p6": execution["exclusive_group"]})
                    if released_stale.rowcount != 1:
                        raise RuntimeError(
                            "event exclusive group claim was lost before atomic completion"
                        )

            conn.execute(text("""
                INSERT INTO event_trigger_log
                (event_id, character_id, player_id, session_id, triggered_at,
                 context_snapshot, effects_applied, execution_id, status)
                VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, 'succeeded')
                """), {"p0": execution["event_id"], "p1": execution["character_id"], "p2": player_id, "p3": execution["session_id"], "p4": now, "p5": execution["context_snapshot"], "p6": execution["effects_applied"], "p7": execution["execution_id"]})
            conn.execute(text("""
                UPDATE event_definition
                SET trigger_count = trigger_count + 1, last_triggered_at = :p0
                WHERE owner_user_id = :p1 AND event_id = :p2
                """), {"p0": now, "p1": player_id, "p2": execution["event_id"]})

            context_state = execution.get("context_state")
            if context_state:
                conn.execute(text("""
                    INSERT INTO event_context_state
                    (event_id, character_id, player_id, context_data, status,
                     progress, last_session_id, created_at, updated_at)
                    VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8)
                    ON CONFLICT(event_id, character_id, player_id)
                    DO UPDATE SET
                        context_data=excluded.context_data,
                        status=excluded.status,
                        progress=excluded.progress,
                        last_session_id=excluded.last_session_id,
                        updated_at=excluded.updated_at
                    """), {"p0": execution["event_id"], "p1": execution["character_id"], "p2": player_id, "p3": context_state["context_data"], "p4": context_state["status"], "p5": context_state["progress"], "p6": execution["session_id"], "p7": now, "p8": now})

            for unlock_key in execution.get("unlock_keys") or []:
                conn.execute(text("""
                    INSERT INTO event_unlock
                    (player_id, character_id, unlock_key, event_id, unlocked_at)
                    VALUES (:p0, :p1, :p2, :p3, :p4)
                    ON CONFLICT(player_id, character_id, unlock_key) DO NOTHING
                    """), {"p0": player_id, "p1": execution["character_id"], "p2": unlock_key, "p3": execution["event_id"], "p4": now})

            for memory in execution.get("memories") or []:
                inserted = _insert_long_term_fact_in_transaction(conn, memory)
                if inserted:
                    inserted_memories.append(inserted)

            for claim in execution.get("fact_claims") or []:
                identity = derive_fact_claim_identity(
                    player_id,
                    claim["scope_type"],
                    claim["scope_id"],
                    claim["fact_text"],
                )
                _record_fact_claim_in_transaction(
                    conn,
                    claim_id=identity["claim_id"],
                    owner_user_id=player_id,
                    scope_type=claim["scope_type"],
                    scope_id=claim["scope_id"],
                    fact_text=claim["fact_text"],
                    normalized_fact_text=identity["normalized_fact_text"],
                    content_hash=identity["content_hash"],
                    normalized_content_hash=identity["normalized_content_hash"],
                    source_kind=claim["source_kind"],
                    source_ids=clean_source_ids(claim.get("source_ids") or []),
                    provenance=dict(claim.get("provenance") or {}),
                    direct_support=bool(claim.get("direct_support")),
                    verification_policy=lambda evidence, normalized=identity[
                        "normalized_fact_text"
                    ]: evaluate_verification(normalized, evidence),
                    event_context={
                        "correlation_id": execution["execution_id"],
                        "causation_id": execution["event_id"],
                        "session_id": claim.get("session_id"),
                        "world_occurred_at": claim.get("world_occurred_at"),
                        "metadata": {
                            "producer": "memoria.core.event_executor",
                        },
                    },
                )
                provenance = dict(claim.get("provenance") or {})
                witnesses = provenance.get("allowed_character_ids") or [
                    execution["character_id"]
                ]
                if claim.get("world_occurred_at"):
                    for witness in dict.fromkeys(witnesses):
                        memory_curve_evidence.append({
                            "owner_user_id": player_id,
                            "character_id": witness,
                            "memory_type": "player_fact",
                            "memory_id": identity["claim_id"],
                            "evidence_id": (
                                f"event:{execution['execution_id']}:"
                                f"{identity['claim_id']}"
                            ),
                            "world_occurred_at": claim["world_occurred_at"],
                            "source_kind": claim["source_kind"],
                            "importance": provenance.get("importance", 0.5),
                        })

            for story_update in execution.get("story_updates") or []:
                _apply_story_update_in_transaction(
                    conn,
                    player_id,
                    story_update,
                )

            for inbox_item in execution.get("inbox_items") or []:
                conn.execute(text("""
                    INSERT INTO player_event_inbox
                    (player_id, event_id, character_id, session_id, event_type,
                     title, content, payload, world_created_at, created_at)
                    VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9)
                    """), {"p0": player_id, "p1": execution["event_id"], "p2": execution["character_id"], "p3": inbox_item.get("session_id"), "p4": inbox_item.get("event_type", "event"), "p5": inbox_item.get("title"), "p6": inbox_item["content"], "p7": inbox_item.get("payload"), "p8": inbox_item.get("world_created_at"), "p9": now})

            for message in execution.get("proactive_messages") or []:
                target = conn.execute(text("""
                    SELECT 1
                    FROM session s
                    INNER JOIN multi_session_participant p
                      ON p.session_id = s.session_id
                     AND p.character_id = :p0
                     AND p.is_active = 1
                    WHERE s.session_id = :p1
                      AND s.player_id = :p2
                      AND s.is_multi_character = 1
                      AND s.status <> 'ended'
                    """), {"p0": message["character_id"], "p1": message["session_id"], "p2": player_id}).mappings().fetchone()
                if target is None:
                    raise RuntimeError(
                        "proactive dialogue target is not an owned active group participant"
                    )
                conn.execute(text("""
                    INSERT INTO short_term_message
                    (session_id, role, content, character_id, character_name,
                     created_at, knowledge_sources, world_created_at)
                    VALUES (:p0, 'assistant', :p1, :p2, :p3, :p4, :p5, :p6)
                    """), {"p0": message["session_id"], "p1": message["content"], "p2": message["character_id"], "p3": message.get("character_name"), "p4": now, "p5": _encode_knowledge_sources(message.get("knowledge_sources")), "p6": message.get("world_created_at")})
                conn.execute(text("""
                    UPDATE multi_session_participant
                    SET last_spoke_at = :p0, message_count = message_count + 1
                    WHERE session_id = :p1 AND character_id = :p2
                    """), {"p0": now, "p1": message["session_id"], "p2": message["character_id"]})

        _save_runtime_states_in_transaction(
            conn,
            player_id=player_id,
            runtime_states=runtime_states,
            now=now,
        )

        if schedule_completion:
            _complete_event_schedule_in_transaction(
                conn,
                player_id=player_id,
                schedule_completion=schedule_completion,
                now=now,
            )
        dialogue_response = (
            _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)
            if dialogue_turn
            else None
        )

    if configs.memory_curve_enabled:
        for evidence in memory_curve_evidence:
            try:
                record_memory_curve_evidence(**evidence)
            except Exception as exc:
                logger.warning("事件记忆曲线写入失败，保留事实账本: %s", exc)

    return {
        "deduplicated": False,
        "batch": {
            "player_id": player_id,
            "execution_key": execution_key,
            "results_data": results_data,
            "status": batch_status,
        },
        "inserted_memories": inserted_memories,
        "dialogue_response": dialogue_response,
    }


def list_event_unlocks(player_id: str, character_id: str) -> list[str]:
    with db_session() as conn:
        rows = conn.execute(text("""
            SELECT unlock_key FROM event_unlock
            WHERE player_id = :p0 AND character_id = :p1
            ORDER BY unlocked_at ASC, unlock_key ASC
            """), {"p0": player_id, "p1": character_id}).mappings().fetchall()
    return [row["unlock_key"] for row in rows]


def get_event_execution_metrics(
    owner_user_id: str,
    event_id: str | None = None,
) -> dict:
    with db_session() as conn:
        where = "owner_user_id = :owner_user_id"
        params: dict = {"owner_user_id": owner_user_id}
        if event_id:
            where += " AND event_id = :event_id"
            params["event_id"] = event_id
        aggregate = conn.execute(text(f"""
            SELECT
                COUNT(*) AS matched_count,
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count,
                AVG(duration_ms) AS average_duration_ms,
                MAX(completed_at) AS last_execution_at
            FROM event_execution
            WHERE {where}
            """), params).mappings().fetchone()
        last_error = conn.execute(text(f"""
            SELECT error FROM event_execution
            WHERE {where} AND error IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
            """), params).mappings().fetchone()
        if event_id:
            deduplicated = conn.execute(text("""
                SELECT COALESCE(SUM(batch.deduplicated_count), 0) AS count
                FROM event_execution_batch AS batch
                WHERE batch.player_id = :p0
                  AND EXISTS (
                      SELECT 1 FROM event_execution AS execution
                      WHERE execution.owner_user_id = batch.player_id
                        AND execution.execution_key = batch.execution_key
                        AND execution.event_id = :p1
                  )
                """), {"p0": owner_user_id, "p1": event_id}).mappings().fetchone()
        else:
            deduplicated = conn.execute(text("""
                SELECT COALESCE(SUM(deduplicated_count), 0) AS count
                FROM event_execution_batch WHERE player_id = :p0
                """), {"p0": owner_user_id}).mappings().fetchone()
    return {
        "matched_count": int(aggregate["matched_count"] or 0),
        "succeeded_count": int(aggregate["succeeded_count"] or 0),
        "failed_count": int(aggregate["failed_count"] or 0),
        "partial_count": int(aggregate["partial_count"] or 0),
        "skipped_count": int(aggregate["skipped_count"] or 0),
        "deduplicated_count": int(deduplicated["count"] or 0),
        "average_duration_ms": float(aggregate["average_duration_ms"] or 0.0),
        "last_execution_at": aggregate["last_execution_at"],
        "last_error": last_error["error"] if last_error else None,
    }

def delete_trigger_history(
    event_id: str,
    character_id: str,
    player_id: str,
) -> int:
    """
    删除某事件对特定玩家的所有触发记录
    返回删除的行数
    """
    with db_session() as conn:
        cur = conn.execute(text("""
            DELETE FROM event_trigger_log
            WHERE event_id = :p0 AND character_id = :p1 AND player_id = :p2
            """), {"p0": event_id, "p1": character_id, "p2": player_id})
        conn.execute(text("""
            DELETE FROM event_trigger_guard
            WHERE event_id = :p0 AND player_id = :p1
              AND character_scope IN (:p2, '')
            """), {"p0": event_id, "p1": player_id, "p2": character_id})
        conn.execute(text("""
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = :p0 AND selected_event_id = :p1
            """), {"p0": player_id, "p1": event_id})
        return cur.rowcount


# =========================
# 事件系统 - 上下文 / 调度 / 模板
# =========================
def save_event_context_state(
    event_id: str,
    character_id: str,
    player_id: str,
    context_data: str,
    status: str = "active",
    progress: float = 0.0,
    last_session_id: str = None,
) -> bool:
    """保存事件进度上下文，同一 event+character+player 只保留一条。"""
    try:
        with db_session() as conn:
            conn.execute(text("""
                INSERT INTO event_context_state
                (event_id, character_id, player_id, context_data, status, progress,
                 last_session_id, created_at, updated_at)
                VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8)
                ON CONFLICT(event_id, character_id, player_id)
                DO UPDATE SET
                    context_data=excluded.context_data,
                    status=excluded.status,
                    progress=excluded.progress,
                    last_session_id=excluded.last_session_id,
                    updated_at=excluded.updated_at
                """), {"p0": event_id, "p1": character_id, "p2": player_id, "p3": context_data, "p4": status, "p5": progress, "p6": last_session_id, "p7": _now(), "p8": _now()})
        return True
    except Exception as e:
        logger.error(f"保存事件上下文失败: {e}")
        return False


def get_event_context_state(event_id: str, character_id: str, player_id: str) -> dict | None:
    """获取指定事件上下文。"""
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT * FROM event_context_state
            WHERE event_id = :p0 AND character_id = :p1 AND player_id = :p2
            """), {"p0": event_id, "p1": character_id, "p2": player_id}).mappings().fetchone()
    return _row_to_dict(row)


def list_event_context_states(
    character_id: str = None,
    player_id: str = None,
    status: str = None,
    limit: int = 100,
) -> list[dict]:
    """列出事件上下文，可按角色、玩家和状态过滤。"""
    with db_session() as conn:
        query = "SELECT * FROM event_context_state WHERE 1=1"
        params: dict[str, Any] = {}
        if character_id:
            query += " AND character_id = :character_id"
            params["character_id"] = character_id
        if player_id:
            query += " AND player_id = :player_id"
            params["player_id"] = player_id
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY updated_at DESC LIMIT :limit"
        params["limit"] = limit
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(r) for r in rows]


def _save_event_schedule_state_in_transaction(
    conn,
    *,
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    next_run_at: str = None,
    next_due_real_at: str = None,
    last_checked_at: str = None,
    last_run_at: str = None,
    status: str = "active",
    missed_count: int = 0,
) -> None:
    now = _now()
    conn.execute(text("""
        INSERT INTO event_schedule_state
        (event_id, character_id, player_id, schedule, last_checked_at,
         last_run_at, next_run_at, next_due_real_at, missed_count,
         status, created_at, updated_at)
        VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8, :p9, :p10, :p11)
        ON CONFLICT(event_id, character_id, player_id)
        DO UPDATE SET
            schedule=excluded.schedule,
            last_checked_at=excluded.last_checked_at,
            last_run_at=excluded.last_run_at,
            next_run_at=excluded.next_run_at,
            next_due_real_at=excluded.next_due_real_at,
            missed_count=excluded.missed_count,
            status=excluded.status,
            updated_at=excluded.updated_at
        """), {"p0": event_id, "p1": character_id, "p2": player_id, "p3": schedule, "p4": last_checked_at, "p5": last_run_at, "p6": next_run_at, "p7": next_due_real_at, "p8": missed_count, "p9": status, "p10": now, "p11": now})


def _preserve_schedule_history(
    conn,
    owner_user_id: str,
    event_id: str,
    schedule: str | None,
) -> None:
    """保存定义保存时的调度历史：调度存在时保留注册的调度行。

    - 若定义带 schedule（直接保存），按定义重建调度行（upsert）。
    - 若定义不带 schedule 但已存在注册的调度行，保留原行（不删除）。
    - 若定义不带 schedule 且无注册调度，保留原行为（无调度）。
    """
    if schedule:
        _save_event_schedule_state_in_transaction(
            conn,
            event_id=event_id,
            character_id=None,
            player_id=owner_user_id,
            schedule=schedule,
        )
        return
    with conn.execute(text("""
        SELECT schedule FROM event_schedule_state
        WHERE event_id = :p0 AND player_id = :p1
        """), {"p0": event_id, "p1": owner_user_id}).mappings() as rows:
        existing = rows.fetchall()
    if not existing:
        return
    if len(existing) > 1:
        logger.warning(
            "事件 %s 存在多条调度记录，定义保存仅保留一条",
            event_id,
        )
        conn.execute(text("""
            DELETE FROM event_schedule_state
            WHERE event_id = :p0 AND player_id = :p1
              AND rowid NOT IN (
                SELECT MIN(rowid) FROM event_schedule_state
                WHERE event_id = :p0 AND player_id = :p1
              )
            """), {"p0": event_id, "p1": owner_user_id})
    # 保留注册的调度行（不删除）


def save_event_schedule_state(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    next_run_at: str = None,
    next_due_real_at: str = None,
    last_checked_at: str = None,
    last_run_at: str = None,
    status: str = "active",
    missed_count: int = 0,
) -> bool:
    """保存时间驱动事件的调度状态。"""
    try:
        with db_session() as conn:
            _save_event_schedule_state_in_transaction(
                conn,
                event_id=event_id,
                character_id=character_id,
                player_id=player_id,
                schedule=schedule,
                next_run_at=next_run_at,
                next_due_real_at=next_due_real_at,
                last_checked_at=last_checked_at,
                last_run_at=last_run_at,
                status=status,
                missed_count=missed_count,
            )
        return True
    except Exception as e:
        logger.error(f"保存事件调度状态失败: {e}")
        return False


def save_event_definition_with_schedule(
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    *,
    schedule_state: dict | None,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> bool:
    """Atomically save an event definition and its single schedule state."""
    try:
        with db_session() as conn:
            _save_event_definition_in_transaction(
                conn,
                owner_user_id=owner_user_id,
                event_id=event_id,
                event_name=event_name,
                trigger_config=trigger_config,
                effects_config=effects_config,
                character_id=character_id,
                description=description,
                priority=priority,
                exclusive_group=exclusive_group,
                exclusive_scope=exclusive_scope,
                max_triggers_per_turn=max_triggers_per_turn,
                stop_processing=stop_processing,
                is_active=is_active,
                schedule=schedule,
                template_id=template_id,
                story_id=story_id,
            )
            if schedule_state is not None:
                if schedule_state.get("event_id") != event_id:
                    raise ValueError("Schedule event_id does not match definition")
                if schedule_state.get("player_id") != owner_user_id:
                    raise ValueError("Schedule player_id does not match definition owner")

            if schedule_state is not None:
                _save_event_schedule_state_in_transaction(conn, **schedule_state)
            else:
                _preserve_schedule_history(conn, owner_user_id, event_id, schedule)
        return True
    except Exception as e:
        logger.error(f"原子保存事件定义和调度失败: {e}")
        return False


def list_due_event_schedules(
    now_iso: str,
    limit: int = 50,
    player_id: str | None = None,
    after: tuple[str, str, str, str] | None = None,
) -> list[dict]:
    """List schedules due against indexed real UTC time."""
    with db_session() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NOT NULL
              AND next_due_real_at <= :now_iso
        """
        params: dict[str, Any] = {"now_iso": now_iso}
        if player_id:
            query += " AND player_id = :player_id"
            params["player_id"] = player_id
        if after:
            query += """
                AND (next_due_real_at, event_id, character_id, player_id)
                    > (:after_0, :after_1, :after_2, :after_3)
            """
            params.update({
                "after_0": after[0],
                "after_1": after[1],
                "after_2": after[2],
                "after_3": after[3],
            })
        query += """
            ORDER BY next_due_real_at, event_id, character_id, player_id
            LIMIT :limit
        """
        params["limit"] = limit
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(r) for r in rows]


def list_active_event_schedules(
    limit: int = 500,
    player_id: str | None = None,
) -> list[dict]:
    """List active schedules for per-player world-time evaluation."""
    with db_session() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active' AND next_run_at IS NOT NULL
        """
        params: dict[str, Any] = {}
        if player_id:
            query += " AND player_id = :player_id"
            params["player_id"] = player_id
        query += " ORDER BY next_run_at ASC LIMIT :limit"
        params["limit"] = limit
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(row) for row in rows]


def list_event_schedules(
    player_id: str,
    event_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    with db_session() as conn:
        query = "SELECT * FROM event_schedule_state WHERE player_id = :player_id"
        params: dict[str, Any] = {"player_id": player_id}
        if event_id:
            query += " AND event_id = :event_id"
            params["event_id"] = event_id
        if status:
            query += " AND status = :status"
            params["status"] = status
        query += " ORDER BY next_run_at ASC, updated_at DESC LIMIT :limit"
        params["limit"] = max(1, min(limit, 1000))
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(row) for row in rows]


def get_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
) -> dict | None:
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT * FROM event_schedule_state
            WHERE event_id = :p0 AND character_id = :p1 AND player_id = :p2
            """), {"p0": event_id, "p1": character_id, "p2": player_id}).mappings().fetchone()
    return _row_to_dict(row)


def set_event_schedule_status(
    event_id: str,
    character_id: str,
    player_id: str,
    status: str,
    *,
    next_run_at: str | None = None,
) -> bool:
    if status not in {"active", "paused"}:
        raise ValueError("schedule status must be active or paused")
    with db_session() as conn:
        if next_run_at is None:
            cursor = conn.execute(text("""
                UPDATE event_schedule_state
                SET status = :p0, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = :p1
                WHERE event_id = :p2 AND character_id = :p3 AND player_id = :p4
                """), {"p0": status, "p1": _now(), "p2": event_id, "p3": character_id, "p4": player_id})
        else:
            cursor = conn.execute(text("""
                UPDATE event_schedule_state
                SET status = :p0, next_run_at = :p1, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = :p2
                WHERE event_id = :p3 AND character_id = :p4 AND player_id = :p5
                """), {"p0": status, "p1": next_run_at, "p2": _now(), "p3": event_id, "p4": character_id, "p5": player_id})
    return cursor.rowcount == 1


def delete_event_schedules(
    event_id: str,
    player_id: str,
    character_id: str | None = None,
) -> int:
    """Delete schedules owned by a player, optionally for one character."""
    with db_session() as conn:
        if character_id is None:
            cursor = conn.execute(text("""DELETE FROM event_schedule_state WHERE event_id = :p0 AND player_id = :p1"""), {"p0": event_id, "p1": player_id})
        else:
            cursor = conn.execute(text("""
                DELETE FROM event_schedule_state
                WHERE event_id = :p0 AND character_id = :p1 AND player_id = :p2
                """), {"p0": event_id, "p1": character_id, "p2": player_id})
    return cursor.rowcount


def claim_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    lease_expires_at: str,
    real_now_iso: str,
    expected_next_run_at: str,
    expected_next_due_real_at: str | None = None,
) -> bool:
    """Conditionally claim a schedule using a real-UTC lease.

    若上次执行失败（``last_failed_at`` 在 60 秒内），拒绝立即重试，
    避免失败调度以 30 秒间隔无限重跑烧 LLM。
    """
    backoff_cutoff = (
        datetime.now(timezone.utc) - timedelta(seconds=60)
    ).isoformat()
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_schedule_state
            SET lease_owner = :p0, lease_expires_at = :p1, updated_at = :p2
            WHERE event_id = :p3 AND character_id = :p4 AND player_id = :p5
              AND status = 'active'
              AND next_run_at = :p6
              AND (
                next_due_real_at = :p7
                OR (next_due_real_at IS NULL AND CAST(:p8 AS TEXT) IS NULL)
              )
              AND (lease_expires_at IS NULL OR lease_expires_at <= :p9)
              AND (
                last_failed_at IS NULL
                OR last_failed_at <= :p10
              )
            """), {"p0": lease_owner, "p1": lease_expires_at, "p2": real_now_iso, "p3": event_id, "p4": character_id, "p5": player_id, "p6": expected_next_run_at, "p7": expected_next_due_real_at, "p8": expected_next_due_real_at, "p9": real_now_iso, "p10": backoff_cutoff})
    return cursor.rowcount == 1


def complete_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    last_checked_at: str,
    last_run_at: str,
    next_run_at: str,
    next_due_real_at: str | None = None,
    missed_count: int = 0,
) -> bool:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_schedule_state
            SET last_checked_at = :p0, last_run_at = :p1, next_run_at = :p2,
                next_due_real_at = :p3, missed_count = :p4,
                lease_owner = NULL, lease_expires_at = NULL,
                last_error = NULL, last_failed_at = NULL, updated_at = :p5
            WHERE event_id = :p6 AND character_id = :p7 AND player_id = :p8
              AND lease_owner = :p9
            """), {"p0": last_checked_at, "p1": last_run_at, "p2": next_run_at, "p3": next_due_real_at, "p4": missed_count, "p5": _now(), "p6": event_id, "p7": character_id, "p8": player_id, "p9": lease_owner})
    return cursor.rowcount == 1


def get_next_event_schedule(player_id: str) -> dict | None:
    """Return the player's earliest active schedule for clock UI display."""
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT s.*, d.event_name
            FROM event_schedule_state s
            LEFT JOIN event_definition d
              ON d.owner_user_id = s.player_id AND d.event_id = s.event_id
            WHERE s.player_id = :p0 AND s.status = 'active'
              AND s.next_run_at IS NOT NULL
            ORDER BY
              CASE WHEN s.next_due_real_at IS NULL THEN 1 ELSE 0 END,
              s.next_due_real_at ASC,
              s.next_run_at ASC
            LIMIT 1
            """), {"p0": player_id}).mappings().fetchone()
    return _row_to_dict(row)


def list_event_schedules_for_player(player_id: str) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(text("""
            SELECT * FROM event_schedule_state
            WHERE player_id = :p0
            ORDER BY next_run_at ASC
            """), {"p0": player_id}).mappings().fetchall()
    return [dict(row) for row in rows]


def list_event_schedules_missing_due_projection(
    player_id: str | None = None,
) -> list[dict]:
    """Return active schedules that need a real-time due projection."""
    with db_session() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NULL
        """
        params: dict[str, Any] = {}
        if player_id:
            query += " AND player_id = :player_id"
            params["player_id"] = player_id
        query += " ORDER BY player_id, next_run_at"
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(row) for row in rows]


def set_event_schedule_due_projection(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    expected_next_run_at: str,
    next_due_real_at: str,
) -> bool:
    """Backfill a missing projection without changing schedule ownership."""
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_schedule_state
            SET next_due_real_at = :p0, updated_at = :p1
            WHERE event_id = :p2 AND character_id = :p3 AND player_id = :p4
              AND status = 'active'
              AND next_run_at = :p5
              AND next_due_real_at IS NULL
            """), {"p0": next_due_real_at, "p1": _now(), "p2": event_id, "p3": character_id, "p4": player_id, "p5": expected_next_run_at})
    return cursor.rowcount == 1


def fail_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    error: str,
    failed_at: str,
) -> bool:
    """Record a scheduler failure and release only the current worker's lease."""
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_schedule_state
            SET last_error = :p0, last_failed_at = :p1, lease_owner = NULL,
                lease_expires_at = NULL, updated_at = :p2
            WHERE event_id = :p3 AND character_id = :p4 AND player_id = :p5
              AND lease_owner = :p6
            """), {"p0": error[:2000], "p1": failed_at, "p2": _now(), "p3": event_id, "p4": character_id, "p5": player_id, "p6": lease_owner})
    return cursor.rowcount == 1


def release_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
) -> bool:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE event_schedule_state
            SET lease_owner = NULL, lease_expires_at = NULL, updated_at = :p0
            WHERE event_id = :p1 AND character_id = :p2 AND player_id = :p3
              AND lease_owner = :p4
            """), {"p0": _now(), "p1": event_id, "p2": character_id, "p3": player_id, "p4": lease_owner})
    return cursor.rowcount == 1


def get_latest_active_multi_session(player_id: str) -> dict | None:
    """Return the player's most recently active group session."""
    with db_session() as conn:
        row = conn.execute(text("""
            SELECT
                s.*,
                (
                    SELECT created_at
                    FROM short_term_message
                    WHERE session_id = s.session_id
                    ORDER BY id DESC
                    LIMIT 1
                ) AS last_message_at
            FROM session s
            WHERE s.player_id = :p0
              AND s.status = 'active'
              AND COALESCE(s.is_multi_character, 0) = 1
            ORDER BY COALESCE(
                (SELECT created_at FROM short_term_message
                 WHERE session_id = s.session_id ORDER BY id DESC LIMIT 1),
                s.created_at) DESC
            LIMIT 1
            """), {"p0": player_id}).mappings().fetchone()
    return _row_to_dict(row)


def enqueue_player_event(
    player_id: str,
    content: str,
    *,
    event_id: str | None = None,
    character_id: str | None = None,
    session_id: str | None = None,
    event_type: str = "event",
    group_thread_id: str | None = None,
    unread_count: int = 0,
    title: str | None = None,
    payload: str | None = None,
    world_created_at: str | None = None,
) -> int:
    with db_session() as conn:
        sql = """
            INSERT INTO player_event_inbox
            (player_id, event_id, character_id, session_id, event_type,
             group_thread_id, unread_count, title, content, payload,
             world_created_at, created_at)
            VALUES (:player_id, :event_id, :character_id, :session_id,
                    :event_type, :group_thread_id, :unread_count, :title,
                    :content, :payload, :world_created_at, :created_at)
        """
        if _is_postgres_enabled():
            sql += " RETURNING id"
        cursor = conn.execute(
            text(sql),
            {
                "player_id": player_id,
                "event_id": event_id,
                "character_id": character_id,
                "session_id": session_id,
                "event_type": event_type,
                "group_thread_id": group_thread_id,
                "unread_count": max(0, int(unread_count or 0)),
                "title": title,
                "content": content,
                "payload": payload,
                "world_created_at": world_created_at,
                "created_at": _now(),
            },
        )
        return cursor.mappings().fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid


def _upsert_group_message_notification_in_transaction(
    conn,
    player_id: str,
    group_thread_id: str,
    session_id: str,
    new_message_count: int,
    *,
    group_name: str | None = None,
    world_created_at: str | None = None,
) -> int:
    """每个逻辑群聊只保留一条未读聚合通知。"""
    increment = max(0, int(new_message_count or 0))
    if increment <= 0:
        return 0

    row = conn.execute(text("""
        SELECT id, unread_count
        FROM player_event_inbox
        WHERE player_id = :p0 AND event_type = 'group_message'
          AND group_thread_id = :p1 AND read_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """), {"p0": player_id, "p1": group_thread_id}).mappings().fetchone()
    if row:
        unread_count = int(row["unread_count"] or 0) + increment
        conn.execute(text("""
            UPDATE player_event_inbox
            SET session_id = :p0, unread_count = :p1, content = :p2, title = :p3,
                world_created_at = :p4, created_at = :p5, payload = :p6
            WHERE id = :p7
            """), {"p0": session_id, "p1": unread_count, "p2": f"群聊中有 {unread_count} 条新消息", "p3": group_name or "群聊新消息", "p4": world_created_at, "p5": _now(), "p6": json.dumps(
                    {"group_thread_id": group_thread_id, "unread_count": unread_count},
                    ensure_ascii=False,
                ), "p7": row["id"]})
        return int(row["id"])

    sql = """
        INSERT INTO player_event_inbox
        (player_id, session_id, event_type, group_thread_id, unread_count,
         title, content, payload, world_created_at, created_at)
        VALUES (:player_id, :session_id, 'group_message', :group_thread_id,
                :unread_count, :title, :content, :payload, :world_created_at,
                :created_at)
    """
    if _is_postgres_enabled():
        sql += " RETURNING id"
    cursor = conn.execute(
        text(sql),
        {
            "player_id": player_id,
            "session_id": session_id,
            "group_thread_id": group_thread_id,
            "unread_count": increment,
            "title": group_name or "群聊新消息",
            "content": f"群聊中有 {increment} 条新消息",
            "payload": json.dumps(
                {"group_thread_id": group_thread_id, "unread_count": increment},
                ensure_ascii=False,
            ),
            "world_created_at": world_created_at,
            "created_at": _now(),
        },
    )
    return int(cursor.mappings().fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid)


def upsert_group_message_notification(
    player_id: str,
    group_thread_id: str,
    session_id: str,
    new_message_count: int,
    *,
    group_name: str | None = None,
    world_created_at: str | None = None,
) -> int:
    with db_session() as conn:
        return _upsert_group_message_notification_in_transaction(
            conn,
            player_id,
            group_thread_id,
            session_id,
            new_message_count,
            group_name=group_name,
            world_created_at=world_created_at,
        )


def list_player_event_inbox(
    player_id: str,
    *,
    unread_only: bool = True,
    limit: int = 50,
) -> list[dict]:
    with db_session() as conn:
        unread_clause = "AND read_at IS NULL" if unread_only else ""
        rows = conn.execute(text(f"""
            SELECT * FROM player_event_inbox
            WHERE player_id = :p0 {unread_clause}
            ORDER BY id DESC
            LIMIT :p1
            """), {"p0": player_id, "p1": limit}).mappings().fetchall()
    return [dict(row) for row in rows]


def mark_player_event_read(player_id: str, inbox_id: int) -> bool:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, :p0)
            WHERE id = :p1 AND player_id = :p2
            """), {"p0": _now(), "p1": inbox_id, "p2": player_id})
    return cursor.rowcount == 1


def mark_group_thread_notifications_read(player_id: str, group_thread_id: str) -> int:
    with db_session() as conn:
        cursor = conn.execute(text("""
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, :p0)
            WHERE player_id = :p1 AND event_type = 'group_message'
              AND group_thread_id = :p2 AND read_at IS NULL
            """), {"p0": _now(), "p1": player_id, "p2": group_thread_id})
    return cursor.rowcount


def save_event_template(
    template_id: str,
    template_name: str,
    category: str,
    description: str,
    trigger_config: str,
    effects_config: str,
    metadata: str = None,
) -> bool:
    """保存事件模板。"""
    try:
        with db_session() as conn:
            conn.execute(text("""
                INSERT INTO event_template
                (template_id, template_name, category, description, trigger_config,
                 effects_config, metadata, created_at, updated_at)
                VALUES (:p0, :p1, :p2, :p3, :p4, :p5, :p6, :p7, :p8)
                ON CONFLICT(template_id)
                DO UPDATE SET
                    template_name=excluded.template_name,
                    category=excluded.category,
                    description=excluded.description,
                    trigger_config=excluded.trigger_config,
                    effects_config=excluded.effects_config,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """), {"p0": template_id, "p1": template_name, "p2": category, "p3": description, "p4": trigger_config, "p5": effects_config, "p6": metadata, "p7": _now(), "p8": _now()})
        return True
    except Exception as e:
        logger.error(f"保存事件模板失败: {e}")
        return False


def list_event_templates(category: str = None) -> list[dict]:
    """列出事件模板。"""
    with db_session() as conn:
        query = "SELECT * FROM event_template WHERE 1=1"
        params: dict[str, Any] = {}
        if category:
            query += " AND category = :category"
            params["category"] = category
        query += " ORDER BY category ASC, template_name ASC"
        rows = conn.execute(text(query), params).mappings().fetchall()
    return [dict(r) for r in rows]


def get_event_template(template_id: str) -> dict | None:
    """获取事件模板。"""
    with db_session() as conn:
        row = conn.execute(text("""SELECT * FROM event_template WHERE template_id = :p0"""), {"p0": template_id}).mappings().fetchone()
    return _row_to_dict(row)


def delete_event_template(template_id: str) -> bool:
    """删除事件模板。"""
    with db_session() as conn:
        cursor = conn.execute(text("""DELETE FROM event_template WHERE template_id = :p0"""), {"p0": template_id})
    return cursor.rowcount > 0
