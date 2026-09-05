"""add incident geocoding and terminal route metadata

Revision ID: 0003_incident_google_geo
Revises: 0002_news_feed_url
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_incident_google_geo"
down_revision = "0002_news_feed_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("incident")}
    additions = (
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("geocoded_address", sa.Text(), nullable=True),
        sa.Column("geocoding_provider", sa.String(length=32), nullable=True),
        sa.Column("geocoding_confidence", sa.Float(), nullable=True),
        sa.Column("nearest_terminal_distance_source", sa.String(length=40), nullable=True),
        sa.Column("nearest_terminal_duration_minutes", sa.Float(), nullable=True),
    )
    for column in additions:
        if column.name not in existing:
            op.add_column("incident", column)
    op.execute(
        """
        UPDATE incident AS i
        SET latitude = l.latitude,
            longitude = l.longitude,
            geocoded_address = l.normalized_name,
            geocoding_provider = 'MASTER_LOCATION',
            geocoding_confidence = 0.95,
            nearest_terminal_distance_source = CASE
                WHEN i.nearest_terminal_distance_km IS NOT NULL THEN 'POSTGIS_STRAIGHT_LINE'
                ELSE NULL
            END
        FROM master_location AS l
        WHERE i.location_id = l.id
        """
    )


def downgrade() -> None:
    op.drop_column("incident", "nearest_terminal_duration_minutes")
    op.drop_column("incident", "nearest_terminal_distance_source")
    op.drop_column("incident", "geocoding_confidence")
    op.drop_column("incident", "geocoding_provider")
    op.drop_column("incident", "geocoded_address")
    op.drop_column("incident", "longitude")
    op.drop_column("incident", "latitude")
