"""Domain repository functions (split from monolith)."""
from __future__ import annotations

# Standard/third-party imports used across repository domains.
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
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
# session 管理
# =========================
def _lock_session_creation(conn, lock_key: str) -> None:
    if _is_postgres_enabled():
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
            {"lock_key": lock_key},
        )
    else:
        _lock_sqlite_write(conn)


def create_session(
    session_id: str,
    character_id: str,
    player_id: str,
    player_name: str,
    locale: str = "zh-CN",
    story_id: str | None = None,
) -> dict:
    session, _ = get_or_create_active_session(
        session_id=session_id,
        character_id=character_id,
        player_id=player_id,
        player_name=player_name,
        locale=locale,
        story_id=story_id,
    )
    return session


def get_or_create_active_session(
    *,
    session_id: str,
    character_id: str,
    player_id: str,
    player_name: str,
    locale: str = "zh-CN",
    story_id: str | None = None,
) -> tuple[dict, bool]:
    """Atomically reuse or create one active single-character session."""
    with db_session() as conn:
        _lock_session_creation(
            conn,
            f"active-single-session:{player_id}:{character_id}",
        )
        row = conn.execute(
            text("""
            SELECT *
            FROM session
            WHERE player_id = :player_id
              AND character_id = :character_id
              AND status = 'active'
              AND COALESCE(is_multi_character, 0) = 0
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """),
            {"player_id": player_id, "character_id": character_id},
        ).mappings().fetchone()
        if row is not None:
            return dict(row), False

        conn.execute(
            text("""
            INSERT INTO session
            (session_id, character_id, player_id, player_name, created_at, status,
             locale, story_id)
            VALUES (:session_id, :character_id, :player_id, :player_name,
                    :created_at, 'active', :locale, :story_id)
            """),
            {
                "session_id": session_id,
                "character_id": character_id,
                "player_id": player_id,
                "player_name": player_name,
                "created_at": _now(),
                "locale": locale,
                "story_id": (story_id or "").strip() or None,
            },
        )
        row = conn.execute(
            text("SELECT * FROM session WHERE session_id = :session_id"),
            {"session_id": session_id},
        ).mappings().fetchone()
        return dict(row), True


def get_session(session_id: str) -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            text("SELECT * FROM session WHERE session_id = :session_id"),
            {"session_id": session_id},
        ).mappings().fetchone()

    return _row_to_dict(row)

def end_session(session_id: str):
    """标记会话为结束状态"""
    with db_session() as conn:
        conn.execute(
            text("""
            UPDATE session
            SET status = 'ended', ended_at = :ended_at
            WHERE session_id = :session_id
            """),
            {"ended_at": _now(), "session_id": session_id},
        )


def get_latest_active_session(player_id: str, character_id: str | None = None) -> dict | None:
    """获取玩家最近的 active session（用于断线恢复）"""
    with db_session() as conn:
        if character_id:
            row = conn.execute(
                text("""
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
                WHERE s.player_id = :player_id AND s.character_id = :character_id
                  AND s.status = 'active'
                  AND COALESCE(s.is_multi_character, 0) = 0
                ORDER BY COALESCE(
                    (SELECT created_at FROM short_term_message
                     WHERE session_id = s.session_id ORDER BY id DESC LIMIT 1),
                    s.created_at) DESC
                LIMIT 1
                """),
                {
                    "player_id": player_id,
                    "character_id": character_id,
                },
            ).mappings().fetchone()
        else:
            row = conn.execute(
                text("""
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
                WHERE s.player_id = :player_id AND s.status = 'active'
                ORDER BY COALESCE(
                    (SELECT created_at FROM short_term_message
                     WHERE session_id = s.session_id ORDER BY id DESC LIMIT 1),
                    s.created_at) DESC
                LIMIT 1
                """),
                {"player_id": player_id},
            ).mappings().fetchone()
    return _row_to_dict(row)


