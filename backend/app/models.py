from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class NewsSource(Base, TimestampMixin):
    __tablename__ = "news_source"
    __table_args__ = (UniqueConstraint("feed_url", name="uq_news_source_feed_url"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    coverage_area: Mapped[str | None] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), index=True)
    source_type: Mapped[str] = mapped_column(String(32), default="RSS")
    feed_url: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=3)
    credibility_score: Mapped[float] = mapped_column(Float, default=0.7)
    fetch_frequency_minutes: Mapped[int] = mapped_column(Integer, default=120)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class NewsKeyword(Base, TimestampMixin):
    __tablename__ = "news_keyword"
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(180))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class RawArticle(Base):
    __tablename__ = "raw_article"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("news_source.id"), index=True)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    raw_html: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[NewsSource] = relationship()


class Article(Base, TimestampMixin):
    __tablename__ = "article"
    id: Mapped[int] = mapped_column(primary_key=True)
    raw_article_id: Mapped[int] = mapped_column(ForeignKey("raw_article.id"), unique=True)
    title: Mapped[str] = mapped_column(Text)
    clean_text: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    raw_article: Mapped[RawArticle] = relationship()


class TikTokQuery(Base, TimestampMixin):
    __tablename__ = "tiktok_query"
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(180))
    location_scope: Mapped[str] = mapped_column(String(32), default="COUNTRY")
    location_name: Mapped[str | None] = mapped_column(String(180))
    priority: Mapped[int] = mapped_column(Integer, default=3)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TikTokPost(Base, TimestampMixin):
    __tablename__ = "tiktok_post"
    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[str] = mapped_column(String(120), unique=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    username: Mapped[str] = mapped_column(String(120))
    creator_name: Mapped[str | None] = mapped_column(String(180))
    caption: Mapped[str] = mapped_column(Text)
    hashtags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0)
    like_count: Mapped[int] = mapped_column(BigInteger, default=0)
    comment_count: Mapped[int] = mapped_column(BigInteger, default=0)
    share_count: Mapped[int] = mapped_column(BigInteger, default=0)
    raw_location_text: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="PENDING")


