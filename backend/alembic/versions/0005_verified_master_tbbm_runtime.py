"""use verified Master TBBM for operational relationships

Revision ID: 0005_verified_tbbm_runtime
Revises: 0004_master_tbbm_discovery
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0005_verified_tbbm_runtime"
down_revision = "0004_master_tbbm_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)

    inspector = sa.inspect(op.get_bind())
    master_spbu_columns = {item["name"] for item in inspector.get_columns("master_spbu")}
    if "serving_tbbm_id" not in master_spbu_columns:
        op.add_column("master_spbu", sa.Column("serving_tbbm_id", uuid_type, nullable=True))
        op.create_foreign_key("fk_master_spbu_serving_tbbm", "master_spbu", "master_tbbm", ["serving_tbbm_id"], ["id"])
        op.create_index("ix_master_spbu_serving_tbbm_id", "master_spbu", ["serving_tbbm_id"])

    incident_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("incident")}
    if "nearest_tbbm_id" not in incident_columns:
        op.add_column("incident", sa.Column("nearest_tbbm_id", uuid_type, nullable=True))
        op.create_foreign_key("fk_incident_nearest_tbbm", "incident", "master_tbbm", ["nearest_tbbm_id"], ["id"])
        op.create_index("ix_incident_nearest_tbbm_id", "incident", ["nearest_tbbm_id"])
    if "serving_tbbm_id" not in incident_columns:
        op.add_column("incident", sa.Column("serving_tbbm_id", uuid_type, nullable=True))
        op.create_foreign_key("fk_incident_serving_tbbm", "incident", "master_tbbm", ["serving_tbbm_id"], ["id"])
        op.create_index("ix_incident_serving_tbbm_id", "incident", ["serving_tbbm_id"])

    analytics_columns = {item["name"] for item in sa.inspect(op.get_bind()).get_columns("analytics_daily")}
    if "tbbm_id" not in analytics_columns:
        op.add_column("analytics_daily", sa.Column("tbbm_id", uuid_type, nullable=True))
        op.create_foreign_key("fk_analytics_daily_tbbm", "analytics_daily", "master_tbbm", ["tbbm_id"], ["id"])
        op.create_index("ix_analytics_daily_tbbm_id", "analytics_daily", ["tbbm_id"])

    # Preserve explicit SPBU mappings by matching the canonical terminal code.
    op.execute("""
        UPDATE master_spbu AS s
        SET serving_tbbm_id = mt.id
        FROM master_terminal AS legacy
        JOIN master_tbbm AS mt ON mt.tbbm_code = legacy.terminal_code
        WHERE s.serving_terminal_id = legacy.id
          AND mt.verification_status = 'VERIFIED'
          AND mt.deleted_at IS NULL
    """)
    op.execute("""
        UPDATE incident AS i
        SET serving_tbbm_id = s.serving_tbbm_id
        FROM master_spbu AS s
        WHERE i.spbu_id = s.id
          AND s.serving_tbbm_id IS NOT NULL
    """)

    # Recalculate every geolocated incident against the full verified registry.
    # This is local PostGIS work and does not trigger Google Routes requests.
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

    op.execute("""
        UPDATE analytics_daily AS daily
        SET tbbm_id = mt.id
        FROM master_terminal AS legacy
        JOIN master_tbbm AS mt ON mt.tbbm_code = legacy.terminal_code
        WHERE daily.terminal_id = legacy.id
          AND mt.verification_status = 'VERIFIED'
          AND mt.deleted_at IS NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_analytics_daily_tbbm_id", table_name="analytics_daily")
    op.drop_constraint("fk_analytics_daily_tbbm", "analytics_daily", type_="foreignkey")
    op.drop_column("analytics_daily", "tbbm_id")

    op.drop_index("ix_incident_serving_tbbm_id", table_name="incident")
    op.drop_index("ix_incident_nearest_tbbm_id", table_name="incident")
    op.drop_constraint("fk_incident_serving_tbbm", "incident", type_="foreignkey")
    op.drop_constraint("fk_incident_nearest_tbbm", "incident", type_="foreignkey")
    op.drop_column("incident", "serving_tbbm_id")
    op.drop_column("incident", "nearest_tbbm_id")

    op.drop_index("ix_master_spbu_serving_tbbm_id", table_name="master_spbu")
    op.drop_constraint("fk_master_spbu_serving_tbbm", "master_spbu", type_="foreignkey")
    op.drop_column("master_spbu", "serving_tbbm_id")
