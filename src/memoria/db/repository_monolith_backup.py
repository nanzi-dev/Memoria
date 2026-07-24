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


# =========================
# 持久化后台任务
# =========================
def _background_job_time(value: datetime | str | None = None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decode_background_job(row) -> dict | None:
    job = _row_to_dict(row)
    if job is None:
        return None
    try:
        job["payload"] = json.loads(job["payload"])
    except (TypeError, ValueError):
        job["payload"] = {}
    return job


def _lock_background_job_write(conn) -> None:
    if isinstance(conn, sqlite3.Connection):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")


def _enqueue_background_job_in_transaction(
    conn,
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    available_at: datetime | str | None = None,
    now: datetime | str | None = None,
) -> dict:
    if not job_type or not dedupe_key:
        raise ValueError("job_type and dedupe_key are required")
    if not isinstance(payload, dict):
        raise TypeError("background job payload must be a dict")

    queued_at = _background_job_time(now)
    now_iso = queued_at.isoformat()
    available_at_iso = _background_job_time(available_at or queued_at).isoformat()
    job_id = f"job_{uuid.uuid4().hex}"
    encoded_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    _lock_background_job_write(conn)
    conn.execute(
        """
        INSERT INTO background_job (
            job_id, job_type, dedupe_key, payload, status, attempts,
            available_at, lease_owner, lease_expires_at, last_error,
            created_at, updated_at, completed_at
        )
        VALUES (?, ?, ?, ?, 'pending', 0, ?, NULL, NULL, NULL, ?, ?, NULL)
        ON CONFLICT(dedupe_key) DO NOTHING
        """,
        (
            job_id,
            job_type,
            dedupe_key,
            encoded_payload,
            available_at_iso,
            now_iso,
            now_iso,
        ),
    )
    row = conn.execute(
        "SELECT * FROM background_job WHERE dedupe_key = ?",
        (dedupe_key,),
    ).fetchone()
    if row["job_type"] != job_type:
        raise ValueError("dedupe_key is already used by another job type")
    return _decode_background_job(row)


def enqueue_background_job(
    *,
    job_type: str,
    dedupe_key: str,
    payload: dict[str, Any],
    available_at: datetime | str | None = None,
) -> dict:
    """Persist one immutable job payload, deduplicated by caller-provided key."""
    now = _background_job_time()
    with get_conn() as conn:
        return _enqueue_background_job_in_transaction(
            conn,
            job_type=job_type,
            dedupe_key=dedupe_key,
            payload=payload,
            available_at=available_at,
            now=now,
        )


def get_background_job(job_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _decode_background_job(row)


def claim_background_job(
    *,
    lease_owner: str,
    lease_seconds: int = 60,
    now: datetime | str | None = None,
) -> dict | None:
    """Atomically claim one due or expired job and increment its attempt count."""
    if not lease_owner:
        raise ValueError("lease_owner is required")
    claimed_at = _background_job_time(now)
    claimed_at_iso = claimed_at.isoformat()
    lease_expires_at = (
        claimed_at + timedelta(seconds=max(1, int(lease_seconds)))
    ).isoformat()

    with get_conn() as conn:
        _lock_background_job_write(conn)
        select_sql = """
            SELECT *
            FROM background_job
            WHERE (
                status IN ('pending', 'retry')
                AND available_at <= ?
            ) OR (
                status = 'running'
                AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            )
            ORDER BY available_at ASC, created_at ASC, job_id ASC
            LIMIT 1
        """
        if _is_postgres_enabled():
            select_sql = _append_postgres_clause(
                select_sql,
                "FOR UPDATE SKIP LOCKED",
            )
        candidate = conn.execute(
            select_sql,
            (claimed_at_iso, claimed_at_iso),
        ).fetchone()
        if candidate is None:
            return None

        updated = conn.execute(
            """
            UPDATE background_job
            SET status = 'running',
                attempts = attempts + 1,
                lease_owner = ?,
                lease_expires_at = ?,
                last_error = NULL,
                updated_at = ?,
                completed_at = NULL
            WHERE job_id = ?
              AND (
                    (
                        status IN ('pending', 'retry')
                        AND available_at <= ?
                    ) OR (
                        status = 'running'
                        AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
                    )
              )
            """,
            (
                lease_owner,
                lease_expires_at,
                claimed_at_iso,
                candidate["job_id"],
                claimed_at_iso,
                claimed_at_iso,
            ),
        )
        if updated.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (candidate["job_id"],),
        ).fetchone()
        return _decode_background_job(row)


def complete_background_job(
    job_id: str,
    *,
    lease_owner: str,
    now: datetime | str | None = None,
) -> bool:
    """Complete a job only while the caller still owns its active lease."""
    completed_at = _background_job_time(now).isoformat()
    with get_conn() as conn:
        updated = conn.execute(
            """
            UPDATE background_job
            SET status = 'completed',
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error = NULL,
                updated_at = ?,
                completed_at = ?
            WHERE job_id = ?
              AND status = 'running'
              AND lease_owner = ?
              AND lease_expires_at > ?
            """,
            (
                completed_at,
                completed_at,
                job_id,
                lease_owner,
                completed_at,
            ),
        )
        return updated.rowcount == 1


def record_background_job_failure(
    job_id: str,
    *,
    lease_owner: str,
    error: str,
    max_attempts: int,
    retry_delay_seconds: float = 0,
    now: datetime | str | None = None,
) -> dict | None:
    """Release a failed attempt for retry, or mark it terminal at the limit."""
    failed_at = _background_job_time(now)
    failed_at_iso = failed_at.isoformat()
    max_attempts = max(1, int(max_attempts))
    retry_at = (
        failed_at + timedelta(seconds=max(0.0, float(retry_delay_seconds)))
    ).isoformat()

    with get_conn() as conn:
        _lock_background_job_write(conn)
        if _is_postgres_enabled():
            row = conn.execute(
                """
                SELECT * FROM background_job
                WHERE job_id = ?
                FOR UPDATE
                """,
                (job_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM background_job WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        if (
            row is None
            or row["status"] != "running"
            or row["lease_owner"] != lease_owner
            or not row["lease_expires_at"]
            or row["lease_expires_at"] <= failed_at_iso
        ):
            return None

        terminal = int(row["attempts"]) >= max_attempts
        status = "failed" if terminal else "retry"
        available_at = row["available_at"] if terminal else retry_at
        completed_at = failed_at_iso if terminal else None
        conn.execute(
            """
            UPDATE background_job
            SET status = ?,
                available_at = ?,
                lease_owner = NULL,
                lease_expires_at = NULL,
                last_error = ?,
                updated_at = ?,
                completed_at = ?
            WHERE job_id = ? AND status = 'running' AND lease_owner = ?
            """,
            (
                status,
                available_at,
                str(error)[:4000],
                failed_at_iso,
                completed_at,
                job_id,
                lease_owner,
            ),
        )
        updated = conn.execute(
            "SELECT * FROM background_job WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        return _decode_background_job(updated)


# =========================
# 权威领域事件账本
# =========================
class DomainEventConcurrencyError(RuntimeError):
    """聚合版本与调用方预期不一致。"""


class DomainEventIdempotencyConflictError(DomainEventConcurrencyError):
    """同一 event_id 被用于不同的不可变事件内容。"""


class UnsupportedDomainEventVersionError(ValueError):
    """投影器无法安全处理事件的主版本。"""


FACT_CLAIM_PROJECTOR = "fact_claim.v1"
STORY_STATE_PROJECTOR = "story_state.v1"


_DOMAIN_EVENT_IMMUTABLE_FIELDS = (
    "owner_user_id",
    "aggregate_type",
    "aggregate_id",
    "event_type",
    "payload",
    "metadata",
    "correlation_id",
    "causation_id",
    "session_id",
    "group_thread_id",
    "source_turn_id",
    "source_message_id",
    "world_occurred_at",
)


def _domain_event_from_row(row) -> StoredDomainEvent | None:
    if row is None:
        return None
    values = dict(row)
    values["payload"] = json.loads(values["payload"])
    values["metadata"] = json.loads(values["metadata"])
    return StoredDomainEvent(**values)


def _get_domain_event_by_id_in_transaction(
    conn,
    event_id: str,
) -> StoredDomainEvent | None:
    row = conn.execute(
        """
        SELECT *
        FROM domain_event
        WHERE event_id = ?
        """,
        (event_id,),
    ).fetchone()
    return _domain_event_from_row(row)


def _get_domain_event_in_transaction(
    conn,
    event_id: str,
    owner_user_id: str,
) -> StoredDomainEvent | None:
    row = conn.execute(
        """
        SELECT *
        FROM domain_event
        WHERE event_id = ? AND owner_user_id = ?
        """,
        (event_id, owner_user_id),
    ).fetchone()
    return _domain_event_from_row(row)


def _canonical_domain_event_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_domain_event_retry(
    event: NewDomainEvent,
    existing: StoredDomainEvent,
) -> StoredDomainEvent:
    submitted = event.model_dump()
    stored = existing.model_dump()
    mismatched_fields = []
    for field_name in _DOMAIN_EVENT_IMMUTABLE_FIELDS:
        submitted_value = submitted[field_name]
        stored_value = stored[field_name]
        if field_name in {"payload", "metadata"}:
            matches = (
                _canonical_domain_event_json(submitted_value)
                == _canonical_domain_event_json(stored_value)
            )
        else:
            matches = submitted_value == stored_value
        if not matches:
            mismatched_fields.append(field_name)
    if mismatched_fields:
        raise DomainEventIdempotencyConflictError(
            "domain event idempotency conflict for "
            f"event_id {event.event_id!r}: immutable fields differ: "
            + ", ".join(mismatched_fields)
        )
    return existing


def _current_domain_event_version(
    conn,
    aggregate_key: tuple[str, str, str],
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(aggregate_version), 0) AS aggregate_version
        FROM domain_event
        WHERE owner_user_id = ?
          AND aggregate_type = ?
          AND aggregate_id = ?
        """,
        aggregate_key,
    ).fetchone()
    return int(row["aggregate_version"] or 0)


def _is_unique_constraint_error(exc: Exception) -> bool:
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    return getattr(exc, "sqlstate", None) == "23505"


def _append_domain_events_in_transaction(
    conn,
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
) -> list[StoredDomainEvent]:
    expected_versions = expected_versions or {}
    current_versions: dict[tuple[str, str, str], int] = {}
    stored_events: list[StoredDomainEvent] = []

    for event_index, event in enumerate(events):
        existing = _get_domain_event_by_id_in_transaction(
            conn,
            event.event_id,
        )
        if existing is not None:
            stored_events.append(
                _validate_domain_event_retry(event, existing)
            )
            continue

        aggregate_key = (
            event.owner_user_id,
            event.aggregate_type,
            event.aggregate_id,
        )
        if aggregate_key not in current_versions:
            current_version = _current_domain_event_version(
                conn,
                aggregate_key,
            )
            expected_version = expected_versions.get(aggregate_key)
            if (
                expected_version is not None
                and current_version != expected_version
            ):
                raise DomainEventConcurrencyError(
                    "domain event aggregate version conflict: "
                    f"expected {expected_version}, found {current_version}"
                )
            current_versions[aggregate_key] = current_version

        aggregate_version = current_versions[aggregate_key] + 1
        recorded_at = _now()
        values = event.model_dump()
        insert_sql = """
            INSERT INTO domain_event (
                event_id,
                owner_user_id,
                aggregate_type,
                aggregate_id,
                aggregate_version,
                event_type,
                payload,
                metadata,
                correlation_id,
                causation_id,
                session_id,
                group_thread_id,
                source_turn_id,
                source_message_id,
                world_occurred_at,
                recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING sequence"
        savepoint_name = f"domain_event_append_{event_index}"
        use_savepoint = _is_postgres_enabled()
        if use_savepoint:
            conn.execute(f"SAVEPOINT {savepoint_name}")
        try:
            cursor = conn.execute(
                insert_sql,
                (
                    values["event_id"],
                    values["owner_user_id"],
                    values["aggregate_type"],
                    values["aggregate_id"],
                    aggregate_version,
                    values["event_type"],
                    json.dumps(
                        values["payload"],
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    json.dumps(
                        values["metadata"],
                        ensure_ascii=False,
                        allow_nan=False,
                    ),
                    values["correlation_id"],
                    values["causation_id"],
                    values["session_id"],
                    values["group_thread_id"],
                    values["source_turn_id"],
                    values["source_message_id"],
                    values["world_occurred_at"],
                    recorded_at,
                ),
            )
            sequence = (
                cursor.fetchone()["sequence"]
                if _is_postgres_enabled()
                else cursor.lastrowid
            )
        except Exception as exc:
            if use_savepoint:
                conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
            existing = _get_domain_event_by_id_in_transaction(
                conn,
                event.event_id,
            )
            if existing is not None:
                recovered = _validate_domain_event_retry(
                    event,
                    existing,
                )
                stored_events.append(recovered)
                current_versions[aggregate_key] = max(
                    current_versions[aggregate_key],
                    recovered.aggregate_version,
                )
                continue
            if _is_unique_constraint_error(exc):
                raise DomainEventConcurrencyError(
                    "domain event aggregate version conflict"
                ) from exc
            raise
        if use_savepoint:
            conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        stored = StoredDomainEvent(
            **values,
            sequence=sequence,
            aggregate_version=aggregate_version,
            recorded_at=recorded_at,
        )
        stored_events.append(stored)
        current_versions[aggregate_key] = aggregate_version

    return stored_events


def _append_domain_event_batch(
    conn,
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
) -> list[StoredDomainEvent]:
    if not events:
        return []

    if isinstance(conn, sqlite3.Connection) and not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")

    savepoint_name = "domain_event_append_batch"
    conn.execute(f"SAVEPOINT {savepoint_name}")
    try:
        stored_events = _append_domain_events_in_transaction(
            conn,
            events,
            expected_versions=expected_versions,
        )
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
        raise
    conn.execute(f"RELEASE SAVEPOINT {savepoint_name}")
    return stored_events


def append_domain_events(
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
    conn=None,
) -> list[StoredDomainEvent]:
    """原子追加一批领域事件；已有事务可通过 conn 复用。"""
    if conn is not None:
        return _append_domain_event_batch(
            conn,
            events,
            expected_versions=expected_versions,
        )
    with get_conn() as transaction:
        return _append_domain_event_batch(
            transaction,
            events,
            expected_versions=expected_versions,
        )


def append_domain_event(
    event: NewDomainEvent,
    *,
    expected_version: int | None = None,
    conn=None,
) -> StoredDomainEvent:
    """追加单个领域事件。"""
    aggregate_key = (
        event.owner_user_id,
        event.aggregate_type,
        event.aggregate_id,
    )
    expected_versions = (
        {aggregate_key: expected_version}
        if expected_version is not None
        else None
    )
    return append_domain_events(
        [event],
        expected_versions=expected_versions,
        conn=conn,
    )[0]


def get_domain_event(
    event_id: str,
    *,
    owner_user_id: str,
) -> StoredDomainEvent | None:
    """在租户边界内按全局 event_id 获取事件。"""
    with get_conn() as conn:
        return _get_domain_event_in_transaction(
            conn,
            event_id,
            owner_user_id,
        )


def list_domain_events(
    owner_user_id: str,
    aggregate_type: str | None = None,
    aggregate_id: str | None = None,
    *,
    after_sequence: int = 0,
    limit: int | None = None,
) -> list[StoredDomainEvent]:
    """按全局序列读取租户领域事件。"""
    if limit is not None and (
        isinstance(limit, bool)
        or limit < 0
    ):
        raise ValueError("limit must be a non-negative integer")

    clauses = ["owner_user_id = ?", "sequence > ?"]
    params: list[Any] = [owner_user_id, after_sequence]
    if aggregate_type is not None:
        clauses.append("aggregate_type = ?")
        params.append(aggregate_type)
    if aggregate_id is not None:
        clauses.append("aggregate_id = ?")
        params.append(aggregate_id)
    sql = (
        "SELECT * FROM domain_event WHERE "
        + " AND ".join(clauses)
        + " ORDER BY sequence ASC"
    )
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [_domain_event_from_row(row) for row in rows]


# =========================
# story state projection
# =========================
class StoryStateTransitionError(ValueError):
    """剧情事件违反聚合状态转换规则。"""


_STORY_EVENT_TYPES = {
    "story.started.v1",
    "story.progressed.v1",
    "story.completed.v1",
    "story.failed.v1",
}
_TERMINAL_STORY_STATUSES = {"completed", "failed"}


def _decode_story_state_row(row) -> dict | None:
    if row is None:
        return None
    state = dict(row)
    state["progress"] = float(state["progress"])
    state["ledger_version"] = int(state["ledger_version"])
    return state


def _get_story_state_in_transaction(
    conn,
    owner_user_id: str,
    story_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM story_state
        WHERE owner_user_id = ? AND story_id = ?
        """,
        (owner_user_id, story_id),
    ).fetchone()
    return _decode_story_state_row(row)


def _clamp_story_progress(value: Any) -> float:
    try:
        progress = float(value)
    except (TypeError, ValueError) as exc:
        raise StoryStateTransitionError(
            "story progress must be numeric"
        ) from exc
    return max(0.0, min(1.0, progress))


def _project_story_event_in_transaction(
    conn,
    event: StoredDomainEvent,
) -> dict:
    if event.aggregate_type != "story":
        raise ValueError("story projector received another aggregate type")
    if event.event_type not in _STORY_EVENT_TYPES:
        raise ValueError(f"unsupported story event type: {event.event_type}")

    state = _get_story_state_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if state is not None and event.aggregate_version == state["ledger_version"]:
        return state

    expected_version = 1 if state is None else state["ledger_version"] + 1
    if event.aggregate_version != expected_version:
        raise DomainEventConcurrencyError(
            "story projection version conflict: "
            f"expected {expected_version}, found {event.aggregate_version}"
        )

    payload = event.model_dump()["payload"]
    if event.event_type == "story.started.v1":
        if state is not None:
            raise StoryStateTransitionError("story has already started")
        progress = _clamp_story_progress(payload.get("progress", 0.0))
        conn.execute(
            """
            INSERT INTO story_state (
                owner_user_id,
                story_id,
                status,
                progress,
                terminal_reason,
                ledger_version,
                started_at,
                updated_at,
                completed_at,
                failed_at
            )
            VALUES (?, ?, 'active', ?, NULL, ?, ?, ?, NULL, NULL)
            """,
            (
                event.owner_user_id,
                event.aggregate_id,
                progress,
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
            ),
        )
    elif event.event_type == "story.progressed.v1":
        if state is None:
            raise StoryStateTransitionError("story must be started before progress")
        if state["status"] in _TERMINAL_STORY_STATUSES:
            raise StoryStateTransitionError(
                "story progress cannot change after terminal state"
            )
        if "progress" in payload:
            progress = _clamp_story_progress(payload["progress"])
        else:
            progress = _clamp_story_progress(
                state["progress"] + float(payload.get("progress_delta", 0.0))
            )
        conn.execute(
            """
            UPDATE story_state
            SET progress = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND story_id = ?
              AND ledger_version = ?
            """,
            (
                progress,
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                state["ledger_version"],
            ),
        )
    else:
        if state is None:
            raise StoryStateTransitionError(
                "story must be started before reaching a terminal state"
            )
        if state["status"] in _TERMINAL_STORY_STATUSES:
            raise StoryStateTransitionError("story is already terminal")
        status = (
            "completed"
            if event.event_type == "story.completed.v1"
            else "failed"
        )
        progress = (
            1.0
            if status == "completed"
            else _clamp_story_progress(payload.get("progress", state["progress"]))
        )
        reason = str(payload.get("reason") or "").strip() or None
        conn.execute(
            """
            UPDATE story_state
            SET status = ?,
                progress = ?,
                terminal_reason = ?,
                ledger_version = ?,
                updated_at = ?,
                completed_at = ?,
                failed_at = ?
            WHERE owner_user_id = ?
              AND story_id = ?
              AND ledger_version = ?
            """,
            (
                status,
                progress,
                reason,
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at if status == "completed" else None,
                event.recorded_at if status == "failed" else None,
                event.owner_user_id,
                event.aggregate_id,
                state["ledger_version"],
            ),
        )

    projected = _get_story_state_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if projected is None or projected["ledger_version"] != event.aggregate_version:
        raise DomainEventConcurrencyError(
            "story projection changed concurrently"
        )
    return projected


def append_story_event(
    owner_user_id: str,
    story_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    event_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    session_id: str | None = None,
    group_thread_id: str | None = None,
    source_turn_id: str | None = None,
    source_message_id: int | None = None,
    world_occurred_at: str | None = None,
) -> dict:
    """追加剧情事件并在同一事务内更新规范化剧情状态。"""
    event_values = {
        "owner_user_id": owner_user_id,
        "aggregate_type": "story",
        "aggregate_id": story_id,
        "event_type": event_type,
        "payload": payload or {},
        "metadata": metadata or {},
        "correlation_id": correlation_id,
        "causation_id": causation_id,
        "session_id": session_id,
        "group_thread_id": group_thread_id,
        "source_turn_id": source_turn_id,
        "source_message_id": source_message_id,
        "world_occurred_at": world_occurred_at,
    }
    if event_id is not None:
        event_values["event_id"] = event_id
    event = NewDomainEvent(**event_values)
    with get_conn() as conn:
        return _append_and_project_story_event_in_transaction(conn, event)


def _append_and_project_story_event_in_transaction(
    conn,
    event: NewDomainEvent,
) -> dict:
    stored = append_domain_event(event, conn=conn)
    return _project_story_event_in_transaction(conn, stored)


def _event_execution_domain_event_id(
    execution_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
) -> str:
    identity = "\0".join(
        (
            "event_execution",
            execution_id,
            aggregate_type,
            aggregate_id,
            event_type,
        )
    )
    return uuid.uuid5(uuid.NAMESPACE_URL, identity).hex


def _apply_story_update_in_transaction(
    conn,
    owner_user_id: str,
    update: dict[str, Any],
) -> dict:
    story_id = str(update.get("story_id") or "").strip()
    execution_id = str(update.get("execution_id") or "").strip()
    source_event_id = str(update.get("source_event_id") or "").strip()
    if not story_id or not execution_id or not source_event_id:
        raise ValueError("story update requires story_id, execution_id, and source_event_id")

    event_context = {
        "correlation_id": execution_id,
        "causation_id": source_event_id,
        "session_id": update.get("session_id"),
        "world_occurred_at": update.get("world_occurred_at"),
        "metadata": {
            "producer": "memoria.core.event_executor",
            "source_event_id": source_event_id,
            "source_event_name": update.get("source_event_name"),
        },
    }
    state = _get_story_state_in_transaction(conn, owner_user_id, story_id)
    if state is None:
        started = NewDomainEvent(
            event_id=_event_execution_domain_event_id(
                execution_id,
                "story",
                story_id,
                "story.started.v1",
            ),
            owner_user_id=owner_user_id,
            aggregate_type="story",
            aggregate_id=story_id,
            event_type="story.started.v1",
            payload={"progress": 0.0},
            **event_context,
        )
        state = _append_and_project_story_event_in_transaction(conn, started)

    requested_status = update.get("status")
    if requested_status == "completed":
        event_type = "story.completed.v1"
        payload = {
            "reason": f"event:{source_event_id}",
            "progress": 1.0,
        }
    elif requested_status == "failed":
        event_type = "story.failed.v1"
        payload = {
            "reason": f"event:{source_event_id}",
        }
        if update.get("progress") is not None:
            payload["progress"] = update["progress"]
    else:
        has_progress = (
            update.get("progress") is not None
            or update.get("progress_delta") is not None
        )
        if not has_progress and requested_status not in {"active", "pending"}:
            return state
        event_type = "story.progressed.v1"
        payload = {}
        if update.get("progress") is not None:
            payload["progress"] = update["progress"]
        if update.get("progress_delta") is not None:
            payload["progress_delta"] = update["progress_delta"]

    domain_event = NewDomainEvent(
        event_id=_event_execution_domain_event_id(
            execution_id,
            "story",
            story_id,
            event_type,
        ),
        owner_user_id=owner_user_id,
        aggregate_type="story",
        aggregate_id=story_id,
        event_type=event_type,
        payload=payload,
        **event_context,
    )
    return _append_and_project_story_event_in_transaction(conn, domain_event)


def get_story_state(
    owner_user_id: str,
    story_id: str,
) -> dict | None:
    """在租户边界内读取规范化剧情状态。"""
    with get_conn() as conn:
        return _get_story_state_in_transaction(
            conn,
            owner_user_id,
            story_id,
        )


# =========================
# fact claim projection
# =========================
class FactClaimConcurrencyError(RuntimeError):
    """Fact claim projection version or status changed concurrently."""


def _decode_fact_claim_row(row) -> dict | None:
    if row is None:
        return None
    claim = dict(row)
    for field_name, default in (
        ("provenance", {}),
        ("source_ids", []),
    ):
        raw_value = claim.get(field_name)
        if isinstance(raw_value, str):
            try:
                claim[field_name] = json.loads(raw_value)
            except (TypeError, ValueError):
                claim[field_name] = default
        elif raw_value is None:
            claim[field_name] = default
    return claim


def _get_fact_claim_in_transaction(
    conn,
    owner_user_id: str,
    claim_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT *
        FROM fact_claim
        WHERE owner_user_id = ? AND claim_id = ?
        """,
        (owner_user_id, claim_id),
    ).fetchone()
    return _decode_fact_claim_row(row)


def _begin_fact_claim_write(conn) -> None:
    if isinstance(conn, sqlite3.Connection) and not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _lock_fact_claim_for_write(conn, claim_id: str) -> None:
    if _is_postgres_enabled():
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
            (claim_id,),
        )


def _fact_claim_event_id(event_type: str, *identity_parts: str) -> str:
    identity = "\0".join((event_type, *identity_parts))
    return uuid.uuid5(uuid.NAMESPACE_URL, identity).hex


def _new_fact_claim_event(
    *,
    owner_user_id: str,
    claim_id: str,
    event_type: str,
    payload: dict[str, Any],
    identity_parts: tuple[str, ...] = (),
    event_context: dict[str, Any] | None = None,
) -> NewDomainEvent:
    event_context = event_context or {}
    return NewDomainEvent(
        event_id=_fact_claim_event_id(
            event_type,
            owner_user_id,
            claim_id,
            *identity_parts,
        ),
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=claim_id,
        event_type=event_type,
        payload=payload,
        metadata={
            "producer": "memoria.core.fact_claims",
            **dict(event_context.get("metadata") or {}),
        },
        correlation_id=event_context.get("correlation_id"),
        causation_id=event_context.get("causation_id"),
        session_id=event_context.get("session_id"),
        group_thread_id=event_context.get("group_thread_id"),
        source_turn_id=event_context.get("source_turn_id"),
        source_message_id=event_context.get("source_message_id"),
        world_occurred_at=event_context.get("world_occurred_at"),
    )


def _canonical_fact_claim_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _fact_claim_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    return normalize_evidence_entry({
        "source_kind": payload["source_kind"],
        "source_ids": payload["source_ids"],
        "direct_support": payload["direct_support"],
        "details": dict(payload.get("provenance") or {}),
    })


def _guard_fact_claim_update(cursor, message: str) -> None:
    if cursor.rowcount != 1:
        raise FactClaimConcurrencyError(message)


def _insert_fact_claim_from_event(
    conn,
    event: StoredDomainEvent,
    payload: dict[str, Any],
) -> dict:
    evidence = _fact_claim_evidence(payload)
    encoded_provenance = json.dumps(
        {"evidence": [evidence]},
        ensure_ascii=False,
        allow_nan=False,
    )
    encoded_source_ids = json.dumps(
        evidence["source_ids"],
        ensure_ascii=False,
        allow_nan=False,
    )
    cursor = conn.execute(
        """
        INSERT INTO fact_claim (
            claim_id,
            owner_user_id,
            scope_type,
            scope_id,
            fact_text,
            normalized_fact_text,
            content_hash,
            normalized_content_hash,
            status,
            source_kind,
            provenance,
            source_ids,
            supersedes_claim_id,
            superseded_by_claim_id,
            ledger_version,
            created_at,
            updated_at,
            verified_at,
            retracted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?, NULL, NULL, ?, ?, ?, NULL, NULL)
        ON CONFLICT DO NOTHING
        """,
        (
            payload["claim_id"],
            payload["owner_user_id"],
            payload["scope_type"],
            payload["scope_id"],
            payload["fact_text"],
            payload["normalized_fact_text"],
            payload["content_hash"],
            payload["normalized_content_hash"],
            payload["source_kind"],
            encoded_provenance,
            encoded_source_ids,
            event.aggregate_version,
            event.recorded_at,
            event.recorded_at,
        ),
    )
    if cursor.rowcount == 1:
        return _get_fact_claim_in_transaction(
            conn,
            event.owner_user_id,
            event.aggregate_id,
        )
    concurrent = _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if (
        concurrent is not None
        and concurrent["ledger_version"] >= event.aggregate_version
    ):
        return concurrent
    raise FactClaimConcurrencyError(
        "fact claim initial projection conflict"
    )


def _validate_fact_claim_event(event: StoredDomainEvent) -> dict[str, Any]:
    if not isinstance(event, StoredDomainEvent):
        raise TypeError("fact claim projector requires StoredDomainEvent")
    if event.aggregate_type != "fact_claim":
        raise ValueError("fact claim projector received another aggregate type")
    payload = event.model_dump()["payload"]
    if payload.get("claim_id") != event.aggregate_id:
        raise ValueError("fact claim event payload identity mismatch")
    if payload.get("owner_user_id", event.owner_user_id) != event.owner_user_id:
        raise ValueError("fact claim event tenant identity mismatch")
    if event.event_type == "fact.claimed.v1":
        source_kind = payload.get("source_kind")
        if source_kind not in (
            CLAIM_SOURCE_KINDS | {ADMIN_VERIFICATION_SOURCE_KIND}
        ):
            raise ValueError(
                f"unsupported fact claim source_kind: {source_kind}"
            )
        clean_source_ids(payload.get("source_ids"))
        if not isinstance(payload.get("direct_support"), bool):
            raise ValueError("direct_support must be a boolean")
        if type(payload.get("provenance", {})) is not dict:
            raise ValueError("fact claim provenance must be an object")
        expected_identity = derive_fact_claim_identity(
            event.owner_user_id,
            payload["scope_type"],
            payload["scope_id"],
            payload["fact_text"],
        )
        for field_name in (
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
            "claim_id",
        ):
            if payload[field_name] != expected_identity[field_name]:
                raise ValueError(
                    f"fact claim {field_name} identity mismatch"
                )
    return payload


def _project_fact_claim_event_in_transaction(
    conn,
    event: StoredDomainEvent,
) -> dict:
    payload = _validate_fact_claim_event(event)
    claim = _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )
    if claim is not None and event.aggregate_version <= claim["ledger_version"]:
        return claim
    if claim is None:
        if (
            event.event_type != "fact.claimed.v1"
            or event.aggregate_version != 1
        ):
            raise FactClaimConcurrencyError(
                "fact claim projection version gap before initial event"
            )
        if payload["source_kind"] == ADMIN_VERIFICATION_SOURCE_KIND:
            raise ValueError(
                "admin verification requires an existing fact claim"
            )
        return _insert_fact_claim_from_event(conn, event, payload)
    if event.aggregate_version != claim["ledger_version"] + 1:
        raise FactClaimConcurrencyError(
            "fact claim projection version conflict: "
            f"expected {claim['ledger_version'] + 1}, "
            f"found {event.aggregate_version}"
        )

    if event.event_type == "fact.claimed.v1":
        if claim["status"] in {"retracted", "superseded"}:
            raise FactClaimConcurrencyError(
                "fact claim terminal status rejects evidence"
            )
        identity_fields = (
            "owner_user_id",
            "claim_id",
            "scope_type",
            "scope_id",
            "fact_text",
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
        )
        if any(
            payload[field_name] != claim[field_name]
            for field_name in identity_fields
        ):
            raise ValueError("fact claim evidence identity mismatch")
        evidence_entries = list(
            (claim.get("provenance") or {}).get("evidence") or []
        )
        evidence = _fact_claim_evidence(payload)
        if evidence not in evidence_entries:
            evidence_entries.append(evidence)
        source_ids = sorted({
            source_id
            for item in evidence_entries
            for source_id in item.get("source_ids") or []
        })
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET provenance = ?,
                source_ids = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
            """,
            (
                json.dumps(
                    {"evidence": evidence_entries},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                json.dumps(
                    source_ids,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim evidence projection changed concurrently",
        )
    elif event.event_type == "fact.verified.v1":
        if claim["status"] != "candidate":
            raise FactClaimConcurrencyError(
                "fact claim verification status changed concurrently"
            )
        raw_snapshot = payload["verification_snapshot"]
        if not isinstance(raw_snapshot, dict):
            raise ValueError(
                "fact claim verification_snapshot must be an object"
            )
        snapshot = dict(raw_snapshot)
        evidence_entries = [
            normalize_evidence_entry(item)
            for item in snapshot.get("evidence") or []
        ]
        current_evidence = [
            normalize_evidence_entry(item)
            for item in (
                (claim.get("provenance") or {}).get("evidence") or []
            )
        ]
        if (
            _canonical_fact_claim_json(evidence_entries)
            != _canonical_fact_claim_json(current_evidence)
        ):
            raise ValueError(
                "fact claim verification evidence does not match claimed events"
            )
        decision = evaluate_verification(
            claim["normalized_fact_text"],
            evidence_entries,
        )
        for field_name, expected_value in decision.items():
            if field_name == "source_ids":
                continue
            if (
                _canonical_fact_claim_json(snapshot.get(field_name))
                != _canonical_fact_claim_json(expected_value)
            ):
                raise ValueError(
                    "fact claim verification decision mismatch: "
                    f"{field_name}"
                )
        if not decision["verified"]:
            raise ValueError(
                "fact claim verification policy is not satisfied"
            )
        source_ids = clean_source_ids(snapshot.get("source_ids"))
        if source_ids != decision["source_ids"]:
            raise ValueError(
                "fact claim verification source_ids do not match evidence"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'verified',
                provenance = ?,
                source_ids = ?,
                ledger_version = ?,
                updated_at = ?,
                verified_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status = 'candidate'
            """,
            (
                json.dumps(
                    {"evidence": evidence_entries},
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                json.dumps(
                    source_ids,
                    ensure_ascii=False,
                    allow_nan=False,
                ),
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim verification projection changed concurrently",
        )
    elif event.event_type == "fact.retracted.v1":
        if claim["status"] not in {"candidate", "verified"}:
            raise FactClaimConcurrencyError(
                "fact claim retraction status changed concurrently"
            )
        if claim["supersedes_claim_id"] is not None:
            raise FactClaimConcurrencyError(
                "fact claim replacement cannot be retracted"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'retracted',
                ledger_version = ?,
                updated_at = ?,
                retracted_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND supersedes_claim_id IS NULL
            """,
            (
                event.aggregate_version,
                event.recorded_at,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim retraction projection changed concurrently",
        )
    elif event.event_type == "fact.superseded.v1":
        if claim["status"] not in {"candidate", "verified"}:
            raise FactClaimConcurrencyError(
                "fact claim supersede status changed concurrently"
            )
        replacement_id = payload["superseded_by_claim_id"]
        replacement = _get_fact_claim_in_transaction(
            conn,
            event.owner_user_id,
            replacement_id,
        )
        if replacement is None:
            raise FactClaimConcurrencyError(
                "fact claim replacement projection is missing"
            )
        if (
            claim["scope_type"] != replacement["scope_type"]
            or claim["scope_id"] != replacement["scope_id"]
        ):
            raise ValueError("superseding claims must share a scope")
        if replacement["status"] in {"retracted", "superseded"}:
            raise FactClaimConcurrencyError(
                "fact claim replacement is terminal"
            )
        if (
            replacement["ledger_version"]
            != payload["replacement_ledger_version"]
        ):
            raise FactClaimConcurrencyError(
                "fact claim replacement version conflict"
            )
        if replacement["supersedes_claim_id"] not in {
            None,
            event.aggregate_id,
        }:
            raise FactClaimConcurrencyError(
                "fact claim replacement already supersedes another claim"
            )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET status = 'superseded',
                superseded_by_claim_id = ?,
                ledger_version = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND superseded_by_claim_id IS NULL
            """,
            (
                replacement_id,
                event.aggregate_version,
                event.recorded_at,
                event.owner_user_id,
                event.aggregate_id,
                claim["ledger_version"],
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim supersede projection changed concurrently",
        )
        cursor = conn.execute(
            """
            UPDATE fact_claim
            SET supersedes_claim_id = ?,
                updated_at = ?
            WHERE owner_user_id = ?
              AND claim_id = ?
              AND ledger_version = ?
              AND status IN ('candidate', 'verified')
              AND (
                    supersedes_claim_id IS NULL
                    OR supersedes_claim_id = ?
              )
            """,
            (
                event.aggregate_id,
                event.recorded_at,
                event.owner_user_id,
                replacement_id,
                replacement["ledger_version"],
                event.aggregate_id,
            ),
        )
        _guard_fact_claim_update(
            cursor,
            "fact claim replacement projection changed concurrently",
        )
    else:
        raise ValueError(
            f"unsupported fact claim event type: {event.event_type}"
        )
    return _get_fact_claim_in_transaction(
        conn,
        event.owner_user_id,
        event.aggregate_id,
    )


def _project_fact_claim_event(
    event: StoredDomainEvent,
    *,
    conn=None,
) -> dict:
    if conn is not None:
        return _project_fact_claim_event_in_transaction(conn, event)
    with get_conn() as transaction:
        _begin_fact_claim_write(transaction)
        _lock_fact_claim_for_write(transaction, event.aggregate_id)
        return _project_fact_claim_event_in_transaction(transaction, event)


def _domain_event_major_version(event_type: str) -> int:
    match = re.fullmatch(r".+\.v([1-9][0-9]*)", event_type)
    if match is None:
        raise UnsupportedDomainEventVersionError(
            f"domain event type has no supported major version: {event_type}"
        )
    return int(match.group(1))


def _validate_projector_event_version(event: StoredDomainEvent) -> None:
    major_version = _domain_event_major_version(event.event_type)
    if major_version != 1:
        raise UnsupportedDomainEventVersionError(
            f"unsupported domain event {event.event_type}: "
            f"major version {major_version}"
        )


def _get_projection_checkpoint_in_transaction(
    conn,
    projector_name: str,
    owner_user_id: str,
) -> dict | None:
    row = conn.execute(
        """
        SELECT projector_name, owner_user_id, last_sequence, updated_at
        FROM projection_checkpoint
        WHERE projector_name = ? AND owner_user_id = ?
        """,
        (projector_name, owner_user_id),
    ).fetchone()
    if row is None:
        return None
    checkpoint = dict(row)
    checkpoint["last_sequence"] = int(checkpoint["last_sequence"])
    return checkpoint


def get_projection_checkpoint(
    projector_name: str,
    owner_user_id: str,
) -> dict | None:
    """读取租户内单个投影器的全局序列检查点。"""
    projector_name = str(projector_name or "").strip()
    owner_user_id = str(owner_user_id or "").strip()
    if not projector_name or not owner_user_id:
        raise ValueError("projector_name and owner_user_id must not be blank")
    with get_conn() as conn:
        return _get_projection_checkpoint_in_transaction(
            conn,
            projector_name,
            owner_user_id,
        )


def _save_projection_checkpoint_in_transaction(
    conn,
    projector_name: str,
    owner_user_id: str,
    last_sequence: int,
) -> None:
    conn.execute(
        """
        INSERT INTO projection_checkpoint (
            projector_name,
            owner_user_id,
            last_sequence,
            updated_at
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(projector_name, owner_user_id)
        DO UPDATE SET
            last_sequence=excluded.last_sequence,
            updated_at=excluded.updated_at
        """,
        (
            projector_name,
            owner_user_id,
            int(last_sequence),
            _now(),
        ),
    )


def rebuild_domain_projections(owner_user_id: str) -> dict:
    """从不可变账本原子重建指定租户的事实与剧情投影。"""
    owner_user_id = str(owner_user_id or "").strip()
    if not owner_user_id:
        raise ValueError("owner_user_id must not be blank")

    projectors = {
        "fact_claim": (
            FACT_CLAIM_PROJECTOR,
            _project_fact_claim_event_in_transaction,
        ),
        "story": (
            STORY_STATE_PROJECTOR,
            _project_story_event_in_transaction,
        ),
    }
    progress = {
        projector_name: {
            "processed_events": 0,
            "last_sequence": 0,
        }
        for projector_name, _project in projectors.values()
    }

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM fact_claim WHERE owner_user_id = ?",
            (owner_user_id,),
        )
        conn.execute(
            "DELETE FROM story_state WHERE owner_user_id = ?",
            (owner_user_id,),
        )
        conn.execute(
            """
            DELETE FROM projection_checkpoint
            WHERE owner_user_id = ?
              AND projector_name IN (?, ?)
            """,
            (
                owner_user_id,
                FACT_CLAIM_PROJECTOR,
                STORY_STATE_PROJECTOR,
            ),
        )
        rows = conn.execute(
            """
            SELECT *
            FROM domain_event
            WHERE owner_user_id = ?
            ORDER BY sequence ASC
            """,
            (owner_user_id,),
        ).fetchall()

        for row in rows:
            event = _domain_event_from_row(row)
            projector_spec = projectors.get(event.aggregate_type)
            if projector_spec is None:
                continue
            projector_name, projector = projector_spec
            _validate_projector_event_version(event)
            projector(conn, event)
            progress[projector_name]["processed_events"] += 1
            progress[projector_name]["last_sequence"] = event.sequence

        for projector_name, projector_progress in progress.items():
            _save_projection_checkpoint_in_transaction(
                conn,
                projector_name,
                owner_user_id,
                projector_progress["last_sequence"],
            )

    return {
        "owner_user_id": owner_user_id,
        "projectors": progress,
    }


def _record_fact_claim_in_transaction(
    conn,
    *,
    claim_id: str,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
    normalized_fact_text: str,
    content_hash: str,
    normalized_content_hash: str,
    source_kind: str,
    source_ids: list[str],
    provenance: dict[str, Any],
    direct_support: bool,
    verification_policy: Callable[[list[dict[str, Any]]], dict[str, Any]],
    event_context: dict[str, Any] | None = None,
) -> dict:
    _begin_fact_claim_write(conn)
    _lock_fact_claim_for_write(conn, claim_id)
    existing = _get_fact_claim_in_transaction(
        conn,
        owner_user_id,
        claim_id,
    )
    if (
        existing is not None
        and existing["status"] in {"retracted", "superseded"}
    ):
        raise ValueError("terminal fact claim cannot accept evidence")

    identity = existing or {
        "owner_user_id": owner_user_id,
        "claim_id": claim_id,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "fact_text": fact_text,
        "normalized_fact_text": normalized_fact_text,
        "content_hash": content_hash,
        "normalized_content_hash": normalized_content_hash,
    }
    evidence_payload = {
        "source_kind": source_kind,
        "source_ids": sorted(set(source_ids)),
        "direct_support": bool(direct_support),
        "provenance": provenance,
    }
    claimed_payload = {
        field_name: identity[field_name]
        for field_name in (
            "owner_user_id",
            "claim_id",
            "scope_type",
            "scope_id",
            "fact_text",
            "normalized_fact_text",
            "content_hash",
            "normalized_content_hash",
        )
    }
    claimed_payload.update(evidence_payload)
    evidence_identity = _canonical_fact_claim_json(evidence_payload)
    claimed_event = append_domain_event(
        _new_fact_claim_event(
            owner_user_id=owner_user_id,
            claim_id=claim_id,
            event_type="fact.claimed.v1",
            payload=claimed_payload,
            identity_parts=(evidence_identity,),
            event_context=event_context,
        ),
        expected_version=(
            existing["ledger_version"] if existing is not None else 0
        ),
        conn=conn,
    )
    projected = _project_fact_claim_event_in_transaction(
        conn,
        claimed_event,
    )
    evidence_entries = list(
        (projected.get("provenance") or {}).get("evidence") or []
    )
    decision = verification_policy(evidence_entries)
    if projected["status"] == "candidate" and decision["verified"]:
        snapshot = {
            **decision,
            "evidence": evidence_entries,
            "source_ids": projected["source_ids"],
        }
        verified_event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.verified.v1",
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "reason": "deterministic_policy",
                    "verification_snapshot": snapshot,
                },
                event_context=event_context,
            ),
            expected_version=projected["ledger_version"],
            conn=conn,
        )
        projected = _project_fact_claim_event_in_transaction(
            conn,
            verified_event,
        )
    return projected


def _record_fact_claim(
    *,
    claim_id: str,
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    fact_text: str,
    normalized_fact_text: str,
    content_hash: str,
    normalized_content_hash: str,
    source_kind: str,
    source_ids: list[str],
    provenance: dict[str, Any],
    direct_support: bool,
    verification_policy: Callable[[list[dict[str, Any]]], dict[str, Any]],
) -> dict:
    """Append claim lifecycle events and update the projection atomically."""
    with get_conn() as conn:
        return _record_fact_claim_in_transaction(
            conn,
            claim_id=claim_id,
            owner_user_id=owner_user_id,
            scope_type=scope_type,
            scope_id=scope_id,
            fact_text=fact_text,
            normalized_fact_text=normalized_fact_text,
            content_hash=content_hash,
            normalized_content_hash=normalized_content_hash,
            source_kind=source_kind,
            source_ids=source_ids,
            provenance=provenance,
            direct_support=direct_support,
            verification_policy=verification_policy,
        )


def get_fact_claim(
    owner_user_id: str,
    claim_id: str,
) -> dict | None:
    with get_conn() as conn:
        return _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )


def _retract_fact_claim(
    owner_user_id: str,
    claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        _lock_fact_claim_for_write(conn, claim_id)
        claim = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )
        if claim is None:
            raise KeyError(f"fact claim not found: {claim_id}")
        if claim["supersedes_claim_id"] is not None:
            raise ValueError("fact claim replacement cannot be retracted")
        if claim["status"] == "retracted":
            return claim
        if claim["status"] == "superseded":
            raise ValueError("terminal fact claim cannot be retracted")

        event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.retracted.v1",
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "reason": reason,
                },
            ),
            expected_version=claim["ledger_version"],
            conn=conn,
        )
        return _project_fact_claim_event_in_transaction(conn, event)