def get_latest_session_locale(
    character_id: str,
    player_id: str,
    preferred_session_id: str | None = None,
) -> str:
    """Return a persisted locale for a single-character history response."""
    if preferred_session_id:
        preferred = get_session(preferred_session_id)
        if preferred and (
            preferred.get("character_id") == character_id
            and preferred.get("player_id") == player_id
            and not preferred.get("is_multi_character")
        ):
            return preferred.get("locale") or "zh-CN"

    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT locale
            FROM session
            WHERE character_id = :character_id AND player_id = :player_id
              AND COALESCE(is_multi_character, 0) = 0
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """),
            {"character_id": character_id, "player_id": player_id},
        ).mappings().fetchone()
    return (row["locale"] if row else None) or "zh-CN"


# =========================
# short term memory（对话历史）
# =========================
def append_short_term_message(
    session_id: str,
    role: str,
    content: str,
    action: str | None = None,
    affinity_delta: float | None = None,
    trust_delta: float | None = None,
    current_affinity: float | None = None,
    current_trust: float | None = None,
    current_mood: str | None = None,
    event_notification: str | None = None,
    world_created_at: str | None = None,
    knowledge_sources: list[dict] | None = None,
) -> int:
    """
    追加短期对话消息。

    Returns:
        int: 新消息的 id
    """
    with db_session() as conn:
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, action, affinity_delta, trust_delta,
             current_affinity, current_trust, current_mood, event_notification,
             knowledge_sources, created_at, world_created_at)
            VALUES (:session_id, :role, :content, :action, :affinity_delta,
                    :trust_delta, :current_affinity, :current_trust,
                    :current_mood, :event_notification, :knowledge_sources,
                    :created_at, :world_created_at)
            """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            text(insert_sql),
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "action": action,
                "affinity_delta": affinity_delta,
                "trust_delta": trust_delta,
                "current_affinity": current_affinity,
                "current_trust": current_trust,
                "current_mood": current_mood,
                "event_notification": event_notification,
                "knowledge_sources": _encode_knowledge_sources(knowledge_sources),
                "created_at": _now(),
                "world_created_at": world_created_at,
            },
        )
        if _is_postgres_enabled():
            return cursor.mappings().fetchone()["id"]
        return cursor.lastrowid


def get_short_term_message(session_id: str, message_id: int) -> dict | None:
    """Return one persisted message, scoped to its session."""
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT *
            FROM short_term_message
            WHERE session_id = :session_id AND id = :message_id
            LIMIT 1
            """),
            {"session_id": session_id, "message_id": message_id},
        ).mappings().fetchone()
    return _decode_message_row(row) if row else None
        
def get_short_term_history(session_id: str, limit_turns: int) -> list[dict]:
    """
    获取短期记忆（最近 N 轮对话）

    说明：
    - 每轮 = user + assistant = 2条消息
    - 返回按时间正序（适配 LLM）
    """

    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT role, content
            FROM short_term_message
            WHERE session_id = :session_id
            ORDER BY id DESC
            LIMIT :limit
            """),
            {"session_id": session_id, "limit": limit_turns * 2},
        ).mappings().fetchall()

    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    messages.reverse()
    return messages


def get_session_user_turn_count(session_id: str) -> int:
    """获取当前会话已经写入的玩家回合数。"""
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT COUNT(*) AS turn_count
            FROM short_term_message
            WHERE session_id = :session_id AND role = 'user'
            """),
            {"session_id": session_id},
        ).mappings().fetchone()
    return int(row["turn_count"]) if row else 0


def count_character_user_turns(player_id: str, character_id: str) -> int:
    """Count player turns across every single and group chat involving a character."""
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT COUNT(*) AS turn_count
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND m.role = 'user'
              AND (
                  (COALESCE(s.is_multi_character, 0) = 0
                   AND s.character_id = :character_id)
                  OR
                  (
                      COALESCE(s.is_multi_character, 0) = 1
                      AND EXISTS (
                          SELECT 1
                          FROM multi_session_participant p
                          WHERE p.session_id = s.session_id
                            AND p.character_id = :character_id
                      )
                  )
              )
            """),
            {"player_id": player_id, "character_id": character_id},
        ).mappings().fetchone()
    return int(row["turn_count"]) if row else 0


def is_long_term_memory_checkpoint(session_id: str, interval_turns: int) -> bool:
    """当前会话是否到达长期记忆保存检查点。"""
    turn_count = get_session_user_turn_count(session_id)
    return turn_count > 0 and turn_count % max(1, interval_turns) == 0


