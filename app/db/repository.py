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

from app.core.config import configs

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
# SQLite 连接管理
# =========================
@contextmanager
def get_conn():
    """
    SQLite 连接上下文管理
    """
    conn = sqlite3.connect(
        configs.database_path,
        check_same_thread = False # 避免多线程问题
    )
    
    conn.row_factory = sqlite3.Row
    
    # WAL 模式（推荐用于并发读写）
    conn.execute("PRAGMA journal_mode=WAL;")
    
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
-- 角色卡存储
-- =========================
CREATE TABLE IF NOT EXISTS character_card (
    character_id    TEXT PRIMARY KEY,
    
    card_data       TEXT NOT NULL,      -- 完整的角色卡 JSON 数据
    version         TEXT DEFAULT '1.0.0',
    
    -- 元信息（便于查询和展示）
    name            TEXT,
    display_name    TEXT,
    
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
    status          TEXT DEFAULT 'active'  -- active / ended
);

-- =========================
-- 短期记忆（对话）
-- =========================
CREATE TABLE IF NOT EXISTS short_term_message (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,

    session_id      TEXT NOT NULL,
    role            TEXT NOT NULL,   -- user / assistant
    content         TEXT NOT NULL,

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
    
    created_at      TEXT,

    FOREIGN KEY (session_id) REFERENCES session(session_id)
);

-- =========================
-- 索引优化
-- =========================

CREATE INDEX IF NOT EXISTS idx_session_lookup
ON session(character_id, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_message_session
ON short_term_message(session_id, id ASC);

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

CREATE INDEX IF NOT EXISTS idx_relationship_lookup
ON character_relationship(character_id_a, character_id_b);
"""

def init_db():
    """初始化数据库结构"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        

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
            from app.core.vector_memory import get_vector_store
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
        from app.core.vector_memory import get_vector_store
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


# =========================
# short term memory（对话历史）
# =========================
def append_short_term_message(session_id: str, role: str, content: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO short_term_message
            (session_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, role, content, _now()),
        )
        
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
                (
                    SELECT content
                    FROM short_term_message
                    WHERE session_id = s.session_id
                    ORDER BY id DESC
                    LIMIT 1
                ) AS last_message,
                (
                    SELECT COUNT(*)
                    FROM short_term_message
                    WHERE session_id = s.session_id
                ) AS message_count
            FROM session s
            WHERE s.character_id = ? AND s.player_id = ?
            ORDER BY s.created_at DESC
            """,
            (character_id, player_id),
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
            SELECT role, content, created_at
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


# =========================
# 会话摘要（中期记忆）
# =========================
def save_session_summary(
    session_id: str,
    character_id: str,
    player_id: str,
    summary_text: str,
    message_count: int
):
    """保存会话摘要"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO session_summary
            (session_id, character_id, player_id, summary_text, message_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session_id, character_id, player_id, summary_text, message_count, _now()),
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
# 角色卡管理（CRUD）
# =========================
def save_character_card_to_db(
    character_id: str,
    card_data_json: str,
    version: str = "1.0.0",
    name: str = None,
    display_name: str = None,
    source: str = "db"
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
                (character_id, card_data, version, name, display_name, created_at, updated_at, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(character_id)
                DO UPDATE SET
                    card_data=excluded.card_data,
                    version=excluded.version,
                    name=excluded.name,
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (character_id, card_data_json, version, name, display_name, _now(), _now(), source),
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
            SELECT character_id, name, display_name, version, created_at, updated_at, is_active, source
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
    is_active: bool = True
) -> bool:
    """保存事件定义"""
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO event_definition
                (event_id, event_name, description, character_id, trigger_config, 
                 effects_config, priority, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id)
                DO UPDATE SET
                    event_name=excluded.event_name,
                    description=excluded.description,
                    character_id=excluded.character_id,
                    trigger_config=excluded.trigger_config,
                    effects_config=excluded.effects_config,
                    priority=excluded.priority,
                    is_active=excluded.is_active,
                    updated_at=excluded.updated_at
                """,
                (event_id, event_name, description, character_id, trigger_config,
                 effects_config, priority, 1 if is_active else 0, _now(), _now()),
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



 