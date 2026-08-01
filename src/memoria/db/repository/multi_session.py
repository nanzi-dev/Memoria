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
# 多角色会话管理
# =========================

def _new_group_thread_id() -> str:
    return f"group-thread-{uuid.uuid4().hex}"


def _insert_multi_character_session_in_transaction(
    conn,
    *,
    session_id: str,
    player_id: str,
    player_name: str,
    character_ids: list[str],
    group_name: str | None,
    group_thread_id: str | None,
    locale: str,
    story_id: str | None,
) -> str:
    clean_group_name = (group_name or "").strip() or None
    clean_story_id = (story_id or "").strip() or None
    requested_thread_id = (group_thread_id or "").strip() or None
    thread_id = requested_thread_id or _new_group_thread_id()
    if clean_story_id is None and requested_thread_id:
        story_row = conn.execute(
            text("""
            SELECT story_id
            FROM session
            WHERE player_id = :player_id
              AND group_thread_id = :thread_id
              AND COALESCE(story_id, '') <> ''
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """),
            {"player_id": player_id, "thread_id": thread_id},
        ).mappings().fetchone()
        if story_row:
            clean_story_id = str(story_row["story_id"]).strip() or None

    created_at = _now()
    conn.execute(
        text("""
        INSERT INTO session
        (session_id, character_id, player_id, player_name, created_at, status,
         group_name, group_thread_id, story_id, is_multi_character, locale)
        VALUES (:session_id, :character_id, :player_id, :player_name,
                :created_at, 'active', :group_name, :thread_id, :story_id,
                1, :locale)
        """),
        {
            "session_id": session_id,
            "character_id": character_ids[0],
            "player_id": player_id,
            "player_name": player_name,
            "created_at": created_at,
            "group_name": clean_group_name,
            "thread_id": thread_id,
            "story_id": clean_story_id,
            "locale": locale,
        },
    )

    for idx, char_id in enumerate(character_ids):
        conn.execute(
            text("""
            INSERT INTO multi_session_participant
            (session_id, character_id, join_order, speak_frequency, is_active, created_at)
            VALUES (:session_id, :character_id, :join_order,
                    :speak_frequency, 1, :created_at)
            """),
            {
                "session_id": session_id,
                "character_id": char_id,
                "join_order": idx,
                "speak_frequency": 1.0,
                "created_at": created_at,
            },
        )

    conn.execute(
        text("""
        INSERT INTO group_dialogue_state
        (group_thread_id, player_id, created_at, updated_at)
        VALUES (:thread_id, :player_id, :created_at, :updated_at)
        ON CONFLICT(group_thread_id) DO UPDATE SET
            player_id = excluded.player_id,
            updated_at = excluded.updated_at
        """),
        {
            "thread_id": thread_id,
            "player_id": player_id,
            "created_at": created_at,
            "updated_at": created_at,
        },
    )
    return thread_id


def create_multi_character_session(
    session_id: str,
    player_id: str,
    player_name: str,
    character_ids: list[str],
    group_name: str | None = None,
    group_thread_id: str | None = None,
    locale: str = "zh-CN",
    story_id: str | None = None,
) -> bool:
    """
    创建多角色群聊会话
    
    Args:
        session_id: 会话 ID
        player_id: 玩家 ID
        player_name: 玩家名称
        character_ids: 参与角色ID列表
    
    Returns:
        bool: 是否创建成功
    """
    if not character_ids:
        logger.error("多角色会话必须至少包含一个角色")
        return False
    
    try:
        with db_session() as conn:
            _insert_multi_character_session_in_transaction(
                conn,
                session_id=session_id,
                player_id=player_id,
                player_name=player_name,
                character_ids=character_ids,
                group_name=group_name,
                group_thread_id=group_thread_id,
                locale=locale,
                story_id=story_id,
            )
        
        logger.info(f"多角色会话已创建: {session_id}, 参与角色: {character_ids}")
        return True
    
    except Exception as e:
        logger.error(f"创建多角色会话失败: {e}")
        return False


