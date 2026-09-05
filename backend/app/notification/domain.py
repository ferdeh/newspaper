from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.notification.enums import NotificationErrorCode


@dataclass(frozen=True, slots=True)
class AlertCreatedEvent:
    event_type: str
    alert_id: int
    incident_id: int
    incident_code: str
    severity: str
    category: str
    confidence_score: float
    risk_score: float
    title: str
    summary: str
    province: str | None
    location: str
    tbbm_id: UUID | None
    nearest_tbbm_name: str | None
    distance_tbbm_km: float | None
    source_url: str | None
    source_name: str | None
    published_at: datetime
    source_count: int

    def as_payload(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "alert_id": self.alert_id,
            "incident_id": self.incident_id,
            "incident_code": self.incident_code,
            "severity": self.severity,
            "category": self.category,
            "confidence_score": self.confidence_score,
            "risk_score": self.risk_score,
            "title": self.title,
            "summary": self.summary,
            "province": self.province,
            "location": self.location,
            "tbbm_id": str(self.tbbm_id) if self.tbbm_id else None,
            "nearest_tbbm_name": self.nearest_tbbm_name,
            "distance_tbbm_km": self.distance_tbbm_km,
            "source_url": self.source_url,
            "source_name": self.source_name,
            "published_at": self.published_at.isoformat(),
            "source_count": self.source_count,
        }


@dataclass(frozen=True, slots=True)
class EmailMessage:
    sender_account_id: UUID
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    subject: str
    html_body: str
    text_body: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderDeliveryResult:
    provider_message_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class NotificationDeliveryError(RuntimeError):
    def __init__(
        self,
        code: NotificationErrorCode,
        message: str,
        *,
        retryable: bool = False,
        reconnect_required: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.reconnect_required = reconnect_required
