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
# 角色关系网络
# =========================
def _normalize_relationship_pair(character_id_a: str, character_id_b: str) -> tuple[str, str]:
    return (character_id_b, character_id_a) if character_id_a > character_id_b else (character_id_a, character_id_b)


def _touch_character_relationship_revision(
    conn,
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
    updated_at: str
) -> None:
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
    conn.execute(
        """
        INSERT INTO character_relationship_revision
        (owner_user_id, character_id_a, character_id_b, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(owner_user_id, character_id_a, character_id_b)
        DO UPDATE SET updated_at=excluded.updated_at
        """,
        (owner_user_id, character_id_a, character_id_b, updated_at),
    )


def _player_edge_character_id(
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
) -> str | None:
    player_id = player_node_id(owner_user_id)
    if character_id_a == player_id and not is_player_node_id(character_id_b):
        return character_id_b
    if character_id_b == player_id and not is_player_node_id(character_id_a):
        return character_id_a
    return None


def _sync_runtime_affection_from_player_edge(
    conn,
    *,
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
    affinity: float,
    now: str,
) -> None:
    character_id = _player_edge_character_id(
        owner_user_id,
        character_id_a,
        character_id_b,
    )
    if not character_id:
        return
    conn.execute(
        """
        INSERT INTO relationship_state
        (character_id, player_id, affection_level, trust_level,
         current_mood, updated_at)
        VALUES (?, ?, ?, 0, 'neutral', ?)
        ON CONFLICT(character_id, player_id)
        DO UPDATE SET
            affection_level=excluded.affection_level,
            updated_at=excluded.updated_at
        """,
        (character_id, owner_user_id, affinity, now),
    )


def save_character_relationship(
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
    relationship_type: str,
    affinity: float = 0.0,
    description: str = None
) -> bool:
    """保存角色关系（无向关系，自动排序确保唯一性）"""
    try:
        # 确保 character_id_a < character_id_b（字母序）
        character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
        now = _now()
        
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO character_relationship
                (owner_user_id, character_id_a, character_id_b, relationship_type, affinity,
                 description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                DO UPDATE SET
                    relationship_type=excluded.relationship_type,
                    affinity=excluded.affinity,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (owner_user_id, character_id_a, character_id_b, relationship_type, affinity,
                 description, now, now),
            )
            _sync_runtime_affection_from_player_edge(
                conn,
                owner_user_id=owner_user_id,
                character_id_a=character_id_a,
                character_id_b=character_id_b,
                affinity=affinity,
                now=now,
            )
            _touch_character_relationship_revision(conn, owner_user_id, character_id_a, character_id_b, now)
        return True
    except Exception as e:
        logger.error(f"保存角色关系失败: {e}")
        return False

def get_character_relationship(owner_user_id: str, character_id_a: str, character_id_b: str) -> dict | None:
    """获取两个角色之间的关系"""
    # 排序确保查询顺序一致
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
    
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM character_relationship
            WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
            """,
            (owner_user_id, character_id_a, character_id_b),
        ).fetchone()
    
    return _row_to_dict(row)


def get_character_relationship_updated_at(owner_user_id: str, character_id_a: str, character_id_b: str) -> str | None:
    """获取某对角色关系图谱最近一次变更时间，包含已删除关系。"""
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)

    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT updated_at
            FROM character_relationship_revision
            WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
            """,
            (owner_user_id, character_id_a, character_id_b),
        ).fetchone()
        if row:
            return row["updated_at"]

        if is_player_node_id(character_id_a) or is_player_node_id(character_id_b):
            return None

        row = conn.execute(
            """
            SELECT updated_at
            FROM character_relationship
            WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
            """,
            (owner_user_id, character_id_a, character_id_b),
        ).fetchone()

    return row["updated_at"] if row else None

def list_character_relationships(owner_user_id: str, character_id: str) -> list[dict]:
    """列出指定角色的所有关系"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM character_relationship
            WHERE owner_user_id = ? AND (character_id_a = ? OR character_id_b = ?)
            ORDER BY affinity DESC, updated_at DESC
            """,
            (owner_user_id, character_id, character_id),
        ).fetchall()
        
    return [dict(r) for r in rows]

def list_all_character_relationships(owner_user_id: str) -> list[dict]:
    """列出所有角色关系（用于关系网络可视化）"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM character_relationship
            WHERE owner_user_id = ?
            ORDER BY affinity DESC, updated_at DESC
            """,
            (owner_user_id,),
        ).fetchall()
    
    return [dict(r) for r in rows]


def delete_character_relationship(owner_user_id: str, character_id_a: str, character_id_b: str) -> bool:
    """删除角色关系"""
    try:
        character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
        now = _now()
        
        with get_conn() as conn:
            conn.execute(
                """
                DELETE FROM character_relationship
                WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
                """,
                (owner_user_id, character_id_a, character_id_b),
            )
            _sync_runtime_affection_from_player_edge(
                conn,
                owner_user_id=owner_user_id,
                character_id_a=character_id_a,
                character_id_b=character_id_b,
                affinity=0,
                now=now,
            )
            _touch_character_relationship_revision(conn, owner_user_id, character_id_a, character_id_b, now)
        return True
    except Exception as e:
        logger.error(f"删除角色关系失败: {e}")
        return False
    
def delete_all_relationships_of_character(owner_user_id: str, character_id: str) -> int:
    """删除某个角色涉及的所有关系"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT character_id_a, character_id_b
            FROM character_relationship
            WHERE owner_user_id = ? AND (character_id_a = ? OR character_id_b = ?)
            """,
            (owner_user_id, character_id, character_id),
        ).fetchall()
        now = _now()
        for row in rows:
            _touch_character_relationship_revision(
                conn,
                owner_user_id,
                row["character_id_a"],
                row["character_id_b"],
                now
            )
        cur = conn.execute(
            """
            DELETE FROM character_relationship
            WHERE owner_user_id = ? AND (character_id_a = ? OR character_id_b = ?)
            """,
            (owner_user_id, character_id, character_id),
        )
        return cur.rowcount

def update_relationship_affinity(
    owner_user_id: str,
    character_id_a: str,
    character_id_b: str,
    affinity_delta: float
):
    """更新关系强度"""
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
    now = _now()
    
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE character_relationship
            SET affinity = affinity + ?,
                updated_at = ?
            WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
            """,
            (affinity_delta, now, owner_user_id, character_id_a, character_id_b),
        )
        if cursor.rowcount > 0:
            relationship = conn.execute(
                """
                SELECT affinity
                FROM character_relationship
                WHERE owner_user_id = ? AND character_id_a = ? AND character_id_b = ?
                """,
                (owner_user_id, character_id_a, character_id_b),
            ).fetchone()
            _sync_runtime_affection_from_player_edge(
                conn,
                owner_user_id=owner_user_id,
                character_id_a=character_id_a,
                character_id_b=character_id_b,
                affinity=relationship["affinity"],
                now=now,
            )
            _touch_character_relationship_revision(conn, owner_user_id, character_id_a, character_id_b, now)



 


