from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from pydantic import SecretStr

from app.config import settings
from app.models import EmailAccount, EmailOAuthProviderConfig, NotificationJob, NotificationRule
from app.notification.credentials import EmailCredentialService
from app.notification.domain import AlertCreatedEvent, EmailMessage, NotificationDeliveryError
from app.notification.enums import ConnectionStatus, NotificationChannel, NotificationErrorCode
from app.notification.oauth import EmailOAuthService
from app.notification.oauth_config import ResolvedEmailOAuthConfig, resolve_email_oauth_config
from app.notification.providers import GmailProvider, MicrosoftGraphProvider
from app.notification.registries import EmailProviderRegistry, NotificationChannelRegistry
from app.notification.renderer import EmailRenderer, safe_subject
from app.notification.service import NotificationService
from app.notification.worker import NotificationWorker
from app.notification_schemas import EmailOAuthProviderConfigUpdate


def event(severity: str = "CRITICAL") -> AlertCreatedEvent:
    return AlertCreatedEvent(
        event_type="ALERT_CREATED",
        alert_id=12,
        incident_id=11,
        incident_code="INC-20260904-0011",
        severity=severity,
        category="TANKER_ACCIDENT",
        confidence_score=0.88,
        risk_score=82,
        title="Tanker <script>alert(1)</script>",
        summary="External <b>content</b>",
        province="Jawa Timur",
        location="Kabupaten X",
        tbbm_id=None,
        nearest_tbbm_name="Fuel Terminal ABC",
        distance_tbbm_km=24.7,
        source_url="https://example.com/article",
        source_name="Media XYZ",
        published_at=datetime(2026, 9, 4, 10, 42, tzinfo=timezone.utc),
        source_count=5,
    )


def account(provider: str, credentials: EmailCredentialService) -> EmailAccount:
    return EmailAccount(
        id=uuid.uuid4(),
        account_name="Pilot sender",
        channel="EMAIL",
        provider=provider,
        email_address="sender@example.com",
        display_name="News Intelligence",
        enabled=True,
        connection_status=ConnectionStatus.CONNECTED,
        oauth_access_token_encrypted=credentials.encrypt("access-token"),
        oauth_refresh_token_encrypted=credentials.encrypt("refresh-token"),
        oauth_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        oauth_scope="Mail.Send",
        oauth_provider_account_id="provider-id",
    )


def message(account_id: uuid.UUID) -> EmailMessage:
    return EmailMessage(
        sender_account_id=account_id,
        to=("recipient@example.com",),
        cc=("manager@example.com",),
        bcc=(),
        subject="[TEST] Notification",
        html_body="<strong>Working</strong>",
        text_body="Working",
    )


def test_alert_event_is_provider_agnostic():
    payload = event().as_payload()
    assert payload["event_type"] == "ALERT_CREATED"
    assert "provider" not in payload
    assert "gmail" not in str(payload).lower()
    assert "microsoft" not in str(payload).lower()


def test_rule_matching_uses_generic_severity_and_filters():
    service = NotificationService(None)  # type: ignore[arg-type]
    rule = NotificationRule(
        name="Critical tanker",
        channel="EMAIL",
        minimum_severity="CRITICAL",
        category="TANKER_ACCIDENT",
        delivery_mode="IMMEDIATE",
    )
    assert service._matches(rule, event("CRITICAL")) is True
    assert service._matches(rule, event("LOW")) is False


def test_provider_and_channel_registries_are_separate():
    providers = EmailProviderRegistry()
    gmail = object()
    microsoft = object()
    providers.register("GMAIL", lambda: gmail)  # type: ignore[arg-type,return-value]
    providers.register("MICROSOFT", lambda: microsoft)  # type: ignore[arg-type,return-value]
    channels = NotificationChannelRegistry()
    email = object()
    channels.register(NotificationChannel.EMAIL, lambda: email)  # type: ignore[arg-type,return-value]
    assert providers.get("GMAIL") is gmail
    assert providers.get("MICROSOFT") is microsoft
    assert channels.get("EMAIL") is email


