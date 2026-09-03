"""增加文档处理字段并创建 document_chunks 表。

Revision ID: 20260901_01
Revises: 20260813_02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_01"
down_revision: str | None = "20260813_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """扩展 documents，并创建带完整约束的 Chunk 持久化表。"""
    op.add_column(
        "documents",
        sa.Column(
            "processing_version",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("processed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("processing_error", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_documents_processing_version_non_negative",
        "documents",
        "processing_version >= 0",
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("processing_version", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("ocr_confidence", sa.REAL(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "processing_version > 0",
            name="ck_document_chunks_processing_version_positive",
        ),
        sa.CheckConstraint(
            "chunk_index >= 0",
            name="ck_document_chunks_chunk_index_non_negative",
        ),
        sa.CheckConstraint(
            "btrim(content) <> ''",
            name="ck_document_chunks_content_not_blank",
        ),
        sa.CheckConstraint(
            "char_length(content_hash) = 64",
            name="ck_document_chunks_content_hash_length",
        ),
        sa.CheckConstraint(
            "char_start >= 0",
            name="ck_document_chunks_char_start_non_negative",
        ),
        sa.CheckConstraint(
            "char_end > char_start",
            name="ck_document_chunks_char_range",
        ),
        sa.CheckConstraint(
            "(page_start IS NULL AND page_end IS NULL) OR "
            "(page_start > 0 AND page_end >= page_start)",
            name="ck_document_chunks_page_range",
        ),
        sa.CheckConstraint(
            "source_type IN ('parser', 'ocr', 'mixed')",
            name="ck_document_chunks_source_type",
        ),
        sa.CheckConstraint(
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
            name="ck_document_chunks_ocr_confidence",
        ),
        sa.CheckConstraint(
            "token_count > 0",
            name="ck_document_chunks_token_count_positive",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_document_chunks"),
        sa.UniqueConstraint(
            "document_id",
            "processing_version",
            "chunk_index",
            name="uq_document_chunks_document_version_index",
        ),
    )
    op.create_index(
        "ix_document_chunks_document_chunk",
        "document_chunks",
        ["document_id", "chunk_index"],
        unique=False,
    )
    op.create_index(
        "ix_document_chunks_document_version",
        "document_chunks",
        ["document_id", "processing_version"],
        unique=False,
    )


def downgrade() -> None:
    """删除 Chunk 表和文档处理字段，恢复上一版本结构。"""
    op.drop_index("ix_document_chunks_document_version", table_name="document_chunks")
    op.drop_index("ix_document_chunks_document_chunk", table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_constraint(
        "ck_documents_processing_version_non_negative",
        "documents",
        type_="check",
    )
    op.drop_column("documents", "processing_error")
    op.drop_column("documents", "processed_at")
    op.drop_column("documents", "content_hash")
    op.drop_column("documents", "processing_version")
