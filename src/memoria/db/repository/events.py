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
    conn.execute(
        """
        INSERT INTO event_definition
        (owner_user_id, event_id, event_name, description, character_id, story_id, trigger_config,
         effects_config, priority, exclusive_group, exclusive_scope, max_triggers_per_turn,
         stop_processing, is_active, created_at, updated_at, schedule, template_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        """,
        (
            owner_user_id,
            event_id,
            event_name,
            description,
            character_id,
            story_id,
            trigger_config,
            effects_config,
            priority,
            exclusive_group,
            exclusive_scope,
            max_triggers_per_turn,
            1 if stop_processing else 0,
            1 if is_active else 0,
            now,
            now,
            schedule,
            template_id,
        ),
    )
    if exclusive_scope == "player" and exclusive_group:
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
              AND exclusive_group <> ?
            """,
            (owner_user_id, event_id, exclusive_group),
        )
    else:
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
            """,
            (owner_user_id, event_id),
        )


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
        with get_conn() as conn:
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
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM event_definition WHERE owner_user_id = ? AND event_id = ?",
            (owner_user_id, event_id),
        ).fetchone()
    return _row_to_dict(row)

def list_event_definitions(
    owner_user_id: str,
    character_id: str = None,
    only_active: bool = True
) -> list[dict]:
    """列出事件定义"""
    with get_conn() as conn:
        query = "SELECT * FROM event_definition WHERE owner_user_id = ?"
        params = [owner_user_id]

        if character_id is not None:
            query += " AND (character_id = ? OR character_id IS NULL)"
            params.append(character_id)

        if only_active:
            query += " AND is_active = 1"

        query += " ORDER BY priority DESC, created_at DESC"

        rows = conn.execute(query, params).fetchall()

    return [dict(r) for r in rows]

def delete_event_definition(owner_user_id: str, event_id: str) -> bool:
    """Delete an event definition and its operational trigger state."""
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM event_schedule_state WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_context_state WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_trigger_log WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_trigger_guard WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                """
                DELETE FROM event_exclusive_group_guard
                WHERE player_id = ? AND selected_event_id = ?
                """,
                (owner_user_id, event_id),
            )
            deleted = conn.execute(
                "DELETE FROM event_definition WHERE owner_user_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
        return deleted.rowcount == 1
    except Exception as e:
        logger.error(f"删除事件定义失败: {e}")
        return False

def increment_event_trigger_count(owner_user_id: str, event_id: str):
    """增加事件触发计数"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE event_definition
            SET trigger_count = trigger_count + 1,
                last_triggered_at = ?
            WHERE owner_user_id = ? AND event_id = ?
            """,
            (_now(), owner_user_id, event_id),
        )


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
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO event_trigger_log
            (event_id, character_id, player_id, session_id, 
             triggered_at, context_snapshot, effects_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, character_id, player_id, session_id,
             _now(), context_snapshot, effects_applied),
        )

def get_event_trigger_history(
    event_id: str = None,
    character_id: str = None,
    player_id: str = None,
    limit: int = 50
) -> list[dict]:
    """获取事件触发历史"""
    with get_conn() as conn:
        query = "SELECT * FROM event_trigger_log WHERE 1=1"
        params = []
        
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        
        query += " ORDER BY triggered_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
    
    return [dict(r) for r in rows]

def get_last_trigger_time(event_id: str, character_id: str | None, player_id: str) -> str | None:
    """获取事件最后触发时间（用于冷却时间判断）"""
    with get_conn() as conn:
        if character_id is None:
            row = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = ? AND player_id = ? AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (event_id, player_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (event_id, character_id, player_id),
            ).fetchone()

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
    with get_conn() as conn:
        if scope:
            legacy = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = ? AND event_id = ? AND character_id = ?
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (player_id, event_id, scope),
            ).fetchone()
        else:
            legacy = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = ? AND event_id = ? AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (player_id, event_id),
            ).fetchone()
        legacy_last_triggered_at = legacy["triggered_at"] if legacy else None
        conn.execute(
            """
            INSERT INTO event_trigger_guard
            (player_id, event_id, character_scope, last_triggered_at,
             claim_token, claim_expires_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, ?)
            ON CONFLICT(player_id, event_id, character_scope) DO NOTHING
            """,
            (
                player_id,
                event_id,
                scope,
                legacy_last_triggered_at,
                claimed_at,
            ),
        )
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(
            """
            SELECT last_triggered_at, claim_token, claim_expires_at
            FROM event_trigger_guard
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
            """ + lock_suffix,
            (player_id, event_id, scope),
        ).fetchone()
        last_triggered_at = row["last_triggered_at"] or legacy_last_triggered_at
        if not row["last_triggered_at"] and legacy_last_triggered_at:
            conn.execute(
                """
                UPDATE event_trigger_guard
                SET last_triggered_at = ?, updated_at = ?
                WHERE player_id = ? AND event_id = ? AND character_scope = ?
                """,
                (
                    legacy_last_triggered_at,
                    claimed_at,
                    player_id,
                    event_id,
                    scope,
                ),
            )

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

        cursor = conn.execute(
            """
            UPDATE event_trigger_guard
            SET claim_token = ?, claim_expires_at = ?, updated_at = ?
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
            """,
            (
                claim_token,
                claim_expires_at,
                claimed_at,
                player_id,
                event_id,
                scope,
            ),
        )
        return cursor.rowcount == 1


