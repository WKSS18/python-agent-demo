"""SQLAlchemy 基础设施：Engine、Session 工厂、ORM Base 与请求级数据库依赖。"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


settings = get_settings()

# SQLite 单连接默认限制线程归属，而 FastAPI 同一请求可能在线程池中切换线程。
# 该参数只对 SQLite 开启；切换 MySQL/PostgreSQL 时不会携带无效参数。
connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


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
