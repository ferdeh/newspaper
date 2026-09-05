"""add audited TikTok discovery

Revision ID: 0010_tiktok_discovery
Revises: 0009_news_source_feed_identity
Create Date: 2026-09-04
"""

import uuid

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0010_tiktok_discovery"
down_revision = "0009_news_source_feed_identity"
branch_labels = None
depends_on = None

NOW = sa.text("CURRENT_TIMESTAMP")
JSON_OBJECT = sa.text("'{}'::jsonb")
DEFAULT_SETTINGS_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_KEYWORDS = (
    "BBM langka", "bensin langka", "pertalite langka", "solar langka", "pertalite habis",
    "solar habis", "SPBU kosong", "antrian SPBU", "antre bensin", "antre solar", "BBM dibatasi",
    "pembatasan BBM", "mobil tangki kecelakaan", "truk tangki kecelakaan", "mobil tangki terbalik",
    "truk tangki terbalik", "mobil tangki terbakar", "truk tangki terbakar", "SPBU tutup",
    "pengiriman BBM terlambat",
)


def _create_tables() -> None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_settings"):
        op.create_table(
            "tiktok_settings",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("singleton_key", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("provider", sa.String(40), nullable=False, server_default="SCRAPECREATORS"),
            sa.Column("api_key_encrypted", sa.Text()),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("default_region", sa.String(8), nullable=False, server_default="ID"),
            sa.Column("default_date_filter", sa.String(32), nullable=False, server_default="this-week"),
            sa.Column("default_sort_by", sa.String(32), nullable=False, server_default="date-posted"),
            sa.Column("default_max_pages", sa.Integer(), nullable=False, server_default="2"),
            sa.Column("default_trim", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("transcript_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("ai_transcript_fallback_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("download_media_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("global_discovery_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("daily_credit_limit", sa.Integer()),
            sa.Column("monthly_credit_limit", sa.Integer(), server_default="15000"),
            sa.Column("warning_threshold_percent", sa.Integer(), nullable=False, server_default="80"),
            sa.Column("critical_threshold_percent", sa.Integer(), nullable=False, server_default="95"),
            sa.Column("adaptive_scheduler_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("provider_health_status", sa.String(24), nullable=False, server_default="NOT_CONFIGURED"),
            sa.Column("last_health_checked_at", sa.DateTime(timezone=True)),
            sa.Column("last_successful_request_at", sa.DateTime(timezone=True)),
            sa.Column("last_provider_error", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.UniqueConstraint("singleton_key", name="uq_tiktok_settings_singleton"),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("master_tiktok_keyword"):
        op.create_table(
            "master_tiktok_keyword",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("keyword", sa.String(180), nullable=False),
            sa.Column("category", sa.String(64)),
            sa.Column("priority", sa.String(16), nullable=False, server_default="MEDIUM"),
            sa.Column("frequency_minutes", sa.Integer()),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("date_filter", sa.String(32)),
            sa.Column("sort_by", sa.String(32)),
            sa.Column("region", sa.String(8)),
            sa.Column("max_pages", sa.Integer()),
            sa.Column("last_run_at", sa.DateTime(timezone=True)),
            sa.Column("next_run_at", sa.DateTime(timezone=True)),
            sa.Column("last_result_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_new_video_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_relevant_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_search_run"):
        op.create_table(
            "tiktok_search_run",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("keyword_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_tiktok_keyword.id")),
            sa.Column("query_text", sa.String(180), nullable=False),
            sa.Column("search_params", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("finished_at", sa.DateTime(timezone=True)),
            sa.Column("status", sa.String(24), nullable=False, server_default="RUNNING"),
            sa.Column("pages_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("api_requests", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("search_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("video_info_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transcript_credits", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("results_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("new_videos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_videos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("relevant_videos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("irrelevant_videos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("uncertain_videos", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transcripts_requested", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("transcripts_found", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("incidents_created", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_video"):
        op.create_table(
            "tiktok_video",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("provider_video_id", sa.String(120), nullable=False),
            sa.Column("video_url", sa.Text(), nullable=False),
            sa.Column("thumbnail_url", sa.Text()),
            sa.Column("author_id", sa.String(160)),
            sa.Column("author_username", sa.String(160)),
            sa.Column("author_display_name", sa.String(180)),
            sa.Column("caption", sa.Text()),
            sa.Column("hashtags", postgresql.JSONB()),
            sa.Column("tiktok_created_at", sa.DateTime(timezone=True)),
            sa.Column("duration_seconds", sa.Integer()),
            sa.Column("view_count", sa.BigInteger()),
            sa.Column("like_count", sa.BigInteger()),
            sa.Column("comment_count", sa.BigInteger()),
            sa.Column("share_count", sa.BigInteger()),
            sa.Column("raw_response", postgresql.JSONB(), nullable=False, server_default=JSON_OBJECT),
            sa.Column("processing_status", sa.String(32), nullable=False, server_default="DISCOVERED"),
            sa.Column("relevance_score", sa.Float()),
            sa.Column("relevance_category", sa.String(64)),
            sa.Column("needs_transcript", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("algorithm_version", sa.String(40)),
            sa.Column("canonical_tiktok_post_id", sa.Integer(), sa.ForeignKey("tiktok_post.id"), unique=True),
            sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.UniqueConstraint("provider", "provider_video_id", name="uq_tiktok_video_provider_identity"),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_video_keyword_match"):
        op.create_table(
            "tiktok_video_keyword_match",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiktok_video.id", ondelete="CASCADE"), nullable=False),
            sa.Column("keyword_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("master_tiktok_keyword.id"), nullable=False),
            sa.Column("search_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiktok_search_run.id"), nullable=False),
            sa.Column("first_matched_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.UniqueConstraint("video_id", "keyword_id", name="uq_tiktok_video_keyword_match"),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_transcript"):
        op.create_table(
            "tiktok_transcript",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("video_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiktok_video.id", ondelete="CASCADE"), nullable=False, unique=True),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("transcript_raw", sa.Text()),
            sa.Column("transcript_text", sa.Text()),
            sa.Column("language", sa.String(16)),
            sa.Column("status", sa.String(24), nullable=False, server_default="PENDING"),
            sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
        )

    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("tiktok_provider_request"):
        op.create_table(
            "tiktok_provider_request",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            sa.Column("search_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tiktok_search_run.id")),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("operation", sa.String(32), nullable=False),
            sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=NOW),
            sa.Column("succeeded", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("status_code", sa.Integer()),
            sa.Column("credits_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duration_ms", sa.Integer()),
            sa.Column("error_message", sa.Text()),
        )


def _ensure_index(table: str, name: str, columns: list[str], unique: bool = False) -> None:
    existing = {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name not in existing:
        op.create_index(name, table, columns, unique=unique)


def upgrade() -> None:
    _create_tables()
    _ensure_index("master_tiktok_keyword", "uq_master_tiktok_keyword_lower", [sa.text("lower(keyword)")], unique=True)
    _ensure_index("master_tiktok_keyword", "ix_master_tiktok_keyword_active", ["active"])
    _ensure_index("master_tiktok_keyword", "ix_master_tiktok_keyword_next_run_at", ["next_run_at"])
    _ensure_index("tiktok_search_run", "ix_tiktok_search_run_started_at", ["started_at"])
    _ensure_index("tiktok_video", "ix_tiktok_video_provider_video_id", ["provider_video_id"])
    _ensure_index("tiktok_video", "ix_tiktok_video_tiktok_created_at", ["tiktok_created_at"])
    _ensure_index("tiktok_video", "ix_tiktok_video_processing_status", ["processing_status"])
    _ensure_index("tiktok_provider_request", "ix_tiktok_provider_request_requested_at", ["requested_at"])

    bind = op.get_bind()
    if not bind.execute(sa.text("SELECT 1 FROM tiktok_settings WHERE singleton_key = 1")).scalar():
        bind.execute(
            sa.text(
                "INSERT INTO tiktok_settings "
                "(id, singleton_key, provider, enabled, default_region, default_date_filter, default_sort_by, "
                "default_max_pages, default_trim, transcript_enabled, ai_transcript_fallback_enabled, "
                "download_media_enabled, global_discovery_interval_minutes, monthly_credit_limit, "
                "warning_threshold_percent, critical_threshold_percent, adaptive_scheduler_enabled, "
                "provider_health_status, created_at, updated_at) VALUES "
                "(:id, 1, 'SCRAPECREATORS', false, 'ID', 'this-week', 'date-posted', 2, true, true, false, "
                "false, 60, 15000, 80, 95, true, 'NOT_CONFIGURED', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": DEFAULT_SETTINGS_ID},
        )

    if not bind.execute(sa.text("SELECT 1 FROM master_tiktok_keyword LIMIT 1")).scalar():
        for position, keyword in enumerate(DEFAULT_KEYWORDS):
            priority = "HIGH" if position in {4, 5, 14, 15, 16, 17} else "MEDIUM"
            category = "TANKER_INCIDENT" if "tangki" in keyword.lower() else "SUPPLY_DISRUPTION"
            bind.execute(
                sa.text(
                    "INSERT INTO master_tiktok_keyword "
                    "(id, keyword, category, priority, active, last_result_count, last_new_video_count, "
                    "last_relevant_count, created_at, updated_at) VALUES "
                    "(:id, :keyword, :category, :priority, true, 0, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": uuid.uuid5(uuid.NAMESPACE_URL, f"fuel-intelligence:tiktok:{keyword.lower()}"),
                    "keyword": keyword,
                    "category": category,
                    "priority": priority,
                },
            )


def downgrade() -> None:
    for table in (
        "tiktok_provider_request", "tiktok_transcript", "tiktok_video_keyword_match", "tiktok_video",
        "tiktok_search_run", "master_tiktok_keyword", "tiktok_settings",
    ):
        if sa.inspect(op.get_bind()).has_table(table):
            op.drop_table(table)
