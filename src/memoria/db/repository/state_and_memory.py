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
# runtime_state（角色状态）
# =========================
def get_runtime_state(
    character_id: str, 
    player_id: str, 
    card,
    query_context: str = None,
    memory_created_after: str | None = None
) -> dict:
     """
    获取角色运行时状态（好感度 / 信任 / 情绪）

    如果不存在 → 使用角色卡默认值初始化
    
    Args:
        character_id: 角色 ID
        player_id: 玩家 ID
        card: 角色卡对象
        query_context: 查询上下文（用于向量检索长期记忆）
        memory_created_after: 只加载该时间之后保存的长期记忆
    """
     with get_conn() as conn:
         row = conn.execute(
             """
             SELECT affection_level, trust_level, current_mood
             FROM relationship_state
             WHERE character_id = ? AND player_id = ?
             """,
             (character_id, player_id),
         ).fetchone()
         
         if row:
             state = {
                 "affection_level": row["affection_level"],
                 "trust_level": row["trust_level"],
                 "current_mood": row["current_mood"],
             }
         else:
             schema = getattr(card, "runtime_state_schema", None)
             mood_schema = getattr(schema, "current_mood", None)
             
             state = {
                 "affection_level": getattr(schema, "affection_level", 0),
                 "trust_level": getattr(schema, "trust_level", 10),
                 "current_mood": getattr(mood_schema, "default_mood", "neutral"),
             }
             
             conn.execute(
                """
                INSERT INTO relationship_state
                (character_id, player_id, affection_level, trust_level, current_mood, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, player_id) DO NOTHING
                """,
                (
                    character_id,
                    player_id,
                    state["affection_level"],
                    state["trust_level"],
                    state["current_mood"],
                    _now(),
                ),
             )
             row = conn.execute(
                 """
                 SELECT affection_level, trust_level, current_mood
                 FROM relationship_state
                 WHERE character_id = ? AND player_id = ?
                 """,
                 (character_id, player_id),
             ).fetchone()
             state = {
                 "affection_level": row["affection_level"],
                 "trust_level": row["trust_level"],
                 "current_mood": row["current_mood"],
             }
             
         # Task 5 完成迁移后，prompt 路径不得再读取 legacy 长期记忆。
         if has_data_migration(LONG_TERM_FACT_BACKFILL_MIGRATION):
             state["known_player_facts"] = []
         else:
             state["known_player_facts"] = get_long_term_facts(
                 character_id,
                 player_id,
                 query_context=query_context,
                 created_after=memory_created_after
             )
         unlock_rows = conn.execute(
             """
             SELECT unlock_key FROM event_unlock
             WHERE player_id = ? AND character_id = ?
             ORDER BY unlocked_at ASC, unlock_key ASC
             """,
             (player_id, character_id),
         ).fetchall()
         state["unlocked_content"] = [row["unlock_key"] for row in unlock_rows]
         return state
     

def save_runtime_state(character_id: str, player_id: str, affection_level: float, trust_level: float, current_mood: str):
    """更新角色状态"""
    now = _now()
    with get_conn() as conn:
        _save_runtime_state_in_transaction(
            conn,
            character_id=character_id,
            player_id=player_id,
            affection_level=affection_level,
            trust_level=trust_level,
            current_mood=current_mood,
            now=now,
        )
        

# =========================
# long term memory
# =========================
def get_long_term_facts(
    character_id: str, 
    player_id: str, 
    limit: int = 20,
    query_context: str = None,
    created_after: str | None = None
) -> list[str]:
    """
    获取长期记忆
    
    Args:
        character_id: 角色 ID
        player_id: 玩家 ID
        limit: 返回的最大记忆数量
        query_context: 查询上下文（用于向量检索），如果提供则使用语义检索
        created_after: 只返回该时间之后创建的记忆
    
    Returns:
        list[str]: 记忆文本列表
    """
    records = get_long_term_fact_records(
        character_id=character_id,
        player_id=player_id,
        limit=limit,
        query_context=query_context,
        created_after=created_after,
    )
    return [r["fact_text"] for r in records]


