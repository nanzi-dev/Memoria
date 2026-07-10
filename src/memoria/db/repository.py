"""
数据持久化层（SQLite）

设计目标：
- 单文件轻量数据库（适合 demo / MVP）
- 支持角色状态 + 记忆 + 会话管理
- 后续可无缝迁移 PostgreSQL（SQL 层隔离）
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import logging
import sqlite3

from memoria.core.config import configs
import re
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

# =========================
# 工具函数
# =========================
def _now() -> str:
    """统一时间格式（UTC ISO8601）"""
    return datetime.now(timezone.utc).isoformat()

def _row_to_dict(row):
    """安全转换 sqlite Row -> dict"""
    return dict(row) if row is not None else None


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
# SQLite 连接管理
# =========================
@contextmanager
def get_conn():
    """
    SQLite 连接上下文管理
    """
    conn = sqlite3.connect(
        configs.database_path,
        timeout=30,
        check_same_thread = False # 避免多线程问题
    )
    
    conn.row_factory = sqlite3.Row
    
    # WAL 模式（推荐用于并发读写）
    conn.execute("PRAGMA journal_mode=WAL;")
    _migrate(conn)
    try:
        conn.execute("ALTER TABLE session ADD COLUMN group_name TEXT")
    except Exception:
        pass
    
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
    password_hash   TEXT NOT NULL,         -- sha256 hash
    gender          TEXT DEFAULT 'unknown', -- male/female/unknown
    avatar_url      TEXT,                  -- base64 data URL
    created_at      TEXT,
    updated_at      TEXT
);

-- =========================
-- 角色卡存储
-- =========================
CREATE TABLE IF NOT EXISTS character_card (
    character_id    TEXT PRIMARY KEY,
    
    card_data       TEXT NOT NULL,      -- 完整的角色卡 JSON 数据
    version         TEXT DEFAULT '1.0.0',
    
    -- 元信息（便于查询和展示）
    name            TEXT,
    display_name    TEXT,
    avatar_url      TEXT,               -- 头像（base64 data URL 或网络 URL）
    
    created_at      TEXT,
    updated_at      TEXT,
    
    -- 状态标记
    is_active       INTEGER DEFAULT 1,  -- 1=启用, 0=禁用
    source          TEXT DEFAULT 'db'   -- 'db'=数据库创建, 'file'=从文件导入
);

-- =========================
-- 事件定义表
-- =========================
CREATE TABLE IF NOT EXISTS event_definition (
    event_id        TEXT PRIMARY KEY,
    event_name      TEXT NOT NULL,
    description     TEXT,
    
    character_id    TEXT,               -- 角色专属事件，NULL 表示全局
    
    -- 事件配置（JSON 格式）
    trigger_config  TEXT NOT NULL,      -- TriggerCondition JSON
    effects_config  TEXT NOT NULL,      -- EventEffect[] JSON
    
    priority        INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    
    created_at      TEXT,
    updated_at      TEXT,
    
    trigger_count   INTEGER DEFAULT 0,
    last_triggered_at TEXT
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
    
    FOREIGN KEY (event_id) REFERENCES event_definition(event_id)
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
    status          TEXT DEFAULT 'active',

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
    
    character_id_a  TEXT NOT NULL,      -- 角色 A
    character_id_b  TEXT NOT NULL,      -- 角色 B
    
    -- 关系类型
    relationship_type TEXT,             -- friend, enemy, family, rival, mentor, etc.
    
    -- 关系强度和描述
    affinity        REAL DEFAULT 0.0,   -- 关系亲密度（-100 ~ 100）
    description     TEXT,               -- 关系描述
    
    -- 元数据
    created_at      TEXT,
    updated_at      TEXT,
    
    -- 确保同一对角色只有一条关系记录（无向关系）
    UNIQUE(character_id_a, character_id_b)
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
    
    created_at      TEXT
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
-- 索引优化
-- =========================

CREATE INDEX IF NOT EXISTS idx_session_lookup
ON session(character_id, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_session_multi
ON session(is_multi_character, player_id, created_at DESC);

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

CREATE INDEX IF NOT EXISTS idx_character_active
ON character_card(is_active, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_character
ON event_definition(character_id, is_active);

CREATE INDEX IF NOT EXISTS idx_event_trigger_log
ON event_trigger_log(event_id, character_id, player_id, triggered_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_context_lookup
ON event_context_state(character_id, player_id, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_schedule_due
ON event_schedule_state(status, next_run_at);


-- =========================
-- 多角色共享记忆（角色间）
-- =========================
CREATE TABLE IF NOT EXISTS shared_memory (
    id              TEXT PRIMARY KEY,
    character_a_id  TEXT NOT NULL,
    character_b_id  TEXT NOT NULL,
    memory_text     TEXT NOT NULL,
    context         TEXT,
    importance      REAL DEFAULT 0.5,
    created_at      TEXT,
    last_referenced TEXT,
    reference_count INTEGER DEFAULT 0
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
ON character_relationship(character_id_a, character_id_b);
"""