def release_event_trigger_guard(
    *,
    player_id: str,
    event_id: str,
    character_scope: str,
    claim_token: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_trigger_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
              AND claim_token = ?
            """,
            (_now(), player_id, event_id, character_scope or "", claim_token),
        )
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
    with get_conn() as conn:
        if not _is_postgres_enabled():
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO event_exclusive_group_guard
            (player_id, exclusive_group, selected_event_id, claim_token,
             claim_expires_at, updated_at)
            VALUES (?, ?, NULL, NULL, NULL, ?)
            ON CONFLICT(player_id, exclusive_group) DO NOTHING
            """,
            (player_id, exclusive_group, claimed_at),
        )
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(
            """
            SELECT selected_event_id, claim_token, claim_expires_at
            FROM event_exclusive_group_guard
            WHERE player_id = ? AND exclusive_group = ?
            """ + lock_suffix,
            (player_id, exclusive_group),
        ).fetchone()
        if row["selected_event_id"]:
            return False

        legacy_selection = conn.execute(
            """
            SELECT trigger_log.event_id
            FROM event_trigger_log AS trigger_log
            INNER JOIN event_definition AS definition
              ON definition.owner_user_id = trigger_log.player_id
             AND definition.event_id = trigger_log.event_id
            WHERE trigger_log.player_id = ?
              AND trigger_log.status = 'succeeded'
              AND definition.exclusive_group = ?
              AND definition.exclusive_scope = 'player'
            ORDER BY
              CASE WHEN trigger_log.triggered_at IS NULL THEN 1 ELSE 0 END,
              trigger_log.triggered_at ASC,
              trigger_log.id ASC
            LIMIT 1
            """,
            (player_id, exclusive_group),
        ).fetchone()
        if legacy_selection:
            conn.execute(
                """
                UPDATE event_exclusive_group_guard
                SET selected_event_id = ?, claim_token = NULL,
                    claim_expires_at = NULL, updated_at = ?
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (
                    legacy_selection["event_id"],
                    claimed_at,
                    player_id,
                    exclusive_group,
                ),
            )
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

        cursor = conn.execute(
            """
            UPDATE event_exclusive_group_guard
            SET claim_token = ?, claim_expires_at = ?, updated_at = ?
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NULL
            """,
            (
                claim_token,
                claim_expires_at,
                claimed_at,
                player_id,
                exclusive_group,
            ),
        )
        return cursor.rowcount == 1


def release_event_exclusive_group(
    *,
    player_id: str,
    exclusive_group: str,
    claim_token: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_exclusive_group_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NULL AND claim_token = ?
            """,
            (_now(), player_id, exclusive_group, claim_token),
        )
    return cursor.rowcount == 1


def get_event_exclusive_group_selection(
    player_id: str,
    exclusive_group: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_exclusive_group_guard
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NOT NULL
            """,
            (player_id, exclusive_group),
        ).fetchone()
    return _row_to_dict(row)


def get_event_execution_batch(player_id: str, execution_key: str) -> dict | None:
    """读取已完成的事件批次，用于请求重放。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_execution_batch
            WHERE player_id = ? AND execution_key = ?
            """,
            (player_id, execution_key),
        ).fetchone()
    return _row_to_dict(row)


def increment_event_execution_batch_deduplicated(
    player_id: str,
    execution_key: str,
) -> bool:
    """记录一次命中已完成批次的幂等重放。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_execution_batch
            SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
            WHERE player_id = ? AND execution_key = ?
            """,
            (player_id, execution_key),
        )
    return cursor.rowcount == 1


def get_event_execution(
    owner_user_id: str,
    event_id: str,
    execution_key: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_execution
            WHERE owner_user_id = ? AND event_id = ? AND execution_key = ?
            """,
            (owner_user_id, event_id, execution_key),
        ).fetchone()
    return _row_to_dict(row)


