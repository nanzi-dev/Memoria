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
# session 管理
# =========================
def _lock_session_creation(conn, lock_key: str) -> None:
    if isinstance(conn, sqlite3.Connection):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        return
    if _is_postgres_enabled():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (lock_key,),
        )


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
    with get_conn() as conn:
        _lock_session_creation(
            conn,
            f"active-single-session:{player_id}:{character_id}",
        )
        row = conn.execute(
            """
            SELECT *
            FROM session
            WHERE player_id = ?
              AND character_id = ?
              AND status = 'active'
              AND is_multi_character = 0
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """,
            (player_id, character_id),
        ).fetchone()
        if row is not None:
            return dict(row), False

        conn.execute(
            """
            INSERT INTO session
            (session_id, character_id, player_id, player_name, created_at, status,
             locale, story_id)
            VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                session_id,
                character_id,
                player_id,
                player_name,
                _now(),
                locale,
                (story_id or "").strip() or None,
            ),
        )
        row = conn.execute(
            "SELECT * FROM session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return dict(row), True


def get_session(session_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM session WHERE session_id = ?",
            (session_id,),
        ).fetchone()

    return _row_to_dict(row)

def end_session(session_id: str):
    """标记会话为结束状态"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE session
            SET status = 'ended', ended_at = ?
            WHERE session_id = ?
            """,
            (_now(), session_id),
        )


def get_latest_active_session(player_id: str, character_id: str | None = None) -> dict | None:
    """获取玩家最近的 active session（用于断线恢复）"""
    with get_conn() as conn:
        if character_id:
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
                WHERE s.player_id = ? AND s.character_id = ? AND s.status = 'active' AND s.is_multi_character = 0
                ORDER BY COALESCE(last_message_at, s.created_at) DESC
                LIMIT 1
                """,
                (player_id, character_id),
            ).fetchone()
        else:
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
                WHERE s.player_id = ? AND s.status = 'active'
                ORDER BY COALESCE(last_message_at, s.created_at) DESC
                LIMIT 1
                """,
                (player_id,),
            ).fetchone()
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

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT locale
            FROM session
            WHERE character_id = ? AND player_id = ?
              AND COALESCE(is_multi_character, 0) = 0
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """,
            (character_id, player_id),
        ).fetchone()
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
    with get_conn() as conn:
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, action, affinity_delta, trust_delta,
             current_affinity, current_trust, current_mood, event_notification,
             knowledge_sources, created_at, world_created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            insert_sql,
            (
                session_id,
                role,
                content,
                action,
                affinity_delta,
                trust_delta,
                current_affinity,
                current_trust,
                current_mood,
                event_notification,
                _encode_knowledge_sources(knowledge_sources),
                _now(),
                world_created_at,
            ),
        )
        return cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid


def get_short_term_message(session_id: str, message_id: int) -> dict | None:
    """Return one persisted message, scoped to its session."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM short_term_message
            WHERE session_id = ? AND id = ?
            LIMIT 1
            """,
            (session_id, message_id),
        ).fetchone()
    return _decode_message_row(row) if row else None
        
def get_short_term_history(session_id: str, limit_turns: int) -> list[dict]:
    """
    获取短期记忆（最近 N 轮对话）

    说明：
    - 每轮 = user + assistant = 2条消息
    - 返回按时间正序（适配 LLM）
    """

    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit_turns * 2),
        ).fetchall()

    messages = [{"role": r["role"], "content": r["content"]} for r in rows]
    messages.reverse()
    return messages


def get_session_user_turn_count(session_id: str) -> int:
    """获取当前会话已经写入的玩家回合数。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS turn_count
            FROM short_term_message
            WHERE session_id = ? AND role = 'user'
            """,
            (session_id,),
        ).fetchone()
    return int(row["turn_count"]) if row else 0