def _migrate(conn):
    """数据库迁移：为已有数据库添加新列"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS event_context_state (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id        TEXT NOT NULL,
            character_id    TEXT NOT NULL,
            player_id       TEXT NOT NULL,
            context_data    TEXT NOT NULL DEFAULT '{}',
            status          TEXT DEFAULT 'active',
            progress        REAL DEFAULT 0.0,
            last_session_id TEXT,
            created_at      TEXT,
            updated_at      TEXT,
            UNIQUE(event_id, character_id, player_id)
        );

        CREATE TABLE IF NOT EXISTS event_schedule_state (
            event_id        TEXT NOT NULL,
            character_id    TEXT NOT NULL,
            player_id       TEXT NOT NULL,
            schedule        TEXT NOT NULL,
            last_checked_at TEXT,
            last_run_at     TEXT,
            next_run_at     TEXT,
            status          TEXT DEFAULT 'active',
            created_at      TEXT,
            updated_at      TEXT,
            PRIMARY KEY (event_id, character_id, player_id)
        );

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
        """
    )

    def add_column(table: str, column_sql: str) -> None:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")
        except Exception:
            pass  # 列已存在，跳过

    try:
        conn.execute("ALTER TABLE character_card ADD COLUMN avatar_url TEXT")
    except Exception:
        pass  # 列已存在，跳过
    try:
        conn.execute("ALTER TABLE session_summary ADD COLUMN summary_status TEXT DEFAULT 'completed'")
    except Exception:
        pass  # 列已存在，跳过
    try:
        conn.execute("ALTER TABLE session ADD COLUMN group_name TEXT")
    except Exception:
        pass  # 列已存在，跳过
    add_column("event_definition", "schedule TEXT")
    add_column("event_definition", "template_id TEXT")
    add_column("event_context_state", "context_data TEXT NOT NULL DEFAULT '{}'")
    add_column("event_context_state", "status TEXT DEFAULT 'active'")
    add_column("event_context_state", "progress REAL DEFAULT 0.0")
    add_column("event_context_state", "last_session_id TEXT")
    add_column("event_context_state", "created_at TEXT")
    add_column("event_context_state", "updated_at TEXT")
    add_column("event_schedule_state", "schedule TEXT NOT NULL DEFAULT '* * * * *'")
    add_column("event_schedule_state", "last_checked_at TEXT")
    add_column("event_schedule_state", "last_run_at TEXT")
    add_column("event_schedule_state", "next_run_at TEXT")
    add_column("event_schedule_state", "status TEXT DEFAULT 'active'")
    add_column("event_schedule_state", "created_at TEXT")
    add_column("event_schedule_state", "updated_at TEXT")