def get_or_create_active_multi_character_session(
    *,
    session_id: str,
    player_id: str,
    player_name: str,
    character_ids: list[str],
    group_name: str | None,
    group_thread_id: str,
    locale: str = "zh-CN",
    story_id: str | None = None,
) -> tuple[dict, bool]:
    """Atomically reuse or create an active segment for one group thread."""
    if not character_ids:
        raise ValueError("多角色会话必须至少包含一个角色")
    clean_thread_id = (group_thread_id or "").strip()
    if not clean_thread_id:
        raise ValueError("继续群聊必须提供 group_thread_id")

    with db_session() as conn:
        _lock_session_creation(
            conn,
            f"active-multi-session:{clean_thread_id}",
        )
        row = conn.execute(
            text("""
            SELECT *
            FROM session
            WHERE player_id = :player_id
              AND group_thread_id = :group_thread_id
              AND status = 'active'
              AND is_multi_character = 1
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """),
            {"player_id": player_id, "group_thread_id": clean_thread_id},
        ).mappings().fetchone()
        if row is not None:
            return dict(row), False

        _insert_multi_character_session_in_transaction(
            conn,
            session_id=session_id,
            player_id=player_id,
            player_name=player_name,
            character_ids=character_ids,
            group_name=group_name,
            group_thread_id=clean_thread_id,
            locale=locale,
            story_id=story_id,
        )
        row = conn.execute(
            text("SELECT * FROM session WHERE session_id = :session_id"),
            {"session_id": session_id},
        ).mappings().fetchone()
        return dict(row), True


def get_session_participants(session_id: str, only_active: bool = True) -> list[dict]:
    """
    获取会话参与者列表
    
    Args:
        session_id: 会话 ID
        only_active: 是否仅返回活跃参与者
    
    Returns:
        list[dict]: 参与者信息列表
    """
    with db_session() as conn:
        query = """
            SELECT
                p.session_id,
                p.character_id,
                p.join_order,
                p.speak_frequency,
                CASE
                    WHEN p.is_active = 1 AND c.is_active = 1 THEN 1
                    ELSE 0
                END AS is_active,
                p.created_at,
                p.last_spoke_at,
                p.message_count,
                c.name,
                c.display_name,
                c.avatar_url
            FROM multi_session_participant p
            INNER JOIN session s ON s.session_id = p.session_id
            LEFT JOIN character_card c
              ON c.owner_user_id = s.player_id
             AND c.character_id = p.character_id
            WHERE p.session_id = :session_id
        """
        
        if only_active:
            query += " AND p.is_active = 1 AND c.is_active = 1"
        
        query += " ORDER BY p.join_order ASC"
        
        rows = conn.execute(text(query), {"session_id": session_id}).mappings().fetchall()
    
    return [dict(r) for r in rows]


def get_group_thread_id(session_id: str) -> str | None:
    """返回群聊逻辑线程 ID，并为旧群聊补建独立逻辑线程。"""
    session = get_session(session_id)
    if not session or not session.get("is_multi_character"):
        return None
    thread_id = str(session.get("group_thread_id") or "").strip()
    if thread_id:
        return thread_id

    generated_thread_id = _new_group_thread_id()
    now = _now()
    with db_session() as conn:
        conn.execute(
            text("""
            UPDATE session
            SET group_thread_id = :generated_thread_id
            WHERE session_id = :session_id
              AND COALESCE(group_thread_id, '') = ''
            """),
            {
                "generated_thread_id": generated_thread_id,
                "session_id": session_id,
            },
        )
        row = conn.execute(
            text("""
            SELECT group_thread_id
            FROM session
            WHERE session_id = :session_id
            """),
            {"session_id": session_id},
        ).mappings().fetchone()
        thread_id = str(row["group_thread_id"] or "").strip() if row else ""
        if thread_id:
            conn.execute(
                text("""
                INSERT INTO group_dialogue_state
                (group_thread_id, player_id, created_at, updated_at)
                VALUES (:thread_id, :player_id, :created_at, :updated_at)
                ON CONFLICT(group_thread_id) DO UPDATE SET
                    player_id = excluded.player_id,
                    updated_at = excluded.updated_at
                """),
                {
                    "thread_id": thread_id,
                    "player_id": session["player_id"],
                    "created_at": now,
                    "updated_at": now,
                },
            )
    return thread_id or None


