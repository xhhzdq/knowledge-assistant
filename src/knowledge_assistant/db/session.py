"""SQLAlchemy Engine 与 Session Factory 的创建方法。"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from knowledge_assistant.core.config import DatabaseSettings


def create_db_engine(database_url: str, *, echo: bool = False) -> Engine:
    """创建管理数据库连接池的 Engine。"""
    return create_engine(database_url, echo=echo, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """创建按需生成短生命周期 Session 的工厂。"""
    return sessionmaker(bind=engine, expire_on_commit=False)


def create_default_engine() -> Engine:
    """根据 .env 中的开发库 URL 创建默认 Engine。"""
    settings = DatabaseSettings()
    return create_db_engine(settings.database_url)
