"""文档管理业务服务。"""

import logging
from dataclasses import replace
from pathlib import Path
from typing import BinaryIO

from knowledge_assistant.cache.base import DocumentCache
from knowledge_assistant.exceptions import (
    DocumentConflictError,
    InvalidDocumentError,
    StorageError,
)
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.base import DocumentRepository
from knowledge_assistant.storage.base import DocumentStorage

logger = logging.getLogger(__name__)


class DocumentService:
    """Coordinate source files and persisted document metadata."""

    ALLOWED_FILE_TYPES = frozenset({".txt", ".md", ".pdf", ".docx"})

    def __init__(
        self,
        repository: DocumentRepository,
        storage: DocumentStorage,
        cache: DocumentCache | None = None,
        cache_ttl_seconds: int = 300,
    ) -> None:
        """初始化文档服务。

        Args:
            repository: 文档元数据仓库
            storage: 文档原文件存储接口
            cache: 可选的文档详情缓存；CLI 和纯单元测试可以不传
            cache_ttl_seconds: 文档详情缓存的生存时间
        """
        if cache_ttl_seconds <= 0:
            raise ValueError("cache_ttl_seconds must be greater than zero")
        self._repository = repository
        self._storage = storage
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    def add_document(self, source: Path) -> Document:
        """校验本地源文件，并通过存储接口保存原文件和元数据。"""
        source = source.expanduser().resolve()
        if not source.exists():
            logger.warning("添加文档失败，源文件不存在: path=%s", source)
            raise InvalidDocumentError(f"Source file does not exist: {source}")
        if not source.is_file():
            logger.warning("添加文档失败，源路径不是文件: path=%s", source)
            raise InvalidDocumentError(f"Source path is not a file: {source}")

        try:
            with source.open("rb") as source_stream:
                return self._store_document(source.name, source_stream, original_path=str(source))
        except OSError as exc:
            raise StorageError(f"Unable to read document: {source}") from exc

    def add_uploaded_document(self, filename: str, source: BinaryIO) -> Document:
        """保存 HTTP 上传文件，并在成功后写入文档元数据。"""
        safe_name = Path(filename.replace("\\", "/")).name.strip()
        if not safe_name or safe_name in {".", ".."}:
            raise InvalidDocumentError("Uploaded file must have a valid filename")

        file_type = Path(safe_name).suffix.lower()
        if file_type not in self.ALLOWED_FILE_TYPES:
            allowed = ", ".join(sorted(self.ALLOWED_FILE_TYPES))
            raise InvalidDocumentError(
                f"Unsupported file type: {file_type or '(none)'}; allowed: {allowed}"
            )

        return self._store_document(safe_name, source, original_path=safe_name)

    def _store_document(
        self,
        filename: str,
        source: BinaryIO,
        *,
        original_path: str,
    ) -> Document:
        """保存原文件；元数据写入失败时补偿删除已保存对象。"""
        try:
            stored = self._storage.save(filename, source)
        except ValueError as exc:
            raise InvalidDocumentError(str(exc)) from exc
        except OSError as exc:
            raise StorageError(f"Unable to store document: {filename}") from exc

        try:
            document = Document.create(
                original_path=original_path,
                stored_path=stored.object_key,
                file_size=stored.file_size,
            )
            self._repository.add(document)
        except (DocumentConflictError, StorageError):
            try:
                self._storage.delete(stored.object_key)
            except (OSError, StorageError):
                logger.exception("元数据保存失败后清理存储对象失败: key=%s", stored.object_key)
            raise

        logger.info(
            "文档保存成功: id=%s name=%s object_key=%s size=%d",
            document.id,
            document.name,
            document.stored_path,
            document.file_size,
        )
        return document

    def list_documents(self) -> list[Document]:
        """Return all managed documents."""
        return self._repository.list_all()

    def list_documents_page(self, offset: int, limit: int) -> tuple[list[Document], int]:
        """返回一页文档以及数据库中的总数。"""
        return self._repository.list_page(offset, limit), self._repository.count()

    def get_document(self, document_id: str) -> Document:
        """按 Cache Aside 顺序读取文档详情。"""
        if self._cache is not None:
            cached = self._cache.get(document_id)
            if cached is not None:
                return cached

        document = self._repository.get_by_id(document_id)
        if self._cache is not None:
            self._cache.set(document, self._cache_ttl_seconds)
        return document

    def update_document(
        self,
        document_id: str,
        *,
        name: str | None = None,
        document_status: str | None = None,
    ) -> Document:
        """只更新 API 允许修改的名称和状态字段。"""
        document = self._repository.get_by_id(document_id)
        updated_name = document.name
        if name is not None:
            normalized_name = name.strip()
            if not normalized_name:
                raise InvalidDocumentError("Document name must not be blank")
            updated_name = normalized_name

        updated_status = document.status
        if document_status is not None:
            if document_status not in {"uploaded", "processing", "ready", "failed"}:
                raise InvalidDocumentError(f"Unsupported document status: {document_status}")
            updated_status = document_status

        if name is None and document_status is None:
            raise InvalidDocumentError("At least one update field is required")

        updated = self._repository.update(
            replace(document, name=updated_name, status=updated_status)
        )
        if self._cache is not None:
            self._cache.delete(document_id)
        return updated

    def delete_document(self, document_id: str) -> Document:
        """Delete a stored file and its metadata."""
        document = self._repository.get_by_id(document_id)

        # 先做一次安全性和可访问性检查。本地存储会在这里拒绝越界路径。
        self._storage.exists(document.stored_path)
        removed = self._repository.delete(document_id)

        try:
            self._storage.delete(removed.stored_path)
        except (OSError, StorageError) as exc:
            logger.warning(
                "删除元数据后清理存储对象失败: key=%s error=%s",
                removed.stored_path,
                exc,
            )

        if self._cache is not None:
            self._cache.delete(document_id)

        logger.info("文档删除成功: id=%s name=%s", removed.id, removed.name)
        return removed
