"""JSON-backed document repository."""

import json
import logging
from pathlib import Path
from typing import cast

from knowledge_assistant.exceptions import (
    DocumentConflictError,
    DocumentNotFoundError,
    StorageError,
)
from knowledge_assistant.models import Document, DocumentData

logger = logging.getLogger(__name__)


class JsonDocumentRepository:
    """Persist document metadata in a local JSON file."""

    def __init__(self, metadata_file: Path) -> None:
        self._metadata_file = metadata_file

    def list_all(self) -> list[Document]:
        """Return all persisted documents."""
        documents = self._read_all()
        logger.debug("读取文档元数据完成: count=%d", len(documents))
        return documents

    def list_page(self, offset: int, limit: int) -> list[Document]:
        """分页返回 JSON 文件中的文档。"""
        return self._read_all()[offset : offset + limit]

    def count(self) -> int:
        """返回 JSON 文件中的文档总数。"""
        return len(self._read_all())

    def get_by_id(self, document_id: str) -> Document:
        """Return one document or raise when its ID is unknown."""
        for document in self._read_all():
            if document.id == document_id:
                return document

        raise DocumentNotFoundError(f"Document not found: {document_id}")

    def add(self, document: Document) -> None:
        """Append document metadata to the JSON file."""
        documents = self._read_all()
        if any(existing.id == document.id for existing in documents):
            raise DocumentConflictError(f"Duplicate document ID: {document.id}")

        documents.append(document)
        self._write_all(documents)
        logger.debug("写入文档元数据完成: id=%s", document.id)

    def update(self, document: Document) -> Document:
        """替换已有文档元数据并返回更新结果。"""
        documents = self._read_all()
        for index, existing in enumerate(documents):
            if existing.id == document.id:
                documents[index] = document
                self._write_all(documents)
                logger.debug("更新文档元数据完成: id=%s", document.id)
                return document

        raise DocumentNotFoundError(f"Document not found: {document.id}")

    def delete(self, document_id: str) -> Document:
        """Delete document metadata and return the removed document."""
        documents = self._read_all()

        for index, document in enumerate(documents):
            if document.id == document_id:
                removed = documents.pop(index)
                self._write_all(documents)
                logger.debug("删除文档元数据完成: id=%s", document_id)
                return removed

        raise DocumentNotFoundError(f"Document not found: {document_id}")

    def _read_all(self) -> list[Document]:
        if not self._metadata_file.exists():
            return []

        try:
            raw_data: object = json.loads(self._metadata_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("读取文档元数据失败: file=%s", self._metadata_file)
            raise StorageError(f"Unable to read metadata: {self._metadata_file}") from exc

        if not isinstance(raw_data, list):
            raise StorageError("Document metadata must contain a JSON list")

        documents: list[Document] = []
        try:
            for item in raw_data:
                if not isinstance(item, dict):
                    raise TypeError("Each document entry must be a JSON object")
                documents.append(Document.from_dict(cast(DocumentData, item)))
        except (KeyError, TypeError) as exc:
            logger.error("文档元数据内容不合法: file=%s", self._metadata_file)
            raise StorageError("Document metadata contains an invalid entry") from exc

        return documents

    def _write_all(self, documents: list[Document]) -> None:
        self._metadata_file.parent.mkdir(parents=True, exist_ok=True)
        temporary_file = self._metadata_file.with_suffix(".json.tmp")
        payload = [document.to_dict() for document in documents]

        try:
            temporary_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temporary_file.replace(self._metadata_file)
        except OSError as exc:
            temporary_file.unlink(missing_ok=True)
            logger.error("写入文档元数据失败: file=%s", self._metadata_file)
            raise StorageError(f"Unable to write metadata: {self._metadata_file}") from exc
