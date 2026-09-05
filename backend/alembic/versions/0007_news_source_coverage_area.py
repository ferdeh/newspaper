"""add coverage area to news sources

Revision ID: 0007_news_source_coverage_area
Revises: 0006_news_source_soft_delete
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0007_news_source_coverage_area"
down_revision = "0006_news_source_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("news_source")}
    if "coverage_area" not in columns:
        op.add_column("news_source", sa.Column("coverage_area", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("news_source", "coverage_area")
