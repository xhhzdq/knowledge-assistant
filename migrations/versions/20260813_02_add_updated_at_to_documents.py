"""为 documents 添加更新时间。

Revision ID: 20260813_02
Revises: 20260813_01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260813_02"
down_revision: str | None = "20260813_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """增加非空 updated_at，并为已有行提供默认时间。"""
    op.add_column(
        "documents",
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """移除 updated_at，恢复第一版表结构。"""
    op.drop_column("documents", "updated_at")