# =========================
# session 查询（列表页）
# =========================
def get_sessions_by_player_and_character(character_id: str, player_id: str) -> list[dict]:
    """查询玩家与角色的所有会话"""
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT
                s.session_id,
                s.character_id,
                s.player_id,
                s.player_name,
                s.created_at,
                s.ended_at,
                s.status,
                s.group_name,
                s.locale,
                CASE
                    WHEN COALESCE(s.is_multi_character, 0) = 1 THEN COALESCE(s.group_thread_id, s.session_id)
                    ELSE s.group_thread_id
                END AS group_thread_id,
                s.is_multi_character,
                c.name,
                c.display_name,
                c.avatar_url,
                CASE
                    WHEN COALESCE(s.is_multi_character, 0) = 1 THEN (
                        SELECT content
                        FROM short_term_message
                        WHERE session_id = s.session_id
                        ORDER BY id DESC
                        LIMIT 1
                    )
                    ELSE (
                        SELECT m.content
                        FROM short_term_message m
                        WHERE m.session_id = s.session_id
                        ORDER BY m.id DESC
                        LIMIT 1
                    )
                END AS last_message,
                CASE
                    WHEN COALESCE(s.is_multi_character, 0) = 1 THEN (
                        SELECT created_at
                        FROM short_term_message
                        WHERE session_id = s.session_id
                        ORDER BY id DESC
                        LIMIT 1
                    )
                    ELSE (
                        SELECT m.created_at
                        FROM short_term_message m
                        WHERE m.session_id = s.session_id
                        ORDER BY m.id DESC
                        LIMIT 1
                    )
                END AS last_message_at,
                CASE
                    WHEN COALESCE(s.is_multi_character, 0) = 1 THEN (
                        SELECT COUNT(*)
                        FROM short_term_message
                        WHERE session_id = s.session_id
                    )
                    ELSE (
                        SELECT COUNT(*)
                        FROM short_term_message m
                        WHERE m.session_id = s.session_id
                    )
                END AS message_count
            FROM session s
            LEFT JOIN character_card c
              ON c.owner_user_id = s.player_id
             AND c.character_id = s.character_id
            WHERE s.character_id = :character_id
              AND s.player_id = :player_id
              AND COALESCE(s.is_multi_character, 0) = 0
            ORDER BY COALESCE(
                (SELECT m.created_at FROM short_term_message m
                 WHERE m.session_id = s.session_id ORDER BY m.id DESC LIMIT 1),
                s.created_at) DESC
            """),
            {"character_id": character_id, "player_id": player_id},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def get_all_player_sessions(player_id: str) -> list[dict]:
    """查询玩家会话；群聊按逻辑线程聚合，单聊保持原有物理会话结果。"""
    with db_session() as conn:
        single_rows = conn.execute(
            text("""
            SELECT
                s.session_id,
                s.character_id,
                s.player_id,
                s.player_name,
                s.created_at,
                s.ended_at,
                s.status,
                s.group_name,
                s.locale,
                CASE
                    WHEN COALESCE(s.is_multi_character, 0) = 1 THEN COALESCE(s.group_thread_id, s.session_id)
                    ELSE s.group_thread_id
                END AS group_thread_id,
                s.is_multi_character,
                c.name,
                c.display_name,
                c.avatar_url,
                (
                    SELECT m.content
                    FROM short_term_message m
                    INNER JOIN session sm ON sm.session_id = m.session_id
                    WHERE sm.character_id = s.character_id
                      AND sm.player_id = s.player_id
                      AND COALESCE(sm.is_multi_character, 0) = 0
                    ORDER BY m.id DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT m.created_at
                    FROM short_term_message m
                    INNER JOIN session sm ON sm.session_id = m.session_id
                    WHERE sm.character_id = s.character_id
                      AND sm.player_id = s.player_id
                      AND COALESCE(sm.is_multi_character, 0) = 0
                    ORDER BY m.id DESC
                    LIMIT 1
                ) AS last_message_at,
                (
                    SELECT COUNT(*)
                    FROM short_term_message m
                    INNER JOIN session sm ON sm.session_id = m.session_id
                    WHERE sm.character_id = s.character_id
                      AND sm.player_id = s.player_id
                      AND COALESCE(sm.is_multi_character, 0) = 0
                ) AS message_count,
                0 AS unread_count
            FROM session s
            LEFT JOIN character_card c
              ON c.owner_user_id = s.player_id
             AND c.character_id = s.character_id
            WHERE s.player_id = :player_id AND COALESCE(s.is_multi_character, 0) = 0
            ORDER BY COALESCE(
                (SELECT m.created_at FROM short_term_message m
                 WHERE m.session_id = s.session_id ORDER BY m.id DESC LIMIT 1),
                s.created_at) DESC
            """),
            {"player_id": player_id},
        ).mappings().fetchall()

        group_sessions = conn.execute(
            text("""
            SELECT s.*
            FROM session s
            WHERE s.player_id = :player_id AND COALESCE(s.is_multi_character, 0) = 1
            ORDER BY CASE WHEN s.status = 'active' THEN 0 ELSE 1 END,
                     s.created_at DESC, s.session_id DESC
            """),
            {"player_id": player_id},
        ).mappings().fetchall()

        # 批量统计各群聊线程的消息数、最新消息与未读数，避免 N+1 查询。
        message_stats = {
            row["thread_id"]: dict(row)
            for row in conn.execute(
                text("""
                SELECT COALESCE(sm.group_thread_id, sm.session_id) AS thread_id,
                       COUNT(*) AS message_count,
                       MAX(m.id) AS latest_message_id
                FROM short_term_message m
                INNER JOIN session sm ON sm.session_id = m.session_id
                WHERE sm.player_id = :player_id
                  AND COALESCE(sm.is_multi_character, 0) = 1
                GROUP BY COALESCE(sm.group_thread_id, sm.session_id)
                """),
                {"player_id": player_id},
            ).mappings().fetchall()
        }
        latest_ids = [
            stats["latest_message_id"]
            for stats in message_stats.values()
            if stats.get("latest_message_id") is not None
        ]
        latest_messages = {}
        if latest_ids:
            placeholders = ",".join(
                f":latest_id_{idx}" for idx in range(len(latest_ids))
            )
            latest_params = {
                f"latest_id_{idx}": latest_id
                for idx, latest_id in enumerate(latest_ids)
            }
            latest_messages = {
                row["message_id"]: dict(row)
                for row in conn.execute(
                    text(f"""
                    SELECT id AS message_id, content, created_at
                    FROM short_term_message
                    WHERE id IN ({placeholders})
                    """),
                    latest_params,
                ).mappings().fetchall()
            }
        unread_stats = {
            row["group_thread_id"]: int(row["unread_count"] or 0)
            for row in conn.execute(
                text("""
                SELECT group_thread_id,
                       COALESCE(SUM(unread_count), 0) AS unread_count
                FROM player_event_inbox
                WHERE player_id = :player_id AND event_type = 'group_message'
                  AND read_at IS NULL
                GROUP BY group_thread_id
                """),
                {"player_id": player_id},
            ).mappings().fetchall()
        }

        group_rows = []
        seen_group_threads = set()
        for raw_session in group_sessions:
            session = dict(raw_session)
            thread_id = session.get("group_thread_id") or session["session_id"]
            if thread_id in seen_group_threads:
                continue
            seen_group_threads.add(thread_id)

            stats = message_stats.get(thread_id) or {}
            latest = latest_messages.get(stats.get("latest_message_id")) or {}
            session.update({
                "group_thread_id": thread_id,
                "last_message": latest.get("content"),
                "last_message_at": latest.get("created_at"),
                "latest_message_id": stats.get("latest_message_id"),
                "message_count": int(stats.get("message_count") or 0),
                "unread_count": unread_stats.get(thread_id, 0),
            })
            group_rows.append(session)

    rows = [dict(row) for row in single_rows] + group_rows
    rows.sort(
        key=lambda row: row.get("last_message_at") or row.get("created_at") or "",
        reverse=True,
    )
    return rows


def player_group_name_exists(player_id: str, group_name: str) -> bool:
    """检查玩家是否已有同名群聊。"""
    clean_group_name = (group_name or "").strip()
    if not clean_group_name:
        return False

    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT 1
            FROM session
            WHERE player_id = :player_id
              AND COALESCE(is_multi_character, 0) = 1
              AND LOWER(TRIM(group_name)) = LOWER(:group_name)
            LIMIT 1
            """),
            {"player_id": player_id, "group_name": clean_group_name},
        ).mappings().fetchone()
    return row is not None


