"""make PostGIS the sole nearest-TBBM calculation method

Revision ID: 0013_postgis_nearest_tbbm
Revises: 0012_email_oauth_provider_config
Create Date: 2026-09-05
"""

from alembic import op

revision = "0013_postgis_nearest_tbbm"
down_revision = "0012_email_oauth_provider_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Remove historical road-route values before rebuilding every geolocated
    # incident from the canonical verified, non-deleted TBBM registry.
    op.execute("""
        UPDATE incident
        SET nearest_tbbm_id = NULL,
            nearest_terminal_distance_km = NULL,
            nearest_terminal_distance_source = NULL,
            nearest_terminal_duration_minutes = NULL
    """)
    op.execute("""
        WITH ranked AS (
            SELECT i.id AS incident_id,
                   mt.id AS tbbm_id,
                   ST_Distance(
                       mt.geom,
                       ST_SetSRID(ST_MakePoint(i.longitude, i.latitude), 4326)::geography
                   ) / 1000.0 AS distance_km,
                   ROW_NUMBER() OVER (
                       PARTITION BY i.id
                       ORDER BY ST_Distance(
                           mt.geom,
                           ST_SetSRID(ST_MakePoint(i.longitude, i.latitude), 4326)::geography
                       )
                   ) AS rank
            FROM incident AS i
            CROSS JOIN master_tbbm AS mt
            WHERE i.latitude IS NOT NULL
              AND i.longitude IS NOT NULL
              AND mt.geom IS NOT NULL
              AND mt.verification_status = 'VERIFIED'
              AND mt.deleted_at IS NULL
        )
        UPDATE incident AS i
        SET nearest_tbbm_id = ranked.tbbm_id,
            nearest_terminal_distance_km = ROUND(ranked.distance_km::numeric, 2),
            nearest_terminal_distance_source = 'POSTGIS_STRAIGHT_LINE',
            nearest_terminal_duration_minutes = NULL
        FROM ranked
        WHERE ranked.incident_id = i.id
          AND ranked.rank = 1
    """)


def downgrade() -> None:
    # Previous Google route values cannot be reconstructed without external
    # calls. Older application code can recalculate them after a downgrade.
    pass
