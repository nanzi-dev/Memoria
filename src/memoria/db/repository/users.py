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
# 用户管理
# =========================
def player_node_id(user_id: str) -> str:
    return f"player:{user_id}"


def is_player_node_id(node_id: str) -> bool:
    return isinstance(node_id, str) and node_id.startswith("player:")


def _insert_default_user_character_card(
    conn,
    *,
    user_id: str,
    display_name: str,
    gender: str,
    now: str,
) -> None:
    conn.execute(
        """
        INSERT INTO user_character_card
        (user_id, display_name, gender, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO NOTHING
        """,
        (user_id, display_name, gender or "unknown", now, now),
    )


def create_user(
    user_id: str,
    username: str,
    password_hash: str,
    gender: str = "unknown",
    *,
    bootstrap_admin: bool = False,
) -> bool:
    """创建新用户"""
    now = _now()
    with get_conn() as conn:
        is_admin = False
        if bootstrap_admin:
            claimed = conn.execute(
                """
                INSERT INTO system_bootstrap_claim
                (claim_key, claimed_by_user_id, claimed_at)
                SELECT 'admin', ?, ?
                WHERE NOT EXISTS (SELECT 1 FROM users WHERE is_admin = 1)
                ON CONFLICT (claim_key) DO NOTHING
                """,
                (user_id, now),
            )
            if claimed.rowcount != 1:
                raise AdminBootstrapUnavailable("管理员已完成初始化")
            is_admin = True

        conn.execute(
            """
            INSERT INTO users
            (user_id, username, password_hash, is_admin, gender, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, username, password_hash, int(is_admin), gender, now, now),
        )
        _insert_default_user_character_card(
            conn,
            user_id=user_id,
            display_name=username,
            gender=gender,
            now=now,
        )
    return is_admin


def get_user_character_card(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_character_card WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return _row_to_dict(row)


def get_or_create_user_character_card(user_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM user_character_card WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row:
            return _row_to_dict(row)
        user = conn.execute(
            "SELECT username, gender FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            return None
        now = _now()
        _insert_default_user_character_card(
            conn,
            user_id=user_id,
            display_name=user["username"],
            gender=user["gender"] or "unknown",
            now=now,
        )
        row = conn.execute(
            "SELECT * FROM user_character_card WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return _row_to_dict(row)


def update_user_character_card(user_id: str, fields: dict) -> dict | None:
    allowed = {
        "display_name",
        "avatar_url",
        "gender",
        "pronouns",
        "age",
        "species",
        "occupation",
        "appearance",
        "personality",
        "background",
        "goals",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    with get_conn() as conn:
        user = conn.execute(
            "SELECT username, gender FROM users WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not user:
            return None
        now = _now()
        _insert_default_user_character_card(
            conn,
            user_id=user_id,
            display_name=user["username"],
            gender=user["gender"] or "unknown",
            now=now,
        )
        if updates:
            assignments = ", ".join(f"{key} = ?" for key in updates)
            conn.execute(
                f"""
                UPDATE user_character_card
                SET {assignments}, updated_at = ?
                WHERE user_id = ?
                """,
                (*updates.values(), now, user_id),
            )
        card = conn.execute(
            "SELECT * FROM user_character_card WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return _row_to_dict(card)


def get_user_by_username(username: str) -> dict | None:
    """根据用户名查找用户"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_id(user_id: str) -> dict | None:
    """根据 user_id 查找用户"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return _row_to_dict(row)


def update_user_password_hash(user_id: str, password_hash: str):
    """更新用户密码哈希。"""
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE user_id = ?",
            (password_hash, _now(), user_id),
        )


_UNSET = object()


def update_user_profile(user_id: str, username: str = None, gender: str = None, avatar_url=_UNSET):
    """更新用户资料"""
    fields = []
    params = []
    if username is not None:
        fields.append("username = ?")
        params.append(username)
    if gender is not None:
        fields.append("gender = ?")
        params.append(gender)
    if avatar_url is not _UNSET:
        fields.append("avatar_url = ?")
        params.append(avatar_url)
    if not fields:
        return
    fields.append("updated_at = ?")
    params.append(_now())
    params.append(user_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE users SET {', '.join(fields)} WHERE user_id = ?",
            params,
        )


def update_user_speech_settings(
    user_id: str,
    *,
    tts_auto_play: bool,
    stt_auto_send: bool,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE users
            SET tts_auto_play = ?, stt_auto_send = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (int(tts_auto_play), int(stt_auto_send), _now(), user_id),
        )


def create_auth_token(token: str, user_id: str, expires_at: str):
    """持久化登录 token。"""
    storage_key = _auth_token_storage_key(token)
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO auth_token (token, user_id, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (storage_key, user_id, _now(), expires_at),
        )


def get_user_id_for_auth_token(token: str) -> str | None:
    """返回有效 token 对应的 user_id；过期或不存在返回 None。"""
    if not token:
        return None
    now = _now()
    storage_key = _auth_token_storage_key(token)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT token, user_id, created_at, expires_at
            FROM auth_token
            WHERE token IN (?, ?) AND expires_at > ?
            ORDER BY CASE WHEN token = ? THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (storage_key, token, now, storage_key),
        ).fetchone()
        if row:
            if row["token"] == token:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO auth_token
                    (token, user_id, created_at, expires_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (storage_key, row["user_id"], row["created_at"], row["expires_at"]),
                )
                conn.execute("DELETE FROM auth_token WHERE token = ?", (token,))
            return row["user_id"]
        conn.execute(
            "DELETE FROM auth_token WHERE token IN (?, ?) OR expires_at <= ?",
            (storage_key, token, now),
        )
    return None


def delete_auth_token(token: str):
    """删除登录 token。"""
    storage_key = _auth_token_storage_key(token)
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM auth_token WHERE token IN (?, ?)",
            (storage_key, token),
        )
