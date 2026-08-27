"""FastAPI 数据库 Session 与业务服务依赖。"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from knowledge_assistant.core.config import Settings
from knowledge_assistant.db.session import create_default_engine, create_session_factory
from knowledge_assistant.repositories.sqlalchemy_repository import SqlAlchemyDocumentRepository
from knowledge_assistant.services.document_service import DocumentService


@lru_cache
def get_engine() -> Engine:
    """为 API 进程创建并复用一个数据库 Engine。"""
    return create_default_engine()


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """基于共享 Engine 创建 Session 工厂。"""
    return create_session_factory(get_engine())


def get_session() -> Iterator[Session]:
    """每个 HTTP 请求创建并在结束后关闭一个 Session。"""
    with get_session_factory()() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]


def get_document_service(session: SessionDependency) -> DocumentService:
    """将当前请求的 Session 组装成数据库版文档服务。"""
    settings = Settings.default()
    settings.ensure_runtime_directories()
    repository = SqlAlchemyDocumentRepository(session)
    return DocumentService(repository, settings.uploads_dir)
