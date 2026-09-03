"""PostgreSQL 对应的 SQLAlchemy ORM 模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    REAL,
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from knowledge_assistant.db.base import Base


class DocumentORM(Base):
    """将 Python 属性映射到 PostgreSQL 的 documents 表。"""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("btrim(name) <> ''", name="ck_documents_name_not_blank"),
        CheckConstraint("file_size >= 0", name="ck_documents_file_size_non_negative"),
        CheckConstraint(
            "processing_version >= 0",
            name="ck_documents_processing_version_non_negative",
        ),
        CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')",
            name="ck_documents_status",
        ),
        UniqueConstraint("stored_path", name="uq_documents_stored_path"),
        Index("ix_documents_status_created_at", "status", text("created_at DESC")),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    original_path: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[str] = mapped_column(String(32), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="uploaded",
        server_default="uploaded",
    )
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    processing_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=True,
    )
    processing_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunks: Mapped[list["DocumentChunkORM"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DocumentChunkORM(Base):
    """将解析后的稳定文本块映射到 document_chunks 表。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        CheckConstraint(
            "processing_version > 0",
            name="ck_document_chunks_processing_version_positive",
        ),
        CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_non_negative",
        ),
        CheckConstraint(
            "btrim(content) <> ''",
            name="ck_document_chunks_content_not_blank",
        ),
        CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_document_chunks_content_hash_length",
        ),
        CheckConstraint(
            "char_start >= 0",
            name="ck_document_chunks_char_start_non_negative",
        ),
        CheckConstraint(
            "char_end > char_start",
            name="ck_document_chunks_char_range",
        ),
        CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR "
            "(page_start > 0 AND page_end >= page_start)",
            name="ck_document_chunks_page_range",
        ),
        CheckConstraint(
            "source_type IN ('parser', 'ocr', 'mixed')",
            name="ck_document_chunks_source_type",
        ),
        CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_document_chunks_ocr_confidence",
        ),
        CheckConstraint(
            "token_count > 0",
            name="ck_document_chunks_token_count_positive",
        ),
        UniqueConstraint(
            "document_id",
            "processing_version",
            "chunk_index",
            name="uq_document_chunks_document_version_index",
        ),
        Index("ix_document_chunks_document_chunk", "document_id", "chunk_index"),
        Index(
            "ix_document_chunks_document_version",
            "document_id",
            "processing_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(PostgreSQLUUID(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_document_chunks_document_id"),
        nullable=False,
    )
    processing_version: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_type: Mapped[str] = mapped_column(String(16), nullable=False)
    ocr_confidence: Mapped[float | None] = mapped_column(REAL, nullable=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    document: Mapped[DocumentORM] = relationship(back_populates="chunks")
