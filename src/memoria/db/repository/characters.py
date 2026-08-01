"""Domain repository functions (split from monolith)."""
from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select, text

from memoria.db.models import CharacterCard
from memoria.db.repository._common import _now, _row_to_dict, db_session

logger = logging.getLogger(__name__)

# =========================
# 角色卡管理（CRUD）
# =========================
def save_character_card_to_db(
    owner_user_id: str,
    character_id: str,
    card_data_json: str,
    version: str = "1.0.0",
    name: str = None,
    display_name: str = None,
    source: str = "db",
    avatar_url: str = None
) -> str | None:
    """
    保存或更新角色卡到数据库
    
    Args:
        owner_user_id: 角色卡归属用户 ID
        character_id: 角色 ID
        card_data_json: 完整的角色卡 JSON 字符串
        version: 版本号
        name: 角色名称（用于快速查询）
        display_name: 显示名称
        source: 来源标记（'db'=数据库创建, 'file'=从文件导入）
        avatar_url: 角色头像 data URL 或待异步抓取的网络 URL
    
    Returns:
        str | None: 本次头像更新的 revision；保存失败时返回 None
    """
    try:
        avatar_revision = uuid.uuid4().hex
        now = _now()
        with db_session() as session:
            session.execute(
                text("""
                    INSERT INTO character_card
                    (owner_user_id, character_id, card_data, version, name, display_name,
                     avatar_url, avatar_revision, created_at, updated_at, source)
                    VALUES (:owner, :cid, :card_data, :ver, :name, :dname,
                            :avatar, :av_rev, :now, :now2, :source)
                    ON CONFLICT(owner_user_id, character_id)
                    DO UPDATE SET
                        card_data=excluded.card_data,
                        version=excluded.version,
                        name=excluded.name,
                        display_name=excluded.display_name,
                        avatar_url=excluded.avatar_url,
                        avatar_revision=excluded.avatar_revision,
                        updated_at=excluded.updated_at
                """),
                {
                    "owner": owner_user_id,
                    "cid": character_id,
                    "card_data": card_data_json,
                    "ver": version,
                    "name": name,
                    "dname": display_name,
                    "avatar": avatar_url,
                    "av_rev": avatar_revision,
                    "now": now,
                    "now2": now,
                    "source": source,
                },
            )
        logger.info(f"角色卡已保存到数据库: owner={owner_user_id}, character_id={character_id}")
        return avatar_revision
    except Exception as e:
        logger.error(f"保存角色卡失败: {e}")
        return None


def patch_character_card_voice(
    owner_user_id: str,
    character_id: str,
    updates: dict,
) -> bool:
    """在事务内只更新角色卡 voice 字段，避免覆盖并发的整卡编辑。"""
    try:
        with db_session() as session:
            row = session.execute(
                text("""
                    SELECT card_data
                    FROM character_card
                    WHERE owner_user_id = :owner AND character_id = :cid
                """),
                {"owner": owner_user_id, "cid": character_id},
            ).fetchone()
            if row is None:
                return False

            card_data = json.loads(row[0])
            voice = card_data.get("voice")
            if not isinstance(voice, dict):
                voice = {}
                card_data["voice"] = voice
            voice.update(updates)
            session.execute(
                text("""
                    UPDATE character_card
                    SET card_data = :card_data, updated_at = :now
                    WHERE owner_user_id = :owner AND character_id = :cid
                """),
                {
                    "card_data": json.dumps(card_data, ensure_ascii=False),
                    "now": _now(),
                    "owner": owner_user_id,
                    "cid": character_id,
                },
            )
        logger.info(
            "角色声音设置已更新: owner=%s, character_id=%s",
            owner_user_id,
            character_id,
        )
        return True
    except Exception as e:
        logger.error(f"更新角色声音设置失败: {e}")
        return False


def get_character_card_from_db(owner_user_id: str, character_id: str, include_inactive: bool = False) -> dict | None:
    """
    从数据库获取角色卡
    
    Args:
        owner_user_id: 角色卡归属用户 ID
        character_id: 角色 ID
        include_inactive: 是否包含已禁用的角色卡（默认 False）
    
    Returns:
        dict: 角色卡数据，包含 card_data (JSON字符串) 等字段，不存在则返回 None
    """
    with db_session() as session:
        stmt = select(CharacterCard).where(
            CharacterCard.owner_user_id == owner_user_id,
            CharacterCard.character_id == character_id,
        )
        if not include_inactive:
            stmt = stmt.where(CharacterCard.is_active == 1)
        row = session.execute(stmt).scalar_one_or_none()

    return _row_to_dict(row)


def is_character_card_active(owner_user_id: str, character_id: str) -> bool:
    """返回角色卡是否存在且启用。"""
    with db_session() as session:
        row = session.execute(
            select(CharacterCard.is_active).where(
                CharacterCard.owner_user_id == owner_user_id,
                CharacterCard.character_id == character_id,
            )
        ).scalar_one_or_none()

    if not row:
        return False
    return bool(row)


def update_character_avatar(owner_user_id: str, character_id: str, avatar_url: str | None) -> bool:
    """更新角色头像 URL"""
    try:
        with db_session() as session:
            session.execute(
                text("""
                    UPDATE character_card
                    SET avatar_url = :avatar, avatar_revision = NULL, updated_at = :now
                    WHERE owner_user_id = :owner AND character_id = :cid
                """),
                {
                    "avatar": avatar_url,
                    "now": _now(),
                    "owner": owner_user_id,
                    "cid": character_id,
                },
            )
        logger.info(f"头像已更新: owner={owner_user_id}, character_id={character_id}")
        return True
    except Exception as e:
        logger.error(f"更新头像失败: {e}")
        return False


