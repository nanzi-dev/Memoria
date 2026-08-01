"""用户注册、登录与资料管理 — ORM 仓库。"""
from __future__ import annotations

import logging
import random
from typing import Any

from sqlalchemy import delete, func, select, update

from memoria.db.models import AuthToken, SystemBootstrapClaim, User, UserCharacterCard
from memoria.db.repository._common import (
    AdminBootstrapUnavailable,
    _auth_token_storage_key,
    _now,
    _row_to_dict,
    db_session,
)

logger = logging.getLogger(__name__)

# =========================
# 用户管理
# =========================

def player_node_id(user_id: str) -> str:
    return f"player:{user_id}"


def is_player_node_id(node_id: str) -> bool:
    return isinstance(node_id, str) and node_id.startswith("player:")


def _ensure_user_character_card(session, *, user_id: str, display_name: str, gender: str, now: str) -> None:
    """确保 user_character_card 存在（INSERT ... ON CONFLICT DO NOTHING）。"""
    exists = session.execute(
        select(UserCharacterCard).where(UserCharacterCard.user_id == user_id)
    ).scalar_one_or_none()
    if not exists:
        session.add(UserCharacterCard(
            user_id=user_id,
            display_name=display_name,
            gender=gender or "unknown",
            created_at=now,
            updated_at=now,
        ))


def create_user(
    user_id: str,
    username: str,
    password_hash: str,
    gender: str = "unknown",
    *,
    bootstrap_admin: bool = False,
) -> bool:
    """创建新用户。返回是否为管理员。"""
    now = _now()
    with db_session() as session:
        is_admin = False
        if bootstrap_admin:
            has_admin = session.execute(
                select(func.count()).select_from(User).where(User.is_admin == 1)
            ).scalar()
            if has_admin:
                raise AdminBootstrapUnavailable("管理员已完成初始化")
            session.add(SystemBootstrapClaim(
                claim_key="admin",
                claimed_by_user_id=user_id,
                claimed_at=now,
            ))
            is_admin = True

        session.add(User(
            user_id=user_id,
            username=username,
            password_hash=password_hash,
            is_admin=int(is_admin),
            gender=gender,
            created_at=now,
            updated_at=now,
        ))
        _ensure_user_character_card(
            session,
            user_id=user_id,
            display_name=username,
            gender=gender,
            now=now,
        )
    return is_admin


def get_user_character_card(user_id: str) -> dict | None:
    with db_session() as session:
        row = session.execute(
            select(UserCharacterCard).where(UserCharacterCard.user_id == user_id)
        ).scalar_one_or_none()
        return _row_to_dict(row)


def get_or_create_user_character_card(user_id: str) -> dict | None:
    with db_session() as session:
        card = session.execute(
            select(UserCharacterCard).where(UserCharacterCard.user_id == user_id)
        ).scalar_one_or_none()
        if card:
            return _row_to_dict(card)
        user = session.execute(
            select(User).where(User.user_id == user_id)
        ).scalar_one_or_none()
        if not user:
            return None
        now = _now()
        _ensure_user_character_card(
            session,
            user_id=user_id,
            display_name=user.username,
            gender=user.gender or "unknown",
            now=now,
        )
        session.flush()
        card = session.execute(
            select(UserCharacterCard).where(UserCharacterCard.user_id == user_id)
        ).scalar_one_or_none()
        return _row_to_dict(card)