def list_event_execution_history(
    owner_user_id: str,
    character_id: str | None = None,
    event_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent auditable event outcomes for condition evaluation."""
    with get_conn() as conn:
        query = """
            SELECT execution_id, execution_key, event_id, character_id,
                   session_id, trigger_source, status, error, duration_ms,
                   created_at, completed_at
            FROM event_execution
            WHERE owner_user_id = ?
        """
        params: list[Any] = [owner_user_id]
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        query += " ORDER BY completed_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = conn.execute(query, params).fetchall()
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
        "character_id = ? AND player_id = ?",
        (character_id, player_id),
        threshold=0.75,
    )
    now = _now()
    if existing:
        conn.execute(
            "UPDATE long_term_fact SET importance = ?, last_referenced = ? WHERE id = ?",
            (max(existing.get("importance", 0), importance), now, existing["id"]),
        )
        return None

    insert_sql = """
        INSERT INTO long_term_fact
        (character_id, player_id, fact_text, importance, created_at, last_referenced)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    if _is_postgres_enabled():
        insert_sql += " RETURNING id"
    cursor = conn.execute(
        insert_sql,
        (character_id, player_id, fact_text, importance, now, now),
    )
    fact_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
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
    completed = conn.execute(
        """
        UPDATE event_schedule_state
        SET last_checked_at = ?, last_run_at = ?, next_run_at = ?,
            next_due_real_at = ?, missed_count = ?,
            lease_owner = NULL, lease_expires_at = NULL,
            last_error = NULL, last_failed_at = NULL, updated_at = ?
        WHERE event_id = ? AND character_id = ? AND player_id = ?
          AND lease_owner = ?
        """,
        (
            schedule_completion["last_checked_at"],
            schedule_completion["last_run_at"],
            schedule_completion["next_run_at"],
            schedule_completion.get("next_due_real_at"),
            int(schedule_completion.get("missed_count") or 0),
            now,
            schedule_completion["event_id"],
            schedule_completion["character_id"],
            player_id,
            schedule_completion["lease_owner"],
        ),
    )
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
    with get_conn() as conn:
        if _is_postgres_enabled():
            conn.execute(
                "SELECT session_id FROM session WHERE session_id = ? FOR UPDATE",
                (session_id,),
            ).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT * FROM dialogue_turn
            WHERE session_id = ? AND request_id = ?
            """,
            (session_id, request_id),
        ).fetchone()
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

        active = conn.execute(
            """
            SELECT request_id
            FROM dialogue_turn
            WHERE session_id = ? AND status = 'processing'
              AND lease_expires_at > ? AND request_id <> ?
            LIMIT 1
            """,
            (session_id, now_iso, request_id),
        ).fetchone()
        if active:
            raise DialogueTurnConflictError("该会话已有消息正在处理中")

        conn.execute(
            """
            INSERT INTO dialogue_turn
            (session_id, request_id, player_id, turn_kind, status,
             lease_owner, lease_expires_at, response_data, error,
             created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, 'processing', ?, ?, NULL, NULL, ?, ?, NULL)
            ON CONFLICT(session_id, request_id)
            DO UPDATE SET
                status='processing',
                lease_owner=excluded.lease_owner,
                lease_expires_at=excluded.lease_expires_at,
                response_data=NULL,
                error=NULL,
                updated_at=excluded.updated_at,
                completed_at=NULL
            """,
            (
                session_id,
                request_id,
                player_id,
                turn_kind,
                lease_owner,
                lease_expires_at,
                now_iso,
                now_iso,
            ),
        )
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
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE dialogue_turn
            SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                error = ?, updated_at = ?
            WHERE session_id = ? AND request_id = ?
              AND status = 'processing' AND lease_owner = ?
            """,
            (error[:1000], _now(), session_id, request_id, lease_owner),
        )


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
        conn.execute(
            """
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id, player_id) DO NOTHING
            """,
            (
                character_id,
                player_id,
                affection_level,
                trust_level,
                current_mood,
                now,
            ),
        )
        for changes in state_changes:
            assignments: list[str] = []
            parameters: list[Any] = []
            if "affection_level" in changes:
                delta = float(changes["affection_level"])
                assignments.append(
                    """
                    affection_level = CASE
                        WHEN affection_level + ? < -100 THEN -100
                        WHEN affection_level + ? > 100 THEN 100
                        ELSE affection_level + ?
                    END
                    """
                )
                parameters.extend([delta, delta, delta])
            if "trust_level" in changes:
                delta = float(changes["trust_level"])
                assignments.append(
                    """
                    trust_level = CASE
                        WHEN trust_level + ? < 0 THEN 0
                        WHEN trust_level + ? > 100 THEN 100
                        ELSE trust_level + ?
                    END
                    """
                )
                parameters.extend([delta, delta, delta])
            if "current_mood" in changes:
                assignments.append("current_mood = ?")
                parameters.append(str(changes["current_mood"]))
            if not assignments:
                continue
            parameters.extend([now, character_id, player_id])
            conn.execute(
                f"""
                UPDATE relationship_state
                SET {", ".join(assignments)}, updated_at = ?
                WHERE character_id = ? AND player_id = ?
                """,
                parameters,
            )
        row = conn.execute(
            """
            SELECT affection_level, trust_level, current_mood
            FROM relationship_state
            WHERE character_id = ? AND player_id = ?
            """,
            (character_id, player_id),
        ).fetchone()
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
        conn.execute(
            f"""
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id, player_id)
            {relationship_state_conflict}
            """,
            (
                character_id,
                player_id,
                affection_level,
                trust_level,
                current_mood,
                now,
            ),
        )
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
    conn.execute(
        f"""
        INSERT INTO character_relationship
        (owner_user_id, character_id_a, character_id_b, relationship_type,
         affinity, description, created_at, updated_at)
        VALUES (?, ?, ?, '相识', ?, NULL, ?, ?)
        ON CONFLICT(owner_user_id, character_id_a, character_id_b)
        {relationship_conflict}
        """,
        (
            player_id,
            player_id_node,
            character_id_node,
            affection_level,
            now,
            now,
        ),
    )