class TikTokSettings(Base, TimestampMixin):
    __tablename__ = "tiktok_settings"
    __table_args__ = (UniqueConstraint("singleton_key", name="uq_tiktok_settings_singleton"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    singleton_key: Mapped[int] = mapped_column(Integer, default=1)
    provider: Mapped[str] = mapped_column(String(40), default="SCRAPECREATORS")
    api_key_encrypted: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    default_region: Mapped[str] = mapped_column(String(8), default="ID")
    default_date_filter: Mapped[str] = mapped_column(String(32), default="this-week")
    default_sort_by: Mapped[str] = mapped_column(String(32), default="date-posted")
    default_max_pages: Mapped[int] = mapped_column(Integer, default=2)
    default_trim: Mapped[bool] = mapped_column(Boolean, default=True)
    transcript_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_transcript_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    download_media_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    global_discovery_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    daily_credit_limit: Mapped[int | None] = mapped_column(Integer)
    monthly_credit_limit: Mapped[int | None] = mapped_column(Integer, default=15000)
    warning_threshold_percent: Mapped[int] = mapped_column(Integer, default=80)
    critical_threshold_percent: Mapped[int] = mapped_column(Integer, default=95)
    adaptive_scheduler_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_health_status: Mapped[str] = mapped_column(String(24), default="NOT_CONFIGURED")
    last_health_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_request_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_provider_error: Mapped[str | None] = mapped_column(Text)


class MasterTikTokKeyword(Base, TimestampMixin):
    __tablename__ = "master_tiktok_keyword"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keyword: Mapped[str] = mapped_column(String(180))
    category: Mapped[str | None] = mapped_column(String(64))
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    frequency_minutes: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    date_filter: Mapped[str | None] = mapped_column(String(32))
    sort_by: Mapped[str | None] = mapped_column(String(32))
    region: Mapped[str | None] = mapped_column(String(8))
    max_pages: Mapped[int | None] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_result_count: Mapped[int] = mapped_column(Integer, default=0)
    last_new_video_count: Mapped[int] = mapped_column(Integer, default=0)
    last_relevant_count: Mapped[int] = mapped_column(Integer, default=0)


class TikTokSearchRun(Base):
    __tablename__ = "tiktok_search_run"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tiktok_keyword.id"), index=True)
    query_text: Mapped[str] = mapped_column(String(180))
    search_params: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    provider: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(24), default="RUNNING")
    pages_requested: Mapped[int] = mapped_column(Integer, default=0)
    api_requests: Mapped[int] = mapped_column(Integer, default=0)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    search_credits: Mapped[int] = mapped_column(Integer, default=0)
    video_info_credits: Mapped[int] = mapped_column(Integer, default=0)
    transcript_credits: Mapped[int] = mapped_column(Integer, default=0)
    results_found: Mapped[int] = mapped_column(Integer, default=0)
    new_videos: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_videos: Mapped[int] = mapped_column(Integer, default=0)
    relevant_videos: Mapped[int] = mapped_column(Integer, default=0)
    irrelevant_videos: Mapped[int] = mapped_column(Integer, default=0)
    uncertain_videos: Mapped[int] = mapped_column(Integer, default=0)
    transcripts_requested: Mapped[int] = mapped_column(Integer, default=0)
    transcripts_found: Mapped[int] = mapped_column(Integer, default=0)
    incidents_created: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TikTokVideo(Base, TimestampMixin):
    __tablename__ = "tiktok_video"
    __table_args__ = (UniqueConstraint("provider", "provider_video_id", name="uq_tiktok_video_provider_identity"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(40))
    provider_video_id: Mapped[str] = mapped_column(String(120), index=True)
    video_url: Mapped[str] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    author_id: Mapped[str | None] = mapped_column(String(160))
    author_username: Mapped[str | None] = mapped_column(String(160))
    author_display_name: Mapped[str | None] = mapped_column(String(180))
    caption: Mapped[str | None] = mapped_column(Text)
    hashtags: Mapped[list[str] | None] = mapped_column(JSONB)
    tiktok_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    view_count: Mapped[int | None] = mapped_column(BigInteger)
    like_count: Mapped[int | None] = mapped_column(BigInteger)
    comment_count: Mapped[int | None] = mapped_column(BigInteger)
    share_count: Mapped[int | None] = mapped_column(BigInteger)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    processing_status: Mapped[str] = mapped_column(String(32), default="DISCOVERED", index=True)
    relevance_score: Mapped[float | None] = mapped_column(Float)
    relevance_category: Mapped[str | None] = mapped_column(String(64))
    needs_transcript: Mapped[bool] = mapped_column(Boolean, default=False)
    algorithm_version: Mapped[str | None] = mapped_column(String(40))
    canonical_tiktok_post_id: Mapped[int | None] = mapped_column(ForeignKey("tiktok_post.id"), unique=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TikTokVideoKeywordMatch(Base):
    __tablename__ = "tiktok_video_keyword_match"
    __table_args__ = (UniqueConstraint("video_id", "keyword_id", name="uq_tiktok_video_keyword_match"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiktok_video.id", ondelete="CASCADE"), index=True)
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("master_tiktok_keyword.id"), index=True)
    search_run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiktok_search_run.id"), index=True)
    first_matched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TikTokTranscript(Base, TimestampMixin):
    __tablename__ = "tiktok_transcript"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tiktok_video.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(40))
    transcript_raw: Mapped[str | None] = mapped_column(Text)
    transcript_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="PENDING")
    credits_used: Mapped[int] = mapped_column(Integer, default=0)


class TikTokProviderRequest(Base):
    __tablename__ = "tiktok_provider_request"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    search_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tiktok_search_run.id"), index=True)
    provider: Mapped[str] = mapped_column(String(40))
    operation: Mapped[str] = mapped_column(String(32), index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    succeeded: Mapped[bool] = mapped_column(Boolean, default=False)
    status_code: Mapped[int | None] = mapped_column(Integer)
    credits_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)


class Signal(Base, TimestampMixin):
    __tablename__ = "signal"
    __table_args__ = (UniqueConstraint("source_type", "source_record_id", name="uq_signal_source_record"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    source_record_id: Mapped[int] = mapped_column(BigInteger)
    source_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    relevance_score: Mapped[float] = mapped_column(Float, default=0)
    processing_status: Mapped[str] = mapped_column(String(32), default="PENDING")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(64))
    event: Mapped[Event | None] = relationship(back_populates="signal", uselist=False)


class Event(Base):
    __tablename__ = "event"
    id: Mapped[int] = mapped_column(primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal.id"), unique=True, index=True)
    event_category: Mapped[str] = mapped_column(String(40), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    products: Mapped[list[str]] = mapped_column(JSONB, default=list)
    location_raw: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(16), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    possible_cause: Mapped[str | None] = mapped_column(String(64))
    accident_type: Mapped[str | None] = mapped_column(String(64))
    fire: Mapped[bool] = mapped_column(Boolean, default=False)
    spill: Mapped[bool] = mapped_column(Boolean, default=False)
    fatalities: Mapped[int] = mapped_column(Integer, default=0)
    injuries: Mapped[int] = mapped_column(Integer, default=0)
    road_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    structured_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    signal: Mapped[Signal] = relationship(back_populates="event")


class MasterLocation(Base, TimestampMixin):
    __tablename__ = "master_location"
    id: Mapped[int] = mapped_column(primary_key=True)
    province: Mapped[str] = mapped_column(String(120), index=True)
    regency: Mapped[str | None] = mapped_column(String(120), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    district: Mapped[str | None] = mapped_column(String(120))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True)
    aliases: Mapped[list[str]] = mapped_column(JSONB, default=list)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)


class MasterTerminal(Base):
    __tablename__ = "master_terminal"
    id: Mapped[int] = mapped_column(primary_key=True)
    terminal_code: Mapped[str] = mapped_column(String(40), unique=True)
    terminal_name: Mapped[str] = mapped_column(String(180))
    terminal_type: Mapped[str] = mapped_column(String(40))
    province: Mapped[str] = mapped_column(String(120), index=True)
    city: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    products_supported: Mapped[list[str]] = mapped_column(JSONB, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class MasterProvince(Base, TimestampMixin):
    __tablename__ = "master_province"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(8), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class TbbmDiscoveryKeyword(Base, TimestampMixin):
    __tablename__ = "tbbm_discovery_keyword"
    id: Mapped[int] = mapped_column(primary_key=True)
    keyword: Mapped[str] = mapped_column(String(180), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, index=True)


class TbbmSetting(Base, TimestampMixin):
    __tablename__ = "tbbm_setting"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    country: Mapped[str] = mapped_column(String(80), default="Indonesia")
    language_code: Mapped[str] = mapped_column(String(8), default="id")
    search_strategy: Mapped[str] = mapped_column(String(40), default="PROVINCE_BASED")
    request_delay_ms: Mapped[int] = mapped_column(Integer, default=250)
    maximum_retry: Mapped[int] = mapped_column(Integer, default=3)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=15)
    duplicate_radius_meters: Mapped[int] = mapped_column(Integer, default=300)
    name_similarity_threshold: Mapped[float] = mapped_column(Float, default=0.8)


class MasterTbbm(Base, TimestampMixin):
    __tablename__ = "master_tbbm"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tbbm_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180), index=True)
    normalized_name: Mapped[str] = mapped_column(String(180), index=True)
    terminal_type: Mapped[str] = mapped_column(String(40), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any | None] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(120))
    regency: Mapped[str | None] = mapped_column(String(120))
    province_id: Mapped[int | None] = mapped_column(ForeignKey("master_province.id"), index=True)
    province_name: Mapped[str | None] = mapped_column(String(120), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(20))
    google_place_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    google_maps_uri: Mapped[str | None] = mapped_column(Text)
    google_primary_type: Mapped[str | None] = mapped_column(String(120))
    google_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(24), default="MANUAL", index=True)
    verification_status: Mapped[str] = mapped_column(String(24), default="NEED_REVIEW", index=True)
    operational_status: Mapped[str] = mapped_column(String(24), default="UNKNOWN", index=True)
    manual_overrides: Mapped[list[str]] = mapped_column(JSONB, default=list)
    first_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(String(120))
    updated_by: Mapped[str | None] = mapped_column(String(120))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    province: Mapped[MasterProvince | None] = relationship()