def update_character_avatar_if_current(
    owner_user_id: str,
    character_id: str,
    expected_avatar_url: str,
    expected_revision: str,
    avatar_url: str,
) -> bool:
    """Update an avatar only while the originating download request is current."""
    try:
        with db_session() as session:
            cursor = session.execute(
                text("""
                    UPDATE character_card
                    SET avatar_url = :new_avatar, avatar_revision = NULL, updated_at = :now
                    WHERE owner_user_id = :owner
                      AND character_id = :cid
                      AND avatar_url = :expected_url
                      AND avatar_revision = :expected_rev
                """),
                {
                    "new_avatar": avatar_url,
                    "now": _now(),
                    "owner": owner_user_id,
                    "cid": character_id,
                    "expected_url": expected_avatar_url,
                    "expected_rev": expected_revision,
                },
            )
            updated = cursor.rowcount > 0
        if updated:
            logger.info(
                "头像下载结果已更新: owner=%s, character_id=%s",
                owner_user_id,
                character_id,
            )
        return updated
    except Exception as e:
        logger.error(f"条件更新头像失败: {e}")
        return False


def list_character_cards_from_db(owner_user_id: str, only_active: bool = True) -> list[dict]:
    """
    列出所有角色卡（仅返回元信息，不包含完整 card_data）
    
    Args:
        owner_user_id: 角色卡归属用户 ID
        only_active: 是否仅返回启用的角色卡
    
    Returns:
        list[dict]: 角色卡元信息列表
    """
    with db_session() as session:
        query = """
            SELECT character_id, name, display_name, version, avatar_url, created_at, updated_at, is_active, source
            FROM character_card
            WHERE owner_user_id = :owner
        """
        params: dict = {"owner": owner_user_id}
        if only_active:
            query += " AND is_active = 1"

        query += " ORDER BY created_at DESC"

        rows = session.execute(text(query), params).mappings().all()

    return [dict(r) for r in rows]


def delete_character_card_from_db(owner_user_id: str, character_id: str, soft_delete: bool = True) -> bool:
    """
    删除角色卡
    
    Args:
        owner_user_id: 角色卡归属用户 ID
        character_id: 角色 ID
        soft_delete: 是否软删除（仅标记为不活跃）
    
    Returns:
        bool: 是否删除成功
    """
    try:
        with db_session() as session:
            if soft_delete:
                session.execute(
                    text("""
                        UPDATE character_card
                        SET is_active = 0, updated_at = :now
                        WHERE owner_user_id = :owner AND character_id = :cid
                    """),
                    {"now": _now(), "owner": owner_user_id, "cid": character_id},
                )
            else:
                # 硬删除：关系、记忆曲线和角色卡必须在同一事务内删除。
                session.execute(
                    text("""
                        DELETE FROM memory_curve_reinforcement
                        WHERE owner_user_id = :owner AND character_id = :cid
                    """),
                    {"owner": owner_user_id, "cid": character_id},
                )
                session.execute(
                    text("""
                        DELETE FROM memory_curve_state
                        WHERE owner_user_id = :owner AND character_id = :cid
                    """),
                    {"owner": owner_user_id, "cid": character_id},
                )
                rows = session.execute(
                    text("""
                        SELECT character_id_a, character_id_b
                        FROM character_relationship
                        WHERE owner_user_id = :owner
                          AND (character_id_a = :cid OR character_id_b = :cid)
                    """),
                    {"owner": owner_user_id, "cid": character_id},
                ).mappings().all()
                now = _now()
                for row in rows:
                    # Inline _touch_character_relationship_revision logic
                    ca, cb = (row["character_id_b"], row["character_id_a"]) if row["character_id_a"] > row["character_id_b"] else (row["character_id_a"], row["character_id_b"])
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
                session.execute(
                    text("""
                        DELETE FROM character_relationship
                        WHERE owner_user_id = :owner
                          AND (character_id_a = :cid OR character_id_b = :cid)
                    """),
                    {"owner": owner_user_id, "cid": character_id},
                )
                session.execute(
                    text("DELETE FROM character_card WHERE owner_user_id = :owner AND character_id = :cid"),
                    {"owner": owner_user_id, "cid": character_id},
                )
        logger.info(f"角色卡已{'禁用' if soft_delete else '删除'}: owner={owner_user_id}, character_id={character_id}")
        return True
    except Exception as e:
        logger.error(f"删除角色卡失败: {e}")
        return False


def activate_character_card(owner_user_id: str, character_id: str) -> bool:
    """
    激活已禁用的角色卡
    
    Args:
        owner_user_id: 角色卡归属用户 ID
        character_id: 角色 ID
    
    Returns:
        bool: 是否激活成功
    """
    try:
        with db_session() as session:
            session.execute(
                text("""
                    UPDATE character_card
                    SET is_active = 1, updated_at = :now
                    WHERE owner_user_id = :owner AND character_id = :cid
                """),
                {"now": _now(), "owner": owner_user_id, "cid": character_id},
            )
        logger.info(f"角色卡已激活: owner={owner_user_id}, character_id={character_id}")
        return True
    except Exception as e:
        logger.error(f"激活角色卡失败: {e}")
        return False