def _commit_dialogue_turn_in_transaction(
    conn,
    dialogue_turn: dict,
    *,
    now: str,
) -> dict | list:
    session_id = dialogue_turn["session_id"]
    request_id = dialogue_turn["request_id"]
    lease_owner = dialogue_turn["lease_owner"]
    row = conn.execute(
        """
        SELECT status, lease_owner, lease_expires_at, response_data
        FROM dialogue_turn
        WHERE session_id = ? AND request_id = ?
        """,
        (session_id, request_id),
    ).fetchone()
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            insert_sql,
            (
                session_id,
                message["role"],
                message["content"],
                message.get("character_id"),
                message.get("character_name"),
                message.get("action"),
                message.get("affinity_delta"),
                message.get("trust_delta"),
                message.get("current_affinity"),
                message.get("current_trust"),
                message.get("current_mood"),
                message.get("event_notification"),
                _encode_knowledge_sources(message.get("knowledge_sources")),
                reply_to_message_id,
                message.get("reply_to_character_id"),
                message.get("intent"),
                message.get("topic"),
                message.get("trigger_source"),
                now,
                message.get("world_created_at"),
            ),
        )
        message_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
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
            conn.execute(
                """
                UPDATE multi_session_participant
                SET last_spoke_at = ?, message_count = message_count + 1
                WHERE session_id = ? AND character_id = ?
                """,
                (now, session_id, message["character_id"]),
            )

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
        conn.execute(
            """
            INSERT INTO group_dialogue_state
            (group_thread_id, player_id, current_topic, topic_source,
             last_reply_to_message_id, last_reply_to_character_id,
             last_speaker_id, waiting_for_player, unresolved_hooks,
             last_autonomous_pulse_at, last_autonomous_world_at,
             daily_message_date, daily_message_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            """,
            (
                group_state["group_thread_id"],
                dialogue_turn["player_id"],
                group_state.get("current_topic"),
                group_state.get("topic_source"),
                last_reply_to_message_id,
                group_state.get("last_reply_to_character_id"),
                group_state.get("last_speaker_id"),
                int(bool(group_state.get("waiting_for_player"))),
                json.dumps(unresolved_hooks, ensure_ascii=False),
                group_state.get("last_autonomous_pulse_at"),
                group_state.get("last_autonomous_world_at"),
                group_state.get("daily_message_date"),
                int(group_state.get("daily_message_count") or 0),
                now,
                now,
            ),
        )

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
    completed = conn.execute(
        """
        UPDATE dialogue_turn
        SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL,
            response_data = ?, error = NULL, updated_at = ?, completed_at = ?
        WHERE session_id = ? AND request_id = ?
          AND status = 'processing' AND lease_owner = ?
          AND lease_expires_at > ?
        """,
        (
            response_data,
            now,
            now,
            session_id,
            request_id,
            lease_owner,
            now,
        ),
    )
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
    with get_conn() as conn:
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
    now = _now()
    statuses = {execution["status"] for execution in executions}
    if not executions or statuses <= {"succeeded", "skipped"}:
        batch_status = "succeeded"
    elif statuses == {"failed"}:
        batch_status = "failed"
    else:
        batch_status = "partial"
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_execution_batch
            (player_id, execution_key, trigger_source, status, results_data,
             deduplicated_count, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(player_id, execution_key) DO NOTHING
            """,
            (player_id, execution_key, trigger_source, batch_status, results_data, now, now),
        )
        if cursor.rowcount == 0:
            conn.execute(
                """
                UPDATE event_execution_batch
                SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
                WHERE player_id = ? AND execution_key = ?
                """,
                (player_id, execution_key),
            )
            row = conn.execute(
                """
                SELECT * FROM event_execution_batch
                WHERE player_id = ? AND execution_key = ?
                """,
                (player_id, execution_key),
            ).fetchone()
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
                    conn.execute(
                        """
                        UPDATE event_trigger_guard
                        SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
                        WHERE player_id = ? AND event_id = ? AND character_scope = ?
                          AND claim_token = ?
                        """,
                        (
                            now,
                            player_id,
                            execution["event_id"],
                            execution.get("trigger_character_scope") or "",
                            claim_token,
                        ),
                    )
                exclusive_claim_token = execution.get(
                    "exclusive_group_claim_token"
                )
                if exclusive_claim_token:
                    conn.execute(
                        """
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = ?
                        WHERE player_id = ? AND exclusive_group = ?
                          AND selected_event_id IS NULL AND claim_token = ?
                        """,
                        (
                            now,
                            player_id,
                            execution["exclusive_group"],
                            exclusive_claim_token,
                        ),
                    )
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
            conn.execute(
                """
                INSERT INTO event_execution
                (execution_id, execution_key, owner_user_id, event_id, character_id,
                 session_id, trigger_source, status, effects_data, result_data,
                 error, duration_ms, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution["execution_id"],
                    execution_key,
                    player_id,
                    execution["event_id"],
                    execution["character_id"],
                    execution["session_id"],
                    trigger_source,
                    execution["status"],
                    execution["effects_data"],
                    execution["result_data"],
                    execution.get("error"),
                    float(execution.get("duration_ms") or 0.0),
                    now,
                    now,
                ),
            )

            if execution["status"] != "succeeded":
                continue

            claim_token = execution.get("trigger_claim_token")
            if claim_token:
                consumed = conn.execute(
                    """
                    UPDATE event_trigger_guard
                    SET last_triggered_at = ?, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = ?
                    WHERE player_id = ? AND event_id = ? AND character_scope = ?
                      AND claim_token = ?
                    """,
                    (
                        now,
                        now,
                        player_id,
                        execution["event_id"],
                        execution.get("trigger_character_scope") or "",
                        claim_token,
                    ),
                )
                if consumed.rowcount != 1:
                    raise RuntimeError(
                        "event trigger claim was lost before atomic completion"
                    )

            exclusive_claim_token = execution.get(
                "exclusive_group_claim_token"
            )
            if exclusive_claim_token:
                selected = conn.execute(
                    """
                    UPDATE event_exclusive_group_guard
                    SET selected_event_id = ?, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = ?
                    WHERE player_id = ? AND exclusive_group = ?
                      AND selected_event_id IS NULL AND claim_token = ?
                      AND EXISTS (
                          SELECT 1
                          FROM event_definition
                          WHERE owner_user_id = ?
                            AND event_id = ?
                            AND exclusive_scope = 'player'
                            AND exclusive_group = ?
                      )
                    """,
                    (
                        execution["event_id"],
                        now,
                        player_id,
                        execution["exclusive_group"],
                        exclusive_claim_token,
                        player_id,
                        execution["event_id"],
                        execution["exclusive_group"],
                    ),
                )
                if selected.rowcount != 1:
                    released_stale = conn.execute(
                        """
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = ?
                        WHERE player_id = ? AND exclusive_group = ?
                          AND selected_event_id IS NULL AND claim_token = ?
                          AND NOT EXISTS (
                              SELECT 1
                              FROM event_definition
                              WHERE owner_user_id = ?
                                AND event_id = ?
                                AND exclusive_scope = 'player'
                                AND exclusive_group = ?
                          )
                        """,
                        (
                            now,
                            player_id,
                            execution["exclusive_group"],
                            exclusive_claim_token,
                            player_id,
                            execution["event_id"],
                            execution["exclusive_group"],
                        ),
                    )
                    if released_stale.rowcount != 1:
                        raise RuntimeError(
                            "event exclusive group claim was lost before atomic completion"
                        )

            conn.execute(
                """
                INSERT INTO event_trigger_log
                (event_id, character_id, player_id, session_id, triggered_at,
                 context_snapshot, effects_applied, execution_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'succeeded')
                """,
                (
                    execution["event_id"],
                    execution["character_id"],
                    player_id,
                    execution["session_id"],
                    now,
                    execution["context_snapshot"],
                    execution["effects_applied"],
                    execution["execution_id"],
                ),
            )
            conn.execute(
                """
                UPDATE event_definition
                SET trigger_count = trigger_count + 1, last_triggered_at = ?
                WHERE owner_user_id = ? AND event_id = ?
                """,
                (now, player_id, execution["event_id"]),
            )

            context_state = execution.get("context_state")
            if context_state:
                conn.execute(
                    """
                    INSERT INTO event_context_state
                    (event_id, character_id, player_id, context_data, status,
                     progress, last_session_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, character_id, player_id)
                    DO UPDATE SET
                        context_data=excluded.context_data,
                        status=excluded.status,
                        progress=excluded.progress,
                        last_session_id=excluded.last_session_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        execution["event_id"],
                        execution["character_id"],
                        player_id,
                        context_state["context_data"],
                        context_state["status"],
                        context_state["progress"],
                        execution["session_id"],
                        now,
                        now,
                    ),
                )

            for unlock_key in execution.get("unlock_keys") or []:
                conn.execute(
                    """
                    INSERT INTO event_unlock
                    (player_id, character_id, unlock_key, event_id, unlocked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, character_id, unlock_key) DO NOTHING
                    """,
                    (
                        player_id,
                        execution["character_id"],
                        unlock_key,
                        execution["event_id"],
                        now,
                    ),
                )

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

            for story_update in execution.get("story_updates") or []:
                _apply_story_update_in_transaction(
                    conn,
                    player_id,
                    story_update,
                )

            for inbox_item in execution.get("inbox_items") or []:
                conn.execute(
                    """
                    INSERT INTO player_event_inbox
                    (player_id, event_id, character_id, session_id, event_type,
                     title, content, payload, world_created_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player_id,
                        execution["event_id"],
                        execution["character_id"],
                        inbox_item.get("session_id"),
                        inbox_item.get("event_type", "event"),
                        inbox_item.get("title"),
                        inbox_item["content"],
                        inbox_item.get("payload"),
                        inbox_item.get("world_created_at"),
                        now,
                    ),
                )

            for message in execution.get("proactive_messages") or []:
                target = conn.execute(
                    """
                    SELECT 1
                    FROM session s
                    INNER JOIN multi_session_participant p
                      ON p.session_id = s.session_id
                     AND p.character_id = ?
                     AND p.is_active = 1
                    WHERE s.session_id = ?
                      AND s.player_id = ?
                      AND s.is_multi_character = 1
                      AND s.status <> 'ended'
                    """,
                    (
                        message["character_id"],
                        message["session_id"],
                        player_id,
                    ),
                ).fetchone()
                if target is None:
                    raise RuntimeError(
                        "proactive dialogue target is not an owned active group participant"
                    )
                conn.execute(
                    """
                    INSERT INTO short_term_message
                    (session_id, role, content, character_id, character_name,
                     created_at, knowledge_sources, world_created_at)
                    VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message["session_id"],
                        message["content"],
                        message["character_id"],
                        message.get("character_name"),
                        now,
                        _encode_knowledge_sources(message.get("knowledge_sources")),
                        message.get("world_created_at"),
                    ),
                )
                conn.execute(
                    """
                    UPDATE multi_session_participant
                    SET last_spoke_at = ?, message_count = message_count + 1
                    WHERE session_id = ? AND character_id = ?
                    """,
                    (now, message["session_id"], message["character_id"]),
                )

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
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT unlock_key FROM event_unlock
            WHERE player_id = ? AND character_id = ?
            ORDER BY unlocked_at ASC, unlock_key ASC
            """,
            (player_id, character_id),
        ).fetchall()
    return [row["unlock_key"] for row in rows]


