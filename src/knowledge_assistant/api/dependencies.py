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
    EmbeddingSettings,
    MilvusSettings,
    MinioSettings,
    OcrSettings,
    ProcessingSettings,
    RedisSettings,
    Settings,
    StorageSettings,
)
from knowledge_assistant.db.session import create_default_engine, create_session_factory
from knowledge_assistant.embeddings.bge import BgeEmbeddingProvider
from knowledge_assistant.processing.chunker import TextChunker
from knowledge_assistant.processing.ocr.paddle_ocr import PaddleOcrProvider
from knowledge_assistant.processing.parsers import (
    DocxDocumentParser,
    MarkdownTextParser,
    PdfDocumentParser,
    Utf8TextParser,
)
from knowledge_assistant.repositories.chunk_repository import SqlAlchemyDocumentChunkRepository
from knowledge_assistant.repositories.sqlalchemy_repository import SqlAlchemyDocumentRepository
from knowledge_assistant.services.document_processing_service import DocumentProcessingService
from knowledge_assistant.services.document_service import DocumentService
from knowledge_assistant.services.search_service import SearchService
from knowledge_assistant.storage.local_storage import LocalDocumentStorage
from knowledge_assistant.storage.minio_storage import MinioClient, MinioDocumentStorage
from knowledge_assistant.vectors.milvus_repository import MilvusVectorRepository


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
        vectors=get_vector_repository(),
    )


@lru_cache
def get_embedding_provider() -> BgeEmbeddingProvider:
    """创建可跨请求复用的本地 BGE Adapter；模型在首次推理时才加载。"""
    settings = EmbeddingSettings()
    return BgeEmbeddingProvider(
        settings.embedding_model_path,
        model_name=settings.embedding_model,
        dimension=settings.embedding_dimension,
        batch_size=settings.embedding_batch_size,
        device=settings.embedding_device,
    )


@lru_cache
def get_ocr_provider() -> PaddleOcrProvider | None:
    """按配置提供 OCR Adapter；关闭 OCR 时不加载 PaddleOCR。"""
    settings = OcrSettings()
    if not settings.ocr_enabled:
        return None
    return PaddleOcrProvider(device=settings.ocr_device)


@lru_cache
def get_vector_repository() -> MilvusVectorRepository:
    """创建可复用的 Milvus Repository；Collection 在首次操作时检查。"""
    milvus = MilvusSettings()
    embedding = EmbeddingSettings()
    return MilvusVectorRepository(
        str(milvus.milvus_uri),
        collection_name=milvus.milvus_collection,
        dimension=embedding.embedding_dimension,
        metric_type=milvus.milvus_metric_type,
        timeout_seconds=milvus.milvus_timeout_seconds,
    )


def get_document_processing_service(session: SessionDependency) -> DocumentProcessingService:
    """组装一次请求使用的处理服务，复用模型、缓存和 Milvus Client。"""
    processing = ProcessingSettings()
    ocr_settings = OcrSettings()
    embedding = get_embedding_provider()
    return DocumentProcessingService(
        SqlAlchemyDocumentRepository(session),
        SqlAlchemyDocumentChunkRepository(session),
        get_document_storage(),
        (
            Utf8TextParser(),
            MarkdownTextParser(),
            PdfDocumentParser(ocr_settings.ocr_min_text_chars_per_page),
            DocxDocumentParser(),
        ),
        TextChunker(
            target_chars=processing.chunk_target_chars,
            max_chars=processing.chunk_max_chars,
            overlap_chars=processing.chunk_overlap_chars,
            token_counter=embedding.count_tokens,
        ),
        embedding,
        get_vector_repository(),
        ocr=get_ocr_provider(),
        cache=get_document_cache(),
    )


def get_search_service(session: SessionDependency) -> SearchService:
    """组装语义搜索服务，并复用 BGE 模型和 Milvus Client。"""
    return SearchService(
        SqlAlchemyDocumentRepository(session),
        SqlAlchemyDocumentChunkRepository(session),
        get_embedding_provider(),
        get_vector_repository(),
    )