def get_multi_character_thread_sessions(session_id: str) -> list[dict]:
    """获取同一逻辑群聊下的所有物理 session。"""
    session = get_session(session_id)
    if not session:
        return []
    thread_id = session.get("group_thread_id") or session["session_id"]
    if not thread_id:
        return []
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT session_id, status, group_name, group_thread_id, locale, created_at, ended_at
            FROM session
            WHERE player_id = :player_id
              AND COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = :thread_id
            ORDER BY created_at ASC, session_id ASC
            """),
            {"player_id": session["player_id"], "thread_id": thread_id},
        ).mappings().fetchall()
    return [dict(r) for r in rows]


def update_participant_speak_time(session_id: str, character_id: str):
    """
    更新参与者最后发言时间和发言次数
    
    Args:
        session_id: 会话 ID
        character_id: 角色 ID
    """
    with db_session() as conn:
        conn.execute(
            text("""
            UPDATE multi_session_participant
            SET last_spoke_at = :last_spoke_at,
                message_count = message_count + 1
            WHERE session_id = :session_id AND character_id = :character_id
            """),
            {
                "last_spoke_at": _now(),
                "session_id": session_id,
                "character_id": character_id,
            },
        )


def append_multi_character_message(
    session_id: str,
    role: str,
    content: str,
    character_id: str = None,
    character_name: str = None,
    world_created_at: str | None = None,
    knowledge_sources: list[dict] | None = None,
    reply_to_message_id: int | None = None,
    reply_to_character_id: str | None = None,
    intent: str | None = None,
    topic: str | None = None,
    trigger_source: str | None = None,
    runtime_state: dict | None = None,
) -> int:
    """
    添加多角色会话消息
    
    Args:
        session_id: 会话 ID
        role: 角色类型 (user/assistant)
        content: 消息内容
        character_id: 发言角色ID（assistant时必填）
        character_name: 发言角色显示名称
        runtime_state: 可选，随消息在同一事务内写入的角色状态
            （需包含 player_id/affection_level/trust_level/current_mood）
    """
    with db_session() as conn:
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, character_id, character_name, created_at,
             knowledge_sources, world_created_at, reply_to_message_id,
             reply_to_character_id, intent, topic, trigger_source)
            VALUES (:session_id, :role, :content, :character_id,
                    :character_name, :created_at, :knowledge_sources,
                    :world_created_at, :reply_to_message_id,
                    :reply_to_character_id, :intent, :topic, :trigger_source)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            text(insert_sql),
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "character_id": character_id,
                "character_name": character_name,
                "created_at": _now(),
                "knowledge_sources": _encode_knowledge_sources(knowledge_sources),
                "world_created_at": world_created_at,
                "reply_to_message_id": reply_to_message_id,
                "reply_to_character_id": reply_to_character_id,
                "intent": intent,
                "topic": topic,
                "trigger_source": trigger_source,
            },
        )
        if _is_postgres_enabled():
            message_id = cursor.mappings().fetchone()["id"]
        else:
            message_id = cursor.lastrowid

        # 如果是角色发言，在同一事务内更新参与者统计，保证原子性
        if role == "assistant" and character_id:
            conn.execute(
                text("""
                UPDATE multi_session_participant
                SET last_spoke_at = :last_spoke_at,
                    message_count = message_count + 1
                WHERE session_id = :session_id AND character_id = :character_id
                """),
                {
                    "last_spoke_at": _now(),
                    "session_id": session_id,
                    "character_id": character_id,
                },
            )

        if runtime_state and character_id:
            _save_runtime_state_in_transaction(
                conn,
                character_id=character_id,
                player_id=runtime_state["player_id"],
                affection_level=runtime_state["affection_level"],
                trust_level=runtime_state["trust_level"],
                current_mood=runtime_state["current_mood"],
                now=_now(),
            )
    return int(message_id)


def update_multi_character_message(
    message_id: int,
    session_id: str,
    *,
    content: str,
    character_id: str,
    character_name: str,
    world_created_at: str | None = None,
    knowledge_sources: list[dict] | None = None,
    reply_to_message_id: int | None = None,
    reply_to_character_id: str | None = None,
    intent: str | None = None,
    topic: str | None = None,
    trigger_source: str | None = None,
) -> bool:
    """更新群聊脉冲中已落库的角色消息，不重复增加参与者发言计数。"""
    with db_session() as conn:
        cursor = conn.execute(
            text("""
            UPDATE short_term_message
            SET content = :content,
                character_id = :character_id,
                character_name = :character_name,
                knowledge_sources = :knowledge_sources,
                world_created_at = :world_created_at,
                reply_to_message_id = :reply_to_message_id,
                reply_to_character_id = :reply_to_character_id,
                intent = :intent,
                topic = :topic,
                trigger_source = :trigger_source
            WHERE id = :message_id AND session_id = :session_id
              AND role = 'assistant'
            """),
            {
                "content": content,
                "character_id": character_id,
                "character_name": character_name,
                "knowledge_sources": _encode_knowledge_sources(knowledge_sources),
                "world_created_at": world_created_at,
                "reply_to_message_id": reply_to_message_id,
                "reply_to_character_id": reply_to_character_id,
                "intent": intent,
                "topic": topic,
                "trigger_source": trigger_source,
                "message_id": int(message_id),
                "session_id": session_id,
            },
        )
        return cursor.rowcount > 0


def get_multi_character_history(
    session_id: str,
    limit_messages: int | None = 20,
    created_after: str | None = None
) -> list[dict]:
    """
    获取多角色会话历史
    
    Args:
        session_id: 会话 ID
        limit_messages: 最大消息数量；传 None 时返回全部消息
        created_after: 只返回该时间之后创建的消息
    
    Returns:
        list[dict]: 消息列表，包含 role, content, character_id, character_name
    """
    created_after_clause = ""
    base_params = {"session_id": session_id}
    if created_after:
        created_after_clause = "AND created_at >= :created_after"
        base_params["created_after"] = created_after

    with db_session() as conn:
        if limit_messages is None:
            rows = conn.execute(
                text(f"""
                SELECT id AS message_id, session_id, role, content, character_id,
                       character_name, knowledge_sources, reply_to_message_id,
                       reply_to_character_id, intent, topic, trigger_source,
                       created_at, world_created_at
                FROM short_term_message
                WHERE session_id = :session_id
                  {created_after_clause}
                ORDER BY id ASC
                """),
                base_params,
            ).mappings().fetchall()
            return [_decode_message_row(r) for r in rows]

        params = {**base_params, "limit_messages": limit_messages}
        rows = conn.execute(
            text(f"""
            SELECT id AS message_id, session_id, role, content, character_id,
                   character_name, knowledge_sources, reply_to_message_id,
                   reply_to_character_id, intent, topic, trigger_source,
                   created_at, world_created_at
            FROM short_term_message
            WHERE session_id = :session_id
              {created_after_clause}
            ORDER BY id DESC
            LIMIT :limit_messages
            """),
            params,
        ).mappings().fetchall()

    messages = [_decode_message_row(r) for r in rows]
    messages.reverse()  # 按时间正序返回
    return messages


def get_multi_character_thread_history(
    session_id: str,
    limit_messages: int | None = 20,
    created_after: str | None = None
) -> list[dict]:
    """
    获取同一逻辑群聊下跨多个 session 的历史消息。
    """
    session = get_session(session_id)
    if not session:
        return []
    thread_id = session.get("group_thread_id") or session["session_id"]
    if not thread_id:
        return []
    created_after_clause = ""
    base_params = {
        "player_id": session["player_id"],
        "thread_id": thread_id,
    }
    if created_after:
        created_after_clause = "AND m.created_at >= :created_after"
        base_params["created_after"] = created_after

    with db_session() as conn:
        if limit_messages is None:
            rows = conn.execute(
                text(f"""
                SELECT m.id AS message_id, m.session_id, m.role, m.content,
                       m.character_id, m.character_name, m.knowledge_sources,
                       m.reply_to_message_id, m.reply_to_character_id,
                       m.intent, m.topic, m.trigger_source,
                       m.created_at, m.world_created_at
                FROM short_term_message m
                INNER JOIN session s ON s.session_id = m.session_id
                WHERE s.player_id = :player_id
                  AND COALESCE(s.is_multi_character, 0) = 1
                  AND COALESCE(s.group_thread_id, s.session_id) = :thread_id
                  {created_after_clause}
                ORDER BY m.id ASC
                """),
                base_params,
            ).mappings().fetchall()
            return [_decode_message_row(r) for r in rows]

        params = {**base_params, "limit_messages": limit_messages}
        rows = conn.execute(
            text(f"""
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = :thread_id
              {created_after_clause}
            ORDER BY m.id DESC
            LIMIT :limit_messages
            """),
            params,
        ).mappings().fetchall()

    messages = [_decode_message_row(r) for r in rows]
    messages.reverse()
    return messages


def get_multi_character_thread_history_paginated(
    session_id: str,
    offset: int = 0,
    limit: int = 20,
) -> tuple[list[dict], bool]:
    """
    分页获取同一逻辑群聊下跨多个 session 的历史消息。

    offset=0 返回最新一页，结果按时间正序排列；offset 增大时返回更早消息。
    """
    session = get_session(session_id)
    if not session:
        return [], False

    thread_id = session.get("group_thread_id") or session["session_id"]
    if not thread_id:
        return [], False
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = :thread_id
            ORDER BY m.id DESC
            LIMIT :limit
            OFFSET :offset
            """),
            {
                "player_id": session["player_id"],
                "thread_id": thread_id,
                "limit": limit + 1,
                "offset": offset,
            },
        ).mappings().fetchall()

    has_more = len(rows) > limit
    return [_decode_message_row(row) for row in reversed(rows[:limit])], has_more