def _supersede_fact_claim(
    owner_user_id: str,
    claim_id: str,
    superseded_by_claim_id: str,
    *,
    reason: str | None = None,
) -> dict:
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        for locked_claim_id in sorted((claim_id, superseded_by_claim_id)):
            _lock_fact_claim_for_write(conn, locked_claim_id)
        claim = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            claim_id,
        )
        replacement = _get_fact_claim_in_transaction(
            conn,
            owner_user_id,
            superseded_by_claim_id,
        )
        if claim is None or replacement is None:
            raise KeyError("fact claim or replacement not found")
        if claim["scope_type"] != replacement["scope_type"] or (
            claim["scope_id"] != replacement["scope_id"]
        ):
            raise ValueError("superseding claims must share a scope")
        if (
            claim["status"] == "superseded"
            and claim["superseded_by_claim_id"] == superseded_by_claim_id
        ):
            return claim
        if claim["status"] == "superseded":
            raise ValueError("fact claim replacement cannot be changed")
        if claim["status"] == "retracted":
            raise ValueError("terminal fact claim cannot be superseded")
        if replacement["status"] in {"retracted", "superseded"}:
            raise ValueError("replacement fact claim is terminal")

        event = append_domain_event(
            _new_fact_claim_event(
                owner_user_id=owner_user_id,
                claim_id=claim_id,
                event_type="fact.superseded.v1",
                identity_parts=(superseded_by_claim_id,),
                payload={
                    "owner_user_id": owner_user_id,
                    "claim_id": claim_id,
                    "superseded_by_claim_id": superseded_by_claim_id,
                    "replacement_ledger_version": (
                        replacement["ledger_version"]
                    ),
                    "reason": reason,
                },
            ),
            expected_version=claim["ledger_version"],
            conn=conn,
        )
        return _project_fact_claim_event_in_transaction(conn, event)


