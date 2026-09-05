"""add UI-managed email OAuth provider configuration

Revision ID: 0012_email_oauth_provider_config
Revises: 0011_email_notifications
Create Date: 2026-09-05
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_email_oauth_provider_config"
down_revision = "0011_email_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table("email_oauth_provider_configs"):
        return
    op.create_table(
        "email_oauth_provider_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("client_id", sa.String(512), nullable=False),
        sa.Column("client_secret_encrypted", sa.Text()),
        sa.Column("tenant", sa.String(255)),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("provider", name="email_oauth_provider_configs_provider_key"),
    )
    op.create_index(
        "ix_email_oauth_provider_configs_provider",
        "email_oauth_provider_configs",
        ["provider"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_oauth_provider_configs_provider", table_name="email_oauth_provider_configs")
    op.drop_table("email_oauth_provider_configs")