def get_event_execution_metrics(
    owner_user_id: str,
    event_id: str | None = None,
) -> dict:
    with get_conn() as conn:
        where = "owner_user_id = ?"
        params: list = [owner_user_id]
        if event_id:
            where += " AND event_id = ?"
            params.append(event_id)
        aggregate = conn.execute(
            f"""
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
            """,
            tuple(params),
        ).fetchone()
        last_error = conn.execute(
            f"""
            SELECT error FROM event_execution
            WHERE {where} AND error IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if event_id:
            deduplicated = conn.execute(
                """
                SELECT COALESCE(SUM(batch.deduplicated_count), 0) AS count
                FROM event_execution_batch AS batch
                WHERE batch.player_id = ?
                  AND EXISTS (
                      SELECT 1 FROM event_execution AS execution
                      WHERE execution.owner_user_id = batch.player_id
                        AND execution.execution_key = batch.execution_key
                        AND execution.event_id = ?
                  )
                """,
                (owner_user_id, event_id),
            ).fetchone()
        else:
            deduplicated = conn.execute(
                """
                SELECT COALESCE(SUM(deduplicated_count), 0) AS count
                FROM event_execution_batch WHERE player_id = ?
                """,
                (owner_user_id,),
            ).fetchone()
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
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM event_trigger_log
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        )
        conn.execute(
            """
            DELETE FROM event_trigger_guard
            WHERE event_id = ? AND player_id = ?
              AND character_scope IN (?, '')
            """,
            (event_id, player_id, character_id),
        )
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
            """,
            (player_id, event_id),
        )
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
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_context_state
                (event_id, character_id, player_id, context_data, status, progress,
                 last_session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, character_id, player_id)
                DO UPDATE SET
                    context_data=excluded.context_data,
                    status=excluded.status,
                    progress=excluded.progress,
                    last_session_id=excluded.last_session_id,
                    updated_at=excluded.updated_at
                """,
                (event_id, character_id, player_id, context_data, status, progress,
                 last_session_id, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件上下文失败: {e}")
        return False


def get_event_context_state(event_id: str, character_id: str, player_id: str) -> dict | None:
    """获取指定事件上下文。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_context_state
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        ).fetchone()
    return _row_to_dict(row)