def init_db():
    """初始化数据库结构"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


# =========================
# runtime_state（角色状态）
# =========================
def get_runtime_state(
    character_id: str, 
    player_id: str, 
    card,
    query_context: str = None
) -> dict:
     """
    获取角色运行时状态（好感度 / 信任 / 情绪）

    如果不存在 → 使用角色卡默认值初始化
    
    Args:
        character_id: 角色 ID
        player_id: 玩家 ID
        card: 角色卡对象
        query_context: 查询上下文（用于向量检索长期记忆）
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
             schema = card.runtime_state_schema
             
             state = {
                 "affection_level": getattr(schema, "affection_level", 0),
                 "trust_level": getattr(schema, "trust_level", 10),
                 "current_mood": schema.current_mood.default_mood,
             }
             
             conn.execute(
                """
                INSERT INTO relationship_state
                (character_id, player_id, affection_level, trust_level, current_mood, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
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
             
         # 绑定长期记忆（支持向量检索）
         state["known_player_facts"] = get_long_term_facts(
             character_id, 
             player_id,
             query_context=query_context
         )
         return state
     

def save_runtime_state(character_id: str, player_id: str, affection_level: float, trust_level: float, current_mood: str):
    """更新角色状态"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO relationship_state
            (character_id, player_id, affection_level, trust_level, current_mood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id, player_id)
            DO UPDATE SET
                affection_level=excluded.affection_level,
                trust_level=excluded.trust_level,
                current_mood=excluded.current_mood,
                updated_at=excluded.updated_at
            """,
            (character_id, player_id, affection_level, trust_level, current_mood, _now()),
        )
        

# =========================
# long term memory
# =========================
def get_long_term_facts(
    character_id: str, 
    player_id: str, 
    limit: int = 20,
    query_context: str = None
) -> list[str]:
    """
    获取长期记忆
    
    Args:
        character_id: 角色 ID
        player_id: 玩家 ID
        limit: 返回的最大记忆数量
        query_context: 查询上下文（用于向量检索），如果提供则使用语义检索
    
    Returns:
        list[str]: 记忆文本列表
    """
    # 如果提供了查询上下文，使用向量检索
    if query_context:
        try:
            from memoria.core.vector_memory import get_vector_store
            vector_store = get_vector_store()
            
            # 向量检索获取相关记忆
            vector_results = vector_store.search_similar_memories(
                character_id=character_id,
                player_id=player_id,
                query_text=query_context,
                top_k=limit
            )
            
            if vector_results:
                logger.debug(f"向量检索返回 {len(vector_results)} 条记忆")
                return [r["fact_text"] for r in vector_results]
                
        except Exception as e:
            logger.warning(f"向量检索失败，回退到传统查询: {e}")
    
    # 传统查询（按重要性和最近引用排序）
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT fact_text
            FROM long_term_fact
            WHERE character_id = ? AND player_id = ?
            ORDER BY importance DESC, last_referenced DESC
            LIMIT ?
            """,
            (character_id, player_id, limit),
        ).fetchall()
        
    return [r["fact_text"] for r in rows]

