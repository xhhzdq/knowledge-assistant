"""文档管理业务服务。"""

import logging
from dataclasses import replace
from pathlib import Path
from shutil import copy2
from typing import BinaryIO
from uuid import uuid4

from knowledge_assistant.exceptions import (
    DocumentConflictError,
    InvalidDocumentError,
    StorageError,
)
from knowledge_assistant.models import Document
from knowledge_assistant.repositories.base import DocumentRepository

logger = logging.getLogger(__name__)


class DocumentService:
    """Coordinate source files and persisted document metadata."""

    ALLOWED_FILE_TYPES = frozenset({".txt", ".md", ".pdf",".docx"})
    MAX_UPLOAD_SIZE = 10 * 1024 * 1024

    def __init__(self, repository: DocumentRepository, uploads_dir: Path) -> None:
        self._repository = repository
        self._uploads_dir = uploads_dir.resolve()

    def add_document(self, source: Path) -> Document:
        """Validate and copy a source file, then persist its metadata."""
        source = source.expanduser().resolve()
        if not source.exists():
            logger.warning("添加文档失败，源文件不存在: path=%s", source)
            raise InvalidDocumentError(f"Source file does not exist: {source}")
        if not source.is_file():
            logger.warning("添加文档失败，源路径不是文件: path=%s", source)
            raise InvalidDocumentError(f"Source path is not a file: {source}")

        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        destination = self._uploads_dir / f"{uuid4().hex}_{source.name}"
        document = Document.create(
            original_path=str(source),
            stored_path=str(destination),
            file_size=source.stat().st_size,
        )

        try:
            copy2(source, destination)
            self._repository.add(document)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            logger.error("复制文档失败: source=%s destination=%s", source, destination)
            raise StorageError(f"Unable to copy document: {source}") from exc
        except (DocumentConflictError, StorageError):
            destination.unlink(missing_ok=True)
            raise

        logger.info(
            "文档添加成功: id=%s name=%s size=%d",
            document.id,
            document.name,
            document.file_size,
        )
        return document

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

        self._uploads_dir.mkdir(parents=True, exist_ok=True)
        destination = self._uploads_dir / f"{uuid4().hex}_{safe_name}"

        try:
            file_size = self._copy_upload_with_limit(source, destination)
            document = Document.create(
                original_path=safe_name,
                stored_path=str(destination),
                file_size=file_size,
            )
            self._repository.add(document)
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise StorageError(f"Unable to store uploaded file: {safe_name}") from exc
        except (DocumentConflictError, StorageError, InvalidDocumentError):
            destination.unlink(missing_ok=True)
            raise

        logger.info(
            "HTTP 文档上传成功: id=%s name=%s size=%d",
            document.id,
            document.name,
            document.file_size,
        )
        return document

    def _copy_upload_with_limit(self, source: BinaryIO, destination: Path) -> int:
        """分块复制上传内容，并阻止文件超过配置的大小限制。"""
        total = 0
        with destination.open("wb") as target:
            while chunk := source.read(1024 * 1024):
                total += len(chunk)
                if total > self.MAX_UPLOAD_SIZE:
                    raise InvalidDocumentError(
                        f"Uploaded file exceeds {self.MAX_UPLOAD_SIZE} bytes"
                    )
                target.write(chunk)
        return total

    def list_documents(self) -> list[Document]:
        """Return all managed documents."""
        return self._repository.list_all()

    def list_documents_page(self, offset: int, limit: int) -> tuple[list[Document], int]:
        """返回一页文档以及数据库中的总数。"""
        return self._repository.list_page(offset, limit), self._repository.count()

    def get_document(self, document_id: str) -> Document:
        """Return one managed document."""
        return self._repository.get_by_id(document_id)

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

        return self._repository.update(
            replace(document, name=updated_name, status=updated_status)
        )

    def delete_document(self, document_id: str) -> Document:
        """Delete a stored file and its metadata."""
        document = self._repository.get_by_id(document_id)
        stored_file = Path(document.stored_path).resolve()

        try:
            stored_file.relative_to(self._uploads_dir)
        except ValueError as exc:
            logger.error("拒绝删除 uploads 目录外的文件: path=%s", stored_file)
            raise StorageError("Refusing to delete a file outside the uploads directory") from exc

        staged_file = stored_file.with_name(f".{stored_file.name}.{uuid4().hex}.deleting")
        file_was_staged = False

        try:
            if stored_file.exists():
                stored_file.replace(staged_file)
                file_was_staged = True
            removed = self._repository.delete(document_id)
        except (OSError, StorageError):
            if file_was_staged:
                staged_file.replace(stored_file)
            raise

        if file_was_staged:
            try:
                staged_file.unlink()
            except OSError:
                logger.exception("删除暂存文件失败，需要后续清理: path=%s", staged_file)
        logger.info("文档删除成功: id=%s name=%s", removed.id, removed.name)
        return removed
