from __future__ import annotations

import uuid
from urllib.parse import urlparse

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from app.notification.enums import DeliveryMode, NotificationChannel, RecipientRole
from app.notification.renderer import validate_email_address


class EmailNotificationSettingsUpdate(BaseModel):
    enabled: bool


class EmailOAuthProviderConfigUpdate(BaseModel):
    client_id: str = Field(min_length=3, max_length=512)
    client_secret: SecretStr | None = None
    tenant: str | None = Field(default=None, min_length=1, max_length=255)
    redirect_uri: str = Field(min_length=10, max_length=2048)

    @field_validator("client_id", "tenant")
    @classmethod
    def clean_text(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("client_secret")
    @classmethod
    def valid_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and len(value.get_secret_value().strip()) < 8:
            raise ValueError("Client secret minimal 8 karakter.")
        return value

    @field_validator("redirect_uri")
    @classmethod
    def valid_redirect_uri(cls, value: str) -> str:
        cleaned = value.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Redirect URI harus berupa URL HTTP(S) absolut tanpa credential.")
        if parsed.fragment:
            raise ValueError("Redirect URI tidak boleh memiliki fragment.")
        if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
            raise ValueError("Gunakan HTTPS untuk redirect URI selain localhost.")
        return cleaned


class TestEmailRequest(BaseModel):
    recipient: str

    @field_validator("recipient")
    @classmethod
    def valid_recipient(cls, value: str) -> str:
        return validate_email_address(value)


class RecipientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    email_address: str
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("email_address")
    @classmethod
    def valid_email(cls, value: str) -> str:
        return validate_email_address(value)


class RecipientUpdate(RecipientCreate):
    pass


class RecipientGroupCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    enabled: bool = True
    recipient_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())


class RecipientGroupUpdate(RecipientGroupCreate):
    pass


class RuleRecipientTarget(BaseModel):
    recipient_id: uuid.UUID | None = None
    recipient_group_id: uuid.UUID | None = None
    recipient_role: RecipientRole

    @model_validator(mode="after")
    def exactly_one_target(self):
        if (self.recipient_id is None) == (self.recipient_group_id is None):
            raise ValueError("Pilih tepat satu recipient atau recipient group.")
        return self


class NotificationRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool = True
    channel: NotificationChannel = NotificationChannel.EMAIL
    email_account_id: uuid.UUID | None = None
    category: str | None = Field(default=None, max_length=64)
    minimum_severity: str | None = Field(default=None, pattern="^(CRITICAL|HIGH|MEDIUM|LOW)$")
    minimum_confidence_score: float | None = Field(default=None, ge=0, le=1)
    province: str | None = Field(default=None, max_length=120)
    city_or_area: str | None = Field(default=None, max_length=160)
    tbbm_id: uuid.UUID | None = None
    delivery_mode: DeliveryMode = DeliveryMode.IMMEDIATE
    digest_interval_minutes: int | None = Field(default=None, ge=5, le=10080)
    recipients: list[RuleRecipientTarget] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def valid_digest(self):
        if self.delivery_mode == DeliveryMode.DIGEST and self.digest_interval_minutes is None:
            self.digest_interval_minutes = 60
        if self.delivery_mode != DeliveryMode.DIGEST:
            self.digest_interval_minutes = None
        return self


class NotificationRuleUpdate(NotificationRuleCreate):
    pass
