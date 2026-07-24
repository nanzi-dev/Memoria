"""
数据持久化层（SQLite / PostgreSQL）

设计目标：
- 默认单文件轻量数据库（适合 demo / MVP）
- 生产部署可通过 DATABASE_URL 切换 PostgreSQL
- 支持角色状态 + 记忆 + 会话管理
- SQL 层隔离，保留 SQLite 开发模式
"""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import sqlite3
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit

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
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

_UNSET = object()
_AUTH_TOKEN_DIGEST_PREFIX = "sha256:"


class AdminBootstrapUnavailable(RuntimeError):
    """管理员初始化名额已被占用。"""


def _auth_token_storage_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{_AUTH_TOKEN_DIGEST_PREFIX}{digest}"

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - PostgreSQL 仅在生产配置启用
    psycopg = None
    dict_row = None

# =========================
# 工具函数
# =========================
def _now() -> str:
    """统一时间格式（UTC ISO8601）"""
    return datetime.now(timezone.utc).isoformat()

def _row_to_dict(row):
    """安全转换 sqlite Row / psycopg dict row -> dict"""
    return dict(row) if row is not None else None


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


def _is_postgres_enabled() -> bool:
    database_url = (configs.database_url or "").strip().lower()
    return database_url.startswith(("postgresql://", "postgres://"))


def _database_name() -> str:
    if not _is_postgres_enabled():
        return configs.database_path
    parsed = urlsplit(configs.database_url)
    return f"{parsed.hostname or 'postgres'}{parsed.path or ''}"


def _convert_qmark_placeholders(sql: str) -> str:
    """将 sqlite3 的 ? 参数占位符转换为 psycopg 的 %s，跳过字符串字面量。"""
    out = []
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


def _append_postgres_clause(sql: str, clause: str) -> str:
    stripped = sql.rstrip()
    if stripped.endswith(";"):
        return f"{stripped[:-1]} {clause};"
    return f"{stripped} {clause}"


