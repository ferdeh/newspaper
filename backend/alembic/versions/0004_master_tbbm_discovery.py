"""add Master TBBM discovery and review workflow

Revision ID: 0004_master_tbbm_discovery
Revises: 0003_incident_google_geo
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_master_tbbm_discovery"
down_revision = "0003_incident_google_geo"
branch_labels = None
depends_on = None

JSON_DEFAULT = sa.text("'[]'::jsonb")
NOW = sa.text("CURRENT_TIMESTAMP")

PROVINCES = [
    (11, "11", "Aceh"), (12, "12", "Sumatera Utara"), (13, "13", "Sumatera Barat"),
    (14, "14", "Riau"), (15, "15", "Jambi"), (16, "16", "Sumatera Selatan"),
    (17, "17", "Bengkulu"), (18, "18", "Lampung"), (19, "19", "Kepulauan Bangka Belitung"),
    (21, "21", "Kepulauan Riau"), (31, "31", "DKI Jakarta"), (32, "32", "Jawa Barat"),
    (33, "33", "Jawa Tengah"), (34, "34", "DI Yogyakarta"), (35, "35", "Jawa Timur"),
    (36, "36", "Banten"), (51, "51", "Bali"), (52, "52", "Nusa Tenggara Barat"),
    (53, "53", "Nusa Tenggara Timur"), (61, "61", "Kalimantan Barat"),
    (62, "62", "Kalimantan Tengah"), (63, "63", "Kalimantan Selatan"),
    (64, "64", "Kalimantan Timur"), (65, "65", "Kalimantan Utara"),
    (71, "71", "Sulawesi Utara"), (72, "72", "Sulawesi Tengah"),
    (73, "73", "Sulawesi Selatan"), (74, "74", "Sulawesi Tenggara"),
    (75, "75", "Gorontalo"), (76, "76", "Sulawesi Barat"), (81, "81", "Maluku"),
    (82, "82", "Maluku Utara"), (91, "91", "Papua Barat"), (92, "92", "Papua Barat Daya"),
    (94, "94", "Papua"), (95, "95", "Papua Selatan"), (96, "96", "Papua Tengah"),
    (97, "97", "Papua Pegunungan"),
]

KEYWORDS = [
    "TBBM Pertamina", "Terminal BBM Pertamina", "Fuel Terminal Pertamina",
    "Integrated Terminal Pertamina", "Depot Pertamina", "Depot BBM Pertamina",
    "Pertamina Fuel Terminal", "Pertamina Integrated Terminal", "Terminal BBM", "TBBM",
    "TLPG Pertamina",
]


def seed_existing_current_schema() -> None:
    """0001 historically creates current metadata; seed when tables already exist on a fresh install."""
    bind = op.get_bind()
    for province_id, code, name in PROVINCES:
        bind.execute(
            sa.text(
                "INSERT INTO master_province (id, code, name, is_active, created_at, updated_at) "
                "VALUES (:id, :code, :name, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (id) DO NOTHING"
            ),
            {"id": province_id, "code": code, "name": name},
        )
    for index, keyword in enumerate(KEYWORDS, start=1):
        bind.execute(
            sa.text(
                "INSERT INTO tbbm_discovery_keyword (keyword, is_active, sort_order, created_at, updated_at) "
                "VALUES (:keyword, true, :sort_order, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
                "ON CONFLICT (keyword) DO NOTHING"
            ),
            {"keyword": keyword, "sort_order": index},
        )
    bind.execute(
        sa.text(
            "INSERT INTO tbbm_setting "
            "(id, country, language_code, search_strategy, request_delay_ms, maximum_retry, timeout_seconds, "
            "duplicate_radius_meters, name_similarity_threshold, created_at, updated_at) VALUES "
            "(1, 'Indonesia', 'id', 'PROVINCE_BASED', 250, 3, 15, 300, 0.8, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (id) DO NOTHING"
        )
    )
    op.execute("""
        INSERT INTO master_tbbm (
            id, tbbm_code, name, normalized_name, terminal_type, latitude, longitude, geom,
            city, province_name, source, verification_status, operational_status,
            manual_overrides, google_types, created_at, updated_at
        )
        SELECT gen_random_uuid(), terminal_code, terminal_name, lower(trim(terminal_name)), terminal_type,
               latitude, longitude, geom, city, province, 'IMPORT', 'VERIFIED',
               CASE WHEN is_active THEN 'ACTIVE' ELSE 'INACTIVE' END,
               '[]'::jsonb, '[]'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM master_terminal
        ON CONFLICT (tbbm_code) DO NOTHING
    """)


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("master_tbbm"):
        seed_existing_current_schema()
        return
    op.create_table(
        "master_province",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(8), nullable=False, unique=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_master_province_is_active", "master_province", ["is_active"])

    op.create_table(
        "tbbm_discovery_keyword",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("keyword", sa.String(180), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_tbbm_discovery_keyword_is_active", "tbbm_discovery_keyword", ["is_active"])
    op.create_index("ix_tbbm_discovery_keyword_sort_order", "tbbm_discovery_keyword", ["sort_order"])

    op.create_table(
        "tbbm_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("country", sa.String(80), nullable=False, server_default="Indonesia"),
        sa.Column("language_code", sa.String(8), nullable=False, server_default="id"),
        sa.Column("search_strategy", sa.String(40), nullable=False, server_default="PROVINCE_BASED"),
        sa.Column("request_delay_ms", sa.Integer(), nullable=False, server_default="250"),
        sa.Column("maximum_retry", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("duplicate_radius_meters", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("name_similarity_threshold", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )

    op.create_table(
        "master_tbbm",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tbbm_code", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(180), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("terminal_type", sa.String(40), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("address", sa.Text()),
        sa.Column("city", sa.String(120)),
        sa.Column("regency", sa.String(120)),
        sa.Column("province_id", sa.Integer(), sa.ForeignKey("master_province.id")),
        sa.Column("province_name", sa.String(120)),
        sa.Column("postal_code", sa.String(20)),
        sa.Column("google_place_id", sa.String(255), unique=True),
        sa.Column("google_maps_uri", sa.Text()),
        sa.Column("google_primary_type", sa.String(120)),
        sa.Column("google_types", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("source", sa.String(24), nullable=False, server_default="MANUAL"),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="NEED_REVIEW"),
        sa.Column("operational_status", sa.String(24), nullable=False, server_default="UNKNOWN"),
        sa.Column("manual_overrides", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("first_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("last_discovered_at", sa.DateTime(timezone=True)),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.String(120)),
        sa.Column("updated_by", sa.String(120)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    for name, columns in {
        "ix_master_tbbm_tbbm_code": ["tbbm_code"], "ix_master_tbbm_name": ["name"],
        "ix_master_tbbm_normalized_name": ["normalized_name"], "ix_master_tbbm_terminal_type": ["terminal_type"],
        "ix_master_tbbm_province_id": ["province_id"], "ix_master_tbbm_province_name": ["province_name"],
        "ix_master_tbbm_source": ["source"], "ix_master_tbbm_verification_status": ["verification_status"],
        "ix_master_tbbm_operational_status": ["operational_status"], "ix_master_tbbm_deleted_at": ["deleted_at"],
    }.items():
        op.create_index(name, "master_tbbm", columns)
    op.create_index("ix_master_tbbm_geom_gist", "master_tbbm", ["geom"], postgresql_using="gist")

    op.create_table(
        "tbbm_discovery_job",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="PENDING"),
        sa.Column("search_scope", sa.String(32), nullable=False),
        sa.Column("selected_provinces", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("selected_keywords", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("retry_queries", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("existing_data_mode", sa.String(32), nullable=False, server_default="UPDATE_AND_ADD"),
        sa.Column("total_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_queries", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_query_details", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("raw_result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_place_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("existing_match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("possible_duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rejected_auto_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_province", sa.String(120)),
        sa.Column("current_keyword", sa.String(180)),
        sa.Column("created_by", sa.String(120)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    op.create_index("ix_tbbm_discovery_job_status", "tbbm_discovery_job", ["status"])

    op.create_table(
        "tbbm_discovery_result",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("discovery_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tbbm_discovery_job.id"), nullable=False),
        sa.Column("province_id", sa.Integer(), sa.ForeignKey("master_province.id")),
        sa.Column("province_name", sa.String(120)),
        sa.Column("keyword_id", sa.Integer(), sa.ForeignKey("tbbm_discovery_keyword.id")),
        sa.Column("keyword", sa.String(180), nullable=False),
        sa.Column("source_keywords", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("query_text", sa.String(320), nullable=False),
        sa.Column("query_provenance", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("query_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("google_place_id", sa.String(255)),
        sa.Column("place_name", sa.String(180), nullable=False),
        sa.Column("normalized_name", sa.String(180), nullable=False),
        sa.Column("formatted_address", sa.Text()),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("geom", Geography(geometry_type="POINT", srid=4326), nullable=True),
        sa.Column("google_maps_uri", sa.Text()),
        sa.Column("google_types", postgresql.JSONB(), nullable=False, server_default=JSON_DEFAULT),
        sa.Column("google_primary_type", sa.String(120)),
        sa.Column("terminal_type", sa.String(40), nullable=False),
        sa.Column("match_status", sa.String(32), nullable=False, server_default="NEW"),
        sa.Column("matched_master_tbbm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_tbbm.id")),
        sa.Column("duplicate_group_id", postgresql.UUID(as_uuid=True)),
        sa.Column("duplicate_distance_meters", sa.Float()),
        sa.Column("duplicate_score", sa.Float()),
        sa.Column("address_similarity", sa.Float()),
        sa.Column("review_status", sa.String(32), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
    )
    for name, columns in {
        "ix_tbbm_result_job": ["discovery_job_id"], "ix_tbbm_result_province": ["province_id"],
        "ix_tbbm_result_province_name": ["province_name"], "ix_tbbm_result_keyword": ["keyword_id"],
        "ix_tbbm_result_place_id": ["google_place_id"], "ix_tbbm_result_normalized_name": ["normalized_name"],
        "ix_tbbm_result_terminal_type": ["terminal_type"], "ix_tbbm_result_match": ["match_status"],
        "ix_tbbm_result_master": ["matched_master_tbbm_id"], "ix_tbbm_result_group": ["duplicate_group_id"],
        "ix_tbbm_result_review": ["review_status"],
        "ix_tbbm_result_job_match_review": ["discovery_job_id", "match_status", "review_status"],
    }.items():
        op.create_index(name, "tbbm_discovery_result", columns)
    op.create_index("ix_tbbm_result_geom_gist", "tbbm_discovery_result", ["geom"], postgresql_using="gist")

    op.create_table(
        "tbbm_discovery_provenance",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("master_tbbm_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_tbbm.id"), nullable=False),
        sa.Column("discovery_result_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tbbm_discovery_result.id"), nullable=False),
        sa.Column("discovery_job_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tbbm_discovery_job.id"), nullable=False),
        sa.Column("keyword_id", sa.Integer(), sa.ForeignKey("tbbm_discovery_keyword.id")),
        sa.Column("keyword", sa.String(180), nullable=False),
        sa.Column("province_id", sa.Integer(), sa.ForeignKey("master_province.id")),
        sa.Column("query_text", sa.String(320), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        sa.UniqueConstraint("master_tbbm_id", "discovery_result_id", "keyword_id", "province_id", "query_text", name="uq_tbbm_provenance_search"),
    )
    for column in ["master_tbbm_id", "discovery_result_id", "discovery_job_id", "keyword_id", "province_id"]:
        op.create_index(f"ix_tbbm_provenance_{column}", "tbbm_discovery_provenance", [column])

    province_table = sa.table(
        "master_province", sa.column("id", sa.Integer()), sa.column("code", sa.String()),
        sa.column("name", sa.String()), sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(province_table, [{"id": item[0], "code": item[1], "name": item[2], "is_active": True} for item in PROVINCES])
    keyword_table = sa.table(
        "tbbm_discovery_keyword", sa.column("keyword", sa.String()), sa.column("is_active", sa.Boolean()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(keyword_table, [
        {"keyword": keyword, "is_active": True, "sort_order": index}
        for index, keyword in enumerate(KEYWORDS, start=1)
    ])
    op.execute("INSERT INTO tbbm_setting (id) VALUES (1)")

    op.execute("""
        INSERT INTO master_tbbm (
            id, tbbm_code, name, normalized_name, terminal_type, latitude, longitude, geom,
            city, province_name, source, verification_status, operational_status,
            manual_overrides, google_types, created_at, updated_at
        )
        SELECT gen_random_uuid(), terminal_code, terminal_name, lower(trim(terminal_name)), terminal_type,
               latitude, longitude, geom, city, province, 'IMPORT', 'VERIFIED',
               CASE WHEN is_active THEN 'ACTIVE' ELSE 'INACTIVE' END,
               '[]'::jsonb, '[]'::jsonb, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM master_terminal
        ON CONFLICT (tbbm_code) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table("tbbm_discovery_provenance")
    op.drop_table("tbbm_discovery_result")
    op.drop_table("tbbm_discovery_job")
    op.drop_table("master_tbbm")
    op.drop_table("tbbm_setting")
    op.drop_table("tbbm_discovery_keyword")
    op.drop_table("master_province")