def save_long_term_fact(
    character_id: str, 
    player_id: str, 
    fact_text: str, 
    importance: int = 5
) -> int:
    """
    保存长期记忆（同时保存到 SQLite 和向量数据库）
    
    Returns:
        int: 新插入的 fact_id
    """
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

        cursor = conn.execute(
            """
            INSERT INTO long_term_fact
            (character_id, player_id, fact_text, importance, created_at, last_referenced)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (character_id, player_id, fact_text, importance, _now(), _now()),
        )
        fact_id = cursor.lastrowid
        
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
        

# =========================
# session 管理
# =========================
def create_session(session_id: str, character_id: str, player_id: str, player_name: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO session
            (session_id, character_id, player_id, player_name, created_at, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (session_id, character_id, player_id, player_name, _now()),
        )
        
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


# =========================
# short term memory（对话历史）
# =========================
def append_short_term_message(session_id: str, role: str, content: str) -> int:
    """
    追加短期对话消息。

    Returns:
        int: 新消息的 id
    """
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO short_term_message
            (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, _now()),
        )
        return cursor.lastrowid
        
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
            LEFT JOIN character_card c ON c.character_id = s.character_id
            WHERE s.character_id = ? AND s.player_id = ? AND COALESCE(s.is_multi_character, 0) = 0
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            """,
            (character_id, player_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_player_sessions(player_id: str) -> list[dict]:
    """查询玩家所有会话（单聊 + 群聊），含最后消息"""
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
            LEFT JOIN character_card c ON c.character_id = s.character_id
            WHERE s.player_id = ?
            ORDER BY COALESCE(last_message_at, s.created_at) DESC
            """,
            (player_id,),
        ).fetchall()
    return [dict(r) for r in rows]


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
            SELECT id AS message_id, role, content, created_at
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit + 1, offset),
        ).fetchall()

    has_more = len(rows) > limit
    # 取前 limit 条，并反转顺序（变回正序）
    messages = [dict(r) for r in reversed(rows[:limit])]

    return messages, has_more


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
                m.created_at,
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
        [dict(r) for r in reversed(rows[:limit])],
        has_more,
    )

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
# 角色间共享记忆（shared_memory）
# =========================
def save_shared_memory(
    character_a_id: str,
    character_b_id: str,
    memory_text: str,
    context: str = None,
    importance: float = 0.5
) -> str:
    """保存两个角色之间的共享记忆。含去重检查。"""
    import uuid
    memory_id = str(uuid.uuid4())
    a, b = sorted([character_a_id, character_b_id])

    with get_conn() as conn:
        existing = _dedup_check(
            conn, "shared_memory", "memory_text", memory_text,
            "character_a_id = ? AND character_b_id = ?",
            (a, b), threshold=0.75
        )
        if existing:
            new_imp = max(existing.get("importance", 0), importance)
            conn.execute("UPDATE shared_memory SET importance=?, last_referenced=? WHERE id=?",
                         (new_imp, _now(), existing["id"]))
            return existing["id"]

        conn.execute(
            "INSERT INTO shared_memory (id, character_a_id, character_b_id, memory_text, context, importance, created_at, last_referenced, reference_count) VALUES (?,?,?,?,?,?,?,?,0)",
            (memory_id, a, b, memory_text, context, importance, _now(), _now()))

    return memory_id


def get_shared_memories(character_id_a: str, character_id_b: str, limit: int = 10) -> list[dict]:
    """获取两个角色之间的共享记忆"""
    a, b = sorted([character_id_a, character_id_b])
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, memory_text, context, importance, created_at FROM shared_memory WHERE character_a_id=? AND character_b_id=? ORDER BY importance DESC, last_referenced DESC LIMIT ?",
            (a, b, limit)).fetchall()
    return [dict(r) for r in rows]


def get_character_shared_memories(character_id: str, limit: int = 20) -> list[dict]:
    """获取某个角色与其他所有角色的共享记忆"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, character_a_id, character_b_id, memory_text, context, importance, created_at FROM shared_memory WHERE character_a_id=? OR character_b_id=? ORDER BY importance DESC, last_referenced DESC LIMIT ?",
            (character_id, character_id, limit)).fetchall()
    return [dict(r) for r in rows]


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


def get_session_group_memories(session_id: str, limit: int = 20) -> list[dict]:
    """获取某个会话的群体记忆"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, memory_text, participants, context, importance, created_at FROM group_memory WHERE session_id=? ORDER BY importance DESC, last_referenced DESC LIMIT ?",
            (session_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_character_group_memories(character_id: str, limit: int = 20) -> list[dict]:
    """获取某个角色参与过的群体记忆"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, session_id, memory_text, participants, context, importance, created_at FROM group_memory WHERE participants LIKE ? ORDER BY importance DESC, last_referenced DESC LIMIT ?",
            (f"%{character_id}%", limit)).fetchall()
    return [dict(r) for r in rows]

# =========================
# 角色卡管理（CRUD）
# =========================
def save_character_card_to_db(
    character_id: str,
    card_data_json: str,
    version: str = "1.0.0",
    name: str = None,
    display_name: str = None,
    source: str = "db",
    avatar_url: str = None
) -> bool:
    """
    保存或更新角色卡到数据库
    
    Args:
        character_id: 角色 ID
        card_data_json: 完整的角色卡 JSON 字符串
        version: 版本号
        name: 角色名称（用于快速查询）
        display_name: 显示名称
        source: 来源标记（'db'=数据库创建, 'file'=从文件导入）
    
    Returns:
        bool: 是否保存成功
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO character_card
                (character_id, card_data, version, name, display_name, avatar_url, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id)
                DO UPDATE SET
                    card_data=excluded.card_data,
                    version=excluded.version,
                    name=excluded.name,
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    updated_at=excluded.updated_at
                """,
                (character_id, card_data_json, version, name, display_name, avatar_url, _now(), _now(), source),
            )
        logger.info(f"角色卡已保存到数据库: {character_id}")
        return True
    except Exception as e:
        logger.error(f"保存角色卡失败: {e}")
        return False