def test_email_credential_ciphertext_is_random_and_round_trips(monkeypatch):
    monkeypatch.setattr(settings, "email_token_encryption_key", None)
    monkeypatch.setattr(settings, "app_encryption_key", None)
    credentials = EmailCredentialService()
    first = credentials.encrypt("sensitive-token")
    second = credentials.encrypt("sensitive-token")
    assert first != second
    assert credentials.decrypt(first) == "sensitive-token"
    assert "sensitive-token" not in first


def test_common_renderer_escapes_external_content_and_header_injection():
    rendered = EmailRenderer().render(
        uuid.uuid4(),
        {"template": "immediate_alert", "alert": event().as_payload(), "recipients": {"to": ["ops@example.com"]}},
    )
    assert "<script>" not in rendered.html_body
    assert "&lt;script&gt;" in rendered.html_body
    assert "<b>content</b>" not in rendered.html_body
    assert "\n" not in safe_subject("subject\r\nBcc: victim@example.com")


def test_gmail_provider_uses_gmail_api_and_common_message(monkeypatch):
    credentials = EmailCredentialService()
    row = account("GMAIL", credentials)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/gmail/v1/users/me/messages/send")
        assert request.headers["authorization"] == "Bearer access-token"
        assert b"raw" in request.content
        return httpx.Response(200, json={"id": "gmail-message", "threadId": "thread-1"})

    provider = GmailProvider(credentials, httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.send_email(row, message(row.id))
    assert result.provider_message_id == "gmail-message"


def test_microsoft_provider_uses_graph_sendmail_and_common_message():
    credentials = EmailCredentialService()
    row = account("MICROSOFT", credentials)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/v1.0/me/sendMail")
        assert request.headers["authorization"] == "Bearer access-token"
        assert b"toRecipients" in request.content
        return httpx.Response(202, headers={"request-id": "graph-request"})

    provider = MicrosoftGraphProvider(credentials, httpx.Client(transport=httpx.MockTransport(handler)))
    result = provider.send_email(row, message(row.id))
    assert result.provider_message_id == "graph-request"


@pytest.mark.parametrize("provider_type", ["GMAIL", "MICROSOFT"])
def test_provider_rate_limit_is_normalized(provider_type):
    credentials = EmailCredentialService()
    row = account(provider_type, credentials)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "provider-specific text"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GmailProvider(credentials, client) if provider_type == "GMAIL" else MicrosoftGraphProvider(credentials, client)
    with pytest.raises(NotificationDeliveryError) as raised:
        provider.send_email(row, message(row.id))
    assert raised.value.code == NotificationErrorCode.PROVIDER_RATE_LIMIT
    assert raised.value.retryable is True
    assert "provider-specific text" not in str(raised.value)


def test_gmail_refreshes_expired_token_before_send(monkeypatch):
    credentials = EmailCredentialService()
    row = account("GMAIL", credentials)
    row.oauth_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("google-secret"))
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "refreshed-google", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer refreshed-google"
        return httpx.Response(200, json={"id": "gmail-after-refresh"})

    provider = GmailProvider(credentials, httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.send_email(row, message(row.id)).provider_message_id == "gmail-after-refresh"
    assert requests[0].endswith("/token")


def test_microsoft_refreshes_expired_token_before_send(monkeypatch):
    credentials = EmailCredentialService()
    row = account("MICROSOFT", credentials)
    row.oauth_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    monkeypatch.setattr(settings, "microsoft_client_id", "microsoft-client")
    monkeypatch.setattr(settings, "microsoft_client_secret", SecretStr("microsoft-secret"))
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "login.microsoftonline.com":
            return httpx.Response(200, json={"access_token": "refreshed-microsoft", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer refreshed-microsoft"
        return httpx.Response(202, headers={"request-id": "graph-after-refresh"})

    provider = MicrosoftGraphProvider(credentials, httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.send_email(row, message(row.id)).provider_message_id == "graph-after-refresh"
    assert requests[0].endswith("/oauth2/v2.0/token")


def test_google_oauth_requests_send_only_gmail_scope(monkeypatch):
    class FakeSession:
        def scalar(self, query):
            return None

        def add(self, value):
            self.value = value

        def commit(self):
            pass

    monkeypatch.setattr(settings, "google_client_id", "google-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("google-client-secret"))
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://app.example.com/api/email/oauth/google/callback")
    url = EmailOAuthService(FakeSession()).authorization_url("GMAIL")  # type: ignore[arg-type]
    scopes = parse_qs(urlparse(url).query)["scope"][0].split()
    assert "https://www.googleapis.com/auth/gmail.send" in scopes
    assert all("readonly" not in scope and "gmail.read" not in scope for scope in scopes)


def test_ui_provider_configuration_overrides_environment_without_exposing_plain_secret(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "environment-client")
    monkeypatch.setattr(settings, "google_client_secret", SecretStr("environment-secret"))
    monkeypatch.setattr(settings, "google_oauth_redirect_uri", "https://env.example.com/api/email/oauth/google/callback")
    encrypted = EmailCredentialService().encrypt("database-client-secret")
    row = EmailOAuthProviderConfig(
        provider="GMAIL",
        client_id="database-client",
        client_secret_encrypted=encrypted,
        redirect_uri="https://app.example.com/api/email/oauth/google/callback",
    )

    class FakeSession:
        def scalar(self, query):
            return row

    resolved = resolve_email_oauth_config("GMAIL", FakeSession())  # type: ignore[arg-type]
    assert resolved.client_id == "database-client"
    assert resolved.client_secret == "database-client-secret"
    assert resolved.source == "database"
    assert "database-client-secret" not in row.client_secret_encrypted


def test_provider_config_rejects_insecure_non_local_redirect_and_short_secret():
    with pytest.raises(ValueError):
        EmailOAuthProviderConfigUpdate(
            client_id="client-id",
            client_secret=SecretStr("short"),
            redirect_uri="http://example.com/api/email/oauth/google/callback",
        )
    local = EmailOAuthProviderConfigUpdate(
        client_id="client-id",
        client_secret=SecretStr("strong-secret"),
        redirect_uri="http://localhost/api/email/oauth/google/callback",
    )
    assert local.redirect_uri.startswith("http://localhost/")


def test_gmail_refresh_uses_ui_resolved_configuration(monkeypatch):
    credentials = EmailCredentialService()
    row = account("GMAIL", credentials)
    row.oauth_token_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    resolved = ResolvedEmailOAuthConfig(
        provider="GMAIL",
        client_id="ui-client",
        client_secret="ui-secret",
        tenant=None,
        redirect_uri="https://app.example.com/api/email/oauth/google/callback",
        source="database",
    )
    monkeypatch.setattr("app.notification.providers.resolve_email_oauth_config", lambda provider, db=None: resolved)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            assert b"client_id=ui-client" in request.content
            assert b"client_secret=ui-secret" in request.content
            return httpx.Response(200, json={"access_token": "refreshed-ui", "expires_in": 3600})
        assert request.headers["authorization"] == "Bearer refreshed-ui"
        return httpx.Response(200, json={"id": "gmail-ui-config"})

    provider = GmailProvider(credentials, httpx.Client(transport=httpx.MockTransport(handler)))
    assert provider.send_email(row, message(row.id)).provider_message_id == "gmail-ui-config"


def test_retry_schedule_matches_pilot_policy(monkeypatch):
    monkeypatch.setattr(settings, "notification_retry_delays_seconds", [0, 60, 300, 900])
    assert NotificationWorker._retry_delay(1) == 60
    assert NotificationWorker._retry_delay(2) == 300
    assert NotificationWorker._retry_delay(3) == 900


def test_notification_job_is_generic_not_email_job():
    job = NotificationJob(
        channel="EMAIL",
        provider="GMAIL",
        delivery_mode="IMMEDIATE",
        payload_json={},
        idempotency_key="stable",
    )
    assert job.__tablename__ == "notification_jobs"
    assert hasattr(job, "channel")
    assert hasattr(job, "provider")
    assert NotificationErrorCode.PROVIDER_RATE_LIMIT == "PROVIDER_RATE_LIMIT"
