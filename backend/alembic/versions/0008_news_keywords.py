"""add configurable News collection keywords

Revision ID: 0008_news_keywords
Revises: 0007_news_source_coverage_area
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0008_news_keywords"
down_revision = "0007_news_source_coverage_area"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
DEFAULT_KEYWORDS = ("BBM langka", "antrean SPBU", "mobil tangki BBM", "distribusi BBM")


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("news_keyword"):
        op.create_table(
            "news_keyword",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("keyword", sa.String(length=180), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        )

    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("news_keyword")}
    if "ix_news_keyword_is_active" not in existing_indexes:
        op.create_index("ix_news_keyword_is_active", "news_keyword", ["is_active"])
    if "ix_news_keyword_deleted_at" not in existing_indexes:
        op.create_index("ix_news_keyword_deleted_at", "news_keyword", ["deleted_at"])
    if "uq_news_keyword_keyword_lower" not in existing_indexes:
        op.create_index("uq_news_keyword_keyword_lower", "news_keyword", [sa.text("lower(keyword)")], unique=True)

    for keyword in DEFAULT_KEYWORDS:
        exists = bind.execute(
            sa.text("SELECT 1 FROM news_keyword WHERE lower(keyword) = lower(:keyword)"),
            {"keyword": keyword},
        ).scalar()
        if not exists:
            bind.execute(
                sa.text(
                    "INSERT INTO news_keyword (keyword, is_active, created_at, updated_at) "
                    "VALUES (:keyword, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"keyword": keyword},
            )


def downgrade() -> None:
    op.drop_table("news_keyword")