def get_character_card_from_db(character_id: str, include_inactive: bool = False) -> dict | None:
    """
    从数据库获取角色卡
    
    Args:
        character_id: 角色 ID
        include_inactive: 是否包含已禁用的角色卡（默认 False）
    
    Returns:
        dict: 角色卡数据，包含 card_data (JSON字符串) 等字段，不存在则返回 None
    """
    with get_conn() as conn:
        if include_inactive:
            row = conn.execute(
                "SELECT * FROM character_card WHERE character_id = ?",
                (character_id,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT * FROM character_card
                WHERE character_id = ? AND is_active = 1
                """,
                (character_id,),
            ).fetchone()
    
    return _row_to_dict(row)



def update_character_avatar(character_id: str, avatar_url: str | None) -> bool:
    """更新角色头像 URL"""
    try:
        with get_conn() as conn:
            conn.execute(
                "UPDATE character_card SET avatar_url = ?, updated_at = ? WHERE character_id = ?",
                (avatar_url, _now(), character_id),
            )
        logger.info(f"头像已更新: character_id={character_id}")
        return True
    except Exception as e:
        logger.error(f"更新头像失败: {e}")
        return False

def list_character_cards_from_db(only_active: bool = True) -> list[dict]:
    """
    列出所有角色卡（仅返回元信息，不包含完整 card_data）
    
    Args:
        only_active: 是否仅返回启用的角色卡
    
    Returns:
        list[dict]: 角色卡元信息列表
    """
    with get_conn() as conn:
        query = """
            SELECT character_id, name, display_name, version, avatar_url, created_at, updated_at, is_active, source
            FROM character_card
        """
        if only_active:
            query += " WHERE is_active = 1"
        
        query += " ORDER BY created_at DESC"
        
        rows = conn.execute(query).fetchall()
    
    return [dict(r) for r in rows]

def delete_character_card_from_db(character_id: str, soft_delete: bool = True) -> bool:
    """
    删除角色卡
    
    Args:
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
                    WHERE character_id = ?
                    """,
                    (_now(), character_id),
                )
            else:
                # 硬删除：真实删除记录
                conn.execute(
                    "DELETE FROM character_card WHERE character_id = ?",
                    (character_id,),
                )
        logger.info(f"角色卡已{'禁用' if soft_delete else '删除'}: {character_id}")
        return True
    except Exception as e:
        logger.error(f"删除角色卡失败: {e}")
        return False

def activate_character_card(character_id: str) -> bool:
    """
    激活已禁用的角色卡
    
    Args:
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
                WHERE character_id = ?
                """,
                (_now(), character_id),
            )
        logger.info(f"角色卡已激活: {character_id}")
        return True
    except Exception as e:
        logger.error(f"激活角色卡失败: {e}")
        return False


# =========================
# 事件系统 - 事件定义
# =========================
def save_event_definition(
    event_id: str,
    event_name: str,
    trigger_config: str,
    effects_config: str,
    character_id: str = None,
    description: str = None,
    priority: int = 0,
    is_active: bool = True,
    schedule: str = None,
    template_id: str = None,
) -> bool:
    """保存事件定义"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_definition
                (event_id, event_name, description, character_id, trigger_config, 
                 effects_config, priority, is_active, created_at, updated_at, schedule, template_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id)
                DO UPDATE SET
                    event_name=excluded.event_name,
                    description=excluded.description,
                    character_id=excluded.character_id,
                    trigger_config=excluded.trigger_config,
                    effects_config=excluded.effects_config,
                    priority=excluded.priority,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at,
                    schedule=excluded.schedule,
                    template_id=excluded.template_id
                """,
                (event_id, event_name, description, character_id, trigger_config,
                 effects_config, priority, 1 if is_active else 0, _now(), _now(), schedule, template_id),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件定义失败: {e}")
        return False

def get_event_definition(event_id: str) -> dict | None:
    """获取单个事件定义"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM event_definition WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    return _row_to_dict(row)

def list_event_definitions(
    character_id: str = None,
    only_active: bool = True
) -> list[dict]:
    """列出事件定义"""
    with get_conn() as conn:
        query = "SELECT * FROM event_definition WHERE 1=1"
        params = []
        
        if character_id is not None:
            query += " AND (character_id = ? OR character_id IS NULL)"
            params.append(character_id)
        
        if only_active:
            query += " AND is_active = 1"
        
        query += " ORDER BY priority DESC, created_at DESC"
        
        rows = conn.execute(query, params).fetchall()
    
    return [dict(r) for r in rows]

def delete_event_definition(event_id: str) -> bool:
    """删除事件定义"""
    try:
        with get_conn() as conn:
            conn.execute(
                "DELETE FROM event_definition WHERE event_id = ?",
                (event_id,),
            )
        return True
    except Exception as e:
        logger.error(f"删除事件定义失败: {e}")
        return False

def increment_event_trigger_count(event_id: str):
    """增加事件触发计数"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE event_definition
            SET trigger_count = trigger_count + 1,
                last_triggered_at = ?
            WHERE event_id = ?
            """,
            (_now(), event_id),
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

def get_last_trigger_time(event_id: str, character_id: str, player_id: str) -> str | None:
    """获取事件最后触发时间（用于冷却时间判断）"""
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT triggered_at FROM event_trigger_log
            WHERE event_id = ? AND character_id = ? AND player_id = ?
            ORDER BY triggered_at DESC
            LIMIT 1
            """,
            (event_id, character_id, player_id),
        ).fetchone()
    
    return row["triggered_at"] if row else None

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


def save_event_schedule_state(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    next_run_at: str = None,
    last_checked_at: str = None,
    last_run_at: str = None,
    status: str = "active",
) -> bool:
    """保存时间驱动事件的调度状态。"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_schedule_state
                (event_id, character_id, player_id, schedule, last_checked_at,
                 last_run_at, next_run_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, character_id, player_id)
                DO UPDATE SET
                    schedule=excluded.schedule,
                    last_checked_at=excluded.last_checked_at,
                    last_run_at=excluded.last_run_at,
                    next_run_at=excluded.next_run_at,
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                (event_id, character_id, player_id, schedule, last_checked_at,
                 last_run_at, next_run_at, status, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存事件调度状态失败: {e}")
        return False


def list_due_event_schedules(now_iso: str, limit: int = 50) -> list[dict]:
    """列出到期的调度事件。"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM event_schedule_state
            WHERE status = 'active'
              AND next_run_at IS NOT NULL
              AND next_run_at <= ?
            ORDER BY next_run_at ASC
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
    return [dict(r) for r in rows]


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
    

# =========================
# 角色关系网络
# =========================
def save_character_relationship(
    character_id_a: str,
    character_id_b: str,
    relationship_type: str,
    affinity: float = 0.0,
    description: str = None
) -> bool:
    """保存角色关系（无向关系，自动排序确保唯一性）"""
    try:
        # 确保 character_id_a < character_id_b（字母序）
        if character_id_a > character_id_b:
            character_id_a, character_id_b = character_id_b, character_id_a
        
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO character_relationship
                (character_id_a, character_id_b, relationship_type, affinity, 
                 description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id_a, character_id_b)
                DO UPDATE SET
                    relationship_type=excluded.relationship_type,
                    affinity=excluded.affinity,
                    description=excluded.description,
                    updated_at=excluded.updated_at
                """,
                (character_id_a, character_id_b, relationship_type, affinity,
                 description, _now(), _now()),
            )
        return True
    except Exception as e:
        logger.error(f"保存角色关系失败: {e}")
        return False

def get_character_relationship(character_id_a: str, character_id_b: str) -> dict | None:
    """获取两个角色之间的关系"""
    # 排序确保查询顺序一致
    if character_id_a > character_id_b:
        character_id_a, character_id_b = character_id_b, character_id_a
    
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT * FROM character_relationship
            WHERE character_id_a = ? AND character_id_b = ?
            """,
            (character_id_a, character_id_b),
        ).fetchone()
    
    return _row_to_dict(row)

def list_character_relationships(character_id: str) -> list[dict]:
    """列出指定角色的所有关系"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM character_relationship
            WHERE character_id_a = ? OR character_id_b = ?
            ORDER BY affinity DESC, updated_at DESC
            """,
            (character_id, character_id),
        ).fetchall()
        
    return [dict(r) for r in rows]

def list_all_character_relationships() -> list[dict]:
    """列出所有角色关系（用于关系网络可视化）"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM character_relationship
            ORDER BY affinity DESC, updated_at DESC
            """
        ).fetchall()
    
    return [dict(r) for r in rows]


def delete_character_relationship(character_id_a: str, character_id_b: str) -> bool:
    """删除角色关系"""
    try:
        if character_id_a > character_id_b:
            character_id_a, character_id_b = character_id_b, character_id_a
        
        with get_conn() as conn:
            conn.execute(
                """
                DELETE FROM character_relationship
                WHERE character_id_a = ? AND character_id_b = ?
                """,
                (character_id_a, character_id_b),
            )
        return True
    except Exception as e:
        logger.error(f"删除角色关系失败: {e}")
        return False
    
def delete_all_relationships_of_character(character_id: str) -> int:
    """删除某个角色涉及的所有关系"""
    with get_conn() as conn:
        cur = conn.execute(
            """
            DELETE FROM character_relationship
            WHERE character_id_a = ? OR character_id_b = ?
            """,
            (character_id, character_id),
        )
        return cur.rowcount

def update_relationship_affinity(
    character_id_a: str,
    character_id_b: str,
    affinity_delta: float
):
    """更新关系亲密度"""
    if character_id_a > character_id_b:
        character_id_a, character_id_b = character_id_b, character_id_a
    
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE character_relationship
            SET affinity = affinity + ?,
                updated_at = ?
            WHERE character_id_a = ? AND character_id_b = ?
            """,
            (affinity_delta, _now(), character_id_a, character_id_b),
        )



 


# =========================
# 多角色会话管理
# =========================

def create_multi_character_session(
    session_id: str,
    player_id: str,
    player_name: str,
    character_ids: list[str],
    speak_frequencies: dict[str, float] = None,
    group_name: str | None = None
) -> bool:
    """
    创建多角色群聊会话
    
    Args:
        session_id: 会话 ID
        player_id: 玩家 ID
        player_name: 玩家名称
        character_ids: 参与角色ID列表
        speak_frequencies: 角色发言频率配置 {character_id: frequency}
    
    Returns:
        bool: 是否创建成功
    """
    if not character_ids:
        logger.error("多角色会话必须至少包含一个角色")
        return False
    
    speak_frequencies = speak_frequencies or {}
    
    try:
        with get_conn() as conn:
            # 创建会话（使用第一个角色作为主角色）
            clean_group_name = (group_name or "").strip() or None
            conn.execute(
                """
                INSERT INTO session
                (session_id, character_id, player_id, player_name, created_at, status, group_name, is_multi_character)
                VALUES (?, ?, ?, ?, ?, 'active', ?, 1)
                """,
                (session_id, character_ids[0], player_id, player_name, _now(), clean_group_name),
            )
            
            # 添加参与者
            for idx, char_id in enumerate(character_ids):
                frequency = speak_frequencies.get(char_id, 1.0)
                conn.execute(
                    """
                    INSERT INTO multi_session_participant
                    (session_id, character_id, join_order, speak_frequency, is_active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                    """,
                    (session_id, char_id, idx, frequency, _now()),
                )
        
        logger.info(f"多角色会话已创建: {session_id}, 参与角色: {character_ids}")
        return True
    
    except Exception as e:
        logger.error(f"创建多角色会话失败: {e}")
        return False


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
            SELECT p.*, c.name, c.display_name, c.avatar_url
            FROM multi_session_participant p
            LEFT JOIN character_card c ON p.character_id = c.character_id
            WHERE p.session_id = ?
        """
        
        if only_active:
            query += " AND p.is_active = 1"
        
        query += " ORDER BY p.join_order ASC"
        
        rows = conn.execute(query, (session_id,)).fetchall()
    
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
    character_name: str = None
):
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
        conn.execute(
            """
            INSERT INTO short_term_message
            (session_id, role, content, character_id, character_name, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, role, content, character_id, character_name, _now()),
        )
    
    # 如果是角色发言，更新参与者统计
    if role == "assistant" and character_id:
        update_participant_speak_time(session_id, character_id)