def list_event_context_states(
    character_id: str = None,
    player_id: str = None,
    status: str = None,
    limit: int = 100,
) -> list[dict]:
    """列出事件上下文，可按角色、玩家和状态过滤。"""
    with get_conn() as conn:
        query = "SELECT * FROM event_context_state WHERE 1=1"
        params = []
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
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
    conn.execute(
        """
        INSERT INTO event_schedule_state
        (event_id, character_id, player_id, schedule, last_checked_at,
         last_run_at, next_run_at, next_due_real_at, missed_count,
         status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        """,
        (
            event_id,
            character_id,
            player_id,
            schedule,
            last_checked_at,
            last_run_at,
            next_run_at,
            next_due_real_at,
            missed_count,
            status,
            now,
            now,
        ),
    )


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
        with get_conn() as conn:
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
        with get_conn() as conn:
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

            conn.execute(
                """
                DELETE FROM event_schedule_state
                WHERE event_id = ? AND player_id = ?
                """,
                (event_id, owner_user_id),
            )
            if schedule_state is not None:
                _save_event_schedule_state_in_transaction(conn, **schedule_state)
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
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NOT NULL
              AND next_due_real_at <= ?
        """
        params = [now_iso]
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        if after:
            query += """
                AND (next_due_real_at, event_id, character_id, player_id)
                    > (?, ?, ?, ?)
            """
            params.extend(after)
        query += """
            ORDER BY next_due_real_at, event_id, character_id, player_id
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def list_active_event_schedules(
    limit: int = 500,
    player_id: str | None = None,
) -> list[dict]:
    """List active schedules for per-player world-time evaluation."""
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active' AND next_run_at IS NOT NULL
        """
        params: list[Any] = []
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        query += " ORDER BY next_run_at ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_event_schedules(
    player_id: str,
    event_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    with get_conn() as conn:
        query = "SELECT * FROM event_schedule_state WHERE player_id = ?"
        params: list[Any] = [player_id]
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY next_run_at ASC, updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        ).fetchone()
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
    with get_conn() as conn:
        if next_run_at is None:
            cursor = conn.execute(
                """
                UPDATE event_schedule_state
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (status, _now(), event_id, character_id, player_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE event_schedule_state
                SET status = ?, next_run_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (
                    status,
                    next_run_at,
                    _now(),
                    event_id,
                    character_id,
                    player_id,
                ),
            )
    return cursor.rowcount == 1


