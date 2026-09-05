"""add configurable News feed endpoint

Revision ID: 0002_news_feed_url
Revises: 0001_initial_platform
Create Date: 2026-09-01
"""

import sqlalchemy as sa

from alembic import op

revision = "0002_news_feed_url"
down_revision = "0001_initial_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("news_source")}
    if "feed_url" not in columns:
        op.add_column("news_source", sa.Column("feed_url", sa.Text(), nullable=True))


def downgrade() -> None:
    columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("news_source")}
    if "feed_url" in columns:
        op.drop_column("news_source", "feed_url")