def get_multi_character_history(
    session_id: str,
    limit_messages: int | None = 20
) -> list[dict]:
    """
    获取多角色会话历史
    
    Args:
        session_id: 会话 ID
        limit_messages: 最大消息数量；传 None 时返回全部消息
    
    Returns:
        list[dict]: 消息列表，包含 role, content, character_id, character_name
    """
    with get_conn() as conn:
        if limit_messages is None:
            rows = conn.execute(
                """
                SELECT role, content, character_id, character_name, created_at
                FROM short_term_message
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
            return [dict(r) for r in rows]

        rows = conn.execute(
            """
            SELECT role, content, character_id, character_name, created_at
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (session_id, limit_messages),
        ).fetchall()

    messages = [dict(r) for r in rows]
    messages.reverse()  # 按时间正序返回
    return messages


def add_participant_to_session(
    session_id: str,
    character_id: str,
    speak_frequency: float = 1.0
) -> bool:
    """
    向现有会话添加新参与者
    
    Args:
        session_id: 会话 ID
        character_id: 要添加的角色 ID
        speak_frequency: 发言频率权重
    
    Returns:
        bool: 是否添加成功
    """
    try:
        with get_conn() as conn:
            # 获取当前最大加入顺序
            max_order = conn.execute(
                """
                SELECT COALESCE(MAX(join_order), -1) as max_order
                FROM multi_session_participant
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()["max_order"]
            
            # 添加新参与者
            conn.execute(
                """
                INSERT OR IGNORE INTO multi_session_participant
                (session_id, character_id, join_order, speak_frequency, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (session_id, character_id, max_order + 1, speak_frequency, _now()),
            )
        
        logger.info(f"角色 {character_id} 已加入会话 {session_id}")
        return True
    
    except Exception as e:
        logger.error(f"添加参与者失败: {e}")
        return False


def remove_participant_from_session(session_id: str, character_id: str) -> bool:
    """
    从会话中移除参与者（软删除，标记为不活跃）
    
    Args:
        session_id: 会话 ID
        character_id: 要移除的角色 ID
    
    Returns:
        bool: 是否移除成功
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE multi_session_participant
                SET is_active = 0
                WHERE session_id = ? AND character_id = ?
                """,
                (session_id, character_id),
            )
        
        logger.info(f"角色 {character_id} 已从会话 {session_id} 中移除")
        return True
    
    except Exception as e:
        logger.error(f"移除参与者失败: {e}")
        return False


