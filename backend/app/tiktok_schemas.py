from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

TikTokPriority = Literal["HIGH", "MEDIUM", "LOW"]
TikTokDateFilter = Literal["yesterday", "this-week", "this-month", "last-3-months", "last-6-months", "all-time"]
TikTokSort = Literal["relevance", "most-liked", "date-posted"]


class TikTokSettingsUpdate(BaseModel):
    provider: Literal["SCRAPECREATORS"] = "SCRAPECREATORS"
    api_key: SecretStr | None = Field(None, min_length=8, max_length=500)
    clear_api_key: bool = False
    enabled: bool | None = None
    default_region: str | None = Field(None, min_length=2, max_length=8)
    default_date_filter: TikTokDateFilter | None = None
    default_sort_by: TikTokSort | None = None
    default_max_pages: int | None = Field(None, ge=1, le=10)
    default_trim: bool | None = None
    transcript_enabled: bool | None = None
    ai_transcript_fallback_enabled: bool | None = None
    download_media_enabled: bool | None = None
    global_discovery_interval_minutes: int | None = Field(None, ge=5, le=10080)
    daily_credit_limit: int | None = Field(None, ge=1)
    monthly_credit_limit: int | None = Field(None, ge=1)
    warning_threshold_percent: int | None = Field(None, ge=1, le=99)
    critical_threshold_percent: int | None = Field(None, ge=2, le=100)
    adaptive_scheduler_enabled: bool | None = None

    @model_validator(mode="after")
    def validate_thresholds_and_key_action(self):
        if self.clear_api_key and self.api_key is not None:
            raise ValueError("api_key and clear_api_key cannot be submitted together")
        if (
            self.warning_threshold_percent is not None
            and self.critical_threshold_percent is not None
            and self.warning_threshold_percent >= self.critical_threshold_percent
        ):
            raise ValueError("warning threshold must be below critical threshold")
        return self


class TikTokConnectionTest(BaseModel):
    api_key: SecretStr | None = Field(None, min_length=8, max_length=500)


class TikTokKeywordCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=180)
    category: str | None = Field(None, max_length=64)
    priority: TikTokPriority = "MEDIUM"
    frequency_minutes: int | None = Field(None, ge=5, le=10080)
    active: bool = True
    date_filter: TikTokDateFilter | None = None
    sort_by: TikTokSort | None = None
    region: str | None = Field(None, min_length=2, max_length=8)
    max_pages: int | None = Field(None, ge=1, le=10)

    @field_validator("keyword", mode="before")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("category", mode="before")
    @classmethod
    def normalize_category(cls, value: str | None) -> str | None:
        normalized = value.strip().upper().replace(" ", "_") if value else None
        return normalized or None

    @field_validator("region", mode="before")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        return value.strip().upper() if value else None


class TikTokKeywordUpdate(BaseModel):
    keyword: str | None = Field(None, min_length=2, max_length=180)
    category: str | None = Field(None, max_length=64)
    priority: TikTokPriority | None = None
    frequency_minutes: int | None = Field(None, ge=5, le=10080)
    use_global_interval: bool | None = None
    active: bool | None = None
    date_filter: TikTokDateFilter | None = None
    sort_by: TikTokSort | None = None
    region: str | None = Field(None, min_length=2, max_length=8)
    max_pages: int | None = Field(None, ge=1, le=10)

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("at least one field is required")
        return self


class TikTokManualSearch(BaseModel):
    query: str = Field(min_length=2, max_length=180)
    region: str = Field("ID", min_length=2, max_length=8)
    date_posted: TikTokDateFilter = "this-week"
    sort_by: TikTokSort = "date-posted"
    max_pages: int = Field(2, ge=1, le=10)

    @field_validator("query", mode="before")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        return " ".join(value.split())


class TikTokReprocessRequest(BaseModel):
    force: bool = True
