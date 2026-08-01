"""Domain repository functions (split from monolith)."""
from __future__ import annotations

import logging

from sqlalchemy import select, text

from memoria.db.models import (
    CharacterRelationship,
    CharacterRelationshipRevision,
    RelationshipState,
)
from memoria.db.repository._common import _now, _row_to_dict, db_session

logger = logging.getLogger(__name__)

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
        text("""
        INSERT INTO character_relationship_revision
        (owner_user_id, character_id_a, character_id_b, updated_at)
        VALUES (:owner_user_id, :character_id_a, :character_id_b, :updated_at)
        ON CONFLICT(owner_user_id, character_id_a, character_id_b)
        DO UPDATE SET updated_at=excluded.updated_at
        """),
        {
            "owner_user_id": owner_user_id,
            "character_id_a": character_id_a,
            "character_id_b": character_id_b,
            "updated_at": updated_at,
        },
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
        text("""
        INSERT INTO relationship_state
        (character_id, player_id, affection_level, trust_level,
         current_mood, updated_at)
        VALUES (:character_id, :owner_user_id, :affinity, 0, 'neutral', :updated_at)
        ON CONFLICT(character_id, player_id)
        DO UPDATE SET
            affection_level=excluded.affection_level,
            updated_at=excluded.updated_at
        """),
        {
            "character_id": character_id,
            "owner_user_id": owner_user_id,
            "affinity": affinity,
            "updated_at": now,
        },
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
        character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
        now = _now()

        with db_session() as session:
            session.execute(
                text("""
                    INSERT INTO character_relationship
                    (owner_user_id, character_id_a, character_id_b, relationship_type, affinity,
                     description, created_at, updated_at)
                    VALUES (:owner, :ca, :cb, :rtype, :affinity, :desc, :now, :now2)
                    ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                    DO UPDATE SET
                        relationship_type=excluded.relationship_type,
                        affinity=excluded.affinity,
                        description=excluded.description,
                        updated_at=excluded.updated_at
                """),
                {
                    "owner": owner_user_id,
                    "ca": character_id_a,
                    "cb": character_id_b,
                    "rtype": relationship_type,
                    "affinity": affinity,
                    "desc": description,
                    "now": now,
                    "now2": now,
                },
            )
            # Inline _sync_runtime_affection_from_player_edge
            character_id = _player_edge_character_id(owner_user_id, character_id_a, character_id_b)
            if character_id:
                session.execute(
                    text("""
                        INSERT INTO relationship_state
                        (character_id, player_id, affection_level, trust_level,
                         current_mood, updated_at)
                        VALUES (:cid, :pid, :aff, 0, 'neutral', :now)
                        ON CONFLICT(character_id, player_id)
                        DO UPDATE SET
                            affection_level=excluded.affection_level,
                            updated_at=excluded.updated_at
                    """),
                    {"cid": character_id, "pid": owner_user_id, "aff": affinity, "now": now},
                )
            # Inline _touch_character_relationship_revision
            session.execute(
                text("""
                    INSERT INTO character_relationship_revision
                    (owner_user_id, character_id_a, character_id_b, updated_at)
                    VALUES (:owner, :ca, :cb, :now)
                    ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                    DO UPDATE SET updated_at=excluded.updated_at
                """),
                {"owner": owner_user_id, "ca": character_id_a, "cb": character_id_b, "now": now},
            )
        return True
    except Exception as e:
        logger.error(f"保存角色关系失败: {e}")
        return False


def get_character_relationship(owner_user_id: str, character_id_a: str, character_id_b: str) -> dict | None:
    """获取两个角色之间的关系"""
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)

    with db_session() as session:
        row = session.execute(
            select(CharacterRelationship).where(
                CharacterRelationship.owner_user_id == owner_user_id,
                CharacterRelationship.character_id_a == character_id_a,
                CharacterRelationship.character_id_b == character_id_b,
            )
        ).scalar_one_or_none()

    return _row_to_dict(row)


