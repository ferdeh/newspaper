from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

TerminalType = Literal["TBBM", "FUEL_TERMINAL", "INTEGRATED_TERMINAL", "DEPOT_BBM", "TLPG", "OTHER"]
VerificationStatus = Literal["VERIFIED", "NEED_REVIEW", "REJECTED"]
OperationalStatus = Literal["ACTIVE", "INACTIVE", "UNKNOWN"]


class TbbmCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    terminal_type: TerminalType
    address: str | None = None
    province_id: int | None = None
    city: str | None = Field(default=None, max_length=120)
    regency: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    operational_status: OperationalStatus = "UNKNOWN"
    verification_status: VerificationStatus = "NEED_REVIEW"
    google_place_id: str | None = Field(default=None, max_length=255)
    google_maps_uri: HttpUrl | None = None

    @field_validator("name")
    @classmethod
    def normalize_required_name(cls, value: str) -> str:
        value = " ".join(value.split())
        if not value:
            raise ValueError("Terminal name is required")
        return value


class TbbmUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    terminal_type: TerminalType | None = None
    address: str | None = None
    province_id: int | None = None
    city: str | None = Field(default=None, max_length=120)
    regency: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    operational_status: OperationalStatus | None = None
    verification_status: VerificationStatus | None = None
    google_place_id: str | None = Field(default=None, max_length=255)
    google_maps_uri: HttpUrl | None = None


class DiscoveryJobCreate(BaseModel):
    search_scope: Literal["ENTIRE_INDONESIA", "SELECTED_PROVINCE"] = "ENTIRE_INDONESIA"
    selected_province_ids: list[int] = []
    selected_keyword_ids: list[int] = Field(min_length=1)
    existing_data_mode: Literal["UPDATE_AND_ADD", "ADD_NEW_ONLY"] = "UPDATE_AND_ADD"

    @model_validator(mode="after")
    def validate_selected_scope(self):
        if self.search_scope == "SELECTED_PROVINCE" and not self.selected_province_ids:
            raise ValueError("Choose at least one province")
        return self


class DiscoveryResultUpdate(BaseModel):
    place_name: str | None = Field(default=None, min_length=2, max_length=180)
    terminal_type: TerminalType | None = None
    formatted_address: str | None = None
    province_id: int | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class ReviewReason(BaseModel):
    reason: str = Field(min_length=2, max_length=500)


class MergeCandidate(BaseModel):
    master_tbbm_id: UUID


class BulkReview(BaseModel):
    result_ids: list[UUID] = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=500)


class TbbmSettingsUpdate(BaseModel):
    request_delay_ms: int | None = Field(default=None, ge=0, le=60_000)
    maximum_retry: int | None = Field(default=None, ge=0, le=10)
    timeout_seconds: int | None = Field(default=None, ge=1, le=120)
    duplicate_radius_meters: int | None = Field(default=None, ge=10, le=10_000)
    name_similarity_threshold: float | None = Field(default=None, ge=0, le=1)


class KeywordCreate(BaseModel):
    keyword: str = Field(min_length=2, max_length=180)
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0)

    @field_validator("keyword")
    @classmethod
    def normalize_keyword(cls, value: str) -> str:
        return " ".join(value.split())


class KeywordUpdate(BaseModel):
    keyword: str | None = Field(default=None, min_length=2, max_length=180)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)
