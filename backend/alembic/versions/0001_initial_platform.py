"""initial intelligence platform

Revision ID: 0001_initial_platform
Revises:
Create Date: 2026-09-01
"""

from alembic import op
from app import models  # noqa: F401
from app.database import Base

revision = "0001_initial_platform"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
