"""
Real PostgreSQL integration tests against a live server (Docker).

These tests exercise the actual SQL the repository layer runs against
PostgreSQL — the named-bind ``text()`` statements, ``ON CONFLICT``,
``FOR UPDATE``, ``RETURNING``, partial indexes, and BigInteger columns
that the string-transform tests in ``test_postgres_compat.py`` cannot see.

Requires a running PostgreSQL reachable at ``MEMORIA_PG_TEST_URL``
(default: ``postgresql+psycopg://memoria:memoria_dev_pw@127.0.0.1:5432/memoria_test``).
Skipped when the server is unreachable.
"""
import os

import pytest

PG_URL = os.environ.get(
    "MEMORIA_PG_TEST_URL",
    "postgresql+psycopg://memoria:memoria_dev_pw@127.0.0.1:5432/memoria_test",
)


def _pg_reachable() -> bool:
    try:
        from sqlalchemy import create_engine, text

        engine = create_engine(PG_URL, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_reachable(),
    reason="PostgreSQL integration server not reachable (set MEMORIA_PG_TEST_URL)",
)


@pytest.fixture(scope="module")
def pg_conn():
    from sqlalchemy import create_engine

    engine = create_engine(PG_URL, pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_repo_env(pg_conn, monkeypatch):
    """Point the repository layer at the live PostgreSQL and reset its schema."""
    from memoria.db import engine as db_engine
    from memoria.db.models import Base

    # DROP 所有表再 create_all（PostgreSQL 按外键依赖倒序）
    from sqlalchemy import text

    with pg_conn.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))

    from memoria.db.repository import _common

    monkeypatch.setattr(_common.configs, "database_url", PG_URL)
    monkeypatch.setattr(db_engine.configs, "database_url", PG_URL)
    db_engine.configure_engine(PG_URL)

    # repository.init_db() = create_all + 迁移钩子 + 运行时索引（idx_summary_unique / idx_inbox_group_unread）
    from memoria.db import repository

    repository.init_db()

    # PostgreSQL 强制外键：测试用 owner 必须先有 users 行
    for i, uid in enumerate(("u_pg_affinity", "u_pg_owner")):
        repository.create_user(uid, f"pg-test-user-{i}", "pw-hash")

    yield db_engine

    # 还原引擎，并重建表与共享测试用户（本 fixture 曾 DROP 全表）
    from tests.conftest import _precreate_shared_test_users

    db_engine.configure_engine(PG_URL)
    repository.init_db()
    _precreate_shared_test_users()
    db_engine.configure_engine("sqlite:///:memory:")  # 还原，避免影响其他测试


def test_real_pg_update_relationship_affinity_clamps(pg_repo_env):
    """regression: MAX/MIN 在 PG 是聚合函数，UPDATE 中非法 — 必须用 CASE 表达式。"""
    from memoria.db import repository

    owner = "u_pg_affinity"
    a, b = "c_pg_a", "c_pg_b"
    repository.save_character_relationship(
        owner_user_id=owner,
        character_id_a=a,
        character_id_b=b,
        relationship_type="friend",
        affinity=50.0,
    )
    repository.update_relationship_affinity(owner, a, b, 100.0)
    row = repository.get_character_relationship(owner, a, b)
    assert row["affinity"] == 100.0

    repository.update_relationship_affinity(owner, a, b, -500.0)
    row = repository.get_character_relationship(owner, a, b)
    assert row["affinity"] == -100.0


def test_real_pg_partial_inbox_index(pg_repo_env, pg_conn):
    """regression: PG 上必须是部分唯一索引（读后新消息不得冲突）。"""
    from sqlalchemy import text

    with pg_conn.connect() as conn:
        rows = conn.execute(text(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_inbox_group_unread'"
        )).fetchall()
    assert rows, "idx_inbox_group_unread not created"
    assert "WHERE" in rows[0][0], f"expected partial index, got: {rows[0][0]}"


def test_real_pg_bigint_columns(pg_repo_env, pg_conn):
    """regression: 事件账本序列/版本列在 PG 上必须是 BIGINT（而非 INTEGER）。"""
    from sqlalchemy import text

    with pg_conn.connect() as conn:
        rows = conn.execute(text("""
            SELECT column_name, data_type, column_default
            FROM information_schema.columns
            WHERE table_name = 'domain_event'
              AND column_name IN ('sequence', 'aggregate_version', 'source_message_id')
        """)).fetchall()
        by_name = {r[0]: r for r in rows}
        assert by_name["sequence"][1] == "bigint", f"sequence is {by_name['sequence'][1]}"
        assert by_name["aggregate_version"][1] == "bigint"
        assert by_name["source_message_id"][1] == "bigint"

        # projection_checkpoint.last_sequence
        rows = conn.execute(text("""
            SELECT data_type FROM information_schema.columns
            WHERE table_name = 'projection_checkpoint' AND column_name = 'last_sequence'
        """)).fetchall()
        assert rows[0][0] == "bigint"

        # fact_claim / story_state ledger_version
        for table_name in ("fact_claim", "story_state"):
            rows = conn.execute(text("""
                SELECT data_type FROM information_schema.columns
                WHERE table_name = :t AND column_name = 'ledger_version'
            """), {"t": table_name}).fetchall()
            assert rows and rows[0][0] == "bigint", f"{table_name}.ledger_version not bigint"