def get_multi_character_thread_history_after(
    session_id: str,
    after_message_id: int,
    limit: int = 200,
) -> tuple[list[dict], bool, int]:
    """按稳定消息 ID 增量读取逻辑群聊历史，结果按 ID 正序。"""
    session = get_session(session_id)
    if not session:
        return [], False, max(0, int(after_message_id or 0))

    thread_id = session.get("group_thread_id") or session["session_id"]
    after_id = max(0, int(after_message_id or 0))

    with db_session() as conn:
        latest_row = conn.execute(
            text("""
            SELECT MAX(m.id) AS latest_message_id
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = :thread_id
            """),
            {"player_id": session["player_id"], "thread_id": thread_id},
        ).mappings().fetchone()
        rows = conn.execute(
            text("""
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = :player_id
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = :thread_id
              AND m.id > :after_id
            ORDER BY m.id ASC
            LIMIT :limit
            """),
            {
                "player_id": session["player_id"],
                "thread_id": thread_id,
                "after_id": after_id,
                "limit": limit + 1,
            },
        ).mappings().fetchall()

    has_more = len(rows) > limit
    messages = [_decode_message_row(row) for row in rows[:limit]]
    latest = _row_to_dict(latest_row) or {}
    latest_message_id = int(latest.get("latest_message_id") or after_id)
    return messages, has_more, latest_message_id