def get_character_relationship_updated_at(owner_user_id: str, character_id_a: str, character_id_b: str) -> str | None:
    """获取某对角色关系图谱最近一次变更时间，包含已删除关系。"""
    character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)

    with db_session() as session:
        row = session.execute(
            select(CharacterRelationshipRevision.updated_at).where(
                CharacterRelationshipRevision.owner_user_id == owner_user_id,
                CharacterRelationshipRevision.character_id_a == character_id_a,
                CharacterRelationshipRevision.character_id_b == character_id_b,
            )
        ).scalar_one_or_none()
        if row:
            return row

        if is_player_node_id(character_id_a) or is_player_node_id(character_id_b):
            return None

        row = session.execute(
            select(CharacterRelationship.updated_at).where(
                CharacterRelationship.owner_user_id == owner_user_id,
                CharacterRelationship.character_id_a == character_id_a,
                CharacterRelationship.character_id_b == character_id_b,
            )
        ).scalar_one_or_none()

    return row


def get_relationship_revision_after(
    owner_user_id: str,
    character_id: str,
) -> list[dict]:
    """获取指定角色在 revision 表中的最新记录（含已删除关系）。"""
    with db_session() as session:
        rows = session.execute(
            text("""
                SELECT character_id_a, character_id_b, updated_at
                FROM character_relationship_revision
                WHERE owner_user_id = :owner
                  AND (character_id_a = :cid OR character_id_b = :cid)
                ORDER BY updated_at, character_id_a, character_id_b
            """),
            {"owner": owner_user_id, "cid": character_id},
        ).mappings().all()
    return [dict(row) for row in rows]


def list_character_relationships(owner_user_id: str, character_id: str) -> list[dict]:
    """列出指定角色的所有关系"""
    with db_session() as session:
        rows = session.execute(
            text("""
                SELECT * FROM character_relationship
                WHERE owner_user_id = :owner AND (character_id_a = :cid OR character_id_b = :cid)
                ORDER BY affinity DESC, updated_at DESC
            """),
            {"owner": owner_user_id, "cid": character_id},
        ).mappings().all()

    return [dict(r) for r in rows]


def list_all_character_relationships(owner_user_id: str) -> list[dict]:
    """列出所有角色关系（用于关系网络可视化）"""
    with db_session() as session:
        rows = session.execute(
            text("""
                SELECT * FROM character_relationship
                WHERE owner_user_id = :owner
                ORDER BY affinity DESC, updated_at DESC
            """),
            {"owner": owner_user_id},
        ).mappings().all()

    return [dict(r) for r in rows]


def delete_character_relationship(owner_user_id: str, character_id_a: str, character_id_b: str) -> bool:
    """删除角色关系"""
    try:
        character_id_a, character_id_b = _normalize_relationship_pair(character_id_a, character_id_b)
        now = _now()

        with db_session() as session:
            session.execute(
                text("""
                    DELETE FROM character_relationship
                    WHERE owner_user_id = :owner AND character_id_a = :ca AND character_id_b = :cb
                """),
                {"owner": owner_user_id, "ca": character_id_a, "cb": character_id_b},
            )
            # Inline _sync_runtime_affection_from_player_edge (affinity=0)
            character_id = _player_edge_character_id(owner_user_id, character_id_a, character_id_b)
            if character_id:
                session.execute(
                    text("""
                        INSERT INTO relationship_state
                        (character_id, player_id, affection_level, trust_level,
                         current_mood, updated_at)
                        VALUES (:cid, :pid, 0, 0, 'neutral', :now)
                        ON CONFLICT(character_id, player_id)
                        DO UPDATE SET
                            affection_level=excluded.affection_level,
                            updated_at=excluded.updated_at
                    """),
                    {"cid": character_id, "pid": owner_user_id, "now": now},
                )
            # Inline _touch_character_relationship_revision
            session.execute(
                text("""
                    INSERT INTO character_relationship_revision
                    (owner_user_id, character_id_a, character_id_b, updated_at)
                    VALUES (:owner, :ca, :cb, :now)
                    ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                    DO UPDATE SET updated_at=excluded.updated_at
                """),
                {"owner": owner_user_id, "ca": character_id_a, "cb": character_id_b, "now": now},
            )
        return True
    except Exception as e:
        logger.error(f"删除角色关系失败: {e}")
        return False


