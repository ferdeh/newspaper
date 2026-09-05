from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, HttpUrl, SecretStr, field_validator, model_validator


class NewsIngest(BaseModel):
    source_name: str = "Internal News"
    source_domain: str = "internal.local"
    url: HttpUrl
    title: str = Field(min_length=3)
    content: str = Field(min_length=5)
    published_at: datetime


class TikTokIngest(BaseModel):
    video_id: str = Field(min_length=2)
    url: HttpUrl
    username: str
    creator_name: str | None = None
    caption: str = Field(min_length=3)
    hashtags: list[str] = []
    published_at: datetime
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    raw_location_text: str | None = None


class StructuredEvent(BaseModel):
    relevant: bool
    event_category: Literal["SUPPLY_DISRUPTION", "HSSE", "EXTERNAL_DISRUPTION"]
    event_types: list[str]
    products: list[str] = []
    location_raw: str | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    possible_cause: str | None = None
    accident_type: str | None = None
    fire: bool = False
    spill: bool = False
    fatalities: int = 0
    injuries: int = 0
    road_blocked: bool = False
    environmental_impact: bool = False
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ensure_event_type(self):
        if self.relevant and not self.event_types:
            raise ValueError("relevant events require at least one event type")
        return self


class AlertRuleCreate(BaseModel):
    name: str
    event_category: str | None = None
    minimum_risk: float = Field(65, ge=0, le=100)
    minimum_confidence: float = Field(0.65, ge=0, le=1)
    minimum_independent_sources: int = Field(2, ge=1)
    cooldown_minutes: int = Field(180, ge=1)
    is_active: bool = True


class SourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    coverage_area: str | None = Field(None, max_length=255)
    domain: str = Field(min_length=3, max_length=255)
    source_type: Literal["RSS", "HTML", "INTERNAL"] = "RSS"
    feed_url: HttpUrl | None = None
    priority: int = Field(3, ge=1, le=5)
    credibility_score: float = Field(0.7, ge=0, le=1)
    fetch_frequency_minutes: int = Field(120, ge=5, le=10080)
    is_active: bool = True

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return value.strip()

    @field_validator("coverage_area", mode="before")
    @classmethod
    def normalize_coverage_area(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        normalized = value.strip().lower().rstrip(".")
        if "://" in normalized or "/" in normalized or any(character.isspace() for character in normalized):
            raise ValueError("Domain must be a hostname without protocol or path")
        return normalized

    @model_validator(mode="after")
    def require_collection_endpoint(self):
        if self.source_type != "INTERNAL" and self.is_active and self.feed_url is None:
            raise ValueError("Active RSS/HTML sources require a feed URL")
        return self


class SourceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=160)
    coverage_area: str | None = Field(None, max_length=255)
    domain: str | None = Field(None, min_length=3, max_length=255)
    source_type: Literal["RSS", "HTML", "INTERNAL"] | None = None
    feed_url: HttpUrl | None = None
    priority: int | None = Field(None, ge=1, le=5)
    credibility_score: float | None = Field(None, ge=0, le=1)
    fetch_frequency_minutes: int | None = Field(None, ge=5, le=10080)
    is_active: bool | None = None

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("coverage_area", mode="before")
    @classmethod
    def normalize_coverage_area(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None

    @field_validator("domain", mode="before")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower().rstrip(".")
        if "://" in normalized or "/" in normalized or any(character.isspace() for character in normalized):
            raise ValueError("Domain must be a hostname without protocol or path")
        return normalized

    @model_validator(mode="after")
    def require_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one source field must be provided")
        return self


class NewsKeywordCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=180)
    is_active: bool = True

    @field_validator("keyword", mode="before")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return " ".join(value.split())


class NewsKeywordUpdate(BaseModel):
    keyword: str | None = Field(default=None, min_length=2, max_length=180)
    is_active: bool | None = None

    @field_validator("keyword", mode="before")
    @classmethod
    def normalize_keyword(cls, value: str | None) -> str | None:
        return " ".join(value.split()) if value is not None else None

    @model_validator(mode="after")
    def require_fields(self):
        if not self.model_fields_set:
            raise ValueError("At least one keyword field must be provided")
        if "keyword" in self.model_fields_set and self.keyword is None:
            raise ValueError("Keyword cannot be null")
        if "is_active" in self.model_fields_set and self.is_active is None:
            raise ValueError("Keyword active state cannot be null")
        return self


class RSSCollect(BaseModel):
    feed_url: HttpUrl
    source_name: str
    source_domain: str


class GoogleMapsCredentialUpdate(BaseModel):
    api_key: SecretStr

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: SecretStr) -> SecretStr:
        normalized = value.get_secret_value().strip()
        if len(normalized) < 20 or len(normalized) > 200:
            raise ValueError("Google Maps API key must contain between 20 and 200 characters")
        return SecretStr(normalized)
