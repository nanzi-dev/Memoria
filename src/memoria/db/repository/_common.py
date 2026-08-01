"""
数据持久化层 — 公共工具与连接管理

本模块提供：
- ``get_conn()``  — 低层 DBAPI 连接（向后兼容，供测试/外部工具使用）
- ``db_session()`` — SQLAlchemy ORM 会话（新代码请使用此接口）
- ``init_db()``  — 建表入口（委托给 SQLAlchemy ``create_all``）
- 文本去重引擎（``_normalize`` / ``_text_similarity`` / ``_dedup_check``）
- 各类序列化 / 反序列化辅助函数
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from memoria.core.config import configs

logger = logging.getLogger(__name__)

try:
    from sqlalchemy.engine import Row as _SqlAlchemyRow
except ImportError:  # pragma: no cover
    _SqlAlchemyRow = None

# ---------------------------------------------------------------------------
# 延迟导入引擎（避免循环依赖）
# ---------------------------------------------------------------------------

def _get_engine():
    from memoria.db.engine import get_engine as _ge
    return _ge()


# ===========================================================================
# 异常 & 常量
# ===========================================================================

class AdminBootstrapUnavailable(RuntimeError):
    """管理员初始化名额已被占用。"""


_UNSET = object()
_AUTH_TOKEN_DIGEST_PREFIX = "sha256:"


def _auth_token_storage_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_AUTH_TOKEN_DIGEST_PREFIX}{digest}"


# ===========================================================================
# 时间 / 序列化工具
# ===========================================================================

def _now() -> str:
    """统一时间格式（UTC ISO8601）"""
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row) -> dict | None:
    """安全转换 sqlite Row / psycopg dict row / ORM 实例 → dict"""
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    if _SqlAlchemyRow is not None and isinstance(row, _SqlAlchemyRow):
        return dict(row._mapping)
    # ORM model instance
    table = getattr(row, "__table__", None)
    if table is not None:
        return {col.name: getattr(row, col.name) for col in table.columns}
    # sqlite3.Row or any mapping
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _model_to_dict(obj) -> dict | None:
    """将 SQLAlchemy ORM 实例转为 dict（排除 ``_sa_instance_state``）。"""
    return _row_to_dict(obj)


def _encode_knowledge_sources(sources: list[dict] | None) -> str:
    return json.dumps(sources or [], ensure_ascii=False)


def _decode_message_row(row) -> dict:
    message = dict(row)
    raw_sources = message.get("knowledge_sources")
    if isinstance(raw_sources, str):
        try:
            message["knowledge_sources"] = json.loads(raw_sources)
        except (TypeError, ValueError):
            message["knowledge_sources"] = []
    elif raw_sources is None:
        message["knowledge_sources"] = []
    return message


# ===========================================================================
# 数据库类型检测
# ===========================================================================

def _is_postgres_enabled() -> bool:
    database_url = (configs.database_url or "").strip().lower()
    return database_url.startswith(("postgresql://", "postgres://", "postgresql+"))


def _database_name() -> str:
    if not _is_postgres_enabled():
        return configs.database_path
    from urllib.parse import urlsplit
    parsed = urlsplit(configs.database_url)
    return f"{parsed.hostname or 'postgres'}{parsed.path or ''}"


# ===========================================================================
# 文本去重引擎
# ===========================================================================

def _normalize(text: str) -> str:
    """归一化文本"""
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text.strip().lower())


def _text_similarity(a: str, b: str) -> float:
    """文本相似度"""
    na, nb = _normalize(a), _normalize(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _normalize_dialogue_text(text: str | None) -> str:
    return re.sub(r"[\W_]+", "", str(text or "").casefold())


def dialogue_texts_redundant(a: str | None, b: str | None) -> bool:
    """判断两段对白是否属于同一表达；短文本只做精确归一化匹配。"""
    normalized_a = _normalize_dialogue_text(a)
    normalized_b = _normalize_dialogue_text(b)
    if not normalized_a or not normalized_b:
        return False
    if normalized_a == normalized_b:
        return True
    if min(len(normalized_a), len(normalized_b)) < 16:
        return False
    return SequenceMatcher(None, normalized_a, normalized_b).ratio() >= 0.95


def _dedup_check(conn, table, text_col, text, where_clause, params, threshold=0.75):
    """检查是否存在相似记录，返回匹配的行或 None。"""
    from sqlalchemy import text as _text

    norm = _normalize(text)
    if len(norm) < 2:
        return None
    rows = conn.execute(
        _text(f"SELECT *, {text_col} as _cmp FROM {table} WHERE {where_clause}"),
        params,
    ).mappings().fetchall()
    for row in rows:
        if _text_similarity(text, row["_cmp"]) >= threshold:
            return dict(row)
    return None


def _lock_sqlite_write(conn) -> None:
    """在 SQLite 上以可被 SQLAlchemy 管理的方式启动写事务。"""
    from sqlalchemy.engine import Connection
    from sqlalchemy.orm import Session
    from sqlalchemy import text as _text

    if isinstance(conn, Session):
        raw = conn.connection().connection.dbapi_connection
    elif isinstance(conn, Connection):
        raw = conn.connection.connection.dbapi_connection
    else:
        raw = conn
    if isinstance(raw, sqlite3.Connection) and not raw.in_transaction:
        if isinstance(conn, (Connection, Session)):
            conn.execute(_text("BEGIN IMMEDIATE"))
        else:
            conn.execute("BEGIN IMMEDIATE")


# ===========================================================================
# 连接管理 — 向后兼容
# ===========================================================================

_wal_configured_paths: set = set()


class _PgRawConn:
    """将 SQLAlchemy raw connection 包装为 psycopg 兼容接口。"""

    def __init__(self, raw_conn):
        self._raw = raw_conn
        self._dbapi = raw_conn.driver_connection
        # psycopg3 默认行工厂是 tuple_row；设为 dict_row 以支持 row["col"] 访问
        try:
            from psycopg.rows import dict_row
            self._dbapi.row_factory = dict_row
        except ImportError:  # pragma: no cover
            pass

    def execute(self, sql, params=None):
        converted = _prepare_postgres_sql(sql)
        if params:
            return self._dbapi.execute(converted, params)
        return self._dbapi.execute(converted)

    def executemany(self, sql, params_seq):
        converted = _prepare_postgres_sql(sql)
        # psycopg3 的 Connection 无 executemany 方法；用 cursor 执行
        with self._dbapi.cursor() as cursor:
            return cursor.executemany(converted, params_seq)

    def executescript(self, script):
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


@contextmanager
def get_conn():
    """
    低层 DBAPI 连接上下文管理器（**向后兼容**）。

    对 SQLite 直接返回 ``sqlite3.Connection``（保证 ``isinstance`` 检查通过），
    对 PostgreSQL 返回兼容包装器。

    新代码建议使用 ``db_session()`` 获取 ORM 会话。
    """
    engine = _get_engine()
    if engine.dialect.name == "sqlite":
        conn = sqlite3.connect(
            configs.database_path, timeout=30, check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        if configs.database_path not in _wal_configured_paths:
            conn.execute("PRAGMA journal_mode=WAL;")
            _wal_configured_paths.add(configs.database_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        raw = engine.raw_connection()
        conn = _PgRawConn(raw)
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                raw.rollback()
            except Exception:
                pass
            raise
        finally:
            raw.close()

# ===========================================================================
# ORM 会话管理 — 新代码使用此接口
# ===========================================================================

def db_session():
    """
    SQLAlchemy ORM 会话上下文管理器（**新代码推荐**）。

    用法::

        with db_session() as session:
            row = session.execute(select(User).where(...)).scalar_one_or_none()

    自动处理 commit / rollback / close。
    """
    from memoria.db.engine import get_session as _gs
    return _gs()


# ===========================================================================
# 初始化
# ===========================================================================

def init_db():
    """初始化数据库结构（通过 SQLAlchemy ``create_all`` + 迁移钩子）。"""
    from memoria.db.engine import init_db as _idb
    _idb()

    from sqlalchemy import text as _text

    # ── 迁移钩子：ALTER TABLE 兼容已有数据库 ──
    engine = _get_engine()
    is_pg = engine.dialect.name == "postgresql"
    with engine.connect() as conn:
        if is_pg:
            conn.execute(_text(
                "ALTER TABLE session ADD COLUMN IF NOT EXISTS story_id TEXT"
            ))
            conn.execute(_text(
                "ALTER TABLE event_definition ADD COLUMN IF NOT EXISTS story_id TEXT"
            ))
            conn.execute(_text(
                "ALTER TABLE event_definition ADD COLUMN IF NOT EXISTS exclusive_scope TEXT NOT NULL DEFAULT 'turn'"
            ))
            conn.execute(_text(
                "ALTER TABLE character_card ADD COLUMN IF NOT EXISTS avatar_revision TEXT"
            ))
        else:
            session_columns = {
                row[1] for row in conn.execute(
                    _text("PRAGMA table_info(session)")
                ).fetchall()
            }
            if "story_id" not in session_columns:
                conn.execute(_text("ALTER TABLE session ADD COLUMN story_id TEXT"))
            event_columns = {
                row[1] for row in conn.execute(
                    _text("PRAGMA table_info(event_definition)")
                ).fetchall()
            }
            if "story_id" not in event_columns:
                conn.execute(_text(
                    "ALTER TABLE event_definition ADD COLUMN story_id TEXT"
                ))
            if "exclusive_scope" not in event_columns:
                conn.execute(_text(
                    "ALTER TABLE event_definition ADD COLUMN exclusive_scope TEXT NOT NULL DEFAULT 'turn'"
                ))
            character_columns = {
                row[1] for row in conn.execute(
                    _text("PRAGMA table_info(character_card)")
                ).fetchall()
            }
            if "avatar_revision" not in character_columns:
                conn.execute(_text(
                    "ALTER TABLE character_card ADD COLUMN avatar_revision TEXT"
                ))
        conn.commit()

    # ── 去重索引 ──
    with engine.connect() as conn:
        conn.execute(_text(
            "DELETE FROM session_summary WHERE id NOT IN ("
            "  SELECT MAX(id) FROM session_summary"
            "  GROUP BY session_id, character_id, player_id"
            ")"
        ))
        try:
            conn.execute(_text(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_unique "
                "ON session_summary(session_id, character_id, player_id)"
            ))
        except Exception:
            pass
        conn.execute(_text(
            "DELETE FROM player_event_inbox"
            " WHERE event_type = 'group_message' AND read_at IS NULL"
            "  AND id NOT IN ("
            "    SELECT MAX(id) FROM player_event_inbox"
            "    WHERE event_type = 'group_message' AND read_at IS NULL"
            "    GROUP BY player_id, group_thread_id"
            "  )"
        ))
        try:
            if is_pg:
                conn.execute(_text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_group_unread "
                    "ON player_event_inbox(player_id, group_thread_id) "
                    "WHERE event_type = 'group_message' AND read_at IS NULL"
                ))
            else:
                conn.execute(_text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_group_unread "
                    "ON player_event_inbox(player_id, group_thread_id) "
                    "WHERE event_type = 'group_message' AND read_at IS NULL"
                ))
        except Exception:
            pass
        conn.commit()


# ===========================================================================
# 向后兼容辅助（已迁移到 SQLAlchemy 的模块不再需要）
# ===========================================================================

def _append_postgres_clause(sql: str, clause: str) -> str:
    """在 SQL 语句末尾追加子句（如 ``FOR UPDATE SKIP LOCKED``）。"""
    stripped = sql.rstrip()
    if stripped.endswith(";"):
        return f"{stripped[:-1]} {clause};"
    return f"{stripped} {clause}"


def _convert_qmark_placeholders(sql: str) -> str:
    """将 sqlite3 的 ``?`` 占位符转换为 psycopg 的 ``%s``（跳过字符串字面量）。"""
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql):
        char = sql[i]
        next_char = sql[i + 1] if i + 1 < len(sql) else ""
        if char == "'" and not in_double:
            out.append(char)
            if in_single and next_char == "'":
                out.append(next_char)
                i += 2
                continue
            in_single = not in_single
        elif char == '"' and not in_single:
            out.append(char)
            if in_double and next_char == '"':
                out.append(next_char)
                i += 2
                continue
            in_double = not in_double
        elif char == "?" and not in_single and not in_double:
            out.append("%s")
        else:
            out.append(char)
        i += 1
    return "".join(out)


def _prepare_postgres_sql(sql: str) -> str:
    """将 sqlite 风格 SQL 转换为 PostgreSQL 兼容版本。"""
    converted = _convert_qmark_placeholders(sql)
    converted = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        converted,
        flags=re.IGNORECASE,
    )
    return converted


# ===========================================================================
# 过渡辅助：从 SQLAlchemy 会话获取原始 DBAPI 连接
# ===========================================================================

@contextmanager
def get_raw_conn():
    """获取原始 DBAPI 连接（通过 SQLAlchemy 会话管理事务）。

    用于尚未完全迁移到 ORM 的内部事务辅助函数。
    与 ``get_conn()`` 行为一致，但事务由 SQLAlchemy 管理。
    """
    with db_session() as session:
        raw = session.connection().connection.dbapi_connection
        if isinstance(raw, sqlite3.Connection):
            raw.row_factory = sqlite3.Row
        yield raw