def _decode_group_dialogue_state(row) -> dict | None:
    state = _row_to_dict(row)
    if not state:
        return None
    try:
        hooks = json.loads(state.get("unresolved_hooks") or "[]")
    except (TypeError, ValueError):
        hooks = []
    state["unresolved_hooks"] = hooks if isinstance(hooks, list) else []
    state["waiting_for_player"] = bool(state.get("waiting_for_player"))
    state["daily_message_count"] = int(state.get("daily_message_count") or 0)
    return state


def get_group_dialogue_state(group_thread_id: str) -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            text(
                "SELECT * FROM group_dialogue_state "
                "WHERE group_thread_id = :group_thread_id"
            ),
            {"group_thread_id": group_thread_id},
        ).mappings().fetchone()
    return _decode_group_dialogue_state(row)


def save_group_dialogue_state(
    group_thread_id: str,
    player_id: str,
    *,
    current_topic: str | None = None,
    topic_source: str | None = None,
    last_reply_to_message_id: int | None = None,
    last_reply_to_character_id: str | None = None,
    last_speaker_id: str | None = None,
    waiting_for_player: bool = False,
    unresolved_hooks: list[dict] | None = None,
) -> bool:
    now = _now()
    with db_session() as conn:
        conn.execute(
            text("""
            INSERT INTO group_dialogue_state
            (group_thread_id, player_id, current_topic, topic_source,
             last_reply_to_message_id, last_reply_to_character_id,
             last_speaker_id, waiting_for_player, unresolved_hooks,
             created_at, updated_at)
            VALUES (:group_thread_id, :player_id, :current_topic, :topic_source,
                    :last_reply_to_message_id, :last_reply_to_character_id,
                    :last_speaker_id, :waiting_for_player, :unresolved_hooks,
                    :created_at, :updated_at)
            ON CONFLICT(group_thread_id) DO UPDATE SET
                player_id = excluded.player_id,
                current_topic = excluded.current_topic,
                topic_source = excluded.topic_source,
                last_reply_to_message_id = excluded.last_reply_to_message_id,
                last_reply_to_character_id = excluded.last_reply_to_character_id,
                last_speaker_id = excluded.last_speaker_id,
                waiting_for_player = excluded.waiting_for_player,
                unresolved_hooks = excluded.unresolved_hooks,
                updated_at = excluded.updated_at
            """),
            {
                "group_thread_id": group_thread_id,
                "player_id": player_id,
                "current_topic": current_topic,
                "topic_source": topic_source,
                "last_reply_to_message_id": last_reply_to_message_id,
                "last_reply_to_character_id": last_reply_to_character_id,
                "last_speaker_id": last_speaker_id,
                "waiting_for_player": 1 if waiting_for_player else 0,
                "unresolved_hooks": json.dumps(
                    unresolved_hooks or [], ensure_ascii=False
                ),
                "created_at": now,
                "updated_at": now,
            },
        )
    return True


