"""
数据持久化层（SQLite）

设计目标：
- 单文件轻量数据库（适合 demo / MVP）
- 支持角色状态 + 记忆 + 会话管理
- 后续可无缝迁移 PostgreSQL（SQL 层隔离）
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3

from app.core.config import configs

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
    created_at      TEXT
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
-- 索引优化
-- =========================

CREATE INDEX IF NOT EXISTS idx_session_lookup
ON session(character_id, player_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_message_session
ON short_term_message(session_id, id ASC);

CREATE INDEX IF NOT EXISTS idx_fact_lookup
ON long_term_fact(character_id, player_id, importance DESC, last_referenced DESC);
"""

def init_db():
    """初始化数据库结构"""
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        

# =========================
# runtime_state（角色状态）
# =========================
def get_runtime_state(character_id: str, player_id: str, card) -> dict:
     """
    获取角色运行时状态（好感度 / 信任 / 情绪）

    如果不存在 → 使用角色卡默认值初始化
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
             
         # 绑定长期记忆
         state["known_player_facts"] = get_long_term_facts(character_id, player_id)
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
def get_long_term_facts(character_id: str, player_id: str, limit: int = 20) -> list[str]:
    """获取长期记忆"""
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

def save_long_term_fact(character_id: str, player_id: str, fact_text: str, importance: int = 5):
    """保存长期记忆"""
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO long_term_fact
            (character_id, player_id, fact_text, importance, created_at, last_referenced)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (character_id, player_id, fact_text, importance, _now(), _now()),
        )
        

# =========================
# session 管理
# =========================
def create_session(session_id: str, character_id: str, player_id: str, player_name: str):
    with get_conn() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO session
            (session_id, character_id, player_id, player_name, created_at)
            VALUES (?, ?, ?, ?, ?)
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
    """分页查询消息"""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT role, content, created_at
            FROM short_term_message
            WHERE session_id = ?
            ORDER BY id ASC
            LIMIT ? OFFSET ?
            """,
            (session_id, limit + 1, offset),
        ).fetchall()

    has_more = len(rows) > limit
    messages = [dict(r) for r in rows[:limit]]

    return messages, has_more