def list_fact_claims(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM fact_claim
            WHERE owner_user_id = ?
              AND scope_type = ?
              AND scope_id = ?
            ORDER BY created_at ASC, claim_id ASC
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchall()
    return [_decode_fact_claim_row(row) for row in rows]


def list_verified_fact_claims(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM fact_claim
            WHERE owner_user_id = ?
              AND scope_type = ?
              AND scope_id = ?
              AND status = 'verified'
            ORDER BY created_at ASC, claim_id ASC
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchall()
    return [_decode_fact_claim_row(row) for row in rows]


LONG_TERM_FACT_BACKFILL_MIGRATION = (
    "2026-07-15-long-term-fact-event-backfill"
)


def has_data_migration(migration_key: str) -> bool:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM data_migration
            WHERE migration_key = ?
            """,
            (migration_key,),
        ).fetchone()
    return row is not None


def _legacy_long_term_fact_claim_event(row: dict) -> NewDomainEvent:
    legacy_fact_id = int(row["id"])
    owner_user_id = str(row["player_id"]).strip()
    scope_id = str(row["character_id"]).strip()
    fact_text = str(row["fact_text"])
    identity = derive_fact_claim_identity(
        owner_user_id,
        "character",
        scope_id,
        fact_text,
    )
    source_id = f"long_term_fact:{legacy_fact_id}"
    return NewDomainEvent(
        event_id=f"legacy-long-term-fact-{legacy_fact_id}",
        owner_user_id=owner_user_id,
        aggregate_type="fact_claim",
        aggregate_id=identity["claim_id"],
        event_type="fact.claimed.v1",
        payload={
            "owner_user_id": owner_user_id,
            "claim_id": identity["claim_id"],
            "scope_type": "character",
            "scope_id": scope_id,
            "fact_text": fact_text,
            "normalized_fact_text": identity["normalized_fact_text"],
            "content_hash": identity["content_hash"],
            "normalized_content_hash": identity["normalized_content_hash"],
            "source_kind": "legacy",
            "source_ids": [source_id],
            "provenance": {
                "legacy_backfill": True,
                "legacy_fact_id": legacy_fact_id,
                "importance": row.get("importance"),
                "created_at": row.get("created_at"),
                "last_referenced": row.get("last_referenced"),
            },
            "direct_support": False,
        },
        metadata={
            "producer": "memoria.db.repository",
            "legacy_backfill": True,
            "legacy_fact_id": legacy_fact_id,
        },
    )


def backfill_legacy_long_term_fact_events() -> dict:
    """Backfill legacy facts into candidate claim events without deleting sources."""
    with get_conn() as conn:
        _begin_fact_claim_write(conn)
        existing = conn.execute(
            """
            SELECT metadata, applied_at
            FROM data_migration
            WHERE migration_key = ?
            """,
            (LONG_TERM_FACT_BACKFILL_MIGRATION,),
        ).fetchone()
        if existing is not None:
            metadata = json.loads(existing["metadata"])
            return {
                **metadata,
                "applied_at": existing["applied_at"],
                "already_applied": True,
            }

        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, character_id, player_id, fact_text, importance,
                       created_at, last_referenced
                FROM long_term_fact
                ORDER BY id ASC
                """
            ).fetchall()
        ]
        for row in rows:
            stored_event = append_domain_event(
                _legacy_long_term_fact_claim_event(row),
                conn=conn,
            )
            _project_fact_claim_event_in_transaction(
                conn,
                stored_event,
            )

        applied_at = _now()
        metadata = {
            "legacy_fact_count": len(rows),
            "event_count": len(rows),
        }
        conn.execute(
            """
            INSERT INTO data_migration (migration_key, metadata, applied_at)
            VALUES (?, ?, ?)
            """,
            (
                LONG_TERM_FACT_BACKFILL_MIGRATION,
                json.dumps(metadata, ensure_ascii=False, allow_nan=False),
                applied_at,
            ),
        )
        return {
            **metadata,
            "applied_at": applied_at,
            "already_applied": False,
        }


