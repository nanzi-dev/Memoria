"""v1.0.0 initial schema

Memoria v1.0.0 发布时重新建立单一迁移基线。

项目在 v1.0.0 之前没有正式发布版本，因此不兼容/继承旧的
raw-SQL 或 0.x 开发期迁移历史；新装库直接从空库执行本迁移即可。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from memoria.db.models import Base

# revision identifiers, used by Alembic.
revision: str = "v1_0_0"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the full ORM schema from the v1.0.0 metadata."""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # 部分唯一索引等 SQLite 特有对象若不在 ORM metadata 中，由应用启动的
    # repo.init_db() 幂等补齐；这里保留 create_all 作为唯一 DDL 来源。
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS idx_summary_unique ON session_summary(session_id, character_id, player_id)"))
    bind.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS idx_inbox_group_unread ON player_event_inbox(player_id, group_thread_id) WHERE event_type = 'group_message' AND read_at IS NULL"))


def downgrade() -> None:
    """Drop the full ORM schema."""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