# =========================
# 分页消息
# =========================
def get_messages_paginated(session_id: str, offset: int, limit: int) -> tuple[list[dict], bool]:
    """
    分页查询消息
    
    策略：倒序获取（最新的在前），前端需要反转顺序显示
    - offset=0, limit=20: 获取最新的20条
    - offset=20, limit=20: 获取次新的20条（用于"加载更多"）
    """
    with db_session() as conn:
        # 倒序查询（最新的在前）
        rows = conn.execute(
            text("""
            SELECT id AS message_id, role, content, action,
                   affinity_delta, trust_delta,
                   current_affinity, current_trust, current_mood,
                   event_notification, knowledge_sources, created_at,
                   world_created_at
            FROM short_term_message
            WHERE session_id = :session_id
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
            """),
            {
                "session_id": session_id,
                "limit": limit + 1,
                "offset": offset,
            },
        ).mappings().fetchall()

    has_more = len(rows) > limit
    # 取前 limit 条，并反转顺序（变回正序）
    messages = [_decode_message_row(r) for r in reversed(rows[:limit])]

    return messages, has_more


def get_session_messages(session_id: str, limit: int = 1000) -> list[dict]:
    """按时间正序获取单个 session 的消息，用于回放和质量评分。"""
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT id AS message_id, role, content, character_id, character_name,
                   action, affinity_delta, trust_delta,
                   current_affinity, current_trust, current_mood,
                   event_notification, knowledge_sources, created_at,
                   world_created_at
            FROM short_term_message
            WHERE session_id = :session_id
            ORDER BY id ASC
            LIMIT :limit
            """),
            {"session_id": session_id, "limit": limit},
        ).mappings().fetchall()
    return [_decode_message_row(r) for r in rows]


# 跨多个 Session 分页获取消息
def get_messages_by_player_and_character(
    character_id: str,
    player_id: str,
    offset: int = 0,
    limit: int = 20,
    exclude_session_id: str | None = None,
):
    """
    跨多个 Session 分页获取消息。

    offset=0 返回最新一页，但结果按时间正序排列，方便聊天窗口直接显示；
    offset 增大时返回更早的消息，用于上滑加载历史。
    """

    with db_session() as conn:
        exclude_clause = ""
        params: dict = {
            "character_id": character_id,
            "player_id": player_id,
        }

        if exclude_session_id:
            exclude_clause = "AND s.session_id != :exclude_session_id"
            params["exclude_session_id"] = exclude_session_id

        params["limit"] = limit + 1
        params["offset"] = offset

        rows = conn.execute(
            text(f"""
            SELECT
                m.id AS message_id,
                m.role,
                m.content,
                m.action,
                m.affinity_delta,
                m.trust_delta,
                m.current_affinity,
                m.current_trust,
                m.current_mood,
                m.event_notification,
                m.knowledge_sources,
                m.created_at,
                m.world_created_at,
                m.session_id
            FROM short_term_message m
            INNER JOIN session s
                ON m.session_id = s.session_id
            WHERE
                s.character_id = :character_id
                AND s.player_id = :player_id
                AND COALESCE(s.is_multi_character, 0) = 0
                {exclude_clause}
            ORDER BY
                m.id DESC
            LIMIT :limit
            OFFSET :offset
            """),
            params,
        ).mappings().fetchall()

    has_more = len(rows) > limit

    return (
        [_decode_message_row(r) for r in reversed(rows[:limit])],
        has_more,
    )


def get_last_character_interaction_world_at(
    player_id: str,
    character_id: str,
) -> str | None:
    """Return the latest world-semantic interaction timestamp for a character."""
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT COALESCE(m.world_created_at, m.created_at) AS interaction_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND (
                (COALESCE(s.is_multi_character, 0) = 0
                 AND s.character_id = :character_id)
                OR
                (COALESCE(s.is_multi_character, 0) = 1
                 AND m.character_id = :character_id)
              )
            ORDER BY m.id DESC
            LIMIT 1
            """),
            {"player_id": player_id, "character_id": character_id},
        ).mappings().fetchone()
    return row["interaction_at"] if row else None


