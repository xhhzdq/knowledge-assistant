"""PostgreSQL repository for the current set of document chunks."""

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from knowledge_assistant.db.models import DocumentChunkORM
from knowledge_assistant.exceptions import DocumentConflictError, StorageError
from knowledge_assistant.processing.models import TextChunk

logger = logging.getLogger(__name__)


class DocumentChunkRepository(Protocol):
    """Persistence operations required by processing and search services."""

    def replace_for_document(
        self,
        document_id: str,
        chunks: list[TextChunk],
        *,
        commit: bool = True,
    ) -> None:
        """替换文档 Chunk；``commit=False`` 时由同一 Session 的外层事务提交。"""
        ...

    def list_page(
        self,
        document_id: str,
        offset: int,
        limit: int,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> list[TextChunk]:
        """Return current chunks ordered by their stable chunk index."""
        ...

    def count(
        self,
        document_id: str,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> int:
        """Count the current chunks for one document."""
        ...

    def get_many_by_ids(self, chunk_ids: list[str]) -> list[TextChunk]:
        """Return existing chunks in the same order as the requested IDs."""
        ...

    def delete_by_document(self, document_id: str) -> int:
        """Delete all chunks for one document and return the removed count."""
        ...


class SqlAlchemyDocumentChunkRepository:
    """SQLAlchemy implementation backed by the ``document_chunks`` table."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def replace_for_document(
        self,
        document_id: str,
        chunks: list[TextChunk],
        *,
        commit: bool = True,
    ) -> None:
        """替换文档 Chunk，并可把提交动作交给处理服务的文档状态更新。"""
        document_uuid = self._parse_uuid(document_id, "document_id")
        rows: list[DocumentChunkORM] = []
        for chunk in chunks:
            if chunk.document_id != document_id:
                raise ValueError("Every chunk must belong to the document being replaced")
            rows.append(self._from_domain(chunk))

        try:
            self._session.execute(
                delete(DocumentChunkORM).where(DocumentChunkORM.document_id == document_uuid)
            )
            self._session.add_all(rows)
            if commit:
                self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("Chunk 数据违反数据库约束: document_id=%s", document_id)
            raise DocumentConflictError(
                f"Document chunks conflict with existing data: {document_id}"
            ) from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("替换文档 Chunk 失败: document_id=%s", document_id)
            raise StorageError(f"Unable to replace document chunks: {document_id}") from exc

    def list_page(
        self,
        document_id: str,
        offset: int,
        limit: int,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> list[TextChunk]:
        if offset < 0 or limit <= 0:
            raise ValueError("offset must be non-negative and limit must be positive")
        document_uuid = self._parse_uuid(document_id, "document_id")
        filters = self._filters(document_uuid, processing_version, page_number)
        statement = select(DocumentChunkORM).where(*filters)
        statement = statement.order_by(DocumentChunkORM.chunk_index).offset(offset).limit(limit)
        try:
            rows = self._session.scalars(statement).all()
        except SQLAlchemyError as exc:
            logger.exception("分页读取文档 Chunk 失败: document_id=%s", document_id)
            raise StorageError(f"Unable to list document chunks: {document_id}") from exc
        return [self._to_domain(row) for row in rows]

    def count(
        self,
        document_id: str,
        *,
        processing_version: int | None = None,
        page_number: int | None = None,
    ) -> int:
        document_uuid = self._parse_uuid(document_id, "document_id")
        filters = self._filters(document_uuid, processing_version, page_number)
        statement = select(func.count()).select_from(DocumentChunkORM).where(*filters)
        try:
            total = self._session.scalar(statement)
        except SQLAlchemyError as exc:
            logger.exception("统计文档 Chunk 失败: document_id=%s", document_id)
            raise StorageError(f"Unable to count document chunks: {document_id}") from exc
        return total or 0

    @staticmethod
    def _filters(
        document_id: UUID,
        processing_version: int | None,
        page_number: int | None,
    ) -> list[ColumnElement[bool]]:
        """构造版本与页码相交过滤条件，供列表和计数保持一致。"""
        filters: list[ColumnElement[bool]] = [DocumentChunkORM.document_id == document_id]
        if processing_version is not None:
            filters.append(DocumentChunkORM.processing_version == processing_version)
        if page_number is not None:
            filters.extend(
                [
                    DocumentChunkORM.page_start.is_not(None),
                    DocumentChunkORM.page_end.is_not(None),
                    DocumentChunkORM.page_start <= page_number,
                    DocumentChunkORM.page_end >= page_number,
                ]
            )
        return filters

    def get_many_by_ids(self, chunk_ids: list[str]) -> list[TextChunk]:
        if not chunk_ids:
            return []
        parsed_ids = [self._parse_uuid(chunk_id, "chunk_id") for chunk_id in chunk_ids]
        unique_ids = list(dict.fromkeys(parsed_ids))
        statement = select(DocumentChunkORM).where(DocumentChunkORM.id.in_(unique_ids))
        try:
            rows = self._session.scalars(statement).all()
        except SQLAlchemyError as exc:
            logger.exception("批量读取 Chunk 失败: count=%d", len(chunk_ids))
            raise StorageError("Unable to read document chunks") from exc

        rows_by_id = {row.id: self._to_domain(row) for row in rows}
        return [rows_by_id[chunk_id] for chunk_id in parsed_ids if chunk_id in rows_by_id]

    def delete_by_document(self, document_id: str) -> int:
        document_uuid = self._parse_uuid(document_id, "document_id")
        try:
            total = self._session.scalar(
                select(func.count()).select_from(DocumentChunkORM).where(
                    DocumentChunkORM.document_id == document_uuid
                )
            )
            self._session.execute(
                delete(DocumentChunkORM).where(DocumentChunkORM.document_id == document_uuid)
            )
            self._session.commit()
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("删除文档 Chunk 失败: document_id=%s", document_id)
            raise StorageError(f"Unable to delete document chunks: {document_id}") from exc
        return total or 0

    @staticmethod
    def _parse_uuid(raw_value: str, field_name: str) -> UUID:
        try:
            return UUID(raw_value)
        except ValueError as exc:
            raise StorageError(f"Invalid {field_name}: {raw_value}") from exc

    @staticmethod
    def _from_domain(chunk: TextChunk) -> DocumentChunkORM:
        return DocumentChunkORM(
            id=SqlAlchemyDocumentChunkRepository._parse_uuid(chunk.id, "chunk_id"),
            document_id=SqlAlchemyDocumentChunkRepository._parse_uuid(
                chunk.document_id,
                "document_id",
            ),
            processing_version=chunk.processing_version,
            chunk_index=chunk.chunk_index,
            content=chunk.content,
            content_hash=chunk.content_hash,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            page_start=chunk.page_start,
            page_end=chunk.page_end,
            source_type=chunk.source_type,
            ocr_confidence=chunk.ocr_confidence,
            token_count=chunk.token_count,
            created_at=chunk.created_at.astimezone(UTC),
        )

    @staticmethod
    def _to_domain(row: DocumentChunkORM) -> TextChunk:
        created_at: datetime = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        return TextChunk(
            id=str(row.id),
            document_id=str(row.document_id),
            processing_version=row.processing_version,
            chunk_index=row.chunk_index,
            content=row.content,
            content_hash=row.content_hash,
            char_start=row.char_start,
            char_end=row.char_end,
            page_start=row.page_start,
            page_end=row.page_end,
            source_type=row.source_type,  # type: ignore[arg-type]
            ocr_confidence=row.ocr_confidence,
            token_count=row.token_count,
            created_at=created_at.astimezone(UTC),
        )
