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


def test_postgres_schema_uses_bigserial(monkeypatch):
    monkeypatch.setattr(repository.configs, "database_url", "postgresql://user:pass@localhost/memoria")

    schema = repository._schema_for_current_db()

    assert "BIGSERIAL PRIMARY KEY" in schema
    assert "AUTOINCREMENT" not in schema


def test_postgres_insert_or_ignore_becomes_on_conflict_do_nothing():
    sql = """
        INSERT OR IGNORE INTO session
        (session_id, character_id, player_id, player_name, created_at, status)
        VALUES (?, ?, ?, ?, ?, 'active')
    """

    converted = repository._prepare_postgres_sql(sql)

    assert "INSERT INTO session" in converted
    assert "VALUES (%s, %s, %s, %s, %s, 'active')" in converted
    assert "ON CONFLICT DO NOTHING" in converted


def test_postgres_auth_token_replace_becomes_upsert():
    sql = """
        INSERT OR REPLACE INTO auth_token (token, user_id, created_at, expires_at)
        VALUES (?, ?, ?, ?)
    """

    converted = repository._prepare_postgres_sql(sql)

    assert "INSERT INTO auth_token" in converted
    assert "VALUES (%s, %s, %s, %s)" in converted
    assert "ON CONFLICT (token) DO UPDATE SET" in converted
    assert "expires_at = EXCLUDED.expires_at" in converted


def test_postgres_mode_is_enabled_only_for_database_url(monkeypatch):
    monkeypatch.setattr(repository.configs, "database_url", "")
    assert repository._is_postgres_enabled() is False

    monkeypatch.setattr(repository.configs, "database_url", "postgresql://localhost/memoria")
    assert repository._is_postgres_enabled() is True
