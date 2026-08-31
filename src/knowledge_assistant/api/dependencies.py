"""FastAPI 数据库 Session 与业务服务依赖。"""

from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated, cast

from fastapi import Depends
from minio import Minio
from redis import Redis
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from knowledge_assistant.cache.redis_cache import RedisClient, RedisDocumentCache
from knowledge_assistant.core.config import (
    MinioSettings,
    RedisSettings,
    Settings,
    StorageSettings,
)
from knowledge_assistant.db.session import create_default_engine, create_session_factory
from knowledge_assistant.repositories.sqlalchemy_repository import SqlAlchemyDocumentRepository
from knowledge_assistant.services.document_service import DocumentService
from knowledge_assistant.storage.local_storage import LocalDocumentStorage
from knowledge_assistant.storage.minio_storage import MinioClient, MinioDocumentStorage


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


@lru_cache
def get_document_storage() -> LocalDocumentStorage | MinioDocumentStorage:
    """按环境配置创建并复用原文件存储 Adapter。"""
    storage_settings = StorageSettings()
    if storage_settings.document_storage_backend == "local":
        settings = Settings.default()
        settings.ensure_runtime_directories()
        return LocalDocumentStorage(
            upload_dir=settings.uploads_dir,
            max_file_size=10 * 1024 * 1024,
        )

    minio_settings = MinioSettings()
    client = cast(
        "MinioClient",
        Minio(
            endpoint=minio_settings.client_endpoint,
            access_key=minio_settings.minio_access_key,
            secret_key=minio_settings.minio_secret_key,
            secure=minio_settings.minio_secure,
        ),
    )
    return MinioDocumentStorage(
        client=client,
        bucket_name=minio_settings.minio_bucket,
        max_file_size=minio_settings.minio_max_file_size,
    )


@lru_cache
def get_document_cache() -> RedisDocumentCache:
    """创建并复用 Redis 连接池和文档详情缓存 Adapter。"""
    settings = RedisSettings()
    client = cast(
        "RedisClient",
        Redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=settings.redis_connect_timeout_seconds,
            socket_timeout=settings.redis_socket_timeout_seconds,
            health_check_interval=30,
        ),
    )
    return RedisDocumentCache(client)


def get_document_service(session: SessionDependency) -> DocumentService:
    """将当前请求的 Session 和存储接口组装成文档服务。"""
    repository = SqlAlchemyDocumentRepository(session)
    settings = RedisSettings()
    return DocumentService(
        repository,
        get_document_storage(),
        cache=get_document_cache(),
        cache_ttl_seconds=settings.document_cache_ttl_seconds,
    )
