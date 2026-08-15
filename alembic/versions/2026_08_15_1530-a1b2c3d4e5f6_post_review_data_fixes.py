"""post review data fixes

Revision ID: a1b2c3d4e5f6
Revises: 06884ebd4d17
Create Date: 2026-08-15 15:30:00

- Normalize legacy NULL ``event_schedule_state.character_id`` rows to ``''``.
- Idempotently deduplicate legacy ``session_summary`` and unread
  ``player_event_inbox`` rows that were previously removed at every startup.
"""
from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "06884ebd4d17"
branch_labels = None
depends_on = None

_MIGRATION_KEY = "post_review_data_fixes_2026_08_15"


def _already_applied() -> bool:
    conn = op.get_bind()
    row = conn.execute(
        sa.text(
            "SELECT 1 FROM data_migration WHERE migration_key = :key"
        ),
        {"key": _MIGRATION_KEY},
    ).fetchone()
    return row is not None


def _mark_applied() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO data_migration (migration_key, metadata, applied_at)
            VALUES (:key, :metadata, :applied_at)
            """
        ),
        {
            "key": _MIGRATION_KEY,
            "metadata": "{\"description\": \"normalize schedule scopes and deduplicate legacy rows\"}",
            "applied_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def upgrade() -> None:
    if _already_applied():
        return
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite 允许主键出现多个 NULL；直接 UPDATE 会撞唯一约束，
        # 先按 rowid 保留一条，再归一化。
        bind.execute(
            sa.text(
                """
                DELETE FROM event_schedule_state
                WHERE character_id IS NULL
                  AND rowid NOT IN (
                      SELECT MIN(rowid) FROM event_schedule_state
                      WHERE character_id IS NULL
                      GROUP BY event_id, player_id
                  )
                """
            )
        )
    bind.execute(
        sa.text(
            "UPDATE event_schedule_state SET character_id = '' "
            "WHERE character_id IS NULL"
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM session_summary
            WHERE id NOT IN (
                SELECT MAX(id) FROM session_summary
                GROUP BY session_id, character_id, player_id
            )
            """
        )
    )
    bind.execute(
        sa.text(
            """
            DELETE FROM player_event_inbox
            WHERE event_type = 'group_message' AND read_at IS NULL
              AND id NOT IN (
                  SELECT MAX(id) FROM player_event_inbox
                  WHERE event_type = 'group_message' AND read_at IS NULL
                  GROUP BY player_id, group_thread_id
              )
            """
        )
    )
    _mark_applied()


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM data_migration WHERE migration_key = :key"),
        {"key": _MIGRATION_KEY},
    )
