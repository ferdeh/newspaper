from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select, update

from app.database import SessionLocal
from app.models import (
    AlertHistory,
    EmailAccount,
    NotificationOAuthState,
    NotificationRecipient,
    NotificationRule,
    NotificationRuleRecipient,
)
from app.notification.domain import AlertCreatedEvent
from app.notification.oauth import EmailOAuthService, OAuthFlowError
from app.notification.service import NotificationService


@pytest.mark.integration
def test_oauth_state_is_provider_bound_expiring_and_single_use():
    now = datetime.now(timezone.utc)
    valid_raw = f"valid-{uuid.uuid4()}"
    wrong_provider_raw = f"wrong-{uuid.uuid4()}"
    expired_raw = f"expired-{uuid.uuid4()}"
    digests = [hashlib.sha256(value.encode()).hexdigest() for value in (valid_raw, wrong_provider_raw, expired_raw)]
    try:
        with SessionLocal() as db:
            db.add_all(
                [
                    NotificationOAuthState(
                        state_digest=digests[0], provider="GMAIL", redirect_after_success="/settings",
                        created_at=now, expires_at=now + timedelta(minutes=5),
                    ),
                    NotificationOAuthState(
                        state_digest=digests[1], provider="GMAIL", redirect_after_success="/settings",
                        created_at=now, expires_at=now + timedelta(minutes=5),
                    ),
                    NotificationOAuthState(
                        state_digest=digests[2], provider="GMAIL", redirect_after_success="/settings",
                        created_at=now - timedelta(minutes=10), expires_at=now - timedelta(minutes=5),
                    ),
                ]
            )
            db.commit()
            service = EmailOAuthService(db)
            assert service.consume_state("google", valid_raw).consumed_at is not None
            with pytest.raises(OAuthFlowError):
                service.consume_state("google", valid_raw)
            with pytest.raises(OAuthFlowError):
                service.consume_state("microsoft", wrong_provider_raw)
            with pytest.raises(OAuthFlowError):
                service.consume_state("google", expired_raw)
    finally:
        with SessionLocal() as db:
            db.execute(delete(NotificationOAuthState).where(NotificationOAuthState.state_digest.in_(digests)))
            db.commit()


@pytest.mark.integration
def test_same_generic_rule_path_resolves_default_gmail_or_explicit_microsoft_and_deduplicates():
    with SessionLocal() as db:
        alert = db.scalar(select(AlertHistory).order_by(AlertHistory.id))
        if not alert:
            pytest.skip("Live database has no retained incident-level alert fixture")
        suffix = uuid.uuid4().hex[:8]
        db.execute(update(EmailAccount).values(is_default=False))
        gmail = EmailAccount(
            account_name=f"Gmail {suffix}", channel="EMAIL", provider="GMAIL",
            email_address=f"g-{suffix}@example.com", is_default=True, enabled=True,
            oauth_access_token_encrypted="test-only", oauth_scope="gmail.send",
            oauth_provider_account_id=f"g-{suffix}", connection_status="CONNECTED",
        )
        microsoft = EmailAccount(
            account_name=f"Microsoft {suffix}", channel="EMAIL", provider="MICROSOFT",
            email_address=f"m-{suffix}@example.com", is_default=False, enabled=True,
            oauth_access_token_encrypted="test-only", oauth_scope="Mail.Send",
            oauth_provider_account_id=f"m-{suffix}", connection_status="CONNECTED",
        )
        recipient = NotificationRecipient(
            name=f"Operations {suffix}", email_address=f"ops-{suffix}@example.com", enabled=True
        )
        db.add_all([gmail, microsoft, recipient])
        db.flush()
        default_rule = NotificationRule(
            name=f"Default {suffix}", channel="EMAIL", minimum_severity="HIGH", delivery_mode="IMMEDIATE"
        )
        microsoft_rule = NotificationRule(
            name=f"Microsoft {suffix}", channel="EMAIL", email_account_id=microsoft.id,
            minimum_severity="HIGH", delivery_mode="IMMEDIATE",
        )
        db.add_all([default_rule, microsoft_rule])
        db.flush()
        db.add_all(
            [
                NotificationRuleRecipient(
                    notification_rule_id=default_rule.id, recipient_id=recipient.id, recipient_role="TO"
                ),
                NotificationRuleRecipient(
                    notification_rule_id=microsoft_rule.id, recipient_id=recipient.id, recipient_role="TO"
                ),
            ]
        )
        db.flush()
        event = AlertCreatedEvent(
            event_type="ALERT_CREATED", alert_id=alert.id, incident_id=alert.incident_id,
            incident_code="INC-QA", severity="HIGH", category="FUEL_SHORTAGE", confidence_score=0.9,
            risk_score=82, title="Integration test", summary="Integration test", province="Jawa Timur",
            location="Kabupaten X", tbbm_id=None, nearest_tbbm_name=None, distance_tbbm_km=None,
            source_url=None, source_name="QA", published_at=now_utc(), source_count=5,
        )
        service = NotificationService(db)
        gmail_job = service._create_rule_job(default_rule, event)
        duplicate = service._create_rule_job(default_rule, event)
        microsoft_job = service._create_rule_job(microsoft_rule, event)
        assert gmail_job and gmail_job.channel == "EMAIL" and gmail_job.provider == "GMAIL"
        assert microsoft_job and microsoft_job.channel == "EMAIL" and microsoft_job.provider == "MICROSOFT"
        assert duplicate is None
        assert gmail_job.__tablename__ == microsoft_job.__tablename__ == "notification_jobs"
        db.rollback()


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
