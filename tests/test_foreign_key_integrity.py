"""Foreign-key integrity smoke tests.

The main suite deliberately runs with SQLite foreign keys disabled (and PG
with session_replication_role=replica) to preserve historical test ergonomics.
These isolated tests create a private SQLite engine with foreign keys enabled
to ensure the ORM schema still declares and enforces core relationships.
"""

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

from memoria.db.models import Base


def _fk_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def test_character_card_requires_existing_user():
    engine = _fk_engine()
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO users "
                "(user_id, username, password_hash, is_admin, tts_auto_play, stt_auto_send, created_at, updated_at) "
                "VALUES ('u1', 'u1', 'x', 0, 0, 0, 'now', 'now')"
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO character_card "
                    "(owner_user_id, character_id, card_data, name, display_name, created_at, updated_at, is_active, source) "
                    "VALUES ('ghost', 'c', '{}', 'c', 'c', 'now', 'now', 1, 'db')"
                )
            )


def test_user_character_card_requires_existing_user():
    engine = _fk_engine()
    Base.metadata.create_all(engine)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO user_character_card "
                    "(user_id, display_name, gender, created_at, updated_at) "
                    "VALUES ('ghost', 'Ghost', 'unknown', 'now', 'now')"
                )
            )