def delete_event_schedules(
    event_id: str,
    player_id: str,
    character_id: str | None = None,
) -> int:
    """Delete schedules owned by a player, optionally for one character."""
    with get_conn() as conn:
        if character_id is None:
            cursor = conn.execute(
                "DELETE FROM event_schedule_state WHERE event_id = ? AND player_id = ?",
                (event_id, player_id),
            )
        else:
            cursor = conn.execute(
                """
                DELETE FROM event_schedule_state
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (event_id, character_id, player_id),
            )
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
    """Conditionally claim a schedule using a real-UTC lease."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET lease_owner = ?, lease_expires_at = ?, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND status = 'active'
              AND next_run_at = ?
              AND (
                next_due_real_at = ?
                OR (next_due_real_at IS NULL AND ? IS NULL)
              )
              AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            """,
            (
                lease_owner,
                lease_expires_at,
                real_now_iso,
                event_id,
                character_id,
                player_id,
                expected_next_run_at,
                expected_next_due_real_at,
                expected_next_due_real_at,
                real_now_iso,
            ),
        )
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
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET last_checked_at = ?, last_run_at = ?, next_run_at = ?,
                next_due_real_at = ?, missed_count = ?,
                lease_owner = NULL, lease_expires_at = NULL,
                last_error = NULL, last_failed_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (
                last_checked_at,
                last_run_at,
                next_run_at,
                next_due_real_at,
                missed_count,
                _now(),
                event_id,
                character_id,
                player_id,
                lease_owner,
            ),
        )
    return cursor.rowcount == 1


def get_next_event_schedule(player_id: str) -> dict | None:
    """Return the player's earliest active schedule for clock UI display."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.*, d.event_name
            FROM event_schedule_state s
            LEFT JOIN event_definition d
              ON d.owner_user_id = s.player_id AND d.event_id = s.event_id
            WHERE s.player_id = ? AND s.status = 'active'
              AND s.next_run_at IS NOT NULL
            ORDER BY
              CASE WHEN s.next_due_real_at IS NULL THEN 1 ELSE 0 END,
              s.next_due_real_at ASC,
              s.next_run_at ASC
            LIMIT 1
            """,
            (player_id,),
        ).fetchone()
    return _row_to_dict(row)


def list_event_schedules_for_player(player_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE player_id = ?
            ORDER BY next_run_at ASC
            """,
            (player_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_event_schedules_missing_due_projection(
    player_id: str | None = None,
) -> list[dict]:
    """Return active schedules that need a real-time due projection."""
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NULL
        """
        params: list[Any] = []
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        query += " ORDER BY player_id, next_run_at"
        rows = conn.execute(query, params).fetchall()
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
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET next_due_real_at = ?, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND status = 'active'
              AND next_run_at = ?
              AND next_due_real_at IS NULL
            """,
            (
                next_due_real_at,
                _now(),
                event_id,
                character_id,
                player_id,
                expected_next_run_at,
            ),
        )
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
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET last_error = ?, last_failed_at = ?, lease_owner = NULL,
                lease_expires_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (
                error[:2000],
                failed_at,
                _now(),
                event_id,
                character_id,
                player_id,
                lease_owner,
            ),
        )
    return cursor.rowcount == 1