# =========================
# 会话摘要（中期记忆）
# =========================
def save_session_summary(
    session_id: str,
    character_id: str,
    player_id: str,
    summary_text: str,
    message_count: int,
    summary_status: str = "completed"
):
    """
    保存会话摘要。同一 session+character+player 只保留一条。
    summary_status: pending / generating / completed / failed
    """
    with db_session() as conn:
        conn.execute(
            text("""INSERT INTO session_summary
               (session_id, character_id, player_id, summary_text, message_count, summary_status, created_at)
               VALUES (:session_id, :character_id, :player_id, :summary_text,
                       :message_count, :summary_status, :created_at)
               ON CONFLICT(session_id, character_id, player_id) DO UPDATE SET
                   summary_text=excluded.summary_text,
                   message_count=excluded.message_count,
                   summary_status=excluded.summary_status,
                   created_at=excluded.created_at"""),
            {
                "session_id": session_id,
                "character_id": character_id,
                "player_id": player_id,
                "summary_text": summary_text,
                "message_count": message_count,
                "summary_status": summary_status,
                "created_at": _now(),
            },
        )
        
def get_session_summary(session_id: str) -> dict | None:
    """获取指定会话的摘要"""
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT * FROM session_summary
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT 1
            """),
            {"session_id": session_id},
        ).mappings().fetchone()
        
    return _row_to_dict(row)

def get_recent_summaries(
    character_id: str,
    player_id: str,
    limit: int = 5
) -> list[dict]:
    """获取角色与玩家的最近会话摘要"""
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT ss.*, s.created_at as session_created_at
            FROM session_summary ss
            JOIN session s ON ss.session_id = s.session_id
            WHERE ss.character_id = :character_id AND ss.player_id = :player_id
            ORDER BY ss.created_at DESC
            LIMIT :limit
            """),
            {"character_id": character_id, "player_id": player_id, "limit": limit},
        ).mappings().fetchall()
        
    return [dict(r) for r in rows]