def update_participant_frequency(
    session_id: str,
    character_id: str,
    speak_frequency: float
) -> bool:
    """
    更新参与者的发言频率
    
    Args:
        session_id: 会话 ID
        character_id: 角色 ID
        speak_frequency: 新的发言频率权重
    
    Returns:
        bool: 是否更新成功
    """
    try:
        with get_conn() as conn:
            conn.execute(
                """
                UPDATE multi_session_participant
                SET speak_frequency = ?
                WHERE session_id = ? AND character_id = ?
                """,
                (speak_frequency, session_id, character_id),
            )
        
        return True
    
    except Exception as e:
        logger.error(f"更新参与者频率失败: {e}")
        return False
    

def activate_participant_in_session(session_id: str, character_id: str) -> bool:
    """
    重新激活会话中的参与者（从软删除状态恢复为活跃）
    
    与 remove_participant_from_session 对称：将 is_active 由 0 恢复为 1。
    若参与者记录不存在则返回 False。
    
    Args:
        session_id: 会话 ID
        character_id: 要激活的角色 ID
    
    Returns:
        bool: 是否激活成功（无匹配行时返回 False）
    """
    try:
        with get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE multi_session_participant
                SET is_active = 1
                WHERE session_id = ? AND character_id = ?
                """,
                (session_id, character_id),
            )
        
        if cursor.rowcount == 0:
            logger.warning(f"未找到要激活的参与者: session={session_id}, character={character_id}")
            return False
        
        logger.info(f"角色 {character_id} 已在会话 {session_id} 中重新激活")
        return True
    
    except Exception as e:
        logger.error(f"激活参与者失败: {e}")
        return False


# =========================
# 用户管理
# =========================
def create_user(user_id: str, username: str, password_hash: str, gender: str = "unknown"):
    """创建新用户"""
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO users (user_id, username, password_hash, gender, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, username, password_hash, gender, _now(), _now()),
        )


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


def update_user_profile(user_id: str, username: str = None, gender: str = None, avatar_url: str = None):
    """更新用户资料"""
    fields = []
    params = []
    if username is not None:
        fields.append("username = ?")
        params.append(username)
    if gender is not None:
        fields.append("gender = ?")
        params.append(gender)
    if avatar_url is not None:
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