def list_group_dialogue_states(limit: int = 500) -> list[dict]:
    with db_session() as conn:
        rows = conn.execute(
            text("""
            SELECT * FROM group_dialogue_state
            ORDER BY COALESCE(last_autonomous_pulse_at, created_at) ASC
            LIMIT :limit
            """),
            {"limit": limit},
        ).mappings().fetchall()
    return [_decode_group_dialogue_state(row) for row in rows]


def claim_group_dialogue_state(
    group_thread_id: str,
    *,
    lease_owner: str,
    lease_expires_at: str,
    real_now_iso: str,
) -> bool:
    """使用现实 UTC 租约原子领取一个逻辑群聊脉冲。"""
    with db_session() as conn:
        cursor = conn.execute(
            text("""
            UPDATE group_dialogue_state
            SET lease_owner = :lease_owner,
                lease_expires_at = :lease_expires_at,
                updated_at = :real_now_iso
            WHERE group_thread_id = :group_thread_id
              AND (lease_expires_at IS NULL OR lease_expires_at <= :real_now_iso)
            """),
            {
                "lease_owner": lease_owner,
                "lease_expires_at": lease_expires_at,
                "real_now_iso": real_now_iso,
                "group_thread_id": group_thread_id,
            },
        )
    return cursor.rowcount == 1


def complete_group_dialogue_pulse(
    group_thread_id: str,
    *,
    lease_owner: str,
    real_now_iso: str,
    world_now_iso: str,
    autonomous_message_count: int,
    daily_message_date: str,
    current_topic: str | None,
    topic_source: str | None,
    last_reply_to_message_id: int | None,
    last_reply_to_character_id: str | None,
    last_speaker_id: str | None,
    waiting_for_player: bool,
    unresolved_hooks: list[dict] | None,
) -> bool:
    """完成自主脉冲并在持有租约时提交线程状态和每日计数。"""
    with db_session() as conn:
        return _complete_group_dialogue_pulse_in_transaction(
            conn,
            group_thread_id,
            lease_owner=lease_owner,
            real_now_iso=real_now_iso,
            world_now_iso=world_now_iso,
            autonomous_message_count=autonomous_message_count,
            daily_message_date=daily_message_date,
            current_topic=current_topic,
            topic_source=topic_source,
            last_reply_to_message_id=last_reply_to_message_id,
            last_reply_to_character_id=last_reply_to_character_id,
            last_speaker_id=last_speaker_id,
            waiting_for_player=waiting_for_player,
            unresolved_hooks=unresolved_hooks,
        )


def _complete_group_dialogue_pulse_in_transaction(
    conn,
    group_thread_id: str,
    *,
    lease_owner: str,
    real_now_iso: str,
    world_now_iso: str,
    autonomous_message_count: int,
    daily_message_date: str,
    current_topic: str | None,
    topic_source: str | None,
    last_reply_to_message_id: int | None,
    last_reply_to_character_id: str | None,
    last_speaker_id: str | None,
    waiting_for_player: bool,
    unresolved_hooks: list[dict] | None,
) -> bool:
    cursor = conn.execute(
        text("""
        UPDATE group_dialogue_state
        SET current_topic = :current_topic, topic_source = :topic_source,
            last_reply_to_message_id = :last_reply_to_message_id,
            last_reply_to_character_id = :last_reply_to_character_id,
            last_speaker_id = :last_speaker_id,
            waiting_for_player = :waiting_for_player,
            unresolved_hooks = :unresolved_hooks,
            last_autonomous_pulse_at = :real_now_iso,
            last_autonomous_world_at = :world_now_iso,
            daily_message_date = :daily_message_date,
            daily_message_count = CASE
                WHEN daily_message_date = :daily_message_date
                    THEN daily_message_count + :autonomous_message_count
                ELSE :autonomous_message_count
            END,
            lease_owner = NULL, lease_expires_at = NULL, updated_at = :real_now_iso
        WHERE group_thread_id = :group_thread_id AND lease_owner = :lease_owner
        """),
        {
            "current_topic": current_topic,
            "topic_source": topic_source,
            "last_reply_to_message_id": last_reply_to_message_id,
            "last_reply_to_character_id": last_reply_to_character_id,
            "last_speaker_id": last_speaker_id,
            "waiting_for_player": 1 if waiting_for_player else 0,
            "unresolved_hooks": json.dumps(
                unresolved_hooks or [], ensure_ascii=False
            ),
            "real_now_iso": real_now_iso,
            "world_now_iso": world_now_iso,
            "daily_message_date": daily_message_date,
            "autonomous_message_count": autonomous_message_count,
            "group_thread_id": group_thread_id,
            "lease_owner": lease_owner,
        },
    )
    return cursor.rowcount == 1