class TbbmDiscoveryJob(Base, TimestampMixin):
    __tablename__ = "tbbm_discovery_job"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    search_scope: Mapped[str] = mapped_column(String(32))
    selected_provinces: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    selected_keywords: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    retry_queries: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    existing_data_mode: Mapped[str] = mapped_column(String(32), default="UPDATE_AND_ADD")
    total_queries: Mapped[int] = mapped_column(Integer, default=0)
    completed_queries: Mapped[int] = mapped_column(Integer, default=0)
    successful_queries: Mapped[int] = mapped_column(Integer, default=0)
    failed_queries: Mapped[int] = mapped_column(Integer, default=0)
    failed_query_details: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    raw_result_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_place_count: Mapped[int] = mapped_column(Integer, default=0)
    existing_match_count: Mapped[int] = mapped_column(Integer, default=0)
    new_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    possible_duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    rejected_auto_count: Mapped[int] = mapped_column(Integer, default=0)
    current_province: Mapped[str | None] = mapped_column(String(120))
    current_keyword: Mapped[str | None] = mapped_column(String(180))
    created_by: Mapped[str | None] = mapped_column(String(120))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)


class TbbmDiscoveryResult(Base, TimestampMixin):
    __tablename__ = "tbbm_discovery_result"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    discovery_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tbbm_discovery_job.id"), index=True)
    province_id: Mapped[int | None] = mapped_column(ForeignKey("master_province.id"), index=True)
    province_name: Mapped[str | None] = mapped_column(String(120), index=True)
    keyword_id: Mapped[int | None] = mapped_column(ForeignKey("tbbm_discovery_keyword.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(180))
    source_keywords: Mapped[list[str]] = mapped_column(JSONB, default=list)
    query_text: Mapped[str] = mapped_column(String(320))
    query_provenance: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    query_page: Mapped[int] = mapped_column(Integer, default=1)
    google_place_id: Mapped[str | None] = mapped_column(String(255), index=True)
    place_name: Mapped[str] = mapped_column(String(180))
    normalized_name: Mapped[str] = mapped_column(String(180), index=True)
    formatted_address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any | None] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=True)
    google_maps_uri: Mapped[str | None] = mapped_column(Text)
    google_types: Mapped[list[str]] = mapped_column(JSONB, default=list)
    google_primary_type: Mapped[str | None] = mapped_column(String(120))
    terminal_type: Mapped[str] = mapped_column(String(40), index=True)
    match_status: Mapped[str] = mapped_column(String(32), default="NEW", index=True)
    matched_master_tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    duplicate_group_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), index=True)
    duplicate_distance_meters: Mapped[float | None] = mapped_column(Float)
    duplicate_score: Mapped[float | None] = mapped_column(Float)
    address_similarity: Mapped[float | None] = mapped_column(Float)
    review_status: Mapped[str] = mapped_column(String(32), default="PENDING_REVIEW", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    discovery_job: Mapped[TbbmDiscoveryJob] = relationship()
    matched_master: Mapped[MasterTbbm | None] = relationship()


class TbbmDiscoveryProvenance(Base):
    __tablename__ = "tbbm_discovery_provenance"
    __table_args__ = (
        UniqueConstraint(
            "master_tbbm_id", "discovery_result_id", "keyword_id", "province_id", "query_text",
            name="uq_tbbm_provenance_search",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    master_tbbm_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    discovery_result_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tbbm_discovery_result.id"), index=True)
    discovery_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tbbm_discovery_job.id"), index=True)
    keyword_id: Mapped[int | None] = mapped_column(ForeignKey("tbbm_discovery_keyword.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(180))
    province_id: Mapped[int | None] = mapped_column(ForeignKey("master_province.id"), index=True)
    query_text: Mapped[str] = mapped_column(String(320))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class MasterSpbu(Base):
    __tablename__ = "master_spbu"
    id: Mapped[int] = mapped_column(primary_key=True)
    spbu_number: Mapped[str] = mapped_column(String(40), unique=True)
    spbu_name: Mapped[str] = mapped_column(String(180))
    province: Mapped[str] = mapped_column(String(120), index=True)
    regency: Mapped[str | None] = mapped_column(String(120), index=True)
    district: Mapped[str | None] = mapped_column(String(120))
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    geom: Mapped[Any] = mapped_column(Geography(geometry_type="POINT", srid=4326), nullable=False)
    legacy_serving_terminal_id: Mapped[int | None] = mapped_column("serving_terminal_id", ForeignKey("master_terminal.id"))
    serving_tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    serving_tbbm: Mapped[MasterTbbm | None] = relationship(foreign_keys=[serving_tbbm_id])


class Incident(Base, TimestampMixin):
    __tablename__ = "incident"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_code: Mapped[str] = mapped_column(String(40), unique=True)
    event_category: Mapped[str] = mapped_column(String(40), index=True)
    primary_event_type: Mapped[str] = mapped_column(String(64), index=True)
    products: Mapped[list[str]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(24), default="OPEN", index=True)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    supply_risk_score: Mapped[float] = mapped_column(Float, default=0)
    hsse_risk_score: Mapped[float] = mapped_column(Float, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("master_location.id"), index=True)
    location_resolution_status: Mapped[str] = mapped_column(String(24), default="UNRESOLVED")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    geocoded_address: Mapped[str | None] = mapped_column(Text)
    geocoding_provider: Mapped[str | None] = mapped_column(String(32))
    geocoding_confidence: Mapped[float | None] = mapped_column(Float)
    spbu_id: Mapped[int | None] = mapped_column(ForeignKey("master_spbu.id"))
    legacy_nearest_terminal_id: Mapped[int | None] = mapped_column("nearest_terminal_id", ForeignKey("master_terminal.id"), index=True)
    nearest_tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    nearest_terminal_distance_km: Mapped[float | None] = mapped_column(Float)
    nearest_terminal_distance_source: Mapped[str | None] = mapped_column(String(40))
    nearest_terminal_duration_minutes: Mapped[float | None] = mapped_column(Float)
    legacy_serving_terminal_id: Mapped[int | None] = mapped_column("serving_terminal_id", ForeignKey("master_terminal.id"), index=True)
    serving_tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    first_signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    first_tiktok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_news_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tiktok_lead_time_minutes: Mapped[int | None] = mapped_column(Integer)
    first_detection_source: Mapped[str | None] = mapped_column(String(20))
    signal_count: Mapped[int] = mapped_column(Integer, default=0)
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    tiktok_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_news_source_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_tiktok_creator_count: Mapped[int] = mapped_column(Integer, default=0)
    trend_status: Mapped[str] = mapped_column(String(32), default="STABLE")
    mentions_1h: Mapped[int] = mapped_column(Integer, default=0)
    mentions_3h: Mapped[int] = mapped_column(Integer, default=0)
    mentions_6h: Mapped[int] = mapped_column(Integer, default=0)
    mentions_24h: Mapped[int] = mapped_column(Integer, default=0)
    growth_rate: Mapped[float] = mapped_column(Float, default=0)
    location: Mapped[MasterLocation | None] = relationship(foreign_keys=[location_id])
    spbu: Mapped[MasterSpbu | None] = relationship(foreign_keys=[spbu_id])
    nearest_tbbm: Mapped[MasterTbbm | None] = relationship(foreign_keys=[nearest_tbbm_id])
    serving_tbbm: Mapped[MasterTbbm | None] = relationship(foreign_keys=[serving_tbbm_id])
    signal_links: Mapped[list[IncidentSignal]] = relationship(back_populates="incident", cascade="all, delete-orphan")
    risk_history: Mapped[list[RiskScoreHistory]] = relationship(back_populates="incident", cascade="all, delete-orphan")


class IncidentSignal(Base):
    __tablename__ = "incident_signal"
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signal.id"), primary_key=True)
    similarity_score: Mapped[float] = mapped_column(Float, default=1)
    is_primary_signal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    incident: Mapped[Incident] = relationship(back_populates="signal_links")
    signal: Mapped[Signal] = relationship()


class RiskScoreHistory(Base):
    __tablename__ = "risk_score_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    supply_risk_score: Mapped[float] = mapped_column(Float)
    hsse_risk_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    incident: Mapped[Incident] = relationship(back_populates="risk_history")


class AlertRule(Base, TimestampMixin):
    __tablename__ = "alert_rule"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    event_category: Mapped[str | None] = mapped_column(String(40))
    minimum_risk: Mapped[float] = mapped_column(Float, default=65)
    minimum_confidence: Mapped[float] = mapped_column(Float, default=0.65)
    minimum_independent_sources: Mapped[int] = mapped_column(Integer, default=2)
    cooldown_minutes: Mapped[int] = mapped_column(Integer, default=180)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class AlertHistory(Base):
    __tablename__ = "alert_history"
    __table_args__ = (UniqueConstraint("incident_id", "dedupe_key", name="uq_alert_dedupe"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incident.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    recipient: Mapped[str] = mapped_column(String(180))
    risk_score: Mapped[float] = mapped_column(Float)
    severity: Mapped[str] = mapped_column(String(16))
    message_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_status: Mapped[str] = mapped_column(String(32), default="QUEUED", index=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)


class NotificationChannelConfig(Base, TimestampMixin):
    __tablename__ = "notification_channels"
    __table_args__ = (UniqueConstraint("channel_type", name="notification_channels_channel_type_key"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_type: Mapped[str] = mapped_column(String(32), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailOAuthProviderConfig(Base, TimestampMixin):
    __tablename__ = "email_oauth_provider_configs"
    __table_args__ = (
        UniqueConstraint("provider", name="email_oauth_provider_configs_provider_key"),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    client_id: Mapped[str] = mapped_column(String(512))
    client_secret_encrypted: Mapped[str | None] = mapped_column(Text)
    tenant: Mapped[str | None] = mapped_column(String(255))
    redirect_uri: Mapped[str] = mapped_column(Text)


class EmailAccount(Base, TimestampMixin):
    __tablename__ = "email_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "oauth_provider_account_id", name="uq_email_account_provider_identity"),
        Index(
            "uq_email_accounts_active_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default AND enabled"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(32), default="EMAIL", index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    email_address: Mapped[str] = mapped_column(String(320), index=True)
    display_name: Mapped[str | None] = mapped_column(String(160))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    oauth_access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    oauth_refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    oauth_scope: Mapped[str] = mapped_column(Text)
    oauth_provider_account_id: Mapped[str] = mapped_column(String(255))
    connection_status: Mapped[str] = mapped_column(String(32), default="CONNECTED", index=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class NotificationRecipient(Base, TimestampMixin):
    __tablename__ = "notification_recipients"
    __table_args__ = (UniqueConstraint("email_address", name="notification_recipients_email_address_key"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160))
    email_address: Mapped[str] = mapped_column(String(320), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationRecipientGroup(Base, TimestampMixin):
    __tablename__ = "notification_recipient_groups"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class NotificationRecipientGroupMember(Base):
    __tablename__ = "notification_recipient_group_members"
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_recipient_groups.id", ondelete="CASCADE"), primary_key=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_recipients.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationRule(Base, TimestampMixin):
    __tablename__ = "notification_rules"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    channel: Mapped[str] = mapped_column(String(32), default="EMAIL", index=True)
    email_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    category: Mapped[str | None] = mapped_column(String(64), index=True)
    minimum_severity: Mapped[str | None] = mapped_column(String(16))
    minimum_confidence_score: Mapped[float | None] = mapped_column(Float)
    province: Mapped[str | None] = mapped_column(String(120), index=True)
    city_or_area: Mapped[str | None] = mapped_column(String(160))
    tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    delivery_mode: Mapped[str] = mapped_column(String(32), default="IMMEDIATE", index=True)
    digest_interval_minutes: Mapped[int | None] = mapped_column(Integer)


class NotificationRuleRecipient(Base):
    __tablename__ = "notification_rule_recipients"
    __table_args__ = (
        CheckConstraint(
            "(recipient_id IS NOT NULL) <> (recipient_group_id IS NOT NULL)",
            name="ck_notification_rule_recipient_exactly_one_target",
        ),
        UniqueConstraint(
            "notification_rule_id", "recipient_id", "recipient_group_id", "recipient_role",
            name="uq_notification_rule_recipient_target_role",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("notification_rules.id", ondelete="CASCADE"), index=True
    )
    recipient_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("notification_recipients.id"), index=True)
    recipient_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_recipient_groups.id"), index=True
    )
    recipient_role: Mapped[str] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationOAuthState(Base):
    __tablename__ = "notification_oauth_states"
    __table_args__ = (UniqueConstraint("state_digest", name="notification_oauth_states_state_digest_key"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    state_digest: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    redirect_after_success: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NotificationJob(Base, TimestampMixin):
    __tablename__ = "notification_jobs"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_notification_job_idempotency"),)
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[int | None] = mapped_column(ForeignKey("alert_history.id"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incident.id"), index=True)
    notification_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notification_rules.id", ondelete="SET NULL"), index=True
    )
    channel: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    sender_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    delivery_mode: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(64))
    last_error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(64), index=True)


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    notification_job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("notification_jobs.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), index=True)
    provider: Mapped[str | None] = mapped_column(String(32), index=True)
    sender_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("email_accounts.id"), index=True)
    recipient_summary: Mapped[str] = mapped_column(Text)
    provider_message_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AnalyticsDaily(Base):
    __tablename__ = "analytics_daily"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    province: Mapped[str | None] = mapped_column(String(120), index=True)
    regency: Mapped[str | None] = mapped_column(String(120), index=True)
    event_category: Mapped[str | None] = mapped_column(String(40), index=True)
    event_type: Mapped[str | None] = mapped_column(String(64), index=True)
    product: Mapped[str | None] = mapped_column(String(64), index=True)
    legacy_terminal_id: Mapped[int | None] = mapped_column("terminal_id", ForeignKey("master_terminal.id"), index=True)
    tbbm_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("master_tbbm.id"), index=True)
    incident_count: Mapped[int] = mapped_column(Integer, default=0)
    news_count: Mapped[int] = mapped_column(Integer, default=0)
    tiktok_count: Mapped[int] = mapped_column(Integer, default=0)
    critical_count: Mapped[int] = mapped_column(Integer, default=0)
    high_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_supply_risk: Mapped[float] = mapped_column(Float, default=0)
    avg_hsse_risk: Mapped[float] = mapped_column(Float, default=0)
    avg_tiktok_lead_time_minutes: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"
    service: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="HEALTHY")
    queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


Index("ix_signal_published_source", Signal.published_at, Signal.source_type)
Index("ix_incident_status_category", Incident.status, Incident.event_category)
Index("ix_incident_products_gin", Incident.products, postgresql_using="gin")
Index("ix_location_geom_gist", MasterLocation.geom, postgresql_using="gist")
Index("ix_spbu_geom_gist", MasterSpbu.geom, postgresql_using="gist")
Index("ix_terminal_geom_gist", MasterTerminal.geom, postgresql_using="gist")
Index("ix_master_tbbm_geom_gist", MasterTbbm.geom, postgresql_using="gist")
Index("ix_tbbm_result_geom_gist", TbbmDiscoveryResult.geom, postgresql_using="gist")
Index("ix_tbbm_result_job_match_review", TbbmDiscoveryResult.discovery_job_id, TbbmDiscoveryResult.match_status, TbbmDiscoveryResult.review_status)
Index("uq_news_keyword_keyword_lower", func.lower(NewsKeyword.keyword), unique=True)