# =========================
# player world clock
# =========================
def get_or_create_player_world_clock(
    player_id: str,
    timezone_name: str,
    real_now_iso: str,
) -> dict:
    """Return a player's clock row, creating a real-time 1x clock if absent."""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO player_world_clock
            (player_id, timezone, timezone_mode, anchor_real_utc, anchor_world_utc,
             time_scale, clock_revision, updated_at)
            VALUES (?, ?, 'fixed', ?, ?, 1, 1, ?)
            ON CONFLICT(player_id) DO NOTHING
            """,
            (player_id, timezone_name, real_now_iso, real_now_iso, real_now_iso),
        )
        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return dict(row)


def get_player_world_clock(player_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return _row_to_dict(row)


class ClockRevisionConflictError(RuntimeError):
    pass


class ClockScheduleBusyError(RuntimeError):
    pass


def update_player_world_clock_and_schedules(
    *,
    player_id: str,
    expected_revision: int,
    timezone_name: str,
    timezone_mode: str,
    anchor_real_utc: str,
    anchor_world_utc: str,
    time_scale: int,
    updated_at: str,
    resolve_schedule: Callable[[dict], tuple[str | None, str | None]],
) -> dict:
    """Atomically update a clock and all active schedules derived from it."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_world_clock
            SET timezone = ?, timezone_mode = ?, anchor_real_utc = ?,
                anchor_world_utc = ?, time_scale = ?,
                clock_revision = clock_revision + 1, updated_at = ?
            WHERE player_id = ? AND clock_revision = ?
            """,
            (
                timezone_name,
                timezone_mode,
                anchor_real_utc,
                anchor_world_utc,
                time_scale,
                updated_at,
                player_id,
                expected_revision,
            ),
        )
        if cursor.rowcount != 1:
            raise ClockRevisionConflictError("world clock revision is stale")

        schedules = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE player_id = ? AND status = 'active'
              AND next_run_at IS NOT NULL
            """,
            (player_id,),
        ).fetchall()
        for raw_schedule in schedules:
            schedule = dict(raw_schedule)
            lease_expires_at = schedule.get("lease_expires_at")
            if lease_expires_at and lease_expires_at > updated_at:
                raise ClockScheduleBusyError("a scheduled event is currently executing")
            next_run_at, next_due_real_at = resolve_schedule(schedule)
            conn.execute(
                """
                UPDATE event_schedule_state
                SET next_run_at = ?, next_due_real_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (
                    next_run_at,
                    next_due_real_at,
                    updated_at,
                    schedule["event_id"],
                    schedule["character_id"],
                    player_id,
                ),
            )

        row = conn.execute(
            "SELECT * FROM player_world_clock WHERE player_id = ?",
            (player_id,),
        ).fetchone()
    return dict(row)


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
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO character_card
                (owner_user_id, character_id, card_data, version, name, display_name,
                 avatar_url, avatar_revision, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(owner_user_id, character_id)
                DO UPDATE SET
                    card_data=excluded.card_data,
                    version=excluded.version,
                    name=excluded.name,
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    avatar_revision=excluded.avatar_revision,
                    updated_at=excluded.updated_at
                """,
                (
                    owner_user_id,
                    character_id,
                    card_data_json,
                    version,
                    name,
                    display_name,
                    avatar_url,
                    avatar_revision,
                    now,
                    now,
                    source,
                ),
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
        with get_conn() as conn:
            if _is_postgres_enabled():
                row = conn.execute(
                    """
                    SELECT card_data
                    FROM character_card
                    WHERE owner_user_id = ? AND character_id = ?
                    FOR UPDATE
                    """,
                    (owner_user_id, character_id),
                ).fetchone()
            else:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    """
                    SELECT card_data
                    FROM character_card
                    WHERE owner_user_id = ? AND character_id = ?
                    """,
                    (owner_user_id, character_id),
                ).fetchone()
            if row is None:
                return False

            card_data = json.loads(row["card_data"])
            voice = card_data.get("voice")
            if not isinstance(voice, dict):
                voice = {}
                card_data["voice"] = voice
            voice.update(updates)
            conn.execute(
                """
                UPDATE character_card
                SET card_data = ?, updated_at = ?
                WHERE owner_user_id = ? AND character_id = ?
                """,
                (
                    json.dumps(card_data, ensure_ascii=False),
                    _now(),
                    owner_user_id,
                    character_id,
                ),
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
    with get_conn() as conn:
        if include_inactive:
            row = conn.execute(
                "SELECT * FROM character_card WHERE owner_user_id = ? AND character_id = ?",
                (owner_user_id, character_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM character_card
                WHERE owner_user_id = ? AND character_id = ? AND is_active = 1
                """,
                (owner_user_id, character_id),
            ).fetchone()
    
    return _row_to_dict(row)


def is_character_card_active(owner_user_id: str, character_id: str) -> bool:
    """返回角色卡是否存在且启用。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT is_active FROM character_card WHERE owner_user_id = ? AND character_id = ?",
            (owner_user_id, character_id),
        ).fetchone()

    if not row:
        return False
    data = _row_to_dict(row) or {}
    return bool(data.get("is_active"))



def update_character_avatar(owner_user_id: str, character_id: str, avatar_url: str | None) -> bool:
    """更新角色头像 URL"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE character_card
                SET avatar_url = ?, avatar_revision = NULL, updated_at = ?
                WHERE owner_user_id = ? AND character_id = ?
                """,
                (avatar_url, _now(), owner_user_id, character_id),
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
        with get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE character_card
                SET avatar_url = ?, avatar_revision = NULL, updated_at = ?
                WHERE owner_user_id = ?
                  AND character_id = ?
                  AND avatar_url = ?
                  AND avatar_revision = ?
                """,
                (
                    avatar_url,
                    _now(),
                    owner_user_id,
                    character_id,
                    expected_avatar_url,
                    expected_revision,
                ),
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
    with get_conn() as conn:
        query = """
            SELECT character_id, name, display_name, version, avatar_url, created_at, updated_at, is_active, source
            FROM character_card
            WHERE owner_user_id = ?
        """
        params = [owner_user_id]
        if only_active:
            query += " AND is_active = 1"
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
    
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
        with get_conn() as conn:
            if soft_delete:
                # 软删除：标记为不活跃
                conn.execute(
                    """
                    UPDATE character_card
                    SET is_active = 0, updated_at = ?
                    WHERE owner_user_id = ? AND character_id = ?
                    """,
                    (_now(), owner_user_id, character_id),
                )
            else:
                # 硬删除：关系和角色卡必须在同一事务内删除。
                rows = conn.execute(
                    """
                    SELECT character_id_a, character_id_b
                    FROM character_relationship
                    WHERE owner_user_id = ?
                      AND (character_id_a = ? OR character_id_b = ?)
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
                        now,
                    )
                conn.execute(
                    """
                    DELETE FROM character_relationship
                    WHERE owner_user_id = ?
                      AND (character_id_a = ? OR character_id_b = ?)
                    """,
                    (owner_user_id, character_id, character_id),
                )
                conn.execute(
                    "DELETE FROM character_card WHERE owner_user_id = ? AND character_id = ?",
                    (owner_user_id, character_id),
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
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE character_card
                SET is_active = 1, updated_at = ?
                WHERE owner_user_id = ? AND character_id = ?
                """,
                (_now(), owner_user_id, character_id),
            )
        logger.info(f"角色卡已激活: owner={owner_user_id}, character_id={character_id}")
        return True
    except Exception as e:
        logger.error(f"激活角色卡失败: {e}")
        return False


# =========================
# 事件系统 - 事件定义
# =========================
def _save_event_definition_in_transaction(
    conn,
    *,
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO event_definition
        (owner_user_id, event_id, event_name, description, character_id, story_id, trigger_config,
         effects_config, priority, exclusive_group, exclusive_scope, max_triggers_per_turn,
         stop_processing, is_active, created_at, updated_at, schedule, template_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(owner_user_id, event_id)
        DO UPDATE SET
            event_name=excluded.event_name,
            description=excluded.description,
            character_id=excluded.character_id,
            story_id=excluded.story_id,
            trigger_config=excluded.trigger_config,
            effects_config=excluded.effects_config,
            priority=excluded.priority,
            exclusive_group=excluded.exclusive_group,
            exclusive_scope=excluded.exclusive_scope,
            max_triggers_per_turn=excluded.max_triggers_per_turn,
            stop_processing=excluded.stop_processing,
            is_active=excluded.is_active,
            updated_at=excluded.updated_at,
            schedule=excluded.schedule,
            template_id=excluded.template_id
        """,
        (
            owner_user_id,
            event_id,
            event_name,
            description,
            character_id,
            story_id,
            trigger_config,
            effects_config,
            priority,
            exclusive_group,
            exclusive_scope,
            max_triggers_per_turn,
            1 if stop_processing else 0,
            1 if is_active else 0,
            now,
            now,
            schedule,
            template_id,
        ),
    )
    if exclusive_scope == "player" and exclusive_group:
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
              AND exclusive_group <> ?
            """,
            (owner_user_id, event_id, exclusive_group),
        )
    else:
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
            """,
            (owner_user_id, event_id),
        )


def save_event_definition(
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> bool:
    """保存事件定义"""
    try:
        with get_conn() as conn:
            _save_event_definition_in_transaction(
                conn,
                owner_user_id=owner_user_id,
                event_id=event_id,
                event_name=event_name,
                trigger_config=trigger_config,
                effects_config=effects_config,
                character_id=character_id,
                description=description,
                priority=priority,
                exclusive_group=exclusive_group,
                exclusive_scope=exclusive_scope,
                max_triggers_per_turn=max_triggers_per_turn,
                stop_processing=stop_processing,
                is_active=is_active,
                schedule=schedule,
                template_id=template_id,
                story_id=story_id,
            )
        return True
    except Exception as e:
        logger.error(f"保存事件定义失败: {e}")
        return False

def get_event_definition(owner_user_id: str, event_id: str) -> dict | None:
    """获取单个事件定义"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM event_definition WHERE owner_user_id = ? AND event_id = ?",
            (owner_user_id, event_id),
        ).fetchone()
    return _row_to_dict(row)

def list_event_definitions(
    owner_user_id: str,
    character_id: str = None,
    only_active: bool = True
) -> list[dict]:
    """列出事件定义"""
    with get_conn() as conn:
        query = "SELECT * FROM event_definition WHERE owner_user_id = ?"
        params = [owner_user_id]

        if character_id is not None:
            query += " AND (character_id = ? OR character_id IS NULL)"
            params.append(character_id)

        if only_active:
            query += " AND is_active = 1"

        query += " ORDER BY priority DESC, created_at DESC"

        rows = conn.execute(query, params).fetchall()

    return [dict(r) for r in rows]

def delete_event_definition(owner_user_id: str, event_id: str) -> bool:
    """Delete an event definition and its operational trigger state."""
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM event_schedule_state WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_context_state WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_trigger_log WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                "DELETE FROM event_trigger_guard WHERE player_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
            conn.execute(
                """
                DELETE FROM event_exclusive_group_guard
                WHERE player_id = ? AND selected_event_id = ?
                """,
                (owner_user_id, event_id),
            )
            deleted = conn.execute(
                "DELETE FROM event_definition WHERE owner_user_id = ? AND event_id = ?",
                (owner_user_id, event_id),
            )
        return deleted.rowcount == 1
    except Exception as e:
        logger.error(f"删除事件定义失败: {e}")
        return False

def increment_event_trigger_count(owner_user_id: str, event_id: str):
    """增加事件触发计数"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE event_definition
            SET trigger_count = trigger_count + 1,
                last_triggered_at = ?
            WHERE owner_user_id = ? AND event_id = ?
            """,
            (_now(), owner_user_id, event_id),
        )


# =========================
# 事件系统 - 触发记录
# =========================
def log_event_trigger(
    event_id: str,
    character_id: str,
    player_id: str,
    session_id: str,
    context_snapshot: str,
    effects_applied: str
):
    """记录事件触发"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO event_trigger_log
            (event_id, character_id, player_id, session_id, 
             triggered_at, context_snapshot, effects_applied)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (event_id, character_id, player_id, session_id,
             _now(), context_snapshot, effects_applied),
        )

def get_event_trigger_history(
    event_id: str = None,
    character_id: str = None,
    player_id: str = None,
    limit: int = 50
) -> list[dict]:
    """获取事件触发历史"""
    with get_conn() as conn:
        query = "SELECT * FROM event_trigger_log WHERE 1=1"
        params = []
        
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        
        query += " ORDER BY triggered_at DESC LIMIT ?"
        params.append(limit)
        
        rows = conn.execute(query, params).fetchall()
    
    return [dict(r) for r in rows]

def get_last_trigger_time(event_id: str, character_id: str | None, player_id: str) -> str | None:
    """获取事件最后触发时间（用于冷却时间判断）"""
    with get_conn() as conn:
        if character_id is None:
            row = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = ? AND player_id = ? AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (event_id, player_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (event_id, character_id, player_id),
            ).fetchone()

    return row["triggered_at"] if row else None


