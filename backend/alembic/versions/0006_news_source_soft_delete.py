"""add soft delete lifecycle to news sources

Revision ID: 0006_news_source_soft_delete
Revises: 0005_verified_tbbm_runtime
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0006_news_source_soft_delete"
down_revision = "0005_verified_tbbm_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {item["name"] for item in sa.inspect(bind).get_columns("news_source")}
    if "deleted_at" not in columns:
        op.add_column("news_source", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    indexes = {item["name"] for item in sa.inspect(bind).get_indexes("news_source")}
    if "ix_news_source_deleted_at" not in indexes:
        op.create_index("ix_news_source_deleted_at", "news_source", ["deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_news_source_deleted_at", table_name="news_source")
    op.drop_column("news_source", "deleted_at")
