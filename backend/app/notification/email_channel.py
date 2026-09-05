from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import EmailAccount, NotificationJob
from app.notification.domain import EmailMessage, NotificationDeliveryError, ProviderDeliveryResult
from app.notification.enums import ConnectionStatus, NotificationErrorCode
from app.notification.interfaces import NotificationChannelAdapter
from app.notification.registries import EmailProviderRegistry, email_provider_registry
from app.notification.renderer import EmailRenderer


class EmailChannelAdapter(NotificationChannelAdapter):
    def __init__(
        self,
        db: Session,
        renderer: EmailRenderer | None = None,
        providers: EmailProviderRegistry = email_provider_registry,
    ) -> None:
        self.db = db
        self.renderer = renderer or EmailRenderer()
        self.providers = providers

    def _account(self, job: NotificationJob) -> EmailAccount:
        account = self.db.get(EmailAccount, job.sender_account_id) if job.sender_account_id else None
        if not account or not account.enabled or account.connection_status != ConnectionStatus.CONNECTED:
            raise NotificationDeliveryError(
                NotificationErrorCode.ACCOUNT_DISCONNECTED,
                "Akun pengirim email tidak terhubung.",
                reconnect_required=bool(account),
            )
        return account

    def validate_configuration(self, job: NotificationJob) -> None:
        self._account(job)
        recipients = job.payload_json.get("recipients", {})
        if not any(recipients.get(role) for role in ("to", "cc", "bcc")):
            raise NotificationDeliveryError(
                NotificationErrorCode.CONFIGURATION_ERROR,
                "Notification rule tidak memiliki penerima aktif.",
            )

    def prepare(self, job: NotificationJob) -> EmailMessage:
        account = self._account(job)
        try:
            return self.renderer.render(account.id, job.payload_json)
        except ValueError as exc:
            raise NotificationDeliveryError(NotificationErrorCode.INVALID_RECIPIENT, str(exc)) from exc

    def send(self, job: NotificationJob) -> ProviderDeliveryResult:
        self.validate_configuration(job)
        account = self._account(job)
        message = self.prepare(job)
        provider = self.providers.get(account.provider)
        return provider.send_email(account, message)

    def health_check(self) -> dict:
        return {"channel": "EMAIL", "registered_providers": ["GMAIL", "MICROSOFT"]}