def claim_event_trigger_guard(
    *,
    player_id: str,
    event_id: str,
    character_scope: str,
    cooldown_hours: int,
    claim_token: str,
    claimed_at: str,
    claim_expires_at: str,
) -> bool:
    """领取 once/cooldown 事件的持久化触发权。"""
    scope = character_scope or ""
    with get_conn() as conn:
        if scope:
            legacy = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = ? AND event_id = ? AND character_id = ?
                  AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (player_id, event_id, scope),
            ).fetchone()
        else:
            legacy = conn.execute(
                """
                SELECT triggered_at FROM event_trigger_log
                WHERE player_id = ? AND event_id = ? AND status = 'succeeded'
                ORDER BY triggered_at DESC
                LIMIT 1
                """,
                (player_id, event_id),
            ).fetchone()
        legacy_last_triggered_at = legacy["triggered_at"] if legacy else None
        conn.execute(
            """
            INSERT INTO event_trigger_guard
            (player_id, event_id, character_scope, last_triggered_at,
             claim_token, claim_expires_at, updated_at)
            VALUES (?, ?, ?, ?, NULL, NULL, ?)
            ON CONFLICT(player_id, event_id, character_scope) DO NOTHING
            """,
            (
                player_id,
                event_id,
                scope,
                legacy_last_triggered_at,
                claimed_at,
            ),
        )
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(
            """
            SELECT last_triggered_at, claim_token, claim_expires_at
            FROM event_trigger_guard
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
            """ + lock_suffix,
            (player_id, event_id, scope),
        ).fetchone()
        last_triggered_at = row["last_triggered_at"] or legacy_last_triggered_at
        if not row["last_triggered_at"] and legacy_last_triggered_at:
            conn.execute(
                """
                UPDATE event_trigger_guard
                SET last_triggered_at = ?, updated_at = ?
                WHERE player_id = ? AND event_id = ? AND character_scope = ?
                """,
                (
                    legacy_last_triggered_at,
                    claimed_at,
                    player_id,
                    event_id,
                    scope,
                ),
            )

        claimed_time = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
        if claimed_time.tzinfo is None:
            claimed_time = claimed_time.replace(tzinfo=timezone.utc)
        if last_triggered_at:
            last_time = datetime.fromisoformat(
                last_triggered_at.replace("Z", "+00:00")
            )
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=timezone.utc)
            if cooldown_hours == 0:
                return False
            if claimed_time - last_time < timedelta(hours=cooldown_hours):
                return False

        existing_claim = row["claim_token"]
        existing_expiry = row["claim_expires_at"]
        if existing_claim and existing_claim != claim_token and existing_expiry:
            expires_at = datetime.fromisoformat(existing_expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > claimed_time:
                return False

        cursor = conn.execute(
            """
            UPDATE event_trigger_guard
            SET claim_token = ?, claim_expires_at = ?, updated_at = ?
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
            """,
            (
                claim_token,
                claim_expires_at,
                claimed_at,
                player_id,
                event_id,
                scope,
            ),
        )
        return cursor.rowcount == 1


def release_event_trigger_guard(
    *,
    player_id: str,
    event_id: str,
    character_scope: str,
    claim_token: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_trigger_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
            WHERE player_id = ? AND event_id = ? AND character_scope = ?
              AND claim_token = ?
            """,
            (_now(), player_id, event_id, character_scope or "", claim_token),
        )
    return cursor.rowcount == 1


def claim_event_exclusive_group(
    *,
    player_id: str,
    exclusive_group: str,
    claim_token: str,
    claimed_at: str,
    claim_expires_at: str,
) -> bool:
    """Claim a player-scoped exclusive group unless it is already selected."""
    with get_conn() as conn:
        if not _is_postgres_enabled():
            conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO event_exclusive_group_guard
            (player_id, exclusive_group, selected_event_id, claim_token,
             claim_expires_at, updated_at)
            VALUES (?, ?, NULL, NULL, NULL, ?)
            ON CONFLICT(player_id, exclusive_group) DO NOTHING
            """,
            (player_id, exclusive_group, claimed_at),
        )
        lock_suffix = " FOR UPDATE" if _is_postgres_enabled() else ""
        row = conn.execute(
            """
            SELECT selected_event_id, claim_token, claim_expires_at
            FROM event_exclusive_group_guard
            WHERE player_id = ? AND exclusive_group = ?
            """ + lock_suffix,
            (player_id, exclusive_group),
        ).fetchone()
        if row["selected_event_id"]:
            return False

        legacy_selection = conn.execute(
            """
            SELECT trigger_log.event_id
            FROM event_trigger_log AS trigger_log
            INNER JOIN event_definition AS definition
              ON definition.owner_user_id = trigger_log.player_id
             AND definition.event_id = trigger_log.event_id
            WHERE trigger_log.player_id = ?
              AND trigger_log.status = 'succeeded'
              AND definition.exclusive_group = ?
              AND definition.exclusive_scope = 'player'
            ORDER BY
              CASE WHEN trigger_log.triggered_at IS NULL THEN 1 ELSE 0 END,
              trigger_log.triggered_at ASC,
              trigger_log.id ASC
            LIMIT 1
            """,
            (player_id, exclusive_group),
        ).fetchone()
        if legacy_selection:
            conn.execute(
                """
                UPDATE event_exclusive_group_guard
                SET selected_event_id = ?, claim_token = NULL,
                    claim_expires_at = NULL, updated_at = ?
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (
                    legacy_selection["event_id"],
                    claimed_at,
                    player_id,
                    exclusive_group,
                ),
            )
            return False

        claimed_time = datetime.fromisoformat(claimed_at.replace("Z", "+00:00"))
        if claimed_time.tzinfo is None:
            claimed_time = claimed_time.replace(tzinfo=timezone.utc)
        existing_claim = row["claim_token"]
        existing_expiry = row["claim_expires_at"]
        if existing_claim and existing_claim != claim_token and existing_expiry:
            expires_at = datetime.fromisoformat(existing_expiry.replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at > claimed_time:
                return False

        cursor = conn.execute(
            """
            UPDATE event_exclusive_group_guard
            SET claim_token = ?, claim_expires_at = ?, updated_at = ?
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NULL
            """,
            (
                claim_token,
                claim_expires_at,
                claimed_at,
                player_id,
                exclusive_group,
            ),
        )
        return cursor.rowcount == 1


def release_event_exclusive_group(
    *,
    player_id: str,
    exclusive_group: str,
    claim_token: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_exclusive_group_guard
            SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NULL AND claim_token = ?
            """,
            (_now(), player_id, exclusive_group, claim_token),
        )
    return cursor.rowcount == 1


def get_event_exclusive_group_selection(
    player_id: str,
    exclusive_group: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_exclusive_group_guard
            WHERE player_id = ? AND exclusive_group = ?
              AND selected_event_id IS NOT NULL
            """,
            (player_id, exclusive_group),
        ).fetchone()
    return _row_to_dict(row)


def get_event_execution_batch(player_id: str, execution_key: str) -> dict | None:
    """读取已完成的事件批次，用于请求重放。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_execution_batch
            WHERE player_id = ? AND execution_key = ?
            """,
            (player_id, execution_key),
        ).fetchone()
    return _row_to_dict(row)


def increment_event_execution_batch_deduplicated(
    player_id: str,
    execution_key: str,
) -> bool:
    """记录一次命中已完成批次的幂等重放。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_execution_batch
            SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
            WHERE player_id = ? AND execution_key = ?
            """,
            (player_id, execution_key),
        )
    return cursor.rowcount == 1


def get_event_execution(
    owner_user_id: str,
    event_id: str,
    execution_key: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_execution
            WHERE owner_user_id = ? AND event_id = ? AND execution_key = ?
            """,
            (owner_user_id, event_id, execution_key),
        ).fetchone()
    return _row_to_dict(row)


def list_event_execution_history(
    owner_user_id: str,
    character_id: str | None = None,
    event_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Return recent auditable event outcomes for condition evaluation."""
    with get_conn() as conn:
        query = """
            SELECT execution_id, execution_key, event_id, character_id,
                   session_id, trigger_source, status, error, duration_ms,
                   created_at, completed_at
            FROM event_execution
            WHERE owner_user_id = ?
        """
        params: list[Any] = [owner_user_id]
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        query += " ORDER BY completed_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def _insert_long_term_fact_in_transaction(conn, memory: dict) -> dict | None:
    fact_text = normalize_long_term_fact_text(memory.get("fact_text"))
    if not fact_text:
        return None
    character_id = memory["character_id"]
    player_id = memory["player_id"]
    importance = int(memory.get("importance") or 5)
    existing = _dedup_check(
        conn,
        "long_term_fact",
        "fact_text",
        fact_text,
        "character_id = ? AND player_id = ?",
        (character_id, player_id),
        threshold=0.75,
    )
    now = _now()
    if existing:
        conn.execute(
            "UPDATE long_term_fact SET importance = ?, last_referenced = ? WHERE id = ?",
            (max(existing.get("importance", 0), importance), now, existing["id"]),
        )
        return None

    insert_sql = """
        INSERT INTO long_term_fact
        (character_id, player_id, fact_text, importance, created_at, last_referenced)
        VALUES (?, ?, ?, ?, ?, ?)
    """
    if _is_postgres_enabled():
        insert_sql += " RETURNING id"
    cursor = conn.execute(
        insert_sql,
        (character_id, player_id, fact_text, importance, now, now),
    )
    fact_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
    return {
        "fact_id": fact_id,
        "character_id": character_id,
        "player_id": player_id,
        "fact_text": fact_text,
        "importance": importance,
    }


def _complete_event_schedule_in_transaction(
    conn,
    *,
    player_id: str,
    schedule_completion: dict,
    now: str,
) -> None:
    completed = conn.execute(
        """
        UPDATE event_schedule_state
        SET last_checked_at = ?, last_run_at = ?, next_run_at = ?,
            next_due_real_at = ?, missed_count = ?,
            lease_owner = NULL, lease_expires_at = NULL,
            last_error = NULL, last_failed_at = NULL, updated_at = ?
        WHERE event_id = ? AND character_id = ? AND player_id = ?
          AND lease_owner = ?
        """,
        (
            schedule_completion["last_checked_at"],
            schedule_completion["last_run_at"],
            schedule_completion["next_run_at"],
            schedule_completion.get("next_due_real_at"),
            int(schedule_completion.get("missed_count") or 0),
            now,
            schedule_completion["event_id"],
            schedule_completion["character_id"],
            player_id,
            schedule_completion["lease_owner"],
        ),
    )
    if completed.rowcount != 1:
        raise RuntimeError("schedule lease was lost before atomic completion")


class DialogueTurnConflictError(RuntimeError):
    """A session already has an active dialogue turn."""


def claim_dialogue_turn(
    *,
    session_id: str,
    request_id: str,
    player_id: str,
    turn_kind: str,
    lease_seconds: int = 240,
) -> dict:
    """Claim one idempotent turn, or return its completed response."""
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    lease_owner = uuid.uuid4().hex
    lease_expires_at = (now + timedelta(seconds=max(30, lease_seconds))).isoformat()
    with get_conn() as conn:
        if _is_postgres_enabled():
            conn.execute(
                "SELECT session_id FROM session WHERE session_id = ? FOR UPDATE",
                (session_id,),
            ).fetchone()
        else:
            conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            """
            SELECT * FROM dialogue_turn
            WHERE session_id = ? AND request_id = ?
            """,
            (session_id, request_id),
        ).fetchone()
        if existing and existing["status"] == "completed":
            return {
                "completed": True,
                "response": json.loads(existing["response_data"]),
            }
        if existing and (
            existing["player_id"] != player_id
            or existing["turn_kind"] != turn_kind
        ):
            raise DialogueTurnConflictError("request_id 已用于其他对话请求")
        if (
            existing
            and existing["status"] == "processing"
            and existing["lease_expires_at"]
            and existing["lease_expires_at"] > now_iso
        ):
            raise DialogueTurnConflictError("该请求正在处理中")

        active = conn.execute(
            """
            SELECT request_id
            FROM dialogue_turn
            WHERE session_id = ? AND status = 'processing'
              AND lease_expires_at > ? AND request_id <> ?
            LIMIT 1
            """,
            (session_id, now_iso, request_id),
        ).fetchone()
        if active:
            raise DialogueTurnConflictError("该会话已有消息正在处理中")

        conn.execute(
            """
            INSERT INTO dialogue_turn
            (session_id, request_id, player_id, turn_kind, status,
             lease_owner, lease_expires_at, response_data, error,
             created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, 'processing', ?, ?, NULL, NULL, ?, ?, NULL)
            ON CONFLICT(session_id, request_id)
            DO UPDATE SET
                status='processing',
                lease_owner=excluded.lease_owner,
                lease_expires_at=excluded.lease_expires_at,
                response_data=NULL,
                error=NULL,
                updated_at=excluded.updated_at,
                completed_at=NULL
            """,
            (
                session_id,
                request_id,
                player_id,
                turn_kind,
                lease_owner,
                lease_expires_at,
                now_iso,
                now_iso,
            ),
        )
    return {
        "completed": False,
        "lease_owner": lease_owner,
        "request_id": request_id,
    }


def fail_dialogue_turn(
    session_id: str,
    request_id: str,
    lease_owner: str,
    error: str,
) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE dialogue_turn
            SET status = 'failed', lease_owner = NULL, lease_expires_at = NULL,
                error = ?, updated_at = ?
            WHERE session_id = ? AND request_id = ?
              AND status = 'processing' AND lease_owner = ?
            """,
            (error[:1000], _now(), session_id, request_id, lease_owner),
        )


def _save_runtime_states_in_transaction(
    conn,
    *,
    player_id: str,
    runtime_states: list[dict] | None,
    now: str,
) -> None:
    for state in runtime_states or []:
        _save_runtime_state_in_transaction(
            conn,
            character_id=state["character_id"],
            player_id=player_id,
            affection_level=state["affection_level"],
            trust_level=state["trust_level"],
            current_mood=state["current_mood"],
            now=now,
            insert_only=bool(state.get("insert_only")),
            state_changes=state.get("state_changes"),
        )


def _save_runtime_state_in_transaction(
    conn,
    *,
    character_id: str,
    player_id: str,
    affection_level: float,
    trust_level: float,
    current_mood: str,
    now: str,
    insert_only: bool = False,
    state_changes: list[dict] | None = None,
) -> None:
    if state_changes:
        conn.execute(
            """
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id, player_id) DO NOTHING
            """,
            (
                character_id,
                player_id,
                affection_level,
                trust_level,
                current_mood,
                now,
            ),
        )
        for changes in state_changes:
            assignments: list[str] = []
            parameters: list[Any] = []
            if "affection_level" in changes:
                delta = float(changes["affection_level"])
                assignments.append(
                    """
                    affection_level = CASE
                        WHEN affection_level + ? < -100 THEN -100
                        WHEN affection_level + ? > 100 THEN 100
                        ELSE affection_level + ?
                    END
                    """
                )
                parameters.extend([delta, delta, delta])
            if "trust_level" in changes:
                delta = float(changes["trust_level"])
                assignments.append(
                    """
                    trust_level = CASE
                        WHEN trust_level + ? < 0 THEN 0
                        WHEN trust_level + ? > 100 THEN 100
                        ELSE trust_level + ?
                    END
                    """
                )
                parameters.extend([delta, delta, delta])
            if "current_mood" in changes:
                assignments.append("current_mood = ?")
                parameters.append(str(changes["current_mood"]))
            if not assignments:
                continue
            parameters.extend([now, character_id, player_id])
            conn.execute(
                f"""
                UPDATE relationship_state
                SET {", ".join(assignments)}, updated_at = ?
                WHERE character_id = ? AND player_id = ?
                """,
                parameters,
            )
        row = conn.execute(
            """
            SELECT affection_level, trust_level, current_mood
            FROM relationship_state
            WHERE character_id = ? AND player_id = ?
            """,
            (character_id, player_id),
        ).fetchone()
        affection_level = row["affection_level"]
        trust_level = row["trust_level"]
        current_mood = row["current_mood"]
    else:
        relationship_state_conflict = (
            "DO NOTHING"
            if insert_only
            else """
            DO UPDATE SET
                affection_level=excluded.affection_level,
                trust_level=excluded.trust_level,
                current_mood=excluded.current_mood,
                updated_at=excluded.updated_at
            """
        )
        conn.execute(
            f"""
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level,
             current_mood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id, player_id)
            {relationship_state_conflict}
            """,
            (
                character_id,
                player_id,
                affection_level,
                trust_level,
                current_mood,
                now,
            ),
        )
    player_id_node, character_id_node = _normalize_relationship_pair(
        player_node_id(player_id),
        character_id,
    )
    relationship_conflict = (
        "DO NOTHING"
        if insert_only
        else """
        DO UPDATE SET
            affinity=excluded.affinity,
            updated_at=excluded.updated_at
        """
    )
    conn.execute(
        f"""
        INSERT INTO character_relationship
        (owner_user_id, character_id_a, character_id_b, relationship_type,
         affinity, description, created_at, updated_at)
        VALUES (?, ?, ?, '相识', ?, NULL, ?, ?)
        ON CONFLICT(owner_user_id, character_id_a, character_id_b)
        {relationship_conflict}
        """,
        (
            player_id,
            player_id_node,
            character_id_node,
            affection_level,
            now,
            now,
        ),
    )


def _commit_dialogue_turn_in_transaction(
    conn,
    dialogue_turn: dict,
    *,
    now: str,
) -> dict | list:
    session_id = dialogue_turn["session_id"]
    request_id = dialogue_turn["request_id"]
    lease_owner = dialogue_turn["lease_owner"]
    row = conn.execute(
        """
        SELECT status, lease_owner, lease_expires_at, response_data
        FROM dialogue_turn
        WHERE session_id = ? AND request_id = ?
        """,
        (session_id, request_id),
    ).fetchone()
    if not row:
        raise RuntimeError("dialogue turn claim does not exist")
    if row["status"] == "completed":
        return json.loads(row["response_data"])
    if (
        row["status"] != "processing"
        or row["lease_owner"] != lease_owner
        or not row["lease_expires_at"]
        or row["lease_expires_at"] <= now
    ):
        raise DialogueTurnConflictError("对话轮次租约已失效")

    response = dialogue_turn["response"]
    temporary_ids: dict[int, int] = {}
    for message in dialogue_turn.get("messages") or []:
        reply_to_message_id = message.get("reply_to_message_id")
        if isinstance(reply_to_message_id, int) and reply_to_message_id < 0:
            reply_to_message_id = temporary_ids.get(reply_to_message_id)
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, character_id, character_name,
             action, affinity_delta, trust_delta, current_affinity,
             current_trust, current_mood, event_notification,
             knowledge_sources, reply_to_message_id, reply_to_character_id,
             intent, topic, trigger_source, created_at, world_created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if _is_postgres_enabled():
            insert_sql += " RETURNING id"
        cursor = conn.execute(
            insert_sql,
            (
                session_id,
                message["role"],
                message["content"],
                message.get("character_id"),
                message.get("character_name"),
                message.get("action"),
                message.get("affinity_delta"),
                message.get("trust_delta"),
                message.get("current_affinity"),
                message.get("current_trust"),
                message.get("current_mood"),
                message.get("event_notification"),
                _encode_knowledge_sources(message.get("knowledge_sources")),
                reply_to_message_id,
                message.get("reply_to_character_id"),
                message.get("intent"),
                message.get("topic"),
                message.get("trigger_source"),
                now,
                message.get("world_created_at"),
            ),
        )
        message_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
        temporary_id = message.get("temporary_id")
        if isinstance(temporary_id, int):
            temporary_ids[temporary_id] = message_id
        response_field = message.get("response_field")
        response_index = message.get("response_index")
        if response_field and response_index is None and isinstance(response, dict):
            response[response_field] = message_id
        elif (
            response_field
            and isinstance(response_index, int)
            and isinstance(response, list)
            and response_index < len(response)
        ):
            response[response_index][response_field] = message_id
        if message.get("character_id"):
            conn.execute(
                """
                UPDATE multi_session_participant
                SET last_spoke_at = ?, message_count = message_count + 1
                WHERE session_id = ? AND character_id = ?
                """,
                (now, session_id, message["character_id"]),
            )

    if isinstance(response, list):
        for item in response:
            reply_to_message_id = item.get("reply_to_message_id")
            if isinstance(reply_to_message_id, int) and reply_to_message_id < 0:
                item["reply_to_message_id"] = temporary_ids.get(reply_to_message_id)

    group_state = dialogue_turn.get("group_state")
    if group_state:
        last_reply_to_message_id = group_state.get("last_reply_to_message_id")
        if isinstance(last_reply_to_message_id, int) and last_reply_to_message_id < 0:
            last_reply_to_message_id = temporary_ids.get(last_reply_to_message_id)
        unresolved_hooks = []
        for hook in group_state.get("unresolved_hooks") or []:
            mapped_hook = dict(hook)
            message_id = mapped_hook.get("message_id")
            if isinstance(message_id, int) and message_id < 0:
                mapped_hook["message_id"] = temporary_ids.get(message_id)
            unresolved_hooks.append(mapped_hook)
        conn.execute(
            """
            INSERT INTO group_dialogue_state
            (group_thread_id, player_id, current_topic, topic_source,
             last_reply_to_message_id, last_reply_to_character_id,
             last_speaker_id, waiting_for_player, unresolved_hooks,
             last_autonomous_pulse_at, last_autonomous_world_at,
             daily_message_date, daily_message_count, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(group_thread_id)
            DO UPDATE SET
                current_topic=excluded.current_topic,
                topic_source=excluded.topic_source,
                last_reply_to_message_id=excluded.last_reply_to_message_id,
                last_reply_to_character_id=excluded.last_reply_to_character_id,
                last_speaker_id=excluded.last_speaker_id,
                waiting_for_player=excluded.waiting_for_player,
                unresolved_hooks=excluded.unresolved_hooks,
                last_autonomous_pulse_at=excluded.last_autonomous_pulse_at,
                last_autonomous_world_at=excluded.last_autonomous_world_at,
                daily_message_date=excluded.daily_message_date,
                daily_message_count=excluded.daily_message_count,
                updated_at=excluded.updated_at
            """,
            (
                group_state["group_thread_id"],
                dialogue_turn["player_id"],
                group_state.get("current_topic"),
                group_state.get("topic_source"),
                last_reply_to_message_id,
                group_state.get("last_reply_to_character_id"),
                group_state.get("last_speaker_id"),
                int(bool(group_state.get("waiting_for_player"))),
                json.dumps(unresolved_hooks, ensure_ascii=False),
                group_state.get("last_autonomous_pulse_at"),
                group_state.get("last_autonomous_world_at"),
                group_state.get("daily_message_date"),
                int(group_state.get("daily_message_count") or 0),
                now,
                now,
            ),
        )

    for background_job in dialogue_turn.get("background_jobs") or []:
        _enqueue_background_job_in_transaction(
            conn,
            job_type=background_job["job_type"],
            dedupe_key=background_job["dedupe_key"],
            payload=background_job["payload"],
            available_at=background_job.get("available_at"),
            now=now,
        )

    response_data = json.dumps(response, ensure_ascii=False)
    completed = conn.execute(
        """
        UPDATE dialogue_turn
        SET status = 'completed', lease_owner = NULL, lease_expires_at = NULL,
            response_data = ?, error = NULL, updated_at = ?, completed_at = ?
        WHERE session_id = ? AND request_id = ?
          AND status = 'processing' AND lease_owner = ?
          AND lease_expires_at > ?
        """,
        (
            response_data,
            now,
            now,
            session_id,
            request_id,
            lease_owner,
            now,
        ),
    )
    if completed.rowcount != 1:
        raise DialogueTurnConflictError("对话轮次租约已失效")
    return response


def commit_dialogue_turn(
    *,
    dialogue_turn: dict,
    runtime_states: list[dict] | None = None,
) -> dict | list:
    """Atomically persist a turn without an event execution batch."""
    now = _now()
    with get_conn() as conn:
        _save_runtime_states_in_transaction(
            conn,
            player_id=dialogue_turn["player_id"],
            runtime_states=runtime_states,
            now=now,
        )
        return _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)


