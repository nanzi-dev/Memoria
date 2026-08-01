"""
Pytest database isolation.

The application database may contain an older local schema. Tests should always
run against a fresh database built from the current repository schema.

By default tests run against a fresh SQLite database in a temp dir.  To run the
whole suite against a real PostgreSQL (e.g. Docker), set ``MEMORIA_PG_TEST_URL``
before invoking pytest — the suite will drop/recreate tables on that server
and run against it (exercising the real named-bind SQL, ON CONFLICT, FOR
UPDATE, partial indexes and BigInteger columns).
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memoria.core.config import configs
from memoria.db import repository


def _precreate_shared_test_users() -> None:
    """PG 强制外键：预建测试套件中硬编码使用的用户 ID。

    SQLite 不强制外键所以测试从不创建这些用户；PG 下必须先存在。
    与仓库层无关——纯测试基建。
    """
    from memoria.db.repository import _common

    hardcoded = {
        "admin", "another-user", "cfP", "chain_p", "curve-fallback-owner",
        "deduplicated-worker", "english-player", "esP", "group-player", "lsP",
        "noone", "opening-owner", "opening-player", "other", "other-player",
        "other-user", "owner", "owner-1", "owner-a", "p", "p1", "player",
        "player_001", "player-1", "prompt-player", "scheduled_player",
        "stale-worker", "test-user", "too-early", "u_pg_affinity", "user-1",
        "user_auto_shared", "user_shared_auto", "user_shared_d",
        "user_shared_invalid", "user_shared_pulse", "usr_1", "usr_a",
        "usr_knowledge_owner", "usr_story_other", "usr_story_session_competitor",
        "usr_test", "worker-1", "worker-2", "worker-a", "worker-b",
        "worker-dedup", "worker-rollback",
    }
    for i, uid in enumerate(sorted(hardcoded)):
        if repository.get_user_by_id(uid):
            continue
        try:
            repository.create_user(uid, f"shared_test_user_{i}", "test-hash")
        except Exception:
            _common.logger.warning("预建测试用户 %s 失败", uid, exc_info=True)


def pytest_sessionstart(session):
    pg_url = os.environ.get("MEMORIA_PG_TEST_URL", "").strip()
    if pg_url:
        configs.database_url = pg_url
        configs.database_path = ""
        configs.vector_db_path = ""  # 向量库仍用默认（chroma 不走 PG）
        # 真实 PG 上从干净 schema 开始：drop 全部表再 init_db
        from sqlalchemy import create_engine, event, text
        from sqlalchemy.engine import Engine
        from memoria.db.models import Base

        @event.listens_for(Engine, "connect")
        def _pg_test_bypass_fk(dbapi_conn, connection_record):
            # 测试基建：绕过 PG 外键检查（测试大量使用硬编码/随机 user_id 而不建 users 行，
            # SQLite 默认不强制外键；PG 强制会大面积误报）。唯一约束与 NOT NULL 仍生效。
            # 仅对 PostgreSQL 连接生效（SQLite 连接不执行）。
            import sqlite3
            if isinstance(dbapi_conn, sqlite3.Connection):
                return  # SQLite 连接不执行
            try:
                cur = dbapi_conn.cursor()
                cur.execute("SET session_replication_role = replica")
                cur.execute("COMMIT")  # 立即提交，避免被后续事务隐式覆盖
                cur.close()
            except Exception:
                pass  # 非 PG 驱动（如有）忽略

        engine = create_engine(pg_url, pool_pre_ping=True)
        with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
        engine.dispose()
        repository.init_db()
        _precreate_shared_test_users()
        return

    db_dir = Path(tempfile.mkdtemp(prefix="memoria_pytest_"))
    configs.database_url = ""
    configs.database_path = str(db_dir / "memoria.db")
    configs.vector_db_path = str(db_dir / "chroma_db")
    repository.init_db()