def release_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (_now(), event_id, character_id, player_id, lease_owner),
        )
    return cursor.rowcount == 1


def get_latest_active_multi_session(player_id: str) -> dict | None:
    """Return the player's most recently active group session."""
    with get_conn() as conn:
        row = conn.execute(
            """
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
            WHERE s.player_id = ?
              AND s.status = 'active'
              AND COALESCE(s.is_multi_character, 0) = 1
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            LIMIT 1
            """,
            (player_id,),
        ).fetchone()
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
    with get_conn() as conn:
        sql = """
            INSERT INTO player_event_inbox
            (player_id, event_id, character_id, session_id, event_type,
             group_thread_id, unread_count, title, content, payload,
             world_created_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if _is_postgres_enabled():
            sql += " RETURNING id"
        cursor = conn.execute(
            sql,
            (
                player_id,
                event_id,
                character_id,
                session_id,
                event_type,
                group_thread_id,
                max(0, int(unread_count or 0)),
                title,
                content,
                payload,
                world_created_at,
                _now(),
            ),
        )
        return cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid


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

    row = conn.execute(
        """
        SELECT id, unread_count
        FROM player_event_inbox
        WHERE player_id = ? AND event_type = 'group_message'
          AND group_thread_id = ? AND read_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (player_id, group_thread_id),
    ).fetchone()
    if row:
        unread_count = int(row["unread_count"] or 0) + increment
        conn.execute(
            """
            UPDATE player_event_inbox
            SET session_id = ?, unread_count = ?, content = ?, title = ?,
                world_created_at = ?, created_at = ?, payload = ?
            WHERE id = ?
            """,
            (
                session_id,
                unread_count,
                f"群聊中有 {unread_count} 条新消息",
                group_name or "群聊新消息",
                world_created_at,
                _now(),
                json.dumps(
                    {"group_thread_id": group_thread_id, "unread_count": unread_count},
                    ensure_ascii=False,
                ),
                row["id"],
            ),
        )
        return int(row["id"])

    sql = """
        INSERT INTO player_event_inbox
        (player_id, session_id, event_type, group_thread_id, unread_count,
         title, content, payload, world_created_at, created_at)
        VALUES (?, ?, 'group_message', ?, ?, ?, ?, ?, ?, ?)
    """
    if _is_postgres_enabled():
        sql += " RETURNING id"
    cursor = conn.execute(
        sql,
        (
            player_id,
            session_id,
            group_thread_id,
            increment,
            group_name or "群聊新消息",
            f"群聊中有 {increment} 条新消息",
            json.dumps(
                {"group_thread_id": group_thread_id, "unread_count": increment},
                ensure_ascii=False,
            ),
            world_created_at,
            _now(),
        ),
    )
    return int(cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid)


def upsert_group_message_notification(
    player_id: str,
    group_thread_id: str,
    session_id: str,
    new_message_count: int,
    *,
    group_name: str | None = None,
    world_created_at: str | None = None,
) -> int:
    with get_conn() as conn:
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
    with get_conn() as conn:
        unread_clause = "AND read_at IS NULL" if unread_only else ""
        rows = conn.execute(
            f"""
            SELECT * FROM player_event_inbox
            WHERE player_id = ? {unread_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (player_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_player_event_read(player_id: str, inbox_id: int) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, ?)
            WHERE id = ? AND player_id = ?
            """,
            (_now(), inbox_id, player_id),
        )
    return cursor.rowcount == 1


def mark_group_thread_notifications_read(player_id: str, group_thread_id: str) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, ?)
            WHERE player_id = ? AND event_type = 'group_message'
              AND group_thread_id = ? AND read_at IS NULL
            """,
            (_now(), player_id, group_thread_id),
        )
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
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_template
                (template_id, template_name, category, description, trigger_config,
                 effects_config, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id)
                DO UPDATE SET
                    template_name=excluded.template_name,
                    category=excluded.category,
                    description=excluded.description,
                    trigger_config=excluded.trigger_config,
                    effects_config=excluded.effects_config,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (template_id, template_name, category, description, trigger_config,
                 effects_config, metadata, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件模板失败: {e}")
        return False


def list_event_templates(category: str = None) -> list[dict]:
    """列出事件模板。"""
    with get_conn() as conn:
        query = "SELECT * FROM event_template WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY category ASC, template_name ASC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_event_template(template_id: str) -> dict | None:
    """获取事件模板。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM event_template WHERE template_id = ?",
            (template_id,),
        ).fetchone()
    return _row_to_dict(row)


def delete_event_template(template_id: str) -> bool:
    """删除事件模板。"""
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM event_template WHERE template_id = ?",
            (template_id,),
        )
    return cursor.rowcount > 0