def _prepare_postgres_sql(sql: str) -> str:
    converted = _convert_qmark_placeholders(sql)
    had_insert_or_ignore = bool(re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", converted, flags=re.IGNORECASE))
    converted = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", converted, flags=re.IGNORECASE)

    if re.search(r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+auth_token\b", converted, flags=re.IGNORECASE):
        converted = re.sub(
            r"\bINSERT\s+OR\s+REPLACE\s+INTO\s+auth_token\b",
            "INSERT INTO auth_token",
            converted,
            flags=re.IGNORECASE,
        )
        return _append_postgres_clause(
            converted,
            """
            ON CONFLICT (token) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                created_at = EXCLUDED.created_at,
                expires_at = EXCLUDED.expires_at
            """.strip(),
        )

    if had_insert_or_ignore and re.search(r"\bINSERT\s+INTO\s+session\b", converted, flags=re.IGNORECASE):
        return _append_postgres_clause(converted, "ON CONFLICT DO NOTHING")

    return converted


def _schema_for_current_db() -> str:
    if not _is_postgres_enabled():
        return SCHEMA
    schema = SCHEMA.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT",
        "BIGSERIAL PRIMARY KEY",
    )
    for sqlite_type, postgres_type in (
        (
            "aggregate_version INTEGER NOT NULL",
            "aggregate_version BIGINT NOT NULL",
        ),
        ("source_message_id INTEGER", "source_message_id BIGINT"),
        (
            "last_sequence    INTEGER NOT NULL DEFAULT 0",
            "last_sequence    BIGINT NOT NULL DEFAULT 0",
        ),
        (
            "ledger_version          INTEGER NOT NULL",
            "ledger_version BIGINT NOT NULL",
        ),
    ):
        schema = schema.replace(sqlite_type, postgres_type)
    return schema


class _PostgresConnection:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        return self._conn.execute(_prepare_postgres_sql(sql), params)

    def executemany(self, sql, params_seq):
        return self._conn.executemany(_prepare_postgres_sql(sql), params_seq)

    def executescript(self, script: str):
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.execute(statement)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


# =========================
# 去重引擎
# =========================

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
    """检查是否存在相似记录，返回匹配的行或None"""
    norm = _normalize(text)
    if len(norm) < 2:
        return None
    rows = conn.execute(
        f"SELECT *, {text_col} as _cmp FROM {table} WHERE {where_clause}",
        params
    ).fetchall()
    for row in rows:
        if _text_similarity(text, row["_cmp"]) >= threshold:
            return dict(row)
    return None


# =========================
# 数据库连接管理
# =========================
@contextmanager
def get_conn():
    """
    数据库连接上下文管理。

    默认使用 SQLite；设置 DATABASE_URL=postgresql://... 后切换 PostgreSQL。
    """
    db_system = "postgresql" if _is_postgres_enabled() else "sqlite"

    if _is_postgres_enabled():
        if psycopg is None:
            raise RuntimeError("PostgreSQL mode requires installing psycopg[binary].")
        raw_conn = psycopg.connect(configs.database_url, row_factory=dict_row)
        conn = _PostgresConnection(raw_conn)
    else:
        conn = sqlite3.connect(
            configs.database_path,
            timeout=30,
            check_same_thread = False # 避免多线程问题
        )

        conn.row_factory = sqlite3.Row

        # WAL 模式（推荐用于并发读写）
        conn.execute("PRAGMA journal_mode=WAL;")
    
    with tracing.start_span("db.transaction", **{"db.system": db_system, "db.name": _database_name()}):
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        
# =========================
# 初始化数据库
# =========================
SCHEMA = """
-- =========================
-- 用户表
-- =========================
CREATE TABLE IF NOT EXISTS users (
    user_id         TEXT PRIMARY KEY,      -- usr_xxxxxxxx 格式
    username        TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,         -- pbkdf2_sha256 (legacy sha256 still accepted on verify)
    is_admin        INTEGER NOT NULL DEFAULT 0,
    gender          TEXT DEFAULT 'unknown', -- male/female/unknown
    avatar_url      TEXT,                  -- base64 data URL
    tts_auto_play   INTEGER NOT NULL DEFAULT 0,
    stt_auto_send   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT,
    updated_at      TEXT
);

CREATE TABLE IF NOT EXISTS user_character_card (
    user_id         TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    avatar_url      TEXT,
    gender          TEXT DEFAULT 'unknown',
    pronouns        TEXT DEFAULT '',
    age             INTEGER,
    species         TEXT DEFAULT '',
    occupation      TEXT DEFAULT '',
    appearance      TEXT DEFAULT '',
    personality     TEXT DEFAULT '',
    background      TEXT DEFAULT '',
    goals           TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS auth_token (
    token           TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    expires_at      TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS system_bootstrap_claim (
    claim_key       TEXT PRIMARY KEY,
    claimed_by_user_id TEXT NOT NULL,
    claimed_at      TEXT NOT NULL
);

-- =========================
-- 玩家世界时钟
-- =========================
CREATE TABLE IF NOT EXISTS player_world_clock (
    player_id        TEXT PRIMARY KEY,
    timezone         TEXT NOT NULL DEFAULT 'UTC',
    timezone_mode    TEXT NOT NULL DEFAULT 'fixed',
    anchor_real_utc  TEXT NOT NULL,
    anchor_world_utc TEXT NOT NULL,
    time_scale       REAL NOT NULL DEFAULT 1,
    clock_revision   INTEGER NOT NULL DEFAULT 1,
    updated_at       TEXT NOT NULL,
    FOREIGN KEY (player_id) REFERENCES users(user_id)
);

-- =========================
-- 角色卡存储
-- =========================
CREATE TABLE IF NOT EXISTS character_card (
    owner_user_id   TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    
    card_data       TEXT NOT NULL,      -- 完整的角色卡 JSON 数据
    version         TEXT DEFAULT '1.0.0',
    
    -- 元信息（便于查询和展示）
    name            TEXT,
    display_name    TEXT,
    avatar_url      TEXT,               -- 头像（base64 data URL 或网络 URL）
    avatar_revision TEXT,               -- 远程头像下载请求代次
    
    created_at      TEXT,
    updated_at      TEXT,
    
    -- 状态标记
    is_active       INTEGER DEFAULT 1,  -- 1=启用, 0=禁用
    source          TEXT DEFAULT 'db',  -- 'db'=数据库创建, 'file'=从文件导入

    PRIMARY KEY (owner_user_id, character_id),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

-- =========================
-- 事件定义表
-- =========================
CREATE TABLE IF NOT EXISTS event_definition (
    owner_user_id   TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    event_name      TEXT NOT NULL,
    description     TEXT,
    
    character_id    TEXT,               -- 角色专属事件，NULL 表示全局
    story_id        TEXT,               -- 所属剧情聚合，NULL 表示无剧情状态
    
    -- 事件配置（JSON 格式）
    trigger_config  TEXT NOT NULL,      -- TriggerCondition JSON
    effects_config  TEXT NOT NULL,      -- EventEffect[] JSON
    schedule        TEXT,
    template_id     TEXT,
    
    priority        INTEGER DEFAULT 0,
    exclusive_group TEXT,
    exclusive_scope TEXT NOT NULL DEFAULT 'turn',
    max_triggers_per_turn INTEGER DEFAULT 3,
    stop_processing INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    
    created_at      TEXT,
    updated_at      TEXT,
    
    trigger_count   INTEGER DEFAULT 0,
    last_triggered_at TEXT,

    PRIMARY KEY (owner_user_id, event_id),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

-- =========================
-- 事件触发记录表
-- =========================
CREATE TABLE IF NOT EXISTS event_trigger_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    
    event_id        TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    
    triggered_at    TEXT,
    
    -- 触发时的上下文快照
    context_snapshot TEXT,              -- EventContext JSON
    
    -- 应用的效果
    effects_applied  TEXT,              -- 效果列表 JSON

    execution_id    TEXT,
    status          TEXT DEFAULT 'succeeded',
    
    FOREIGN KEY (player_id, event_id) REFERENCES event_definition(owner_user_id, event_id)
);

CREATE TABLE IF NOT EXISTS event_trigger_guard (
    player_id       TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    character_scope TEXT NOT NULL,
    last_triggered_at TEXT,
    claim_token     TEXT,
    claim_expires_at TEXT,
    updated_at      TEXT NOT NULL,

    PRIMARY KEY (player_id, event_id, character_scope)
);

CREATE TABLE IF NOT EXISTS event_exclusive_group_guard (
    player_id       TEXT NOT NULL,
    exclusive_group TEXT NOT NULL,
    selected_event_id TEXT,
    claim_token     TEXT,
    claim_expires_at TEXT,
    updated_at      TEXT NOT NULL,

    PRIMARY KEY (player_id, exclusive_group)
);

-- =========================
-- 事件执行批次与逐事件结果
-- =========================
CREATE TABLE IF NOT EXISTS event_execution_batch (
    player_id       TEXT NOT NULL,
    execution_key   TEXT NOT NULL,
    trigger_source  TEXT NOT NULL,
    status          TEXT NOT NULL,
    results_data    TEXT NOT NULL,
    deduplicated_count INTEGER DEFAULT 0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,

    PRIMARY KEY (player_id, execution_key)
);

CREATE TABLE IF NOT EXISTS event_execution (
    execution_id    TEXT PRIMARY KEY,
    execution_key   TEXT NOT NULL,
    owner_user_id   TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    session_id      TEXT NOT NULL,
    trigger_source  TEXT NOT NULL,
    status          TEXT NOT NULL,
    effects_data    TEXT NOT NULL,
    result_data     TEXT NOT NULL,
    error           TEXT,
    duration_ms     REAL DEFAULT 0.0,
    created_at      TEXT NOT NULL,
    completed_at    TEXT,

    UNIQUE(owner_user_id, event_id, execution_key)
);

CREATE TABLE IF NOT EXISTS event_unlock (
    player_id       TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    unlock_key      TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    unlocked_at     TEXT NOT NULL,

    PRIMARY KEY (player_id, character_id, unlock_key)
);

-- =========================
-- 事件上下文持久化
-- =========================
CREATE TABLE IF NOT EXISTS event_context_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    event_id        TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    context_data    TEXT NOT NULL,
    status          TEXT DEFAULT 'active',
    progress        REAL DEFAULT 0.0,
    last_session_id TEXT,

    created_at      TEXT,
    updated_at      TEXT,

    UNIQUE(event_id, character_id, player_id)
);

-- =========================
-- 时间驱动事件调度状态
-- =========================
CREATE TABLE IF NOT EXISTS event_schedule_state (
    event_id        TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    schedule        TEXT NOT NULL,
    last_checked_at TEXT,
    last_run_at     TEXT,
    next_run_at     TEXT,
    next_due_real_at TEXT,
    missed_count    INTEGER NOT NULL DEFAULT 0,
    status          TEXT DEFAULT 'active',
    lease_owner     TEXT,
    lease_expires_at TEXT,
    last_error      TEXT,
    last_failed_at  TEXT,

    created_at      TEXT,
    updated_at      TEXT,

    PRIMARY KEY (event_id, character_id, player_id)
);

-- =========================
-- 事件模板库
-- =========================
CREATE TABLE IF NOT EXISTS event_template (
    template_id     TEXT PRIMARY KEY,
    template_name   TEXT NOT NULL,
    category        TEXT,
    description     TEXT,
    trigger_config  TEXT NOT NULL,
    effects_config  TEXT NOT NULL,
    metadata        TEXT,
    created_at      TEXT,
    updated_at      TEXT
);

-- =========================
-- 角色关系网络表
-- =========================
CREATE TABLE IF NOT EXISTS character_relationship (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id   TEXT NOT NULL,
    
    character_id_a  TEXT NOT NULL,      -- 角色 A
    character_id_b  TEXT NOT NULL,      -- 角色 B
    
    -- 关系类型
    relationship_type TEXT,             -- 用户自定义关系类型文本
    
    -- 关系强度和描述
    affinity        REAL DEFAULT 0.0,   -- 关系强度（-100 ~ 100）
    description     TEXT,               -- 关系描述
    
    -- 元数据
    created_at      TEXT,
    updated_at      TEXT,
    
    -- 确保同一对角色只有一条关系记录（无向关系）
    UNIQUE(owner_user_id, character_id_a, character_id_b),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS character_relationship_revision (
    owner_user_id   TEXT NOT NULL,
    character_id_a  TEXT NOT NULL,
    character_id_b  TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    PRIMARY KEY (owner_user_id, character_id_a, character_id_b),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

-- =========================
-- 角色关系状态（runtime_state核心）
-- =========================
CREATE TABLE IF NOT EXISTS relationship_state (
    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    affection_level REAL DEFAULT 0.0,
    trust_level     REAL DEFAULT 0.0,

    current_mood    TEXT DEFAULT 'neutral',

    updated_at      TEXT,

    PRIMARY KEY (character_id, player_id)
);

-- =========================
-- 长期记忆（事实）
-- =========================
CREATE TABLE IF NOT EXISTS long_term_fact (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    fact_text       TEXT NOT NULL,
    importance      INTEGER DEFAULT 5,

    created_at      TEXT,
    last_referenced TEXT
);

-- =========================
-- 会话表
-- =========================
CREATE TABLE IF NOT EXISTS session (
    session_id      TEXT PRIMARY KEY,

    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    player_name     TEXT NOT NULL,
    created_at      TEXT,
    ended_at        TEXT,           -- 会话结束时间
    status          TEXT DEFAULT 'active',  -- active / ended
    group_name      TEXT,           -- 多角色群聊名称
    group_thread_id TEXT,           -- 逻辑群聊线程 ID，同一群聊多段 session 共享
    story_id        TEXT,           -- 可选的逻辑故事范围；没有故事时保持 NULL
    locale          TEXT NOT NULL DEFAULT 'zh-CN',
    
    -- 多角色会话标识
    is_multi_character INTEGER DEFAULT 0  -- 0=单角色, 1=多角色群聊
);

-- =========================
-- 多角色会话参与者表
-- =========================
CREATE TABLE IF NOT EXISTS multi_session_participant (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    
    session_id      TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    
    -- 参与配置
    join_order      INTEGER DEFAULT 0,      -- 加入顺序
    speak_frequency REAL DEFAULT 1.0,       -- 发言频率权重（0.0~2.0）
    is_active       INTEGER DEFAULT 1,      -- 是否活跃（可以临时移除角色）
    
    -- 统计信息
    message_count   INTEGER DEFAULT 0,      -- 该角色的发言次数
    
    created_at      TEXT,
    last_spoke_at   TEXT,                   -- 最后发言时间
    
    FOREIGN KEY (session_id) REFERENCES session(session_id),
    UNIQUE(session_id, character_id)
);

-- =========================
-- 短期记忆（对话）
-- =========================
CREATE TABLE IF NOT EXISTS short_term_message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,          -- user / assistant
    content         TEXT NOT NULL,
    
    -- 多角色会话扩展
    character_id    TEXT,                   -- 发言角色ID（多角色会话时必填）
    character_name  TEXT,                   -- 发言角色显示名称

    -- 回放/调试状态快照（旧消息可为空）
    action          TEXT,
    affinity_delta  REAL,
    trust_delta     REAL,
    current_affinity REAL,
    current_trust   REAL,
    current_mood    TEXT,
    event_notification TEXT,
    knowledge_sources TEXT,                 -- KnowledgeSource[] JSON

    -- 群聊对话脉冲元数据（旧消息可为空）
    reply_to_message_id INTEGER,
    reply_to_character_id TEXT,
    intent          TEXT,
    topic           TEXT,
    trigger_source  TEXT,
    
    created_at      TEXT,
    world_created_at TEXT
);

CREATE TABLE IF NOT EXISTS dialogue_turn (
    session_id       TEXT NOT NULL,
    request_id       TEXT NOT NULL,
    player_id        TEXT NOT NULL,
    turn_kind        TEXT NOT NULL,
    status           TEXT NOT NULL,
    lease_owner      TEXT,
    lease_expires_at TEXT,
    response_data    TEXT,
    error            TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT,
    PRIMARY KEY (session_id, request_id),
    FOREIGN KEY (session_id) REFERENCES session(session_id),
    FOREIGN KEY (player_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_dialogue_turn_session_lease
ON dialogue_turn(session_id, status, lease_expires_at);

-- =========================
-- 持久化后台任务
-- =========================
CREATE TABLE IF NOT EXISTS background_job (
    job_id           TEXT PRIMARY KEY,
    job_type         TEXT NOT NULL,
    dedupe_key       TEXT NOT NULL UNIQUE,
    payload          TEXT NOT NULL,
    status           TEXT NOT NULL DEFAULT 'pending',
    attempts         INTEGER NOT NULL DEFAULT 0,
    available_at     TEXT NOT NULL,
    lease_owner      TEXT,
    lease_expires_at TEXT,
    last_error       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    completed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_background_job_claim
ON background_job(status, available_at, lease_expires_at, created_at);

-- =========================
-- 世界观知识库
-- =========================
CREATE TABLE IF NOT EXISTS knowledge_base (
    knowledge_base_id TEXT PRIMARY KEY,
    owner_user_id     TEXT NOT NULL,
    name              TEXT NOT NULL,
    description       TEXT,
    is_enabled        INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS knowledge_binding (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id     TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    target_type       TEXT NOT NULL,       -- global / character / group_thread
    target_id         TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL,
    UNIQUE(owner_user_id, knowledge_base_id, target_type, target_id),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(knowledge_base_id)
);

CREATE TABLE IF NOT EXISTS knowledge_document (
    document_id       TEXT PRIMARY KEY,
    owner_user_id     TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    original_name     TEXT NOT NULL,
    media_type        TEXT NOT NULL,
    source_type       TEXT NOT NULL,       -- upload / pasted_text
    storage_path      TEXT,
    checksum          TEXT NOT NULL,
    byte_size         INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'queued',
    error_message     TEXT,
    extracted_chars   INTEGER NOT NULL DEFAULT 0,
    page_count        INTEGER,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(knowledge_base_id)
);

CREATE TABLE IF NOT EXISTS knowledge_chunk (
    chunk_id          TEXT PRIMARY KEY,
    owner_user_id     TEXT NOT NULL,
    knowledge_base_id TEXT NOT NULL,
    document_id       TEXT NOT NULL,
    chunk_index       INTEGER NOT NULL,
    content           TEXT NOT NULL,
    char_count        INTEGER NOT NULL,
    source_metadata   TEXT,
    created_at        TEXT NOT NULL,
    UNIQUE(document_id, chunk_index),
    FOREIGN KEY (owner_user_id) REFERENCES users(user_id),
    FOREIGN KEY (knowledge_base_id) REFERENCES knowledge_base(knowledge_base_id),
    FOREIGN KEY (document_id) REFERENCES knowledge_document(document_id)
);

CREATE TABLE IF NOT EXISTS knowledge_vector_cleanup (
    cleanup_id        TEXT PRIMARY KEY,
    owner_user_id     TEXT NOT NULL,
    scope_type        TEXT NOT NULL,
    scope_id          TEXT NOT NULL,
    attempts          INTEGER NOT NULL DEFAULT 0,
    last_error        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    UNIQUE(owner_user_id, scope_type, scope_id)
);

-- =========================
-- 玩家事件收件箱
-- =========================
CREATE TABLE IF NOT EXISTS player_event_inbox (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id        TEXT NOT NULL,
    event_id         TEXT,
    character_id     TEXT,
    session_id       TEXT,
    event_type       TEXT NOT NULL DEFAULT 'event',
    group_thread_id  TEXT,
    unread_count     INTEGER NOT NULL DEFAULT 0,
    title            TEXT,
    content          TEXT NOT NULL,
    payload          TEXT,
    world_created_at TEXT,
    created_at       TEXT NOT NULL,
    read_at          TEXT,
    FOREIGN KEY (player_id) REFERENCES users(user_id)
);

-- =========================
-- 逻辑群聊自主对话状态
-- =========================
CREATE TABLE IF NOT EXISTS group_dialogue_state (
    group_thread_id          TEXT PRIMARY KEY,
    player_id                TEXT NOT NULL,
    current_topic            TEXT,
    topic_source             TEXT,
    last_reply_to_message_id INTEGER,
    last_reply_to_character_id TEXT,
    last_speaker_id          TEXT,
    waiting_for_player       INTEGER NOT NULL DEFAULT 0,
    unresolved_hooks         TEXT NOT NULL DEFAULT '[]',
    last_autonomous_pulse_at TEXT,
    last_autonomous_world_at TEXT,
    daily_message_date       TEXT,
    daily_message_count      INTEGER NOT NULL DEFAULT 0,
    lease_owner              TEXT,
    lease_expires_at         TEXT,
    created_at               TEXT NOT NULL,
    updated_at               TEXT NOT NULL,
    FOREIGN KEY (player_id) REFERENCES users(user_id)
);

-- =========================
-- 会话摘要（中期记忆）
-- =========================
CREATE TABLE IF NOT EXISTS session_summary (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    session_id      TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    player_id       TEXT NOT NULL,

    summary_text    TEXT NOT NULL,  -- 会话摘要内容
    message_count   INTEGER,        -- 摘要涵盖的消息数
    summary_status  TEXT DEFAULT 'completed',  -- pending/generating/completed/failed
    
    created_at      TEXT,

    FOREIGN KEY (session_id) REFERENCES session(session_id)
);

-- =========================
-- 权威领域事件账本
-- =========================
CREATE TABLE IF NOT EXISTS domain_event (
    sequence          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          TEXT NOT NULL UNIQUE,
    owner_user_id     TEXT NOT NULL,
    aggregate_type    TEXT NOT NULL,
    aggregate_id      TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    event_type        TEXT NOT NULL,
    payload           TEXT NOT NULL,
    metadata          TEXT NOT NULL,
    correlation_id    TEXT,
    causation_id      TEXT,
    session_id        TEXT,
    group_thread_id   TEXT,
    source_turn_id    TEXT,
    source_message_id INTEGER,
    world_occurred_at TEXT,
    recorded_at       TEXT NOT NULL,
    UNIQUE(
        owner_user_id,
        aggregate_type,
        aggregate_id,
        aggregate_version
    )
);

CREATE TABLE IF NOT EXISTS projection_checkpoint (
    projector_name   TEXT NOT NULL,
    owner_user_id    TEXT NOT NULL,
    last_sequence    INTEGER NOT NULL DEFAULT 0,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (projector_name, owner_user_id)
);

CREATE TABLE IF NOT EXISTS data_migration (
    migration_key    TEXT PRIMARY KEY,
    metadata         TEXT NOT NULL DEFAULT '{}',
    applied_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fact_claim (
    claim_id                TEXT PRIMARY KEY,
    owner_user_id           TEXT NOT NULL,
    scope_type              TEXT NOT NULL
                            CHECK (scope_type IN ('character', 'group_thread', 'story')),
    scope_id                TEXT NOT NULL,
    fact_text               TEXT NOT NULL,
    normalized_fact_text    TEXT NOT NULL,
    content_hash            TEXT NOT NULL,
    normalized_content_hash TEXT NOT NULL,
    status                  TEXT NOT NULL
                            CHECK (status IN ('candidate', 'verified', 'retracted', 'superseded')),
    source_kind             TEXT NOT NULL
                            CHECK (source_kind IN (
                                'player_message',
                                'knowledge_chunk',
                                'authored_event',
                                'model_inference',
                                'legacy'
                            )),
    provenance              TEXT NOT NULL DEFAULT '{}',
    source_ids              TEXT NOT NULL DEFAULT '[]',
    supersedes_claim_id     TEXT,
    superseded_by_claim_id  TEXT,
    ledger_version          INTEGER NOT NULL,
    created_at              TEXT NOT NULL,
    updated_at              TEXT NOT NULL,
    verified_at             TEXT,
    retracted_at            TEXT,
    UNIQUE (
        owner_user_id,
        scope_type,
        scope_id,
        normalized_content_hash
    ),
    FOREIGN KEY (supersedes_claim_id) REFERENCES fact_claim(claim_id),
    FOREIGN KEY (superseded_by_claim_id) REFERENCES fact_claim(claim_id)
);

CREATE TABLE IF NOT EXISTS story_state (
    owner_user_id  TEXT NOT NULL,
    story_id       TEXT NOT NULL,
    status         TEXT NOT NULL
                   CHECK (status IN ('active', 'completed', 'failed')),
    progress       REAL NOT NULL DEFAULT 0,
    terminal_reason TEXT,
    ledger_version INTEGER NOT NULL,
    started_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    completed_at   TEXT,
    failed_at      TEXT,
    PRIMARY KEY (owner_user_id, story_id)
);


-- =========================
-- 索引优化
-- =========================

CREATE INDEX IF NOT EXISTS idx_session_lookup
ON session(character_id, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_multi
ON session(is_multi_character, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_group_thread
ON session(group_thread_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_multi_participant
ON multi_session_participant(session_id, is_active);

CREATE INDEX IF NOT EXISTS idx_message_session
ON short_term_message(session_id, id ASC);

CREATE INDEX IF NOT EXISTS idx_message_character
ON short_term_message(session_id, character_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fact_lookup
ON long_term_fact(character_id, player_id, importance DESC, last_referenced DESC);

CREATE INDEX IF NOT EXISTS idx_summary_lookup
ON session_summary(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_summary_player
ON session_summary(character_id, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_domain_event_aggregate
ON domain_event(
    owner_user_id,
    aggregate_type,
    aggregate_id,
    aggregate_version
);

CREATE INDEX IF NOT EXISTS idx_domain_event_correlation
ON domain_event(owner_user_id, correlation_id, sequence);

CREATE INDEX IF NOT EXISTS idx_domain_event_source_turn
ON domain_event(owner_user_id, source_turn_id, sequence);

CREATE INDEX IF NOT EXISTS idx_domain_event_group_thread
ON domain_event(owner_user_id, group_thread_id, sequence);

CREATE INDEX IF NOT EXISTS idx_fact_claim_scope
ON fact_claim(owner_user_id, scope_type, scope_id, created_at, claim_id);

CREATE INDEX IF NOT EXISTS idx_fact_claim_verified
ON fact_claim(
    owner_user_id,
    scope_type,
    scope_id,
    status,
    created_at,
    claim_id
);

CREATE INDEX IF NOT EXISTS idx_story_state_status
ON story_state(owner_user_id, status, updated_at, story_id);

CREATE INDEX IF NOT EXISTS idx_character_active
ON character_card(owner_user_id, is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_character
ON event_definition(owner_user_id, character_id, is_active);

CREATE INDEX IF NOT EXISTS idx_event_trigger_log
ON event_trigger_log(event_id, character_id, player_id, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_execution_metrics
ON event_execution(owner_user_id, event_id, status, completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_unlock_lookup
ON event_unlock(player_id, character_id, unlocked_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_context_lookup
ON event_context_state(character_id, player_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_schedule_due
ON event_schedule_state(status, next_run_at);

CREATE INDEX IF NOT EXISTS idx_event_schedule_due_real
ON event_schedule_state(status, next_due_real_at);

CREATE INDEX IF NOT EXISTS idx_event_schedule_lease
ON event_schedule_state(status, lease_expires_at);

CREATE INDEX IF NOT EXISTS idx_auth_token_user
ON auth_token(user_id, expires_at);

CREATE INDEX IF NOT EXISTS idx_player_event_inbox_unread
ON player_event_inbox(player_id, read_at, id DESC);

CREATE INDEX IF NOT EXISTS idx_player_group_inbox_unread
ON player_event_inbox(player_id, group_thread_id, read_at, id DESC);

CREATE INDEX IF NOT EXISTS idx_group_dialogue_state_scan
ON group_dialogue_state(player_id, lease_expires_at, last_autonomous_pulse_at);

CREATE INDEX IF NOT EXISTS idx_knowledge_base_owner
ON knowledge_base(owner_user_id, is_enabled, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_binding_target
ON knowledge_binding(owner_user_id, target_type, target_id, knowledge_base_id);

CREATE INDEX IF NOT EXISTS idx_knowledge_document_base
ON knowledge_document(owner_user_id, knowledge_base_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_document
ON knowledge_chunk(owner_user_id, document_id, chunk_index);

CREATE INDEX IF NOT EXISTS idx_knowledge_vector_cleanup_pending
ON knowledge_vector_cleanup(updated_at, attempts);


-- =========================
-- 多角色共享记忆（角色间）
-- =========================
CREATE TABLE IF NOT EXISTS shared_memory (
    id              TEXT PRIMARY KEY,
    owner_user_id   TEXT NOT NULL,
    character_a_id  TEXT NOT NULL,
    character_b_id  TEXT NOT NULL,
    observer_character_id TEXT,
    target_character_id TEXT,
    memory_kind     TEXT NOT NULL DEFAULT 'legacy_archived',
    memory_text     TEXT NOT NULL,
    context         TEXT,
    importance      REAL DEFAULT 0.5,
    created_at      TEXT,
    last_referenced TEXT,
    reference_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_shared_memory_owner_pair
ON shared_memory(owner_user_id, character_a_id, character_b_id, importance DESC);

CREATE INDEX IF NOT EXISTS idx_shared_memory_directional
ON shared_memory(
    owner_user_id,
    observer_character_id,
    target_character_id,
    importance DESC
);

-- =========================
-- 多角色群体记忆（会话级）
-- =========================
CREATE TABLE IF NOT EXISTS group_memory (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    memory_text     TEXT NOT NULL,
    participants    TEXT,
    context         TEXT,
    importance      REAL DEFAULT 0.5,
    created_at      TEXT,
    last_referenced TEXT,
    reference_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_relationship_lookup
ON character_relationship(owner_user_id, character_id_a, character_id_b);

CREATE INDEX IF NOT EXISTS idx_relationship_revision_lookup
ON character_relationship_revision(owner_user_id, character_id_a, character_id_b);
"""


def init_db():
    """初始化数据库结构"""
    with get_conn() as conn:
        conn.executescript(_schema_for_current_db())
        if _is_postgres_enabled():
            conn.execute(
                "ALTER TABLE session ADD COLUMN IF NOT EXISTS story_id TEXT"
            )
            conn.execute(
                "ALTER TABLE event_definition "
                "ADD COLUMN IF NOT EXISTS story_id TEXT"
            )
            conn.execute(
                "ALTER TABLE event_definition "
                "ADD COLUMN IF NOT EXISTS exclusive_scope TEXT "
                "NOT NULL DEFAULT 'turn'"
            )
            conn.execute(
                "ALTER TABLE character_card "
                "ADD COLUMN IF NOT EXISTS avatar_revision TEXT"
            )
        else:
            session_columns = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(session)").fetchall()
            }
            if "story_id" not in session_columns:
                conn.execute("ALTER TABLE session ADD COLUMN story_id TEXT")
            event_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(event_definition)"
                ).fetchall()
            }
            if "story_id" not in event_columns:
                conn.execute(
                    "ALTER TABLE event_definition ADD COLUMN story_id TEXT"
                )
            if "exclusive_scope" not in event_columns:
                conn.execute(
                    "ALTER TABLE event_definition "
                    "ADD COLUMN exclusive_scope TEXT NOT NULL DEFAULT 'turn'"
                )
            character_columns = {
                row["name"]
                for row in conn.execute(
                    "PRAGMA table_info(character_card)"
                ).fetchall()
            }
            if "avatar_revision" not in character_columns:
                conn.execute(
                    "ALTER TABLE character_card ADD COLUMN avatar_revision TEXT"
                )


