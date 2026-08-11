"""SQLAlchemy 基础设施：Engine、Session 工厂、ORM Base 与请求级数据库依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()

# SQLite 单连接默认限制线程归属，而 FastAPI 同一请求可能在线程池中切换线程。
# 该参数只对 SQLite 开启；切换 MySQL/PostgreSQL 时不会携带无效参数。
connect_args: dict[str, object] = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine_options: dict[str, object] = {"connect_args": connect_args}
if not settings.database_url.startswith("sqlite"):
    # pre_ping 清理失效连接；recycle 避免 MySQL wait_timeout 导致连接失效。
    engine_options.update(
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_pool_timeout_seconds,
        pool_recycle=settings.db_pool_recycle_seconds,
    )

engine = create_engine(settings.database_url, **engine_options)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """所有 ORM 模型的声明式基类，Alembic 也通过它读取完整表元数据。"""
    pass


def get_db() -> Generator[Session, None, None]:
    """为一次 HTTP 请求提供独立 Session，并在请求结束后可靠释放连接。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def check_database_connection() -> None:
    """执行轻量查询，供就绪探针判断数据库是否可用。"""
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def check_dependencies() -> None:
    """Check the relational database and the enabled vector database."""
    check_database_connection()
    if settings.vector_store_enabled:
        from app.vector_store import VectorStore

        VectorStore().check()
