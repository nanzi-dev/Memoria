"""
Alembic 迁移环境配置。

数据库 URL 和引擎从 ``memoria.core.config.configs`` 和
``memoria.db.engine`` 中获取，而非 alembic.ini，
以确保迁移与应用使用完全相同的连接参数。
"""

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# ── Alembic Config ──────────────────────────────────────────────────────────
config = context.config

# ── Logging ──────────────────────────────────────────────────────────────────
# alembic.ini 中的 logging 配置
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── ORM Model MetaData（autogenerate 的数据源）─────────────────────────────
from memoria.db.models import Base  # noqa: E402
target_metadata = Base.metadata

# ── 数据库 URL（从应用配置获取）─────────────────────────────────────────────
from memoria.core.config import configs  # noqa: E402


def _get_url() -> str:
    """返回当前数据库 URL。

    优先使用 DATABASE_URL（PostgreSQL），否则回退到 SQLite 路径。
    """
    db_url = (configs.database_url or "").strip()
    if db_url:
        return db_url
    return f"sqlite:///{configs.database_path}"


def run_migrations_offline() -> None:
    """以 'offline' 模式运行迁移。

    仅生成 SQL 脚本，不连接数据库。
    """
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite 不支持 ALTER RENAME，启用 batch 模式以重建表
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以 'online' 模式运行迁移。

    创建真实连接并执行 DDL。
    """
    # 直接构建 Engine，不从 alembic.ini 读取 URL
    from sqlalchemy import create_engine

    url = _get_url()
    connect_args = {}
    if url.startswith("sqlite:"):
        connect_args["check_same_thread"] = False

    connectable = create_engine(url, poolclass=pool.NullPool, connect_args=connect_args)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # SQLite batch mode for ALTER TABLE support
            render_as_batch=url.startswith("sqlite:"),
        )

        with context.begin_transaction():
            context.run_migrations()

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
