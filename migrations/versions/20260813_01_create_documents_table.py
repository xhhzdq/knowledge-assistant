"""创建 documents 表。

Revision ID: 20260813_01
Revises: None
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建第一版文档元数据表及索引。"""
    op.create_table(
        "documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("file_type", sa.String(length=32), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'uploaded'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("file_size >= 0", name="ck_documents_file_size_non_negative"),
        sa.CheckConstraint("btrim(name) <> ''", name="ck_documents_name_not_blank"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'processing', 'ready', 'failed')",
            name="ck_documents_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
        sa.UniqueConstraint("stored_path", name="uq_documents_stored_path"),
    )
    op.create_index(
        "ix_documents_status_created_at",
        "documents",
        ["status", sa.literal_column("created_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    """删除文档表并回到空业务数据库。"""
    op.drop_index("ix_documents_status_created_at", table_name="documents")
    op.drop_table("documents")