def commit_event_execution_batch(
    *,
    player_id: str,
    execution_key: str,
    trigger_source: str,
    results_data: str,
    executions: list[dict],
    runtime_states: list[dict] | None = None,
    schedule_completion: dict | None = None,
    dialogue_turn: dict | None = None,
) -> dict:
    """在一个数据库事务中提交整轮事件执行及全部数据库副作用。"""
    inserted_memories: list[dict] = []
    now = _now()
    statuses = {execution["status"] for execution in executions}
    if not executions or statuses <= {"succeeded", "skipped"}:
        batch_status = "succeeded"
    elif statuses == {"failed"}:
        batch_status = "failed"
    else:
        batch_status = "partial"
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO event_execution_batch
            (player_id, execution_key, trigger_source, status, results_data,
             deduplicated_count, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT(player_id, execution_key) DO NOTHING
            """,
            (player_id, execution_key, trigger_source, batch_status, results_data, now, now),
        )
        if cursor.rowcount == 0:
            conn.execute(
                """
                UPDATE event_execution_batch
                SET deduplicated_count = COALESCE(deduplicated_count, 0) + 1
                WHERE player_id = ? AND execution_key = ?
                """,
                (player_id, execution_key),
            )
            row = conn.execute(
                """
                SELECT * FROM event_execution_batch
                WHERE player_id = ? AND execution_key = ?
                """,
                (player_id, execution_key),
            ).fetchone()
            if schedule_completion:
                _complete_event_schedule_in_transaction(
                    conn,
                    player_id=player_id,
                    schedule_completion=schedule_completion,
                    now=now,
                )
            for execution in executions:
                claim_token = execution.get("trigger_claim_token")
                if claim_token:
                    conn.execute(
                        """
                        UPDATE event_trigger_guard
                        SET claim_token = NULL, claim_expires_at = NULL, updated_at = ?
                        WHERE player_id = ? AND event_id = ? AND character_scope = ?
                          AND claim_token = ?
                        """,
                        (
                            now,
                            player_id,
                            execution["event_id"],
                            execution.get("trigger_character_scope") or "",
                            claim_token,
                        ),
                    )
                exclusive_claim_token = execution.get(
                    "exclusive_group_claim_token"
                )
                if exclusive_claim_token:
                    conn.execute(
                        """
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = ?
                        WHERE player_id = ? AND exclusive_group = ?
                          AND selected_event_id IS NULL AND claim_token = ?
                        """,
                        (
                            now,
                            player_id,
                            execution["exclusive_group"],
                            exclusive_claim_token,
                        ),
                    )
            dialogue_response = (
                _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)
                if dialogue_turn
                else None
            )
            return {
                "deduplicated": True,
                "batch": dict(row),
                "inserted_memories": [],
                "dialogue_response": dialogue_response,
            }

        for execution in executions:
            conn.execute(
                """
                INSERT INTO event_execution
                (execution_id, execution_key, owner_user_id, event_id, character_id,
                 session_id, trigger_source, status, effects_data, result_data,
                 error, duration_ms, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    execution["execution_id"],
                    execution_key,
                    player_id,
                    execution["event_id"],
                    execution["character_id"],
                    execution["session_id"],
                    trigger_source,
                    execution["status"],
                    execution["effects_data"],
                    execution["result_data"],
                    execution.get("error"),
                    float(execution.get("duration_ms") or 0.0),
                    now,
                    now,
                ),
            )

            if execution["status"] != "succeeded":
                continue

            claim_token = execution.get("trigger_claim_token")
            if claim_token:
                consumed = conn.execute(
                    """
                    UPDATE event_trigger_guard
                    SET last_triggered_at = ?, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = ?
                    WHERE player_id = ? AND event_id = ? AND character_scope = ?
                      AND claim_token = ?
                    """,
                    (
                        now,
                        now,
                        player_id,
                        execution["event_id"],
                        execution.get("trigger_character_scope") or "",
                        claim_token,
                    ),
                )
                if consumed.rowcount != 1:
                    raise RuntimeError(
                        "event trigger claim was lost before atomic completion"
                    )

            exclusive_claim_token = execution.get(
                "exclusive_group_claim_token"
            )
            if exclusive_claim_token:
                selected = conn.execute(
                    """
                    UPDATE event_exclusive_group_guard
                    SET selected_event_id = ?, claim_token = NULL,
                        claim_expires_at = NULL, updated_at = ?
                    WHERE player_id = ? AND exclusive_group = ?
                      AND selected_event_id IS NULL AND claim_token = ?
                      AND EXISTS (
                          SELECT 1
                          FROM event_definition
                          WHERE owner_user_id = ?
                            AND event_id = ?
                            AND exclusive_scope = 'player'
                            AND exclusive_group = ?
                      )
                    """,
                    (
                        execution["event_id"],
                        now,
                        player_id,
                        execution["exclusive_group"],
                        exclusive_claim_token,
                        player_id,
                        execution["event_id"],
                        execution["exclusive_group"],
                    ),
                )
                if selected.rowcount != 1:
                    released_stale = conn.execute(
                        """
                        UPDATE event_exclusive_group_guard
                        SET claim_token = NULL, claim_expires_at = NULL,
                            updated_at = ?
                        WHERE player_id = ? AND exclusive_group = ?
                          AND selected_event_id IS NULL AND claim_token = ?
                          AND NOT EXISTS (
                              SELECT 1
                              FROM event_definition
                              WHERE owner_user_id = ?
                                AND event_id = ?
                                AND exclusive_scope = 'player'
                                AND exclusive_group = ?
                          )
                        """,
                        (
                            now,
                            player_id,
                            execution["exclusive_group"],
                            exclusive_claim_token,
                            player_id,
                            execution["event_id"],
                            execution["exclusive_group"],
                        ),
                    )
                    if released_stale.rowcount != 1:
                        raise RuntimeError(
                            "event exclusive group claim was lost before atomic completion"
                        )

            conn.execute(
                """
                INSERT INTO event_trigger_log
                (event_id, character_id, player_id, session_id, triggered_at,
                 context_snapshot, effects_applied, execution_id, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'succeeded')
                """,
                (
                    execution["event_id"],
                    execution["character_id"],
                    player_id,
                    execution["session_id"],
                    now,
                    execution["context_snapshot"],
                    execution["effects_applied"],
                    execution["execution_id"],
                ),
            )
            conn.execute(
                """
                UPDATE event_definition
                SET trigger_count = trigger_count + 1, last_triggered_at = ?
                WHERE owner_user_id = ? AND event_id = ?
                """,
                (now, player_id, execution["event_id"]),
            )

            context_state = execution.get("context_state")
            if context_state:
                conn.execute(
                    """
                    INSERT INTO event_context_state
                    (event_id, character_id, player_id, context_data, status,
                     progress, last_session_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(event_id, character_id, player_id)
                    DO UPDATE SET
                        context_data=excluded.context_data,
                        status=excluded.status,
                        progress=excluded.progress,
                        last_session_id=excluded.last_session_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        execution["event_id"],
                        execution["character_id"],
                        player_id,
                        context_state["context_data"],
                        context_state["status"],
                        context_state["progress"],
                        execution["session_id"],
                        now,
                        now,
                    ),
                )

            for unlock_key in execution.get("unlock_keys") or []:
                conn.execute(
                    """
                    INSERT INTO event_unlock
                    (player_id, character_id, unlock_key, event_id, unlocked_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(player_id, character_id, unlock_key) DO NOTHING
                    """,
                    (
                        player_id,
                        execution["character_id"],
                        unlock_key,
                        execution["event_id"],
                        now,
                    ),
                )

            for memory in execution.get("memories") or []:
                inserted = _insert_long_term_fact_in_transaction(conn, memory)
                if inserted:
                    inserted_memories.append(inserted)

            for claim in execution.get("fact_claims") or []:
                identity = derive_fact_claim_identity(
                    player_id,
                    claim["scope_type"],
                    claim["scope_id"],
                    claim["fact_text"],
                )
                _record_fact_claim_in_transaction(
                    conn,
                    claim_id=identity["claim_id"],
                    owner_user_id=player_id,
                    scope_type=claim["scope_type"],
                    scope_id=claim["scope_id"],
                    fact_text=claim["fact_text"],
                    normalized_fact_text=identity["normalized_fact_text"],
                    content_hash=identity["content_hash"],
                    normalized_content_hash=identity["normalized_content_hash"],
                    source_kind=claim["source_kind"],
                    source_ids=clean_source_ids(claim.get("source_ids") or []),
                    provenance=dict(claim.get("provenance") or {}),
                    direct_support=bool(claim.get("direct_support")),
                    verification_policy=lambda evidence, normalized=identity[
                        "normalized_fact_text"
                    ]: evaluate_verification(normalized, evidence),
                    event_context={
                        "correlation_id": execution["execution_id"],
                        "causation_id": execution["event_id"],
                        "session_id": claim.get("session_id"),
                        "world_occurred_at": claim.get("world_occurred_at"),
                        "metadata": {
                            "producer": "memoria.core.event_executor",
                        },
                    },
                )

            for story_update in execution.get("story_updates") or []:
                _apply_story_update_in_transaction(
                    conn,
                    player_id,
                    story_update,
                )

            for inbox_item in execution.get("inbox_items") or []:
                conn.execute(
                    """
                    INSERT INTO player_event_inbox
                    (player_id, event_id, character_id, session_id, event_type,
                     title, content, payload, world_created_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player_id,
                        execution["event_id"],
                        execution["character_id"],
                        inbox_item.get("session_id"),
                        inbox_item.get("event_type", "event"),
                        inbox_item.get("title"),
                        inbox_item["content"],
                        inbox_item.get("payload"),
                        inbox_item.get("world_created_at"),
                        now,
                    ),
                )

            for message in execution.get("proactive_messages") or []:
                target = conn.execute(
                    """
                    SELECT 1
                    FROM session s
                    INNER JOIN multi_session_participant p
                      ON p.session_id = s.session_id
                     AND p.character_id = ?
                     AND p.is_active = 1
                    WHERE s.session_id = ?
                      AND s.player_id = ?
                      AND s.is_multi_character = 1
                      AND s.status <> 'ended'
                    """,
                    (
                        message["character_id"],
                        message["session_id"],
                        player_id,
                    ),
                ).fetchone()
                if target is None:
                    raise RuntimeError(
                        "proactive dialogue target is not an owned active group participant"
                    )
                conn.execute(
                    """
                    INSERT INTO short_term_message
                    (session_id, role, content, character_id, character_name,
                     created_at, knowledge_sources, world_created_at)
                    VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message["session_id"],
                        message["content"],
                        message["character_id"],
                        message.get("character_name"),
                        now,
                        _encode_knowledge_sources(message.get("knowledge_sources")),
                        message.get("world_created_at"),
                    ),
                )
                conn.execute(
                    """
                    UPDATE multi_session_participant
                    SET last_spoke_at = ?, message_count = message_count + 1
                    WHERE session_id = ? AND character_id = ?
                    """,
                    (now, message["session_id"], message["character_id"]),
                )

        _save_runtime_states_in_transaction(
            conn,
            player_id=player_id,
            runtime_states=runtime_states,
            now=now,
        )

        if schedule_completion:
            _complete_event_schedule_in_transaction(
                conn,
                player_id=player_id,
                schedule_completion=schedule_completion,
                now=now,
            )
        dialogue_response = (
            _commit_dialogue_turn_in_transaction(conn, dialogue_turn, now=now)
            if dialogue_turn
            else None
        )

    return {
        "deduplicated": False,
        "batch": {
            "player_id": player_id,
            "execution_key": execution_key,
            "results_data": results_data,
            "status": batch_status,
        },
        "inserted_memories": inserted_memories,
        "dialogue_response": dialogue_response,
    }


def list_event_unlocks(player_id: str, character_id: str) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT unlock_key FROM event_unlock
            WHERE player_id = ? AND character_id = ?
            ORDER BY unlocked_at ASC, unlock_key ASC
            """,
            (player_id, character_id),
        ).fetchall()
    return [row["unlock_key"] for row in rows]


def get_event_execution_metrics(
    owner_user_id: str,
    event_id: str | None = None,
) -> dict:
    with get_conn() as conn:
        where = "owner_user_id = ?"
        params: list = [owner_user_id]
        if event_id:
            where += " AND event_id = ?"
            params.append(event_id)
        aggregate = conn.execute(
            f"""
            SELECT
                COUNT(*) AS matched_count,
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS succeeded_count,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                SUM(CASE WHEN status = 'partial' THEN 1 ELSE 0 END) AS partial_count,
                SUM(CASE WHEN status = 'skipped' THEN 1 ELSE 0 END) AS skipped_count,
                AVG(duration_ms) AS average_duration_ms,
                MAX(completed_at) AS last_execution_at
            FROM event_execution
            WHERE {where}
            """,
            tuple(params),
        ).fetchone()
        last_error = conn.execute(
            f"""
            SELECT error FROM event_execution
            WHERE {where} AND error IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
            """,
            tuple(params),
        ).fetchone()
        if event_id:
            deduplicated = conn.execute(
                """
                SELECT COALESCE(SUM(batch.deduplicated_count), 0) AS count
                FROM event_execution_batch AS batch
                WHERE batch.player_id = ?
                  AND EXISTS (
                      SELECT 1 FROM event_execution AS execution
                      WHERE execution.owner_user_id = batch.player_id
                        AND execution.execution_key = batch.execution_key
                        AND execution.event_id = ?
                  )
                """,
                (owner_user_id, event_id),
            ).fetchone()
        else:
            deduplicated = conn.execute(
                """
                SELECT COALESCE(SUM(deduplicated_count), 0) AS count
                FROM event_execution_batch WHERE player_id = ?
                """,
                (owner_user_id,),
            ).fetchone()
    return {
        "matched_count": int(aggregate["matched_count"] or 0),
        "succeeded_count": int(aggregate["succeeded_count"] or 0),
        "failed_count": int(aggregate["failed_count"] or 0),
        "partial_count": int(aggregate["partial_count"] or 0),
        "skipped_count": int(aggregate["skipped_count"] or 0),
        "deduplicated_count": int(deduplicated["count"] or 0),
        "average_duration_ms": float(aggregate["average_duration_ms"] or 0.0),
        "last_execution_at": aggregate["last_execution_at"],
        "last_error": last_error["error"] if last_error else None,
    }

def delete_trigger_history(
    event_id: str,
    character_id: str,
    player_id: str,
) -> int:
    """
    删除某事件对特定玩家的所有触发记录
    返回删除的行数
    """
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM event_trigger_log
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        )
        conn.execute(
            """
            DELETE FROM event_trigger_guard
            WHERE event_id = ? AND player_id = ?
              AND character_scope IN (?, '')
            """,
            (event_id, player_id, character_id),
        )
        conn.execute(
            """
            DELETE FROM event_exclusive_group_guard
            WHERE player_id = ? AND selected_event_id = ?
            """,
            (player_id, event_id),
        )
        return cur.rowcount


# =========================
# 事件系统 - 上下文 / 调度 / 模板
# =========================
def save_event_context_state(
    event_id: str,
    character_id: str,
    player_id: str,
    context_data: str,
    status: str = "active",
    progress: float = 0.0,
    last_session_id: str = None,
) -> bool:
    """保存事件进度上下文，同一 event+character+player 只保留一条。"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_context_state
                (event_id, character_id, player_id, context_data, status, progress,
                 last_session_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, character_id, player_id)
                DO UPDATE SET
                    context_data=excluded.context_data,
                    status=excluded.status,
                    progress=excluded.progress,
                    last_session_id=excluded.last_session_id,
                    updated_at=excluded.updated_at
                """,
                (event_id, character_id, player_id, context_data, status, progress,
                 last_session_id, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件上下文失败: {e}")
        return False


def get_event_context_state(event_id: str, character_id: str, player_id: str) -> dict | None:
    """获取指定事件上下文。"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_context_state
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        ).fetchone()
    return _row_to_dict(row)


def list_event_context_states(
    character_id: str = None,
    player_id: str = None,
    status: str = None,
    limit: int = 100,
) -> list[dict]:
    """列出事件上下文，可按角色、玩家和状态过滤。"""
    with get_conn() as conn:
        query = "SELECT * FROM event_context_state WHERE 1=1"
        params = []
        if character_id:
            query += " AND character_id = ?"
            params.append(character_id)
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def _save_event_schedule_state_in_transaction(
    conn,
    *,
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    next_run_at: str = None,
    next_due_real_at: str = None,
    last_checked_at: str = None,
    last_run_at: str = None,
    status: str = "active",
    missed_count: int = 0,
) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO event_schedule_state
        (event_id, character_id, player_id, schedule, last_checked_at,
         last_run_at, next_run_at, next_due_real_at, missed_count,
         status, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id, character_id, player_id)
        DO UPDATE SET
            schedule=excluded.schedule,
            last_checked_at=excluded.last_checked_at,
            last_run_at=excluded.last_run_at,
            next_run_at=excluded.next_run_at,
            next_due_real_at=excluded.next_due_real_at,
            missed_count=excluded.missed_count,
            status=excluded.status,
            updated_at=excluded.updated_at
        """,
        (
            event_id,
            character_id,
            player_id,
            schedule,
            last_checked_at,
            last_run_at,
            next_run_at,
            next_due_real_at,
            missed_count,
            status,
            now,
            now,
        ),
    )


def save_event_schedule_state(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    next_run_at: str = None,
    next_due_real_at: str = None,
    last_checked_at: str = None,
    last_run_at: str = None,
    status: str = "active",
    missed_count: int = 0,
) -> bool:
    """保存时间驱动事件的调度状态。"""
    try:
        with get_conn() as conn:
            _save_event_schedule_state_in_transaction(
                conn,
                event_id=event_id,
                character_id=character_id,
                player_id=player_id,
                schedule=schedule,
                next_run_at=next_run_at,
                next_due_real_at=next_due_real_at,
                last_checked_at=last_checked_at,
                last_run_at=last_run_at,
                status=status,
                missed_count=missed_count,
            )
        return True
    except Exception as e:
        logger.error(f"保存事件调度状态失败: {e}")
        return False


def save_event_definition_with_schedule(
    owner_user_id: str,
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    *,
    schedule_state: dict | None,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    exclusive_group: str = None,
    exclusive_scope: str = "turn",
    max_triggers_per_turn: int = 3,
    stop_processing: bool = False,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
    story_id: str = None,
) -> bool:
    """Atomically save an event definition and its single schedule state."""
    try:
        with get_conn() as conn:
            _save_event_definition_in_transaction(
                conn,
                owner_user_id=owner_user_id,
                event_id=event_id,
                event_name=event_name,
                trigger_config=trigger_config,
                effects_config=effects_config,
                character_id=character_id,
                description=description,
                priority=priority,
                exclusive_group=exclusive_group,
                exclusive_scope=exclusive_scope,
                max_triggers_per_turn=max_triggers_per_turn,
                stop_processing=stop_processing,
                is_active=is_active,
                schedule=schedule,
                template_id=template_id,
                story_id=story_id,
            )
            if schedule_state is not None:
                if schedule_state.get("event_id") != event_id:
                    raise ValueError("Schedule event_id does not match definition")
                if schedule_state.get("player_id") != owner_user_id:
                    raise ValueError("Schedule player_id does not match definition owner")

            conn.execute(
                """
                DELETE FROM event_schedule_state
                WHERE event_id = ? AND player_id = ?
                """,
                (event_id, owner_user_id),
            )
            if schedule_state is not None:
                _save_event_schedule_state_in_transaction(conn, **schedule_state)
        return True
    except Exception as e:
        logger.error(f"原子保存事件定义和调度失败: {e}")
        return False


def list_due_event_schedules(
    now_iso: str,
    limit: int = 50,
    player_id: str | None = None,
    after: tuple[str, str, str, str] | None = None,
) -> list[dict]:
    """List schedules due against indexed real UTC time."""
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NOT NULL
              AND next_due_real_at <= ?
        """
        params = [now_iso]
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        if after:
            query += """
                AND (next_due_real_at, event_id, character_id, player_id)
                    > (?, ?, ?, ?)
            """
            params.extend(after)
        query += """
            ORDER BY next_due_real_at, event_id, character_id, player_id
            LIMIT ?
        """
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def list_active_event_schedules(
    limit: int = 500,
    player_id: str | None = None,
) -> list[dict]:
    """List active schedules for per-player world-time evaluation."""
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active' AND next_run_at IS NOT NULL
        """
        params: list[Any] = []
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        query += " ORDER BY next_run_at ASC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_event_schedules(
    player_id: str,
    event_id: str | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[dict]:
    with get_conn() as conn:
        query = "SELECT * FROM event_schedule_state WHERE player_id = ?"
        params: list[Any] = [player_id]
        if event_id:
            query += " AND event_id = ?"
            params.append(event_id)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY next_run_at ASC, updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def get_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            """,
            (event_id, character_id, player_id),
        ).fetchone()
    return _row_to_dict(row)


def set_event_schedule_status(
    event_id: str,
    character_id: str,
    player_id: str,
    status: str,
    *,
    next_run_at: str | None = None,
) -> bool:
    if status not in {"active", "paused"}:
        raise ValueError("schedule status must be active or paused")
    with get_conn() as conn:
        if next_run_at is None:
            cursor = conn.execute(
                """
                UPDATE event_schedule_state
                SET status = ?, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (status, _now(), event_id, character_id, player_id),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE event_schedule_state
                SET status = ?, next_run_at = ?, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (
                    status,
                    next_run_at,
                    _now(),
                    event_id,
                    character_id,
                    player_id,
                ),
            )
    return cursor.rowcount == 1


def delete_event_schedules(
    event_id: str,
    player_id: str,
    character_id: str | None = None,
) -> int:
    """Delete schedules owned by a player, optionally for one character."""
    with get_conn() as conn:
        if character_id is None:
            cursor = conn.execute(
                "DELETE FROM event_schedule_state WHERE event_id = ? AND player_id = ?",
                (event_id, player_id),
            )
        else:
            cursor = conn.execute(
                """
                DELETE FROM event_schedule_state
                WHERE event_id = ? AND character_id = ? AND player_id = ?
                """,
                (event_id, character_id, player_id),
            )
    return cursor.rowcount


def claim_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    lease_expires_at: str,
    real_now_iso: str,
    expected_next_run_at: str,
    expected_next_due_real_at: str | None = None,
) -> bool:
    """Conditionally claim a schedule using a real-UTC lease."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET lease_owner = ?, lease_expires_at = ?, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND status = 'active'
              AND next_run_at = ?
              AND (
                next_due_real_at = ?
                OR (next_due_real_at IS NULL AND ? IS NULL)
              )
              AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            """,
            (
                lease_owner,
                lease_expires_at,
                real_now_iso,
                event_id,
                character_id,
                player_id,
                expected_next_run_at,
                expected_next_due_real_at,
                expected_next_due_real_at,
                real_now_iso,
            ),
        )
    return cursor.rowcount == 1


def complete_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    last_checked_at: str,
    last_run_at: str,
    next_run_at: str,
    next_due_real_at: str | None = None,
    missed_count: int = 0,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET last_checked_at = ?, last_run_at = ?, next_run_at = ?,
                next_due_real_at = ?, missed_count = ?,
                lease_owner = NULL, lease_expires_at = NULL,
                last_error = NULL, last_failed_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (
                last_checked_at,
                last_run_at,
                next_run_at,
                next_due_real_at,
                missed_count,
                _now(),
                event_id,
                character_id,
                player_id,
                lease_owner,
            ),
        )
    return cursor.rowcount == 1


