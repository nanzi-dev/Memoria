"""
SQLAlchemy engine / session 生命周期管理。

本模块是 Memoria 数据库连接的 **唯一真相来源**（single source of truth），
负责：
  - 根据配置创建 / 重建 SQLAlchemy ``Engine``
  - 提供 ``SessionLocal`` 会话工厂
  - 提供 ``get_session()`` 上下文管理器（自动 commit / rollback）
  - 提供 ``init_db()`` 建表入口
  - 支持测试场景下的引擎重配置（``configure_engine()``）

配置来自 ``memoria.core.config.configs``：
  - ``configs.database_url``  非空时走 PostgreSQL
  - 否则使用 ``configs.database_path`` 走 SQLite
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import Session, sessionmaker

from memoria.core.config import configs
from memoria.db.models import Base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 模块级单例（延迟初始化，支持重配置）
# ---------------------------------------------------------------------------
_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _build_url() -> str:
    """根据 configs 构建 SQLAlchemy 数据库 URL。

    优先级：
      1. ``configs.database_url`` 非空 → 直接使用（PostgreSQL）
      2. 否则使用 ``configs.database_path`` 构建 SQLite URL
    """
    db_url = (configs.database_url or "").strip()
    if db_url:
        return db_url
    return f"sqlite:///{configs.database_path}"


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite:")


# ---------------------------------------------------------------------------
# SQLite 事件钩子：WAL 模式
# ---------------------------------------------------------------------------
_wal_configured_engines: set[int] = set()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record) -> None:  # noqa: ANN001
    """对每个新的 SQLite 连接启用 WAL 日志模式。

    WAL 是数据库文件级别的持久属性，但每次新连接都需要声明；
    通过 SET 指令幂等执行，不会造成额外开销。
    """
    # 获取底层 sqlite3 连接（DBAPI 层）
    import sqlite3
    if isinstance(dbapi_conn, sqlite3.Connection):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


# ---------------------------------------------------------------------------
# 引擎构建
# ---------------------------------------------------------------------------
def _build_engine(url: str | None = None) -> Engine:
    """构建 SQLAlchemy Engine。

    Parameters
    ----------
    url : str, optional
        显式指定数据库 URL。为 ``None`` 时从配置推断。
    """
    url = url or _build_url()
    is_sqlite = _is_sqlite(url)

    if is_sqlite:
        from sqlalchemy.pool import NullPool
        engine = create_engine(
            url,
            connect_args={
                "check_same_thread": False,  # 允许多线程访问（FastAPI 场景必需）
            },
            echo=False,
            poolclass=NullPool,
        )
        logger.info("SQLAlchemy engine created (SQLite): %s", url)
    else:
        engine = create_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        logger.info("SQLAlchemy engine created (PostgreSQL): %s", url.split("@")[-1])

    return engine


def configure_engine(url: str | None = None) -> tuple[Engine, sessionmaker]:
    """（重新）配置引擎和会话工厂。

    主要用途：
      - 应用启动时的首次初始化
      - 测试中切换到内存数据库（``sqlite:///:memory:``）

    Returns
    -------
    tuple[Engine, sessionmaker]
        新创建的引擎和会话工厂。
    """
    global _engine, _SessionLocal

    # 关闭旧引擎（如有）
    if _engine is not None:
        _engine.dispose()
        logger.info("Previous engine disposed.")

    _engine = _build_engine(url)
    _SessionLocal = sessionmaker(
        bind=_engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )
    return _engine, _SessionLocal


def get_engine() -> Engine:
    """获取当前 Engine（首次调用时自动初始化）。

    如果配置发生了变化（例如测试中 monkeypatch 更换了 database_path），
    会自动重建引擎。
    """
    global _engine
    expected_url = _build_url()
    if _engine is None or str(_engine.url) != expected_url:
        configure_engine()
    return _engine  # type: ignore[return-value]


def get_session_factory() -> sessionmaker:
    """获取当前 SessionLocal 工厂（首次调用时自动初始化）。"""
    if _SessionLocal is None:
        configure_engine()
    return _SessionLocal  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

#: 应用级会话工厂；惰性初始化，首次属性访问时从配置构建。
#: 外部代码可直接 ``SessionLocal()`` 创建会话，
#: 但推荐使用 ``get_session()`` 上下文管理器以获得自动 commit/rollback。
SessionLocal: sessionmaker = None  # type: ignore[assignment]


def _get_or_create_session_local() -> sessionmaker:
    """延迟初始化 SessionLocal 并返回。

    当配置变更（如测试中 monkeypatch 更换 database_path）导致引擎重建时，
    自动同步 ``SessionLocal`` 到新的会话工厂。
    """
    global SessionLocal
    # get_engine() 内部会检测 URL 变化并调用 configure_engine()，
    # 从而更新 _engine 和 _SessionLocal。
    engine = get_engine()
    if SessionLocal is None or _SessionLocal is None or SessionLocal.kw.get("bind") is not engine:
        SessionLocal = _SessionLocal
    return SessionLocal  # type: ignore[return-value]


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """上下文管理器：获取一个 SQLAlchemy 会话，自动处理 commit / rollback。

    用法::

        with get_session() as session:
            session.add(some_obj)
            # 退出时自动 commit；异常时自动 rollback

    Yields
    ------
    Session
        一个绑定到当前引擎的数据库会话。
    """
    factory = _get_or_create_session_local()
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    """根据 ``Base.metadata`` 创建所有表。

    等价于旧的 ``_common.init_db()`` 中的 ``CREATE TABLE IF NOT EXISTS`` 逻辑。
    仅在 ORM 模型注册到 ``Base.metadata`` 后才有效。
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database tables ensured (create_all) on %s", engine.url)
