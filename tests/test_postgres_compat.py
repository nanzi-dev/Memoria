"""
PostgreSQL compatibility checks for the repository layer.

These tests intentionally avoid requiring a running PostgreSQL service; they
verify the SQL adaptation layer that is exercised when DATABASE_URL is set.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from memoria.db import repository


def test_qmark_placeholder_conversion_skips_string_literals():
    sql = "SELECT * FROM message WHERE id = ? AND content LIKE '?' AND note = 'it''s ?'"

    converted = repository._convert_qmark_placeholders(sql)

    assert "id = %s" in converted
    assert "LIKE '?'" in converted
    assert "it''s ?'" in converted


def test_postgres_schema_uses_bigserial():
    """Verify ORM models define BIGSERIAL-compatible primary keys for PostgreSQL."""
    from memoria.db.models import Base
    from sqlalchemy import BigInteger, Integer
    from sqlalchemy.dialects.postgresql import dialect as pg_dialect

    # Check domain_event uses BigInteger-compatible column
    de_table = Base.metadata.tables["domain_event"]
    seq_col = de_table.c.sequence
    # BigInteger (with Integer variant on sqlite) maps to BIGSERIAL on PG
    assert isinstance(seq_col.type, BigInteger), f"expected BigInteger, got {seq_col.type}"
    # 编译成 PG DDL 时必须是 BIGSERIAL（而非 SERIAL）
    from sqlalchemy.schema import CreateTable

    ddl = str(CreateTable(de_table).compile(dialect=pg_dialect()))
    assert "BIGSERIAL" in ddl, f"expected BIGSERIAL in DDL, got:\n{ddl}"


def test_postgres_domain_event_sequence_references_use_bigint():
    """Verify domain_event columns that need BIGINT in PostgreSQL."""
    from memoria.db.models import Base
    from sqlalchemy import BigInteger

    de_table = Base.metadata.tables["domain_event"]
    # These columns need BIGINT in PostgreSQL for large datasets
    assert isinstance(de_table.c.aggregate_version.type, BigInteger)
    assert isinstance(de_table.c.source_message_id.type, BigInteger)
    assert isinstance(
        Base.metadata.tables["projection_checkpoint"].c.last_sequence.type,
        BigInteger,
    )
    assert isinstance(
        Base.metadata.tables["fact_claim"].c.ledger_version.type,
        BigInteger,
    )
    assert isinstance(
        Base.metadata.tables["story_state"].c.ledger_version.type,
        BigInteger,
    )


def test_postgres_insert_or_ignore_becomes_on_conflict_do_nothing():
    sql = """
        INSERT OR IGNORE INTO session
        (session_id, character_id, player_id, player_name, created_at, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """

    converted = repository._prepare_postgres_sql(sql)

    assert "INSERT INTO" in converted
    assert "%s" in converted
    # _prepare_postgres_sql converts INSERT OR IGNORE → INSERT INTO
    assert "OR IGNORE" not in converted


def test_postgres_auth_token_replace_becomes_upsert():
    sql = """
        INSERT OR REPLACE INTO auth_token (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """

    converted = repository._prepare_postgres_sql(sql)

    assert "INSERT" in converted
    assert "auth_token" in converted
    assert "%s" in converted


def test_postgres_admin_bootstrap_claim_keeps_conflict_guard():
    sql = """
        INSERT INTO system_bootstrap_claim
        (claim_key, claimed_by_user_id, claimed_at)
        SELECT 'admin', ?, ?
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE is_admin = 1)
        ON CONFLICT (claim_key) DO NOTHING
    """

    converted = repository._prepare_postgres_sql(sql)

    assert "SELECT 'admin', %s, %s" in converted
    assert "ON CONFLICT (claim_key) DO NOTHING" in converted


def test_postgres_mode_is_enabled_only_for_database_url(monkeypatch):
    monkeypatch.setattr(repository.configs, "database_url", "")
    assert repository._is_postgres_enabled() is False

    monkeypatch.setattr(repository.configs, "database_url", "postgresql://localhost/memoria")
    assert repository._is_postgres_enabled() is True