def get_next_event_schedule(player_id: str) -> dict | None:
    """Return the player's earliest active schedule for clock UI display."""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT s.*, d.event_name
            FROM event_schedule_state s
            LEFT JOIN event_definition d
              ON d.owner_user_id = s.player_id AND d.event_id = s.event_id
            WHERE s.player_id = ? AND s.status = 'active'
              AND s.next_run_at IS NOT NULL
            ORDER BY
              CASE WHEN s.next_due_real_at IS NULL THEN 1 ELSE 0 END,
              s.next_due_real_at ASC,
              s.next_run_at ASC
            LIMIT 1
            """,
            (player_id,),
        ).fetchone()
    return _row_to_dict(row)


def list_event_schedules_for_player(player_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE player_id = ?
            ORDER BY next_run_at ASC
            """,
            (player_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_event_schedules_missing_due_projection(
    player_id: str | None = None,
) -> list[dict]:
    """Return active schedules that need a real-time due projection."""
    with get_conn() as conn:
        query = """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_due_real_at IS NULL
        """
        params: list[Any] = []
        if player_id:
            query += " AND player_id = ?"
            params.append(player_id)
        query += " ORDER BY player_id, next_run_at"
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def set_event_schedule_due_projection(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    expected_next_run_at: str,
    next_due_real_at: str,
) -> bool:
    """Backfill a missing projection without changing schedule ownership."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET next_due_real_at = ?, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND status = 'active'
              AND next_run_at = ?
              AND next_due_real_at IS NULL
            """,
            (
                next_due_real_at,
                _now(),
                event_id,
                character_id,
                player_id,
                expected_next_run_at,
            ),
        )
    return cursor.rowcount == 1


def fail_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
    error: str,
    failed_at: str,
) -> bool:
    """Record a scheduler failure and release only the current worker's lease."""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET last_error = ?, last_failed_at = ?, lease_owner = NULL,
                lease_expires_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (
                error[:2000],
                failed_at,
                _now(),
                event_id,
                character_id,
                player_id,
                lease_owner,
            ),
        )
    return cursor.rowcount == 1


def release_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    *,
    lease_owner: str,
) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE event_schedule_state
            SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE event_id = ? AND character_id = ? AND player_id = ?
              AND lease_owner = ?
            """,
            (_now(), event_id, character_id, player_id, lease_owner),
        )
    return cursor.rowcount == 1


def get_latest_active_multi_session(player_id: str) -> dict | None:
    """Return the player's most recently active group session."""
    with get_conn() as conn:
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
            WHERE s.player_id = ?
              AND s.status = 'active'
              AND COALESCE(s.is_multi_character, 0) = 1
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            LIMIT 1
            """,
            (player_id,),
        ).fetchone()
    return _row_to_dict(row)


def enqueue_player_event(
    player_id: str,
    content: str,
    *,
    event_id: str | None = None,
    character_id: str | None = None,
    session_id: str | None = None,
    event_type: str = "event",
    group_thread_id: str | None = None,
    unread_count: int = 0,
    title: str | None = None,
    payload: str | None = None,
    world_created_at: str | None = None,
) -> int:
    with get_conn() as conn:
        sql = """
            INSERT INTO player_event_inbox
            (player_id, event_id, character_id, session_id, event_type,
             group_thread_id, unread_count, title, content, payload,
             world_created_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        if _is_postgres_enabled():
            sql += " RETURNING id"
        cursor = conn.execute(
            sql,
            (
                player_id,
                event_id,
                character_id,
                session_id,
                event_type,
                group_thread_id,
                max(0, int(unread_count or 0)),
                title,
                content,
                payload,
                world_created_at,
                _now(),
            ),
        )
        return cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid


def _upsert_group_message_notification_in_transaction(
    conn,
    player_id: str,
    group_thread_id: str,
    session_id: str,
    new_message_count: int,
    *,
    group_name: str | None = None,
    world_created_at: str | None = None,
) -> int:
    """每个逻辑群聊只保留一条未读聚合通知。"""
    increment = max(0, int(new_message_count or 0))
    if increment <= 0:
        return 0

    row = conn.execute(
        """
        SELECT id, unread_count
        FROM player_event_inbox
        WHERE player_id = ? AND event_type = 'group_message'
          AND group_thread_id = ? AND read_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """,
        (player_id, group_thread_id),
    ).fetchone()
    if row:
        unread_count = int(row["unread_count"] or 0) + increment
        conn.execute(
            """
            UPDATE player_event_inbox
            SET session_id = ?, unread_count = ?, content = ?, title = ?,
                world_created_at = ?, created_at = ?, payload = ?
            WHERE id = ?
            """,
            (
                session_id,
                unread_count,
                f"群聊中有 {unread_count} 条新消息",
                group_name or "群聊新消息",
                world_created_at,
                _now(),
                json.dumps(
                    {"group_thread_id": group_thread_id, "unread_count": unread_count},
                    ensure_ascii=False,
                ),
                row["id"],
            ),
        )
        return int(row["id"])

    sql = """
        INSERT INTO player_event_inbox
        (player_id, session_id, event_type, group_thread_id, unread_count,
         title, content, payload, world_created_at, created_at)
        VALUES (?, ?, 'group_message', ?, ?, ?, ?, ?, ?, ?)
    """
    if _is_postgres_enabled():
        sql += " RETURNING id"
    cursor = conn.execute(
        sql,
        (
            player_id,
            session_id,
            group_thread_id,
            increment,
            group_name or "群聊新消息",
            f"群聊中有 {increment} 条新消息",
            json.dumps(
                {"group_thread_id": group_thread_id, "unread_count": increment},
                ensure_ascii=False,
            ),
            world_created_at,
            _now(),
        ),
    )
    return int(cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid)


def upsert_group_message_notification(
    player_id: str,
    group_thread_id: str,
    session_id: str,
    new_message_count: int,
    *,
    group_name: str | None = None,
    world_created_at: str | None = None,
) -> int:
    with get_conn() as conn:
        return _upsert_group_message_notification_in_transaction(
            conn,
            player_id,
            group_thread_id,
            session_id,
            new_message_count,
            group_name=group_name,
            world_created_at=world_created_at,
        )


def list_player_event_inbox(
    player_id: str,
    *,
    unread_only: bool = True,
    limit: int = 50,
) -> list[dict]:
    with get_conn() as conn:
        unread_clause = "AND read_at IS NULL" if unread_only else ""
        rows = conn.execute(
            f"""
            SELECT * FROM player_event_inbox
            WHERE player_id = ? {unread_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            (player_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_player_event_read(player_id: str, inbox_id: int) -> bool:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, ?)
            WHERE id = ? AND player_id = ?
            """,
            (_now(), inbox_id, player_id),
        )
    return cursor.rowcount == 1


def mark_group_thread_notifications_read(player_id: str, group_thread_id: str) -> int:
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE player_event_inbox
            SET read_at = COALESCE(read_at, ?)
            WHERE player_id = ? AND event_type = 'group_message'
              AND group_thread_id = ? AND read_at IS NULL
            """,
            (_now(), player_id, group_thread_id),
        )
    return cursor.rowcount


def save_event_template(
    template_id: str,
    template_name: str,
    category: str,
    description: str,
    trigger_config: str,
    effects_config: str,
    metadata: str = None,
) -> bool:
    """保存事件模板。"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_template
                (template_id, template_name, category, description, trigger_config,
                 effects_config, metadata, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(template_id)
                DO UPDATE SET
                    template_name=excluded.template_name,
                    category=excluded.category,
                    description=excluded.description,
                    trigger_config=excluded.trigger_config,
                    effects_config=excluded.effects_config,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (template_id, template_name, category, description, trigger_config,
                 effects_config, metadata, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件模板失败: {e}")
        return False


def list_event_templates(category: str = None) -> list[dict]:
    """列出事件模板。"""
    with get_conn() as conn:
        query = "SELECT * FROM event_template WHERE 1=1"
        params = []
        if category:
            query += " AND category = ?"
            params.append(category)
        query += " ORDER BY category ASC, template_name ASC"
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_event_template(template_id: str) -> dict | None:
    """获取事件模板。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM event_template WHERE template_id = ?",
            (template_id,),
        ).fetchone()
    return _row_to_dict(row)


def delete_event_template(template_id: str) -> bool:
    """删除事件模板。"""
    with get_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM event_template WHERE template_id = ?",
            (template_id,),
        )
    return cursor.rowcount > 0


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
            """
            SELECT story_id
            FROM session
            WHERE player_id = ?
              AND group_thread_id = ?
              AND COALESCE(story_id, '') <> ''
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """,
            (player_id, thread_id),
        ).fetchone()
        if story_row:
            clean_story_id = str(story_row["story_id"]).strip() or None

    created_at = _now()
    conn.execute(
        """
        INSERT INTO session
        (session_id, character_id, player_id, player_name, created_at, status,
         group_name, group_thread_id, story_id, is_multi_character, locale)
        VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, 1, ?)
        """,
        (
            session_id,
            character_ids[0],
            player_id,
            player_name,
            created_at,
            clean_group_name,
            thread_id,
            clean_story_id,
            locale,
        ),
    )

    for idx, char_id in enumerate(character_ids):
        conn.execute(
            """
            INSERT INTO multi_session_participant
            (session_id, character_id, join_order, speak_frequency, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (session_id, char_id, idx, 1.0, created_at),
        )

    conn.execute(
        """
        INSERT INTO group_dialogue_state
        (group_thread_id, player_id, created_at, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(group_thread_id) DO UPDATE SET
            player_id = excluded.player_id,
            updated_at = excluded.updated_at
        """,
        (thread_id, player_id, created_at, created_at),
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
        with get_conn() as conn:
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

    with get_conn() as conn:
        _lock_session_creation(
            conn,
            f"active-multi-session:{clean_thread_id}",
        )
        row = conn.execute(
            """
            SELECT *
            FROM session
            WHERE player_id = ?
              AND group_thread_id = ?
              AND status = 'active'
              AND is_multi_character = 1
            ORDER BY created_at DESC, session_id DESC
            LIMIT 1
            """,
            (player_id, clean_thread_id),
        ).fetchone()
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
            "SELECT * FROM session WHERE session_id = ?",
            (session_id,),
        ).fetchone()
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
    with get_conn() as conn:
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
            WHERE p.session_id = ?
        """
        
        if only_active:
            query += " AND p.is_active = 1 AND c.is_active = 1"
        
        query += " ORDER BY p.join_order ASC"
        
        rows = conn.execute(query, (session_id,)).fetchall()
    
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
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE session
            SET group_thread_id = ?
            WHERE session_id = ?
              AND COALESCE(group_thread_id, '') = ''
            """,
            (generated_thread_id, session_id),
        )
        row = conn.execute(
            """
            SELECT group_thread_id
            FROM session
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        thread_id = str(row["group_thread_id"] or "").strip() if row else ""
        if thread_id:
            conn.execute(
                """
                INSERT INTO group_dialogue_state
                (group_thread_id, player_id, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_thread_id) DO UPDATE SET
                    player_id = excluded.player_id,
                    updated_at = excluded.updated_at
                """,
                (thread_id, session["player_id"], now, now),
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
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT session_id, status, group_name, group_thread_id, locale, created_at, ended_at
            FROM session
            WHERE player_id = ?
              AND COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = ?
            ORDER BY created_at ASC, session_id ASC
            """,
            (session["player_id"], thread_id),
        ).fetchall()
    return [dict(r) for r in rows]


def update_participant_speak_time(session_id: str, character_id: str):
    """
    更新参与者最后发言时间和发言次数
    
    Args:
        session_id: 会话 ID
        character_id: 角色 ID
    """
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE multi_session_participant
            SET last_spoke_at = ?,
                message_count = message_count + 1
            WHERE session_id = ? AND character_id = ?
            """,
            (_now(), session_id, character_id),
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
) -> int:
    """
    添加多角色会话消息
    
    Args:
        session_id: 会话 ID
        role: 角色类型 (user/assistant)
        content: 消息内容
        character_id: 发言角色ID（assistant时必填）
        character_name: 发言角色显示名称
    """
    with get_conn() as conn:
        insert_sql = """
            INSERT INTO short_term_message
            (session_id, role, content, character_id, character_name, created_at,
             knowledge_sources, world_created_at, reply_to_message_id,
             reply_to_character_id, intent, topic, trigger_source)
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
                character_id,
                character_name,
                _now(),
                _encode_knowledge_sources(knowledge_sources),
                world_created_at,
                reply_to_message_id,
                reply_to_character_id,
                intent,
                topic,
                trigger_source,
            ),
        )
        message_id = cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
    
    # 如果是角色发言，更新参与者统计
    if role == "assistant" and character_id:
        update_participant_speak_time(session_id, character_id)
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
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE short_term_message
            SET content = ?,
                character_id = ?,
                character_name = ?,
                knowledge_sources = ?,
                world_created_at = ?,
                reply_to_message_id = ?,
                reply_to_character_id = ?,
                intent = ?,
                topic = ?,
                trigger_source = ?
            WHERE id = ? AND session_id = ? AND role = 'assistant'
            """,
            (
                content,
                character_id,
                character_name,
                _encode_knowledge_sources(knowledge_sources),
                world_created_at,
                reply_to_message_id,
                reply_to_character_id,
                intent,
                topic,
                trigger_source,
                int(message_id),
                session_id,
            ),
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
    base_params = [session_id]
    if created_after:
        created_after_clause = "AND created_at >= ?"
        base_params.append(created_after)

    with get_conn() as conn:
        if limit_messages is None:
            rows = conn.execute(
                f"""
                SELECT id AS message_id, session_id, role, content, character_id,
                       character_name, knowledge_sources, reply_to_message_id,
                       reply_to_character_id, intent, topic, trigger_source,
                       created_at, world_created_at
                FROM short_term_message
                WHERE session_id = ?
                  {created_after_clause}
                ORDER BY id ASC
                """,
                tuple(base_params),
            ).fetchall()
            return [_decode_message_row(r) for r in rows]

        params = [*base_params, limit_messages]
        rows = conn.execute(
            f"""
            SELECT id AS message_id, session_id, role, content, character_id,
                   character_name, knowledge_sources, reply_to_message_id,
                   reply_to_character_id, intent, topic, trigger_source,
                   created_at, world_created_at
            FROM short_term_message
            WHERE session_id = ?
              {created_after_clause}
            ORDER BY id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

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
    base_params = [session["player_id"], thread_id]
    if created_after:
        created_after_clause = "AND m.created_at >= ?"
        base_params.append(created_after)

    with get_conn() as conn:
        if limit_messages is None:
            rows = conn.execute(
                f"""
                SELECT m.id AS message_id, m.session_id, m.role, m.content,
                       m.character_id, m.character_name, m.knowledge_sources,
                       m.reply_to_message_id, m.reply_to_character_id,
                       m.intent, m.topic, m.trigger_source,
                       m.created_at, m.world_created_at
                FROM short_term_message m
                INNER JOIN session s ON s.session_id = m.session_id
                WHERE s.player_id = ?
                  AND COALESCE(s.is_multi_character, 0) = 1
                  AND COALESCE(s.group_thread_id, s.session_id) = ?
                  {created_after_clause}
                ORDER BY m.id ASC
                """,
                tuple(base_params),
            ).fetchall()
            return [_decode_message_row(r) for r in rows]

        params = [*base_params, limit_messages]
        rows = conn.execute(
            f"""
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = ?
              {created_after_clause}
            ORDER BY m.id DESC
            LIMIT ?
            """,
            tuple(params),
        ).fetchall()

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
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = ?
            ORDER BY m.id DESC
            LIMIT ?
            OFFSET ?
            """,
            (
                session["player_id"],
                thread_id,
                limit + 1,
                offset,
            ),
        ).fetchall()

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

    with get_conn() as conn:
        latest_row = conn.execute(
            """
            SELECT MAX(m.id) AS latest_message_id
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = ?
            """,
            (session["player_id"], thread_id),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT m.id AS message_id, m.session_id, m.role, m.content,
                   m.character_id, m.character_name, m.knowledge_sources,
                   m.reply_to_message_id, m.reply_to_character_id,
                   m.intent, m.topic, m.trigger_source,
                   m.created_at, m.world_created_at
            FROM short_term_message m
            INNER JOIN session s ON s.session_id = m.session_id
            WHERE s.player_id = ?
              AND COALESCE(s.is_multi_character, 0) = 1
              AND COALESCE(s.group_thread_id, s.session_id) = ?
              AND m.id > ?
            ORDER BY m.id ASC
            LIMIT ?
            """,
            (
                session["player_id"],
                thread_id,
                after_id,
                limit + 1,
            ),
        ).fetchall()

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
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM group_dialogue_state WHERE group_thread_id = ?",
            (group_thread_id,),
        ).fetchone()
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
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO group_dialogue_state
            (group_thread_id, player_id, current_topic, topic_source,
             last_reply_to_message_id, last_reply_to_character_id,
             last_speaker_id, waiting_for_player, unresolved_hooks,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            """,
            (
                group_thread_id,
                player_id,
                current_topic,
                topic_source,
                last_reply_to_message_id,
                last_reply_to_character_id,
                last_speaker_id,
                1 if waiting_for_player else 0,
                json.dumps(unresolved_hooks or [], ensure_ascii=False),
                now,
                now,
            ),
        )
    return True


def list_group_dialogue_states(limit: int = 500) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM group_dialogue_state
            ORDER BY COALESCE(last_autonomous_pulse_at, created_at) ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_decode_group_dialogue_state(row) for row in rows]


def claim_group_dialogue_state(
    group_thread_id: str,
    *,
    lease_owner: str,
    lease_expires_at: str,
    real_now_iso: str,
) -> bool:
    """使用现实 UTC 租约原子领取一个逻辑群聊脉冲。"""
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE group_dialogue_state
            SET lease_owner = ?, lease_expires_at = ?, updated_at = ?
            WHERE group_thread_id = ?
              AND (lease_expires_at IS NULL OR lease_expires_at <= ?)
            """,
            (
                lease_owner,
                lease_expires_at,
                real_now_iso,
                group_thread_id,
                real_now_iso,
            ),
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
    with get_conn() as conn:
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
        """
        UPDATE group_dialogue_state
        SET current_topic = ?, topic_source = ?,
            last_reply_to_message_id = ?, last_reply_to_character_id = ?,
            last_speaker_id = ?, waiting_for_player = ?, unresolved_hooks = ?,
            last_autonomous_pulse_at = ?, last_autonomous_world_at = ?,
            daily_message_date = ?,
            daily_message_count = CASE
                WHEN daily_message_date = ? THEN daily_message_count + ?
                ELSE ?
            END,
            lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
        WHERE group_thread_id = ? AND lease_owner = ?
        """,
        (
            current_topic,
            topic_source,
            last_reply_to_message_id,
            last_reply_to_character_id,
            last_speaker_id,
            1 if waiting_for_player else 0,
            json.dumps(unresolved_hooks or [], ensure_ascii=False),
            real_now_iso,
            world_now_iso,
            daily_message_date,
            daily_message_date,
            autonomous_message_count,
            autonomous_message_count,
            real_now_iso,
            group_thread_id,
            lease_owner,
        ),
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

    with get_conn() as conn:
        for response in candidate_responses:
            temporary_message_id = response.get("message_id")
            reply_to_message_id = resolved_message_id(
                response.get("reply_to_message_id")
            )
            recent_rows = conn.execute(
                """
                SELECT id, content, reply_to_message_id
                FROM short_term_message
                WHERE session_id = ?
                  AND role = 'assistant'
                  AND character_id = ?
                ORDER BY id DESC
                LIMIT 20
                """,
                (session_id, response.get("character_id")),
            ).fetchall()
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
                VALUES (?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            if _is_postgres_enabled():
                insert_sql += " RETURNING id"
            cursor = conn.execute(
                insert_sql,
                (
                    session_id,
                    response.get("dialogue", ""),
                    response.get("character_id"),
                    response.get("character_name"),
                    real_now_iso,
                    _encode_knowledge_sources(response.get("knowledge_sources") or []),
                    response.get("world_created_at") or world_now_iso,
                    reply_to_message_id,
                    response.get("reply_to_character_id"),
                    response.get("intent"),
                    response.get("topic"),
                    response.get("trigger_source"),
                ),
            )
            message_id = int(
                cursor.fetchone()["id"] if _is_postgres_enabled() else cursor.lastrowid
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
                """
                INSERT INTO relationship_state
                (character_id, player_id, affection_level, trust_level,
                 current_mood, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id, player_id)
                DO UPDATE SET
                    affection_level = excluded.affection_level,
                    trust_level = excluded.trust_level,
                    current_mood = excluded.current_mood,
                    updated_at = excluded.updated_at
                """,
                (
                    character_id,
                    player_id,
                    response["current_affinity"],
                    response["current_trust"],
                    response["current_mood"],
                    real_now_iso,
                ),
            )

        for character_id, message_count in participant_counts.items():
            conn.execute(
                """
                UPDATE multi_session_participant
                SET last_spoke_at = ?,
                    message_count = message_count + ?
                WHERE session_id = ? AND character_id = ?
                """,
                (real_now_iso, message_count, session_id, character_id),
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
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE group_dialogue_state
            SET lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE group_thread_id = ? AND lease_owner = ?
            """,
            (_now(), group_thread_id, lease_owner),
        )
    return cursor.rowcount == 1


def get_latest_group_thread_session(group_thread_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM session
            WHERE COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = ?
            ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                     created_at DESC, session_id DESC
            LIMIT 1
            """,
            (group_thread_id,),
        ).fetchone()
    return _row_to_dict(row)


# =========================
# 世界观知识库
# =========================
_KNOWLEDGE_BINDING_TYPES = {"global", "character", "group_thread"}
_KNOWLEDGE_DOCUMENT_STATUSES = {"queued", "processing", "ready", "failed"}


def create_knowledge_base(
    owner_user_id: str,
    name: str,
    description: str | None = None,
) -> dict:
    knowledge_base_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_base
            (knowledge_base_id, owner_user_id, name, description,
             is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                knowledge_base_id,
                owner_user_id,
                name.strip(),
                (description or "").strip() or None,
                now,
                now,
            ),
        )
    return get_knowledge_base(owner_user_id, knowledge_base_id)


def get_knowledge_base(owner_user_id: str, knowledge_base_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id) AS document_count,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id
                      AND d.status = 'ready') AS ready_document_count,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = kb.owner_user_id
                      AND c.knowledge_base_id = kb.knowledge_base_id) AS chunk_count
            FROM knowledge_base kb
            WHERE kb.owner_user_id = ? AND kb.knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchone()
    return _row_to_dict(row)