# =========================
# 定向角色印象（shared_memory）
# =========================
def save_character_impression(
    owner_user_id: str,
    observer_character_id: str,
    target_character_id: str,
    impression_text: str,
    context: str = None,
    importance: float = 0.5,
    world_occurred_at: str | None = None,
    evidence_id: str | None = None,
) -> str:
    """保存观察者对目标角色的定向印象。"""
    if not owner_user_id:
        raise ValueError("owner_user_id is required for shared_memory isolation")
    if not observer_character_id or not target_character_id:
        raise ValueError("observer_character_id and target_character_id are required")
    if observer_character_id == target_character_id:
        raise ValueError("observer_character_id and target_character_id must differ")
    impression_text = str(impression_text or "").strip()
    if not impression_text:
        raise ValueError("impression_text is required")
    memory_id = str(uuid.uuid4())

    with db_session() as conn:
        existing = _dedup_check(
            conn,
            "shared_memory",
            "memory_text",
            impression_text,
            """
            owner_user_id = :owner_user_id
            AND observer_character_id = :observer_character_id
            AND target_character_id = :target_character_id
            AND memory_kind = 'character_impression'
            """,
            {
                "owner_user_id": owner_user_id,
                "observer_character_id": observer_character_id,
                "target_character_id": target_character_id,
            },
            threshold=0.92,
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute(
                text(
                    "UPDATE shared_memory SET importance=:importance, "
                    "last_referenced=:last_referenced WHERE id=:id"
                ),
                {
                    "importance": new_imp,
                    "last_referenced": _now(),
                    "id": existing["id"],
                },
            )
            memory_id = existing["id"]
        else:
            conn.execute(
                text("""
                INSERT INTO shared_memory
                (id, owner_user_id, character_a_id, character_b_id,
                 observer_character_id, target_character_id, memory_kind,
                 memory_text, context, importance, created_at, last_referenced,
                 reference_count)
                VALUES (:memory_id, :owner_user_id, :character_a_id,
                        :character_b_id, :observer_character_id,
                        :target_character_id, 'character_impression',
                        :memory_text, :context, :importance, :created_at,
                        :last_referenced, 0)
                """),
                {
                    "memory_id": memory_id,
                    "owner_user_id": owner_user_id,
                    "character_a_id": observer_character_id,
                    "character_b_id": target_character_id,
                    "observer_character_id": observer_character_id,
                    "target_character_id": target_character_id,
                    "memory_text": impression_text,
                    "context": context,
                    "importance": importance,
                    "created_at": _now(),
                    "last_referenced": _now(),
                },
            )

    if configs.memory_curve_enabled and world_occurred_at and evidence_id:
        try:
            record_memory_curve_evidence(
                owner_user_id=owner_user_id,
                character_id=observer_character_id,
                memory_type="character_impression",
                memory_id=memory_id,
                evidence_id=evidence_id,
                world_occurred_at=world_occurred_at,
                source_kind="model_inference",
                importance=importance,
            )
        except Exception as exc:
            logger.warning("角色印象曲线写入失败，保留原始记忆: %s", exc)
    return memory_id


def get_character_impressions(
    owner_user_id: str,
    observer_character_id: str,
    target_character_id: str,
    limit: int = 10,
    created_after: str | None = None
) -> list[dict]:
    """获取观察者对目标角色的定向印象。"""
    if not owner_user_id:
        raise ValueError("owner_user_id is required for shared_memory isolation")
    where_clause = """
        owner_user_id = :owner_user_id
        AND observer_character_id = :observer_character_id
        AND target_character_id = :target_character_id
        AND memory_kind = 'character_impression'
    """
    params = {
        "owner_user_id": owner_user_id,
        "observer_character_id": observer_character_id,
        "target_character_id": target_character_id,
    }
    if created_after:
        where_clause += " AND created_at >= :created_after"
        params["created_after"] = created_after
    params["limit"] = limit
    with db_session() as conn:
        rows = conn.execute(
            text(f"""
            SELECT id, observer_character_id, target_character_id,
                   memory_text, context, importance, created_at
            FROM shared_memory
            WHERE {where_clause}
            ORDER BY importance DESC, last_referenced DESC
            LIMIT :limit
            """),
            params).mappings().fetchall()
    return [dict(r) for r in rows]


def get_observer_character_impressions(
    owner_user_id: str,
    observer_character_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取一个角色对其他角色形成的全部定向印象。"""
    if not owner_user_id:
        raise ValueError("owner_user_id is required for shared_memory isolation")
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT id, owner_user_id, observer_character_id,
                   target_character_id, memory_text, context, importance,
                   created_at
            FROM shared_memory
            WHERE owner_user_id = :owner_user_id
              AND observer_character_id = :observer_character_id
              AND memory_kind = 'character_impression'
            ORDER BY importance DESC, last_referenced DESC
            LIMIT :limit
            """),
            {
                "owner_user_id": owner_user_id,
                "observer_character_id": observer_character_id,
                "limit": limit,
            },
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def save_shared_memory(
    owner_user_id: str,
    character_a_id: str,
    character_b_id: str,
    memory_text: str,
    context: str = None,
    importance: float = 0.5,
) -> str:
    """兼容旧调用；按 A 观察 B 的定向角色印象保存。"""
    return save_character_impression(
        owner_user_id=owner_user_id,
        observer_character_id=character_a_id,
        target_character_id=character_b_id,
        impression_text=memory_text,
        context=context,
        importance=importance,
    )


def get_shared_memories(
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
    limit: int = 10,
    created_after: str | None = None,
) -> list[dict]:
    """兼容旧调用；只返回 A 对 B 的定向角色印象。"""
    return get_character_impressions(
        owner_user_id=owner_user_id,
        observer_character_id=character_id_a,
        target_character_id=character_id_b,
        limit=limit,
        created_after=created_after,
    )


def get_character_shared_memories(
    owner_user_id: str,
    character_id: str,
    limit: int = 20,
) -> list[dict]:
    """兼容旧调用；只返回该角色作为观察者形成的印象。"""
    return get_observer_character_impressions(
        owner_user_id=owner_user_id,
        observer_character_id=character_id,
        limit=limit,
    )


# =========================
# 群体记忆（group_memory）
# =========================
def save_group_memory(
    session_id: str,
    memory_text: str,
    participants: list[str] = None,
    context: str = None,
    importance: float = 0.5,
    world_occurred_at: str | None = None,
    evidence_id: str | None = None,
) -> str:
    """保存多角色会话的群体记忆。含去重检查。"""
    import uuid, json
    memory_id = str(uuid.uuid4())
    participants_json = json.dumps(participants) if participants else None
    session = get_session(session_id)

    with db_session() as conn:
        existing = _dedup_check(
            conn, "group_memory", "memory_text", memory_text,
            "session_id = :session_id",
            {"session_id": session_id}, threshold=0.75
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute(
                text(
                    "UPDATE group_memory SET importance=:importance, "
                    "last_referenced=:last_referenced WHERE id=:id"
                ),
                {
                    "importance": new_imp,
                    "last_referenced": _now(),
                    "id": existing["id"],
                },
            )
            memory_id = existing["id"]
        else:
            conn.execute(
                text(
                    "INSERT INTO group_memory "
                    "(id, session_id, memory_text, participants, context, "
                    "importance, created_at, last_referenced, reference_count) "
                    "VALUES (:id, :session_id, :memory_text, :participants, "
                    ":context, :importance, :created_at, :last_referenced, 0)"
                ),
                {
                    "id": memory_id,
                    "session_id": session_id,
                    "memory_text": memory_text,
                    "participants": participants_json,
                    "context": context,
                    "importance": importance,
                    "created_at": _now(),
                    "last_referenced": _now(),
                },
            )

    if (
        configs.memory_curve_enabled
        and world_occurred_at
        and evidence_id
        and participants
    ):
        if session:
            for character_id in dict.fromkeys(participants):
                try:
                    record_memory_curve_evidence(
                        owner_user_id=session["player_id"],
                        character_id=character_id,
                        memory_type="group_experience",
                        memory_id=memory_id,
                        evidence_id=evidence_id,
                        world_occurred_at=world_occurred_at,
                        source_kind="model_inference",
                        importance=importance,
                    )
                except Exception as exc:
                    logger.warning("群体记忆曲线写入失败，保留原始记忆: %s", exc)
    return memory_id


def get_session_group_memories(
    session_id: str,
    limit: int = 20,
    created_after: str | None = None,
    owner_user_id: str | None = None,
) -> list[dict]:
    """获取某个会话的群体记忆，可按会话归属用户隔离。"""
    table_clause = "group_memory gm"
    where_clause = "gm.session_id = :session_id"
    params = {"session_id": session_id}
    if owner_user_id:
        table_clause += " JOIN session s ON s.session_id = gm.session_id"
        where_clause += " AND s.player_id = :owner_user_id"
        params["owner_user_id"] = owner_user_id
    if created_after:
        where_clause += " AND gm.created_at >= :created_after"
        params["created_after"] = created_after
    params["limit"] = limit
    with db_session() as conn:
        rows = conn.execute(
            text(f"SELECT gm.id, gm.memory_text, gm.participants, gm.context, "
            f"gm.importance, gm.created_at FROM {table_clause} "
            f"WHERE {where_clause} "
            "ORDER BY gm.importance DESC, gm.last_referenced DESC LIMIT :limit"),
            params,
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def get_character_group_memories(
    character_id: str,
    limit: int = 20,
    created_after: str | None = None,
    *,
    owner_user_id: str,
) -> list[dict]:
    """获取某个角色在指定用户下参与过的群体记忆。

    `owner_user_id` 是**必填的关键字参数**：角色 ID 会跨用户重复（预置角色卡
    `source='file'` 对所有用户是同一 ID），缺少租户限定会把 A 用户群聊里形成的
    记忆注入 B 用户的 prompt。设为必填是为了让任何未限定租户的调用直接以
    TypeError 失败，而不是静默返回跨用户数据。
    """
    if not owner_user_id:
        raise ValueError("get_character_group_memories 需要 owner_user_id")

    # participants 以 JSON 数组存储（如 ["char_a","char_b"]）。
    # 用带引号的精确 token 匹配并转义 LIKE 通配符，避免 char-a 误命中 char-a-2。
    escaped_id = (
        character_id
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    where_clause = (
        "gm.participants LIKE :escaped_id ESCAPE '\\' "
        "AND s.player_id = :owner_user_id"
    )
    params = {"escaped_id": f'%"{escaped_id}"%', "owner_user_id": owner_user_id}
    if created_after:
        where_clause += " AND gm.created_at >= :created_after"
        params["created_after"] = created_after
    params["limit"] = limit
    with db_session() as conn:
        rows = conn.execute(
            text("SELECT gm.id, gm.session_id, gm.memory_text, gm.participants, gm.context,"
            " gm.importance, gm.created_at"
            " FROM group_memory gm JOIN session s ON s.session_id = gm.session_id"
            f" WHERE {where_clause}"
            " ORDER BY gm.importance DESC, gm.last_referenced DESC LIMIT :limit"),
            params).mappings().fetchall()
    return [dict(r) for r in rows]