def update_user_character_card(user_id: str, fields: dict) -> dict | None:
    allowed = {
        "display_name", "avatar_url", "gender", "pronouns", "age",
        "species", "occupation", "appearance", "personality", "background", "goals",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    with db_session() as session:
        user = session.execute(
            select(User).where(User.user_id == user_id)
        ).scalar_one_or_none()
        if not user:
            return None
        now = _now()
        _ensure_user_character_card(
            session,
            user_id=user_id,
            display_name=user.username,
            gender=user.gender or "unknown",
            now=now,
        )
        if updates:
            session.execute(
                update(UserCharacterCard)
                .where(UserCharacterCard.user_id == user_id)
                .values(**updates, updated_at=now)
            )
        card = session.execute(
            select(UserCharacterCard).where(UserCharacterCard.user_id == user_id)
        ).scalar_one_or_none()
        return _row_to_dict(card)


def get_user_by_username(username: str) -> dict | None:
    with db_session() as session:
        row = session.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        return _row_to_dict(row)


def get_user_by_id(user_id: str) -> dict | None:
    with db_session() as session:
        row = session.execute(
            select(User).where(User.user_id == user_id)
        ).scalar_one_or_none()
        return _row_to_dict(row)


def update_user_password_hash(user_id: str, password_hash: str):
    with db_session() as session:
        session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(password_hash=password_hash, updated_at=_now())
        )


_UNSET = object()


def update_user_profile(user_id: str, username: str = None, gender: str = None, avatar_url=_UNSET):
    values: dict[str, Any] = {}
    if username is not None:
        values["username"] = username
    if gender is not None:
        values["gender"] = gender
    if avatar_url is not _UNSET:
        values["avatar_url"] = avatar_url
    if not values:
        return
    values["updated_at"] = _now()
    with db_session() as session:
        session.execute(
            update(User).where(User.user_id == user_id).values(**values)
        )


def update_user_speech_settings(
    user_id: str,
    *,
    tts_auto_play: bool,
    stt_auto_send: bool,
) -> None:
    with db_session() as session:
        session.execute(
            update(User)
            .where(User.user_id == user_id)
            .values(
                tts_auto_play=int(tts_auto_play),
                stt_auto_send=int(stt_auto_send),
                updated_at=_now(),
            )
        )


def create_auth_token(token: str, user_id: str, expires_at: str):
    storage_key = _auth_token_storage_key(token)
    now = _now()
    with db_session() as session:
        existing = session.execute(
            select(AuthToken).where(AuthToken.token == storage_key)
        ).scalar_one_or_none()
        if existing:
            existing.user_id = user_id
            existing.created_at = now
            existing.expires_at = expires_at
        else:
            session.add(AuthToken(
                token=storage_key,
                user_id=user_id,
                created_at=now,
                expires_at=expires_at,
            ))


def get_user_id_for_auth_token(token: str) -> str | None:
    if not token:
        return None
    now = _now()
    storage_key = _auth_token_storage_key(token)
    with db_session() as session:
        row = session.execute(
            select(AuthToken)
            .where(AuthToken.token.in_([storage_key, token]))
            .where(AuthToken.expires_at > now)
            .order_by(AuthToken.token == storage_key)  # prefer storage_key
        ).scalar_one_or_none()
        if row:
            if row.token == token:
                # Migrate legacy plaintext token to hashed
                existing = session.execute(
                    select(AuthToken).where(AuthToken.token == storage_key)
                ).scalar_one_or_none()
                if existing:
                    existing.user_id = row.user_id
                    existing.created_at = row.created_at
                    existing.expires_at = row.expires_at
                else:
                    session.add(AuthToken(
                        token=storage_key,
                        user_id=row.user_id,
                        created_at=row.created_at,
                        expires_at=row.expires_at,
                    ))
                session.execute(delete(AuthToken).where(AuthToken.token == token))
            return row.user_id

        session.execute(
            delete(AuthToken)
            .where(AuthToken.token.in_([storage_key, token]))
            .where(AuthToken.expires_at <= now)
        )
        if random.random() < 0.01:
            session.execute(
                delete(AuthToken).where(AuthToken.expires_at <= now)
            )
    return None


def delete_auth_token(token: str):
    storage_key = _auth_token_storage_key(token)
    with db_session() as session:
        session.execute(
            delete(AuthToken).where(AuthToken.token.in_([storage_key, token]))
        )