def count_character_user_turns(player_id: str, character_id: str) -> int:
    """Count player turns across every single and group chat involving a character."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS turn_count
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND m.role = 'user'
              AND (
                  (COALESCE(s.is_multi_character, 0) = 0 AND s.character_id = ?)
                  OR
                  (
                      COALESCE(s.is_multi_character, 0) = 1
                      AND EXISTS (
                          SELECT 1
                          FROM multi_session_participant p
                          WHERE p.session_id = s.session_id
                            AND p.character_id = ?
                      )
                  )
              )
            """,
            (player_id, character_id, character_id),
        ).fetchone()
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
    with get_conn() as conn:
        rows = conn.execute(
            """
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
                        INNER JOIN session sm ON sm.session_id = m.session_id
                        WHERE sm.character_id = s.character_id
                          AND sm.player_id = s.player_id
                          AND COALESCE(sm.is_multi_character, 0) = 0
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
                        INNER JOIN session sm ON sm.session_id = m.session_id
                        WHERE sm.character_id = s.character_id
                          AND sm.player_id = s.player_id
                          AND COALESCE(sm.is_multi_character, 0) = 0
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
                        INNER JOIN session sm ON sm.session_id = m.session_id
                        WHERE sm.character_id = s.character_id
                          AND sm.player_id = s.player_id
                          AND COALESCE(sm.is_multi_character, 0) = 0
                    )
                END AS message_count
            FROM session s
            LEFT JOIN character_card c
              ON c.owner_user_id = s.player_id
             AND c.character_id = s.character_id
            WHERE s.character_id = ? AND s.player_id = ? AND COALESCE(s.is_multi_character, 0) = 0
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            """,
            (character_id, player_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_player_sessions(player_id: str) -> list[dict]:
    """查询玩家会话；群聊按逻辑线程聚合，单聊保持原有物理会话结果。"""
    with get_conn() as conn:
        single_rows = conn.execute(
            """
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
            WHERE s.player_id = ? AND COALESCE(s.is_multi_character, 0) = 0
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            """,
            (player_id,),
        ).fetchall()

        group_sessions = conn.execute(
            """
            SELECT s.*
            FROM session s
            WHERE s.player_id = ? AND COALESCE(s.is_multi_character, 0) = 1
            ORDER BY CASE WHEN s.status = 'active' THEN 0 ELSE 1 END,
                     s.created_at DESC, s.session_id DESC
            """,
            (player_id,),
        ).fetchall()

        group_rows = []
        seen_group_threads = set()
        for raw_session in group_sessions:
            session = dict(raw_session)
            thread_id = session.get("group_thread_id") or session["session_id"]
            if thread_id in seen_group_threads:
                continue
            seen_group_threads.add(thread_id)

            latest_message = conn.execute(
                """
                SELECT m.id AS message_id, m.content, m.created_at
                FROM short_term_message m
                INNER JOIN session sm ON sm.session_id = m.session_id
                WHERE sm.player_id = ?
                  AND COALESCE(sm.is_multi_character, 0) = 1
                  AND COALESCE(sm.group_thread_id, sm.session_id) = ?
                ORDER BY m.id DESC
                LIMIT 1
                """,
                (player_id, thread_id),
            ).fetchone()
            message_count_row = conn.execute(
                """
                SELECT COUNT(*) AS message_count
                FROM short_term_message m
                INNER JOIN session sm ON sm.session_id = m.session_id
                WHERE sm.player_id = ?
                  AND COALESCE(sm.is_multi_character, 0) = 1
                  AND COALESCE(sm.group_thread_id, sm.session_id) = ?
                """,
                (player_id, thread_id),
            ).fetchone()
            unread_row = conn.execute(
                """
                SELECT COALESCE(SUM(unread_count), 0) AS unread_count
                FROM player_event_inbox
                WHERE player_id = ? AND event_type = 'group_message'
                  AND group_thread_id = ? AND read_at IS NULL
                """,
                (player_id, thread_id),
            ).fetchone()

            latest = dict(latest_message) if latest_message else {}
            session.update({
                "group_thread_id": thread_id,
                "last_message": latest.get("content"),
                "last_message_at": latest.get("created_at"),
                "latest_message_id": latest.get("message_id"),
                "message_count": int(message_count_row["message_count"] or 0),
                "unread_count": int(unread_row["unread_count"] or 0),
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

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM session
            WHERE player_id = ?
              AND COALESCE(is_multi_character, 0) = 1
              AND LOWER(TRIM(group_name)) = LOWER(?)
            LIMIT 1
            """,
            (player_id, clean_group_name),
        ).fetchone()
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
    with get_conn() as conn:
        # 先统计总数
        total_count = conn.execute(
            "SELECT COUNT(*) FROM short_term_message WHERE session_id = ?",
            (session_id,)
        ).fetchone()[0]
        
        # 倒序查询（最新的在前）
        rows = conn.execute(
            """
            SELECT id AS message_id, role, content, action,
                   affinity_delta, trust_delta,
                   current_affinity, current_trust, current_mood,
                   event_notification, knowledge_sources, created_at,
                   world_created_at
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit + 1, offset),
        ).fetchall()

    has_more = len(rows) > limit
    # 取前 limit 条，并反转顺序（变回正序）
    messages = [_decode_message_row(r) for r in reversed(rows[:limit])]

    return messages, has_more


def get_session_messages(session_id: str, limit: int = 1000) -> list[dict]:
    """按时间正序获取单个 session 的消息，用于回放和质量评分。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id AS message_id, role, content, character_id, character_name,
                   action, affinity_delta, trust_delta,
                   current_affinity, current_trust, current_mood,
                   event_notification, knowledge_sources, created_at,
                   world_created_at
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
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

    with get_conn() as conn:
        exclude_clause = ""
        params: list = [character_id, player_id]

        if exclude_session_id:
            exclude_clause = "AND s.session_id != ?"
            params.append(exclude_session_id)

        params.extend([limit + 1, offset])

        rows = conn.execute(
            f"""
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
                s.character_id = ?
                AND s.player_id = ?
                AND s.is_multi_character = 0
                {exclude_clause}
            ORDER BY
                m.id DESC
            LIMIT ?
            OFFSET ?
            """,
            params,
        ).fetchall()

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
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT COALESCE(m.world_created_at, m.created_at) AS interaction_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND (
                (COALESCE(s.is_multi_character, 0) = 0 AND s.character_id = ?)
                OR
                (COALESCE(s.is_multi_character, 0) = 1 AND m.character_id = ?)
              )
            ORDER BY m.id DESC
            LIMIT 1
            """,
            (player_id, character_id, character_id),
        ).fetchone()
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
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM session_summary WHERE session_id=? AND character_id=? AND player_id=? LIMIT 1",
            (session_id, character_id, player_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE session_summary SET summary_text=?, message_count=?, summary_status=?, created_at=? WHERE id=?",
                (summary_text, message_count, summary_status, _now(), existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO session_summary
                   (session_id, character_id, player_id, summary_text, message_count, summary_status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, character_id, player_id, summary_text, message_count, summary_status, _now()),
            )
        
def get_session_summary(session_id: str) -> dict | None:
    """获取指定会话的摘要"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM session_summary
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        
    return _row_to_dict(row)

def get_recent_summaries(
    character_id: str,
    player_id: str,
    limit: int = 5
) -> list[dict]:
    """获取角色与玩家的最近会话摘要"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT ss.*, s.created_at as session_created_at
            FROM session_summary ss
            JOIN session s ON ss.session_id = s.session_id
            WHERE ss.character_id = ? AND ss.player_id = ?
            ORDER BY ss.created_at DESC
            LIMIT ?
            """,
            (character_id, player_id, limit),
        ).fetchall()
        
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
    importance: float = 0.5
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

    with get_conn() as conn:
        existing = _dedup_check(
            conn,
            "shared_memory",
            "memory_text",
            impression_text,
            """
            owner_user_id = ?
            AND observer_character_id = ?
            AND target_character_id = ?
            AND memory_kind = 'character_impression'
            """,
            (owner_user_id, observer_character_id, target_character_id),
            threshold=0.92,
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute("UPDATE shared_memory SET importance=?, last_referenced=? WHERE id=?",
                         (new_imp, _now(), existing["id"]))
            return existing["id"]

        conn.execute(
            """
            INSERT INTO shared_memory
            (id, owner_user_id, character_a_id, character_b_id,
             observer_character_id, target_character_id, memory_kind,
             memory_text, context, importance, created_at, last_referenced,
             reference_count)
            VALUES (?, ?, ?, ?, ?, ?, 'character_impression', ?, ?, ?, ?, ?, 0)
            """,
            (
                memory_id,
                owner_user_id,
                observer_character_id,
                target_character_id,
                observer_character_id,
                target_character_id,
                impression_text,
                context,
                importance,
                _now(),
                _now(),
            ),
        )

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
        owner_user_id = ?
        AND observer_character_id = ?
        AND target_character_id = ?
        AND memory_kind = 'character_impression'
    """
    params = [owner_user_id, observer_character_id, target_character_id]
    if created_after:
        where_clause += " AND created_at >= ?"
        params.append(created_after)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, observer_character_id, target_character_id,
                   memory_text, context, importance, created_at
            FROM shared_memory
            WHERE {where_clause}
            ORDER BY importance DESC, last_referenced DESC
            LIMIT ?
            """,
            tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_observer_character_impressions(
    owner_user_id: str,
    observer_character_id: str,
    limit: int = 20,
) -> list[dict]:
    """获取一个角色对其他角色形成的全部定向印象。"""
    if not owner_user_id:
        raise ValueError("owner_user_id is required for shared_memory isolation")
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, owner_user_id, observer_character_id,
                   target_character_id, memory_text, context, importance,
                   created_at
            FROM shared_memory
            WHERE owner_user_id = ?
              AND observer_character_id = ?
              AND memory_kind = 'character_impression'
            ORDER BY importance DESC, last_referenced DESC
            LIMIT ?
            """,
            (owner_user_id, observer_character_id, limit),
        ).fetchall()
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
    importance: float = 0.5
) -> str:
    """保存多角色会话的群体记忆。含去重检查。"""
    import uuid, json
    memory_id = str(uuid.uuid4())
    participants_json = json.dumps(participants) if participants else None

    with get_conn() as conn:
        existing = _dedup_check(
            conn, "group_memory", "memory_text", memory_text,
            "session_id = ?",
            (session_id,), threshold=0.75
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute("UPDATE group_memory SET importance=?, last_referenced=? WHERE id=?",
                         (new_imp, _now(), existing["id"]))
            return existing["id"]

        conn.execute(
            "INSERT INTO group_memory (id, session_id, memory_text, participants, context, importance, created_at, last_referenced, reference_count) VALUES (?,?,?,?,?,?,?,?,0)",
            (memory_id, session_id, memory_text, participants_json, context, importance, _now(), _now()))

    return memory_id


def get_session_group_memories(
    session_id: str,
    limit: int = 20,
    created_after: str | None = None
) -> list[dict]:
    """获取某个会话的群体记忆"""
    where_clause = "session_id=?"
    params = [session_id]
    if created_after:
        where_clause += " AND created_at >= ?"
        params.append(created_after)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT id, memory_text, participants, context, importance, created_at FROM group_memory WHERE {where_clause} ORDER BY importance DESC, last_referenced DESC LIMIT ?",
            tuple(params)).fetchall()
    return [dict(r) for r in rows]


def get_character_group_memories(
    character_id: str,
    limit: int = 20,
    created_after: str | None = None,
    owner_user_id: str | None = None
) -> list[dict]:
    """获取某个角色参与过的群体记忆"""
    table_clause = "group_memory"
    prefix = ""
    where_clause = "participants LIKE ?"
    params = [f"%{character_id}%"]
    if owner_user_id:
        table_clause = "group_memory gm JOIN session s ON s.session_id = gm.session_id"
        prefix = "gm."
        where_clause = "gm.participants LIKE ? AND s.player_id = ?"
        params.append(owner_user_id)
    if created_after:
        where_clause += f" AND {prefix}created_at >= ?"
        params.append(created_after)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT {prefix}id, {prefix}session_id, {prefix}memory_text, {prefix}participants, {prefix}context, {prefix}importance, {prefix}created_at FROM {table_clause} WHERE {where_clause} ORDER BY {prefix}importance DESC, {prefix}last_referenced DESC LIMIT ?",
            tuple(params)).fetchall()
    return [dict(r) for r in rows]