def get_long_term_fact_records(
    character_id: str,
    player_id: str,
    limit: int = 20,
    query_context: str = None,
    created_after: str | None = None
) -> list[dict]:
    """
    获取长期记忆记录，包含创建时间等元数据。

    `get_long_term_facts` 保持只返回文本；关系图谱过滤需要
    `created_at` 来区分图谱修订前后的关系事实。
    """
    # 如果提供了查询上下文，使用向量检索
    if query_context and not created_after:
        try:
            from memoria.core.vector_memory import get_vector_store
            vector_store = get_vector_store()
            
            # 向量检索获取相关记忆
            with tracing.start_span("memory.vector_search", character_id=character_id):
                with performance.measure("memory.vector_search"):
                    vector_results = vector_store.search_similar_memories(
                        character_id=character_id,
                        player_id=player_id,
                        query_text=query_context,
                        top_k=limit
                    )
            
            if vector_results:
                logger.debug(f"向量检索返回 {len(vector_results)} 条记忆")
                fact_ids = [r.get("fact_id") for r in vector_results if r.get("fact_id") is not None]
                records_by_id = {}
                if fact_ids:
                    placeholders = ",".join(["?"] * len(fact_ids))
                    with get_conn() as conn:
                        rows = conn.execute(
                            f"""
                            SELECT id, fact_text, importance, created_at, last_referenced
                            FROM long_term_fact
                            WHERE id IN ({placeholders})
                            """,
                            tuple(fact_ids),
                        ).fetchall()
                    records_by_id = {row["id"]: dict(row) for row in rows}

                records = []
                for result in vector_results:
                    fact_id = result.get("fact_id")
                    record = records_by_id.get(fact_id)
                    if record:
                        record["similarity"] = result.get("similarity")
                        records.append(record)
                    else:
                        records.append({
                            "id": fact_id,
                            "fact_text": result["fact_text"],
                            "importance": result.get("importance", 0),
                            "created_at": None,
                            "last_referenced": None,
                            "similarity": result.get("similarity"),
                        })
                return records
                
        except Exception as e:
            logger.warning(f"向量检索失败，回退到传统查询: {e}")
    
    # 传统查询（按重要性和最近引用排序）
    where_clause = "character_id = ? AND player_id = ?"
    params = [character_id, player_id]
    if created_after:
        where_clause += " AND created_at >= ?"
        params.append(created_after)
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT id, fact_text, importance, created_at, last_referenced
            FROM long_term_fact
            WHERE {where_clause}
            ORDER BY importance DESC, last_referenced DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        
    return [dict(r) for r in rows]


def _prompt_memory_claim_scopes(
    character_id: str,
    player_id: str,
    session_id: str | None,
) -> list[tuple[str, str]]:
    scopes = [("character", character_id)]
    if not session_id:
        return scopes

    session = get_session(session_id)
    if not session or session.get("player_id") != player_id:
        return scopes

    if session.get("is_multi_character"):
        group_thread_id = get_group_thread_id(session_id)
        if group_thread_id:
            scopes.append(("group_thread", group_thread_id))

    story_id = str(session.get("story_id") or "").strip()
    if story_id:
        scopes.append(("story", story_id))
    return scopes


def _fact_claim_visible_to_character(
    claim: dict,
    character_id: str,
) -> bool:
    provenance = claim.get("provenance") or {}
    evidence = provenance.get("evidence") or []
    provenance_entries = [provenance]
    provenance_entries.extend(
        item.get("details") or {}
        for item in evidence
        if isinstance(item, dict)
    )

    has_restriction = False
    allowed_character_ids = set()
    for entry in provenance_entries:
        if not isinstance(entry, dict) or "allowed_character_ids" not in entry:
            continue
        has_restriction = True
        allowed_character_ids.update(
            str(value).strip()
            for value in (entry.get("allowed_character_ids") or [])
            if str(value).strip()
        )
    return not has_restriction or character_id in allowed_character_ids