def commit_group_dialogue_pulse(
    group_thread_id: str,
    session_id: str,
    player_id: str,
    responses: list[dict],
    *,
    lease_owner: str,
    real_now_iso: str,
    world_now_iso: str,
    autonomous_message_count: int,
    daily_message_date: str,
    current_topic: str | None,
    topic_source: str | None,
    last_reply_to_message_id: int | None,
    last_reply_to_character_id: str | None,
    last_speaker_id: str | None,
    waiting_for_player: bool,
    unresolved_hooks: list[dict] | None,
    group_name: str | None = None,
) -> list[dict]:
    """原子提交自主群聊消息、角色状态、线程状态和玩家通知。"""
    candidate_responses = [dict(response) for response in responses]
    committed_responses: list[dict] = []
    message_id_map: dict[int, int] = {}
    duplicate_suppressed = False

    def resolved_message_id(value):
        if not isinstance(value, int) or value >= 0:
            return value
        if value not in message_id_map:
            raise ValueError(f"未解析的群聊临时消息 ID: {value}")
        return message_id_map[value]

    with db_session() as conn:
        for response in candidate_responses:
            temporary_message_id = response.get("message_id")
            reply_to_message_id = resolved_message_id(
                response.get("reply_to_message_id")
            )
            recent_rows = conn.execute(
                text("""
                SELECT id, content, reply_to_message_id
                FROM short_term_message
                WHERE session_id = :session_id
                  AND role = 'assistant'
                  AND character_id = :character_id
                ORDER BY id DESC
                LIMIT 20
                """),
                {
                    "session_id": session_id,
                    "character_id": response.get("character_id"),
                },
            ).mappings().fetchall()
            duplicate_message_id = next(
                (
                    int(row["id"])
                    for index, row in enumerate(recent_rows)
                    if (
                        index < 4
                        or row["id"] == reply_to_message_id
                        or row["reply_to_message_id"] == reply_to_message_id
                    )
                    and dialogue_texts_redundant(
                        response.get("dialogue"),
                        row["content"],
                    )
                ),
                None,
            )
            if duplicate_message_id is not None:
                duplicate_suppressed = True
                if isinstance(temporary_message_id, int) and temporary_message_id < 0:
                    message_id_map[temporary_message_id] = duplicate_message_id
                response["message_id"] = duplicate_message_id
                response["reply_to_message_id"] = reply_to_message_id
                continue

            insert_sql = """
                INSERT INTO short_term_message
                (session_id, role, content, character_id, character_name, created_at,
                 knowledge_sources, world_created_at, reply_to_message_id,
                 reply_to_character_id, intent, topic, trigger_source)
                VALUES (:session_id, 'assistant', :content, :character_id,
                        :character_name, :created_at, :knowledge_sources,
                        :world_created_at, :reply_to_message_id,
                        :reply_to_character_id, :intent, :topic,
                        :trigger_source)
            """
            if _is_postgres_enabled():
                insert_sql += " RETURNING id"
            cursor = conn.execute(
                text(insert_sql),
                {
                    "session_id": session_id,
                    "content": response.get("dialogue", ""),
                    "character_id": response.get("character_id"),
                    "character_name": response.get("character_name"),
                    "created_at": real_now_iso,
                    "knowledge_sources": _encode_knowledge_sources(
                        response.get("knowledge_sources") or []
                    ),
                    "world_created_at": response.get("world_created_at")
                    or world_now_iso,
                    "reply_to_message_id": reply_to_message_id,
                    "reply_to_character_id": response.get("reply_to_character_id"),
                    "intent": response.get("intent"),
                    "topic": response.get("topic"),
                    "trigger_source": response.get("trigger_source"),
                },
            )
            message_id = int(
                cursor.mappings().fetchone()["id"]
                if _is_postgres_enabled()
                else cursor.lastrowid
            )
            if isinstance(temporary_message_id, int) and temporary_message_id < 0:
                message_id_map[temporary_message_id] = message_id
            response["message_id"] = message_id
            response["reply_to_message_id"] = reply_to_message_id
            committed_responses.append(response)

        latest_relationships: dict[str, dict] = {}
        participant_counts: dict[str, int] = {}
        for response in committed_responses:
            character_id = response.get("character_id")
            if not character_id:
                continue
            participant_counts[character_id] = participant_counts.get(character_id, 0) + 1
            if all(
                key in response
                for key in ("current_affinity", "current_trust", "current_mood")
            ):
                latest_relationships[character_id] = response

        for character_id, response in latest_relationships.items():
            conn.execute(
                text("""
                INSERT INTO relationship_state
                (character_id, player_id, affection_level, trust_level,
                 current_mood, updated_at)
                VALUES (:character_id, :player_id, :affection_level,
                        :trust_level, :current_mood, :updated_at)
                ON CONFLICT(character_id, player_id)
                DO UPDATE SET
                    affection_level = excluded.affection_level,
                    trust_level = excluded.trust_level,
                    current_mood = excluded.current_mood,
                    updated_at = excluded.updated_at
                """),
                {
                    "character_id": character_id,
                    "player_id": player_id,
                    "affection_level": response["current_affinity"],
                    "trust_level": response["current_trust"],
                    "current_mood": response["current_mood"],
                    "updated_at": real_now_iso,
                },
            )

        for character_id, message_count in participant_counts.items():
            conn.execute(
                text("""
                UPDATE multi_session_participant
                SET last_spoke_at = :real_now_iso,
                    message_count = message_count + :message_count
                WHERE session_id = :session_id AND character_id = :character_id
                """),
                {
                    "real_now_iso": real_now_iso,
                    "message_count": message_count,
                    "session_id": session_id,
                    "character_id": character_id,
                },
            )

        resolved_hooks = []
        for hook in unresolved_hooks or []:
            resolved_hook = dict(hook)
            resolved_hook["message_id"] = resolved_message_id(
                resolved_hook.get("message_id")
            )
            resolved_hooks.append(resolved_hook)

        completed = _complete_group_dialogue_pulse_in_transaction(
            conn,
            group_thread_id,
            lease_owner=lease_owner,
            real_now_iso=real_now_iso,
            world_now_iso=world_now_iso,
            autonomous_message_count=min(
                max(0, autonomous_message_count),
                len(committed_responses),
            ),
            daily_message_date=daily_message_date,
            current_topic=current_topic,
            topic_source=topic_source,
            last_reply_to_message_id=resolved_message_id(last_reply_to_message_id),
            last_reply_to_character_id=last_reply_to_character_id,
            last_speaker_id=last_speaker_id,
            waiting_for_player=waiting_for_player or duplicate_suppressed,
            unresolved_hooks=resolved_hooks,
        )
        if not completed:
            raise RuntimeError("群聊脉冲完成前租约已丢失")

        if committed_responses:
            _upsert_group_message_notification_in_transaction(
                conn,
                player_id,
                group_thread_id,
                session_id,
                len(committed_responses),
                group_name=group_name,
                world_created_at=world_now_iso,
            )

    return committed_responses


def release_group_dialogue_state(group_thread_id: str, *, lease_owner: str) -> bool:
    with db_session() as conn:
        cursor = conn.execute(
            text("""
            UPDATE group_dialogue_state
            SET lease_owner = NULL, lease_expires_at = NULL,
                updated_at = :updated_at
            WHERE group_thread_id = :group_thread_id AND lease_owner = :lease_owner
            """),
            {
                "updated_at": _now(),
                "group_thread_id": group_thread_id,
                "lease_owner": lease_owner,
            },
        )
    return cursor.rowcount == 1


def get_latest_group_thread_session(group_thread_id: str) -> dict | None:
    with db_session() as conn:
        row = conn.execute(
            text("""
            SELECT * FROM session
            WHERE COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = :group_thread_id
            ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                     created_at DESC, session_id DESC
            LIMIT 1
            """),
            {"group_thread_id": group_thread_id},
        ).mappings().fetchone()
    return _row_to_dict(row)
