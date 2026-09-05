from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    AlertHistory,
    EmailAccount,
    Incident,
    NewsSource,
    NotificationChannelConfig,
    NotificationJob,
    NotificationRecipient,
    NotificationRecipientGroup,
    NotificationRecipientGroupMember,
    NotificationRule,
    NotificationRuleRecipient,
    RawArticle,
)
from app.notification.domain import AlertCreatedEvent
from app.notification.enums import (
    SEVERITY_ORDER,
    ConnectionStatus,
    DeliveryMode,
    NotificationChannel,
    NotificationErrorCode,
    NotificationJobStatus,
    normalize_severity,
)
from app.notification.renderer import validate_email_address
from app.services.tbbm_runtime import verified_tbbm

logger = logging.getLogger("fuel-intelligence.notifications")


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def event_from_alert(self, alert: AlertHistory, incident: Incident) -> AlertCreatedEvent:
        primary_link = next((link for link in incident.signal_links if link.is_primary_signal), None)
        if not primary_link and incident.signal_links:
            primary_link = min(incident.signal_links, key=lambda link: link.signal.published_at)
        signal = primary_link.signal if primary_link else None
        source_name = signal.source_type if signal else None
        if signal and signal.source_type == "NEWS":
            source_name = self.db.scalar(
                select(NewsSource.name)
                .join(RawArticle, RawArticle.source_id == NewsSource.id)
                .where(RawArticle.id == signal.source_record_id)
            ) or "NEWS"
        location = incident.location.normalized_name if incident.location else incident.geocoded_address or "Lokasi belum terverifikasi"
        nearest = verified_tbbm(incident.nearest_tbbm)
        return AlertCreatedEvent(
            event_type="ALERT_CREATED",
            alert_id=alert.id,
            incident_id=incident.id,
            incident_code=incident.incident_code,
            severity=normalize_severity(alert.severity),
            category=incident.primary_event_type,
            confidence_score=incident.confidence,
            risk_score=alert.risk_score,
            title=signal.title if signal else incident.primary_event_type.replace("_", " ").title(),
            summary=(signal.content[:1200] if signal else alert.message_payload.get("text", "")),
            province=incident.location.province if incident.location else None,
            location=location,
            tbbm_id=nearest.id if nearest else None,
            nearest_tbbm_name=nearest.name if nearest else None,
            distance_tbbm_km=incident.nearest_terminal_distance_km if nearest else None,
            source_url=signal.source_url if signal else None,
            source_name=source_name,
            published_at=signal.published_at if signal else incident.first_signal_at,
            source_count=max(incident.signal_count, 1),
        )

    def handle_alert_created(self, event: AlertCreatedEvent) -> int:
        logger.info(
            "notification_event_received",
            extra={"alert_id": event.alert_id, "incident_id": event.incident_id, "event_type": event.event_type},
        )
        email_channel = self.db.scalar(
            select(NotificationChannelConfig).where(
                NotificationChannelConfig.channel_type == NotificationChannel.EMAIL,
                NotificationChannelConfig.enabled.is_(True),
            )
        )
        if not email_channel:
            return 0
        rules = self.db.scalars(
            select(NotificationRule).where(
                NotificationRule.enabled.is_(True),
                NotificationRule.channel == NotificationChannel.EMAIL,
            )
        ).all()
        created = 0
        for rule in rules:
            if self._matches(rule, event) and rule.delivery_mode != DeliveryMode.DASHBOARD_ONLY:
                logger.info(
                    "notification_rule_matched",
                    extra={"alert_id": event.alert_id, "incident_id": event.incident_id, "rule_id": str(rule.id)},
                )
                created += int(self._create_rule_job(rule, event) is not None)
        return created

    def _matches(self, rule: NotificationRule, event: AlertCreatedEvent) -> bool:
        if rule.category and rule.category.upper() != event.category.upper():
            return False
        if rule.minimum_severity and SEVERITY_ORDER[event.severity] < SEVERITY_ORDER[normalize_severity(rule.minimum_severity)]:
            return False
        if rule.minimum_confidence_score is not None and event.confidence_score < rule.minimum_confidence_score:
            return False
        if rule.province and (event.province or "").casefold() != rule.province.casefold():
            return False
        if rule.city_or_area and rule.city_or_area.casefold() not in event.location.casefold():
            return False
        return not rule.tbbm_id or rule.tbbm_id == event.tbbm_id

    def _resolve_account(self, rule: NotificationRule) -> EmailAccount | None:
        if rule.email_account_id:
            return self.db.get(EmailAccount, rule.email_account_id)
        return self.db.scalar(
            select(EmailAccount).where(
                EmailAccount.channel == NotificationChannel.EMAIL,
                EmailAccount.enabled.is_(True),
                EmailAccount.is_default.is_(True),
            )
        )

    def _resolve_recipients(self, rule_id: uuid.UUID) -> dict[str, list[str]]:
        result: dict[str, set[str]] = {"to": set(), "cc": set(), "bcc": set()}
        mappings = self.db.scalars(
            select(NotificationRuleRecipient).where(NotificationRuleRecipient.notification_rule_id == rule_id)
        ).all()
        for mapping in mappings:
            role = mapping.recipient_role.lower()
            recipients: list[NotificationRecipient]
            if mapping.recipient_id:
                recipient = self.db.get(NotificationRecipient, mapping.recipient_id)
                recipients = [recipient] if recipient else []
            else:
                group = self.db.get(NotificationRecipientGroup, mapping.recipient_group_id)
                if not group or not group.enabled:
                    continue
                recipients = self.db.scalars(
                    select(NotificationRecipient)
                    .join(
                        NotificationRecipientGroupMember,
                        NotificationRecipientGroupMember.recipient_id == NotificationRecipient.id,
                    )
                    .where(NotificationRecipientGroupMember.group_id == mapping.recipient_group_id)
                ).all()
            for recipient in recipients:
                if recipient.enabled:
                    result[role].add(validate_email_address(recipient.email_address))
        result["cc"] -= result["to"]
        result["bcc"] -= result["to"] | result["cc"]
        return {role: sorted(values) for role, values in result.items()}

    def _create_rule_job(self, rule: NotificationRule, event: AlertCreatedEvent) -> NotificationJob | None:
        recipients = self._resolve_recipients(rule.id)
        account = self._resolve_account(rule)
        sender_id = str(account.id) if account else "NONE"
        fingerprint = hashlib.sha256(json.dumps(recipients, sort_keys=True).encode()).hexdigest()
        idempotency_key = hashlib.sha256(
            f"{event.alert_id}:{rule.id}:{rule.channel}:{sender_id}:{rule.delivery_mode}:{fingerprint}".encode()
        ).hexdigest()
        now = datetime.now(timezone.utc)
        interval = rule.digest_interval_minutes or 60
        if rule.delivery_mode == DeliveryMode.DIGEST:
            interval_seconds = interval * 60
            scheduled_at = datetime.fromtimestamp(
                ((int(now.timestamp()) // interval_seconds) + 1) * interval_seconds,
                tz=timezone.utc,
            )
        else:
            scheduled_at = now
        status = NotificationJobStatus.PENDING
        error_code = None
        last_error = None
        if not account:
            status = NotificationJobStatus.FAILED
            error_code = NotificationErrorCode.CONFIGURATION_ERROR
            last_error = "Tidak ada default sender email aktif."
        elif not account.enabled or account.connection_status != ConnectionStatus.CONNECTED:
            status = NotificationJobStatus.FAILED
            error_code = NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED
            last_error = "Akun pengirim email perlu dihubungkan kembali."
        elif not any(recipients.values()):
            status = NotificationJobStatus.FAILED
            error_code = NotificationErrorCode.CONFIGURATION_ERROR
            last_error = "Notification rule tidak memiliki penerima aktif."
        job = NotificationJob(
            alert_id=event.alert_id,
            incident_id=event.incident_id,
            notification_rule_id=rule.id,
            channel=rule.channel,
            provider=account.provider if account else None,
            sender_account_id=account.id if account else None,
            delivery_mode=rule.delivery_mode,
            payload_json={
                "template": "digest_alert" if rule.delivery_mode == DeliveryMode.DIGEST else "immediate_alert",
                "alert": event.as_payload(),
                "recipients": recipients,
            },
            status=status,
            priority=500 - SEVERITY_ORDER[event.severity] * 100,
            max_attempts=settings.notification_job_max_attempts,
            scheduled_at=scheduled_at,
            failed_at=now if status == NotificationJobStatus.FAILED else None,
            idempotency_key=idempotency_key,
            last_error=last_error,
            error_code=error_code,
        )
        try:
            with self.db.begin_nested():
                self.db.add(job)
                self.db.flush()
        except IntegrityError:
            existing = self.db.scalar(
                select(NotificationJob.id).where(NotificationJob.idempotency_key == idempotency_key)
            )
            if existing:
                return None
            raise
        logger.info(
            "notification_job_created",
            extra={
                "notification_job_id": str(job.id),
                "alert_id": event.alert_id,
                "incident_id": event.incident_id,
                "channel": job.channel,
                "provider": job.provider,
                "rule_id": str(rule.id),
                "status": job.status,
            },
        )
        return job

    def create_test_email_job(self, account: EmailAccount, recipient: str) -> NotificationJob:
        email_address = validate_email_address(recipient)
        now = datetime.now(timezone.utc)
        job = NotificationJob(
            channel=NotificationChannel.EMAIL,
            provider=account.provider,
            sender_account_id=account.id,
            delivery_mode=DeliveryMode.IMMEDIATE,
            payload_json={
                "template": "test_email",
                "recipients": {"to": [email_address], "cc": [], "bcc": []},
                "account": {"provider": account.provider, "email_address": account.email_address},
                "timestamp": now.isoformat(),
            },
            status=NotificationJobStatus.PENDING,
            priority=0,
            max_attempts=settings.notification_job_max_attempts,
            scheduled_at=now,
            idempotency_key=hashlib.sha256(f"test:{uuid.uuid4()}".encode()).hexdigest(),
        )
        self.db.add(job)
        self.db.flush()
        return job