def delete_all_relationships_of_character(owner_user_id: str, character_id: str) -> int:
    """删除某个角色涉及的所有关系"""
    with db_session() as session:
        rows = session.execute(
            text("""
                SELECT character_id_a, character_id_b
                FROM character_relationship
                WHERE owner_user_id = :owner AND (character_id_a = :cid OR character_id_b = :cid)
            """),
            {"owner": owner_user_id, "cid": character_id},
        ).mappings().all()
        now = _now()
        for row in rows:
            # Inline _touch_character_relationship_revision
            ca, cb = _normalize_relationship_pair(row["character_id_a"], row["character_id_b"])
            session.execute(
                text("""
                    INSERT INTO character_relationship_revision
                    (owner_user_id, character_id_a, character_id_b, updated_at)
                    VALUES (:owner, :ca, :cb, :now)
                    ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                    DO UPDATE SET updated_at=excluded.updated_at
                """),
                {"owner": owner_user_id, "ca": ca, "cb": cb, "now": now},
            )
        cur = session.execute(
            text("""
                DELETE FROM character_relationship
                WHERE owner_user_id = :owner AND (character_id_a = :cid OR character_id_b = :cid)
            """),
            {"owner": owner_user_id, "cid": character_id},
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

    with db_session() as session:
        cursor = session.execute(
            text("""
                UPDATE character_relationship
                SET affinity = CASE
                        WHEN affinity + :delta > 100 THEN 100
                        WHEN affinity + :delta < -100 THEN -100
                        ELSE affinity + :delta
                    END,
                    updated_at = :now
                WHERE owner_user_id = :owner AND character_id_a = :ca AND character_id_b = :cb
            """),
            {
                "delta": affinity_delta,
                "now": now,
                "owner": owner_user_id,
                "ca": character_id_a,
                "cb": character_id_b,
            },
        )
        if cursor.rowcount > 0:
            relationship = session.execute(
                select(CharacterRelationship.affinity).where(
                    CharacterRelationship.owner_user_id == owner_user_id,
                    CharacterRelationship.character_id_a == character_id_a,
                    CharacterRelationship.character_id_b == character_id_b,
                )
            ).scalar_one_or_none()
            # Inline _sync_runtime_affection_from_player_edge
            character_id = _player_edge_character_id(owner_user_id, character_id_a, character_id_b)
            if character_id and relationship is not None:
                session.execute(
                    text("""
                        INSERT INTO relationship_state
                        (character_id, player_id, affection_level, trust_level,
                         current_mood, updated_at)
                        VALUES (:cid, :pid, :aff, 0, 'neutral', :now)
                        ON CONFLICT(character_id, player_id)
                        DO UPDATE SET
                            affection_level=excluded.affection_level,
                            updated_at=excluded.updated_at
                    """),
                    {"cid": character_id, "pid": owner_user_id, "aff": relationship, "now": now},
                )
            # Inline _touch_character_relationship_revision
            session.execute(
                text("""
                    INSERT INTO character_relationship_revision
                    (owner_user_id, character_id_a, character_id_b, updated_at)
                    VALUES (:owner, :ca, :cb, :now)
                    ON CONFLICT(owner_user_id, character_id_a, character_id_b)
                    DO UPDATE SET updated_at=excluded.updated_at
                """),
                {"owner": owner_user_id, "ca": character_id_a, "cb": character_id_b, "now": now},
            )


def list_character_relationship_revisions(
    owner_user_id: str,
    character_id: str,
) -> list[dict]:
    """List current and deleted relationship revision pairs for diagnostics."""
    with db_session() as session:
        from sqlalchemy import text as _text
        rows = session.execute(
            _text("""
                SELECT character_id_a, character_id_b, updated_at
                FROM character_relationship_revision
                WHERE owner_user_id = :owner
                  AND (character_id_a = :cid OR character_id_b = :cid)
                ORDER BY updated_at, character_id_a, character_id_b
            """),
            {"owner": owner_user_id, "cid": character_id},
        ).fetchall()
    return [_row_to_dict(row) for row in rows]