def get_prompt_memory_fact_records(
    character_id: str,
    player_id: str,
    session_id: str | None,
    limit: int = 20,
    query_context: str | None = None,
) -> list[dict]:
    """Merge verified ledger claims with pre-backfill legacy memories."""
    effective_limit = max(0, int(limit))
    records = []
    seen_fact_texts = set()

    def append_record(record: dict) -> bool:
        fact_text = str(record.get("fact_text") or "").strip()
        if not fact_text:
            return False
        normalized = normalize_fact_text(fact_text)
        if normalized in seen_fact_texts:
            return False
        seen_fact_texts.add(normalized)
        records.append(record)
        return True

    claim_iterators = []
    for scope_type, scope_id in _prompt_memory_claim_scopes(
        character_id,
        player_id,
        session_id,
    ):
        visible_claims = []
        for claim in reversed(
            list_verified_fact_claims(
                player_id,
                scope_type,
                scope_id,
            )
        ):
            if not _fact_claim_visible_to_character(claim, character_id):
                continue
            visible_claims.append(claim)
        claim_iterators.append(iter(visible_claims))

    while len(records) < effective_limit:
        advanced = False
        for claims in claim_iterators:
            try:
                claim = next(claims)
            except StopIteration:
                continue
            advanced = True
            append_record(claim)
            if len(records) >= effective_limit:
                break
        if not advanced:
            break

    if (
        len(records) < effective_limit
        and not has_data_migration(LONG_TERM_FACT_BACKFILL_MIGRATION)
    ):
        legacy_records = get_long_term_fact_records(
            character_id=character_id,
            player_id=player_id,
            limit=effective_limit,
            query_context=query_context,
        )
        for record in legacy_records:
            append_record(record)
            if len(records) >= effective_limit:
                break

    return records[:effective_limit]


_EMPTY_LONG_TERM_FACT_VALUES = {
    "",
    "无",
    "暂无",
    "没有",
    "none",
    "null",
    "nil",
    "n/a",
    "无长期记忆",
    "暂无长期记忆",
    "没有长期记忆",
    "无值得记住的信息",
    "没有值得记住的信息",
    "无值得记录的内容",
    "没有值得记录的内容",
}


def normalize_long_term_fact_text(fact_text: str | None) -> str | None:
    """清洗模型返回的长期记忆，过滤空值和“无”类占位文本。"""
    text = str(fact_text or "").strip().strip("\"'")
    normalized = text.lower().rstrip("。.!！").strip()
    if normalized in _EMPTY_LONG_TERM_FACT_VALUES:
        return None
    return text


def save_long_term_fact(
    character_id: str,
    player_id: str,
    fact_text: str | None,
    importance: int = 5
) -> int | None:
    """
    保存长期记忆（同时保存到 SQLite 和向量数据库）
    
    Returns:
        int | None: 新插入的 fact_id；空记忆不写入并返回 None
    """
    fact_text = normalize_long_term_fact_text(fact_text)
    if not fact_text:
        logger.debug("跳过空长期记忆写入")
        return None

    with get_conn() as conn:
        # 去重检查
        existing = _dedup_check(
            conn, "long_term_fact", "fact_text", fact_text,
            "character_id = ? AND player_id = ?",
            (character_id, player_id),
            threshold=0.75
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute(
                "UPDATE long_term_fact SET importance = ?, last_referenced = ? WHERE id = ?",
                (new_imp, _now(), existing["id"]),
            )
            logger.debug(f"长期记忆去重: id={existing['id']}")
            return existing["id"]

        insert_sql = """
            INSERT INTO long_term_fact
            (character_id, player_id, fact_text, importance, created_at, last_referenced)
            VALUES (?, ?, ?, ?, ?, ?)
            """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            insert_sql,
            (character_id, player_id, fact_text, importance, _now(), _now()),
        )
        fact_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
        
    # 同步到向量数据库
    try:
        from memoria.core.vector_memory import get_vector_store
        vector_store = get_vector_store()
        vector_store.add_memory(
            fact_id=fact_id,
            character_id=character_id,
            player_id=player_id,
            fact_text=fact_text,
            importance=importance
        )
        logger.debug(f"长期记忆已同步到向量数据库: fact_id={fact_id}")
    except Exception as e:
        logger.warning(f"向量数据库同步失败: {e}")
        
    return fact_id


def save_long_term_fact_if_checkpoint(
    session_id: str,
    character_id: str,
    player_id: str,
    fact_text: str | None,
    interval_turns: int,
    importance: int = 5,
) -> int | None:
    """仅在指定玩家回合间隔保存有效长期记忆。"""
    fact_text = normalize_long_term_fact_text(fact_text)
    if not fact_text or not is_long_term_memory_checkpoint(session_id, interval_turns):
        return None
    return save_long_term_fact(character_id, player_id, fact_text, importance)
        

