"""allow multiple RSS feeds for one news publisher domain

Revision ID: 0009_news_source_feed_identity
Revises: 0008_news_keywords
Create Date: 2026-09-04
"""

import sqlalchemy as sa

from alembic import op

revision = "0009_news_source_feed_identity"
down_revision = "0008_news_keywords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    unique_constraints = inspector.get_unique_constraints("news_source")

    for constraint in unique_constraints:
        if constraint.get("column_names") == ["domain"] and constraint.get("name"):
            op.drop_constraint(constraint["name"], "news_source", type_="unique")

    if not any(constraint.get("column_names") == ["feed_url"] for constraint in unique_constraints):
        op.create_unique_constraint("uq_news_source_feed_url", "news_source", ["feed_url"])

    existing_indexes = {item["name"] for item in sa.inspect(bind).get_indexes("news_source")}
    if "ix_news_source_domain" not in existing_indexes:
        op.create_index("ix_news_source_domain", "news_source", ["domain"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_indexes = {item["name"] for item in inspector.get_indexes("news_source")}
    if "ix_news_source_domain" in existing_indexes:
        op.drop_index("ix_news_source_domain", table_name="news_source")

    unique_constraints = inspector.get_unique_constraints("news_source")
    for constraint in unique_constraints:
        if constraint.get("column_names") == ["feed_url"] and constraint.get("name"):
            op.drop_constraint(constraint["name"], "news_source", type_="unique")
    if not any(constraint.get("column_names") == ["domain"] for constraint in unique_constraints):
        op.create_unique_constraint("uq_news_source_domain", "news_source", ["domain"])