def list_knowledge_bases(owner_user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id) AS document_count,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id
                      AND d.status = 'ready') AS ready_document_count,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = kb.owner_user_id
                      AND c.knowledge_base_id = kb.knowledge_base_id) AS chunk_count
            FROM knowledge_base kb
            WHERE kb.owner_user_id = ?
            ORDER BY kb.updated_at DESC, kb.name ASC
            """,
            (owner_user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_knowledge_base(
    owner_user_id: str,
    knowledge_base_id: str,
    *,
    name: str | None = None,
    description: str | None | object = _UNSET,
    is_enabled: bool | None = None,
) -> dict | None:
    assignments = []
    params: list = []
    if name is not None:
        assignments.append("name = ?")
        params.append(name.strip())
    if description is not _UNSET:
        assignments.append("description = ?")
        params.append(str(description or "").strip() or None)
    if is_enabled is not None:
        assignments.append("is_enabled = ?")
        params.append(1 if is_enabled else 0)
    if not assignments:
        return get_knowledge_base(owner_user_id, knowledge_base_id)

    assignments.append("updated_at = ?")
    params.extend([_now(), owner_user_id, knowledge_base_id])
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE knowledge_base
            SET {", ".join(assignments)}
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            tuple(params),
        )
    return get_knowledge_base(owner_user_id, knowledge_base_id)


def delete_knowledge_base(
    owner_user_id: str,
    knowledge_base_id: str,
) -> dict | None:
    existing = get_knowledge_base(owner_user_id, knowledge_base_id)
    if not existing:
        return None
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, created_at, updated_at)
            VALUES (?, ?, 'knowledge_base', ?, 0, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (cleanup_id, owner_user_id, knowledge_base_id, now, now),
        )
        documents = conn.execute(
            """
            SELECT document_id, storage_path
            FROM knowledge_document
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_document WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_binding WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_base WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
    return {
        "knowledge_base": existing,
        "documents": [dict(row) for row in documents],
        "vector_cleanup_id": get_knowledge_vector_cleanup_id(
            owner_user_id,
            "knowledge_base",
            knowledge_base_id,
        ),
    }


def _normalize_knowledge_binding(binding: dict) -> tuple[str, str]:
    target_type = str(binding.get("target_type") or "").strip()
    target_id = str(binding.get("target_id") or "").strip()
    if target_type not in _KNOWLEDGE_BINDING_TYPES:
        raise ValueError(f"不支持的知识库绑定类型: {target_type}")
    if target_type == "global":
        return target_type, ""
    if not target_id:
        raise ValueError(f"{target_type} 绑定必须提供 target_id")
    return target_type, target_id


def _validate_knowledge_binding_target(
    conn,
    owner_user_id: str,
    target_type: str,
    target_id: str,
) -> None:
    if target_type == "global":
        return
    if target_type == "character":
        row = conn.execute(
            """
            SELECT 1 FROM character_card
            WHERE owner_user_id = ? AND character_id = ?
            """,
            (owner_user_id, target_id),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT 1 FROM session
            WHERE player_id = ?
              AND COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = ?
            LIMIT 1
            """,
            (owner_user_id, target_id),
        ).fetchone()
    if not row:
        raise ValueError(f"绑定目标不存在或不属于当前用户: {target_type}/{target_id}")


def replace_knowledge_bindings(
    owner_user_id: str,
    knowledge_base_id: str,
    bindings: list[dict],
) -> list[dict]:
    normalized = list(dict.fromkeys(_normalize_knowledge_binding(item) for item in bindings))
    with get_conn() as conn:
        base = conn.execute(
            """
            SELECT 1 FROM knowledge_base
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchone()
        if not base:
            raise ValueError("知识库不存在")

        for target_type, target_id in normalized:
            _validate_knowledge_binding_target(
                conn, owner_user_id, target_type, target_id
            )

        conn.execute(
            """
            DELETE FROM knowledge_binding
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        )
        if normalized:
            conn.executemany(
                """
                INSERT INTO knowledge_binding
                (owner_user_id, knowledge_base_id, target_type, target_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (owner_user_id, knowledge_base_id, target_type, target_id, _now())
                    for target_type, target_id in normalized
                ],
            )
        conn.execute(
            """
            UPDATE knowledge_base SET updated_at = ?
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (_now(), owner_user_id, knowledge_base_id),
        )
    return list_knowledge_bindings(owner_user_id, knowledge_base_id)


def list_knowledge_bindings(
    owner_user_id: str,
    knowledge_base_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT target_type, target_id, created_at
            FROM knowledge_binding
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            ORDER BY target_type ASC, target_id ASC
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_knowledge_binding_targets(owner_user_id: str) -> dict:
    with get_conn() as conn:
        characters = conn.execute(
            """
            SELECT character_id, COALESCE(display_name, name, character_id) AS name
            FROM character_card
            WHERE owner_user_id = ? AND is_active = 1
            ORDER BY name ASC
            """,
            (owner_user_id,),
        ).fetchall()
        groups = conn.execute(
            """
            SELECT COALESCE(group_thread_id, session_id) AS group_thread_id,
                   MAX(COALESCE(group_name, '未命名群聊')) AS name,
                   MAX(created_at) AS last_active_at
            FROM session
            WHERE player_id = ? AND COALESCE(is_multi_character, 0) = 1
            GROUP BY COALESCE(group_thread_id, session_id)
            ORDER BY last_active_at DESC
            """,
            (owner_user_id,),
        ).fetchall()
    return {
        "characters": [dict(row) for row in characters],
        "group_threads": [dict(row) for row in groups],
    }


def create_knowledge_document(
    owner_user_id: str,
    knowledge_base_id: str,
    *,
    original_name: str,
    media_type: str,
    source_type: str,
    storage_path: str | None,
    checksum: str,
    byte_size: int,
) -> dict:
    if not get_knowledge_base(owner_user_id, knowledge_base_id):
        raise ValueError("知识库不存在")
    document_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_document
            (document_id, owner_user_id, knowledge_base_id, original_name,
             media_type, source_type, storage_path, checksum, byte_size,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                document_id,
                owner_user_id,
                knowledge_base_id,
                original_name,
                media_type,
                source_type,
                storage_path,
                checksum,
                byte_size,
                now,
                now,
            ),
        )
    return get_knowledge_document(owner_user_id, document_id)


def get_knowledge_document(owner_user_id: str, document_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.owner_user_id = ? AND d.document_id = ?
            """,
            (owner_user_id, document_id),
        ).fetchone()
    return _row_to_dict(row)


def list_knowledge_documents(
    owner_user_id: str,
    knowledge_base_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.owner_user_id = ? AND d.knowledge_base_id = ?
            ORDER BY d.created_at DESC
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_incomplete_knowledge_documents() -> list[dict]:
    """Return queued or interrupted documents so startup can resume indexing."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.status IN ('queued', 'processing')
            ORDER BY d.created_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def claim_knowledge_document_for_processing(
    owner_user_id: str,
    document_id: str,
    *,
    expected_status: str,
    expected_updated_at: str,
) -> bool:
    """Atomically claim a queued or interrupted document for one worker."""
    if expected_status not in {"queued", "processing"}:
        return False
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE knowledge_document
            SET status = 'processing', error_message = NULL, updated_at = ?
            WHERE owner_user_id = ?
              AND document_id = ?
              AND status = ?
              AND updated_at = ?
            """,
            (
                _now(),
                owner_user_id,
                document_id,
                expected_status,
                expected_updated_at,
            ),
        )
        return cursor.rowcount == 1


def update_knowledge_document_status(
    owner_user_id: str,
    document_id: str,
    status: str,
    *,
    error_message: str | None = None,
    extracted_chars: int | None = None,
    page_count: int | None = None,
) -> dict | None:
    if status not in _KNOWLEDGE_DOCUMENT_STATUSES:
        raise ValueError(f"无效文档状态: {status}")
    assignments = ["status = ?", "error_message = ?", "updated_at = ?"]
    params: list = [status, error_message, _now()]
    if extracted_chars is not None:
        assignments.append("extracted_chars = ?")
        params.append(extracted_chars)
    if page_count is not None:
        assignments.append("page_count = ?")
        params.append(page_count)
    params.extend([owner_user_id, document_id])
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE knowledge_document
            SET {", ".join(assignments)}
            WHERE owner_user_id = ? AND document_id = ?
            """,
            tuple(params),
        )
    return get_knowledge_document(owner_user_id, document_id)


def replace_knowledge_chunks(
    owner_user_id: str,
    document_id: str,
    chunks: list[dict],
) -> list[dict]:
    document = get_knowledge_document(owner_user_id, document_id)
    if not document:
        raise ValueError("知识文档不存在")
    now = _now()
    prepared = []
    for index, chunk in enumerate(chunks):
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        prepared.append(
            (
                str(chunk.get("chunk_id") or uuid.uuid4()),
                owner_user_id,
                document["knowledge_base_id"],
                document_id,
                int(chunk.get("chunk_index", index)),
                content,
                len(content),
                json.dumps(chunk.get("source_metadata") or {}, ensure_ascii=False),
                now,
            )
        )
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
        if prepared:
            conn.executemany(
                """
                INSERT INTO knowledge_chunk
                (chunk_id, owner_user_id, knowledge_base_id, document_id,
                 chunk_index, content, char_count, source_metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                prepared,
            )
    return list_knowledge_chunks(owner_user_id, document_id)


def list_knowledge_chunks(owner_user_id: str, document_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM knowledge_chunk
            WHERE owner_user_id = ? AND document_id = ?
            ORDER BY chunk_index ASC
            """,
            (owner_user_id, document_id),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def _decode_knowledge_chunk_row(row) -> dict:
    item = dict(row)
    try:
        item["source_metadata"] = json.loads(item.get("source_metadata") or "{}")
    except (TypeError, ValueError):
        item["source_metadata"] = {}
    return item


def clear_knowledge_document_chunks(owner_user_id: str, document_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )


def delete_knowledge_document(
    owner_user_id: str,
    document_id: str,
) -> dict | None:
    document = get_knowledge_document(owner_user_id, document_id)
    if not document:
        return None
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, created_at, updated_at)
            VALUES (?, ?, 'document', ?, 0, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (cleanup_id, owner_user_id, document_id, now, now),
        )
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
        conn.execute(
            "DELETE FROM knowledge_document WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
    return {
        **document,
        "vector_cleanup_id": get_knowledge_vector_cleanup_id(
            owner_user_id,
            "document",
            document_id,
        ),
    }


def get_knowledge_vector_cleanup_id(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT cleanup_id
            FROM knowledge_vector_cleanup
            WHERE owner_user_id = ? AND scope_type = ? AND scope_id = ?
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchone()
    return row["cleanup_id"] if row else None


def enqueue_knowledge_vector_cleanup(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    *,
    error: str | None = None,
) -> str:
    if scope_type not in {"document", "knowledge_base"}:
        raise ValueError("无效向量清理范围")
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                cleanup_id,
                owner_user_id,
                scope_type,
                scope_id,
                str(error or "")[:2000] or None,
                now,
                now,
            ),
        )
    return (
        get_knowledge_vector_cleanup_id(owner_user_id, scope_type, scope_id)
        or cleanup_id
    )


def list_knowledge_vector_cleanups(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_vector_cleanup
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def complete_knowledge_vector_cleanup(cleanup_id: str | None) -> None:
    if not cleanup_id:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_vector_cleanup WHERE cleanup_id = ?",
            (cleanup_id,),
        )


def fail_knowledge_vector_cleanup(cleanup_id: str, error: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE knowledge_vector_cleanup
            SET attempts = attempts + 1, last_error = ?, updated_at = ?
            WHERE cleanup_id = ?
            """,
            (str(error)[:2000], _now(), cleanup_id),
        )


def list_all_knowledge_chunks_for_indexing() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*, d.original_name AS document_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            WHERE d.status = 'ready'
            ORDER BY c.document_id, c.chunk_index
            """
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def get_authorized_knowledge_chunks(
    owner_user_id: str,
    chunk_ids: list[str],
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[dict]:
    """Revalidate vector hits against current SQL ownership, status and bindings."""
    if not chunk_ids:
        return []
    visibility = ["b.target_type = 'global'"]
    visibility_params: list = []
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        visibility_params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        visibility_params.append(group_thread_id)

    placeholders = ", ".join("?" for _ in chunk_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.chunk_id IN ({placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
              AND EXISTS (
                  SELECT 1 FROM knowledge_binding b
                  WHERE b.owner_user_id = c.owner_user_id
                    AND b.knowledge_base_id = c.knowledge_base_id
                    AND ({" OR ".join(visibility)})
              )
            """,
            tuple([owner_user_id, *chunk_ids, *visibility_params]),
        ).fetchall()
    by_id = {
        row["chunk_id"]: _decode_knowledge_chunk_row(row)
        for row in rows
    }
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


def get_owned_knowledge_chunks(
    owner_user_id: str,
    chunk_ids: list[str],
    *,
    knowledge_base_ids: list[str],
) -> list[dict]:
    """Load ready, enabled chunks from owner-validated knowledge bases."""
    if not chunk_ids or not knowledge_base_ids:
        return []
    chunk_placeholders = ", ".join("?" for _ in chunk_ids)
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.chunk_id IN ({chunk_placeholders})
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
            """,
            tuple([owner_user_id, *chunk_ids, *knowledge_base_ids]),
        ).fetchall()
    by_id = {
        row["chunk_id"]: _decode_knowledge_chunk_row(row)
        for row in rows
    }
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


def list_authorized_knowledge_chunks(
    owner_user_id: str,
    *,
    knowledge_base_ids: list[str],
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[dict]:
    """List the SQL corpus visible to a dialogue for independent keyword search."""
    if not knowledge_base_ids:
        return []
    visibility = ["b.target_type = 'global'"]
    visibility_params: list = []
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        visibility_params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        visibility_params.append(group_thread_id)
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
              AND EXISTS (
                  SELECT 1 FROM knowledge_binding b
                  WHERE b.owner_user_id = c.owner_user_id
                    AND b.knowledge_base_id = c.knowledge_base_id
                    AND ({" OR ".join(visibility)})
              )
            ORDER BY c.document_id, c.chunk_index
            """,
            tuple(
                [
                    owner_user_id,
                    *knowledge_base_ids,
                    *visibility_params,
                ]
            ),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def list_owned_knowledge_chunks_for_bases(
    owner_user_id: str,
    *,
    knowledge_base_ids: list[str],
) -> list[dict]:
    """List ready chunks in owner-validated bases for admin retrieval preview."""
    if not knowledge_base_ids:
        return []
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
            ORDER BY c.document_id, c.chunk_index
            """,
            tuple([owner_user_id, *knowledge_base_ids]),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def get_authorized_knowledge_base_ids(
    owner_user_id: str,
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[str]:
    visibility = ["b.target_type = 'global'"]
    params: list = [owner_user_id]
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        params.append(group_thread_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT kb.knowledge_base_id
            FROM knowledge_base kb
            INNER JOIN knowledge_binding b
              ON b.owner_user_id = kb.owner_user_id
             AND b.knowledge_base_id = kb.knowledge_base_id
            INNER JOIN knowledge_document d
              ON d.owner_user_id = kb.owner_user_id
             AND d.knowledge_base_id = kb.knowledge_base_id
            WHERE kb.owner_user_id = ?
              AND kb.is_enabled = 1
              AND d.status = 'ready'
              AND ({" OR ".join(visibility)})
            ORDER BY kb.knowledge_base_id
            """,
            tuple(params),
        ).fetchall()
    return [row["knowledge_base_id"] for row in rows]


def has_authorized_knowledge_bases(
    owner_user_id: str,
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> bool:
    return bool(
        get_authorized_knowledge_base_ids(
            owner_user_id,
            character_id=character_id,
            group_thread_id=group_thread_id,
        )
    )



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
