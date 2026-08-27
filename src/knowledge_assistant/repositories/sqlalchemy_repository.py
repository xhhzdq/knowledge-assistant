"""使用 SQLAlchemy 和 PostgreSQL 保存文档元数据。"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from knowledge_assistant.db.models import DocumentORM
from knowledge_assistant.exceptions import (
    DocumentConflictError,
    DocumentNotFoundError,
    StorageError,
)
from knowledge_assistant.models import Document

logger = logging.getLogger(__name__)


class SqlAlchemyDocumentRepository:
    """在一个明确的 Session 生命周期内完成文档 CRUD。"""

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_all(self) -> list[Document]:
        """按创建时间和 ID 返回全部文档。"""
        statement = select(DocumentORM).order_by(DocumentORM.created_at, DocumentORM.id)
        try:
            rows = self._session.scalars(statement).all()
        except SQLAlchemyError as exc:
            logger.exception("查询文档列表失败")
            raise StorageError("Unable to list documents") from exc
        return [self._to_domain(row) for row in rows]

    def list_page(self, offset: int, limit: int) -> list[Document]:
        """在 PostgreSQL 中完成排序和分页。"""
        statement = (
            select(DocumentORM)
            .order_by(DocumentORM.created_at.desc(), DocumentORM.id)
            .offset(offset)
            .limit(limit)
        )
        try:
            rows = self._session.scalars(statement).all()
        except SQLAlchemyError as exc:
            logger.exception("分页查询文档失败: offset=%d limit=%d", offset, limit)
            raise StorageError("Unable to list documents") from exc
        return [self._to_domain(row) for row in rows]

    def count(self) -> int:
        """使用 COUNT 在数据库中统计文档总数。"""
        try:
            total = self._session.scalar(select(func.count()).select_from(DocumentORM))
        except SQLAlchemyError as exc:
            logger.exception("统计文档数量失败")
            raise StorageError("Unable to count documents") from exc
        return total or 0

    def get_by_id(self, document_id: str) -> Document:
        """按 UUID 查询文档，不存在时抛出领域异常。"""
        document_uuid = self._parse_document_id(document_id)
        try:
            row = self._session.get(DocumentORM, document_uuid)
        except SQLAlchemyError as exc:
            logger.exception("查询文档失败: id=%s", document_id)
            raise StorageError(f"Unable to read document: {document_id}") from exc

        if row is None:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        return self._to_domain(row)

    def add(self, document: Document) -> None:
        """写入文档并提交事务。"""
        row = self._from_domain(document)
        self._session.add(row)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("文档数据违反数据库约束: id=%s", document.id)
            raise DocumentConflictError(
                f"Document conflicts with existing data: {document.id}"
            ) from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("写入文档失败: id=%s", document.id)
            raise StorageError(f"Unable to add document: {document.id}") from exc

    def update(self, document: Document) -> Document:
        """使用领域对象中的值更新已有文档。"""
        document_uuid = self._parse_document_id(document.id)
        try:
            row = self._session.get(DocumentORM, document_uuid)
            if row is None:
                raise DocumentNotFoundError(f"Document not found: {document.id}")

            row.name = document.name
            row.original_path = document.original_path
            row.stored_path = document.stored_path
            row.file_type = document.file_type
            row.file_size = document.file_size
            row.status = document.status
            self._session.commit()
        except DocumentNotFoundError:
            self._session.rollback()
            raise
        except IntegrityError as exc:
            self._session.rollback()
            logger.warning("更新数据违反数据库约束: id=%s", document.id)
            raise StorageError(f"Unable to update document: {document.id}") from exc
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("更新文档失败: id=%s", document.id)
            raise StorageError(f"Unable to update document: {document.id}") from exc

        return self._to_domain(row)

    def delete(self, document_id: str) -> Document:
        """删除并返回文档，不存在时抛出领域异常。"""
        document_uuid = self._parse_document_id(document_id)
        try:
            row = self._session.get(DocumentORM, document_uuid)
            if row is None:
                raise DocumentNotFoundError(f"Document not found: {document_id}")

            document = self._to_domain(row)
            self._session.delete(row)
            self._session.commit()
        except DocumentNotFoundError:
            self._session.rollback()
            raise
        except SQLAlchemyError as exc:
            self._session.rollback()
            logger.exception("删除文档失败: id=%s", document_id)
            raise StorageError(f"Unable to delete document: {document_id}") from exc

        return document

    @staticmethod
    def _parse_document_id(document_id: str) -> UUID:
        """将领域层的字符串 ID 转换为 PostgreSQL UUID。"""
        try:
            return UUID(document_id)
        except ValueError as exc:
            raise DocumentNotFoundError(f"Document not found: {document_id}") from exc

    @staticmethod
    def _from_domain(document: Document) -> DocumentORM:
        """把领域对象转换成待持久化的 ORM 对象。"""
        return DocumentORM(
            id=SqlAlchemyDocumentRepository._parse_document_id(document.id),
            name=document.name,
            original_path=document.original_path,
            stored_path=document.stored_path,
            file_type=document.file_type,
            file_size=document.file_size,
            status=document.status,
            created_at=SqlAlchemyDocumentRepository._parse_created_at(document.created_at),
        )

    @staticmethod
    def _to_domain(row: DocumentORM) -> Document:
        """把 ORM 对象转换成不依赖 SQLAlchemy 的领域对象。"""
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        return Document(
            id=str(row.id),
            name=row.name,
            original_path=row.original_path,
            stored_path=row.stored_path,
            file_type=row.file_type,
            file_size=row.file_size,
            status=row.status,
            created_at=created_at.astimezone(UTC).isoformat(),
        )

    @staticmethod
    def _parse_created_at(created_at: str) -> datetime:
        """把领域层 ISO 8601 字符串转换为带时区 datetime。"""
        value = datetime.fromisoformat(created_at)
        if value.tzinfo is None:
            raise StorageError("Document created_at must include a timezone")
        return value
