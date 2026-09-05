from __future__ import annotations

from collections.abc import Callable

from app.notification.enums import EmailProviderType, NotificationChannel
from app.notification.interfaces import EmailProvider, NotificationChannelAdapter
from app.notification.providers import GmailProvider, MicrosoftGraphProvider


class EmailProviderRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], EmailProvider]] = {}

    def register(self, provider: EmailProviderType | str, factory: Callable[[], EmailProvider]) -> None:
        self._factories[str(provider)] = factory

    def get(self, provider: EmailProviderType | str) -> EmailProvider:
        try:
            return self._factories[str(provider)]()
        except KeyError as exc:
            raise ValueError(f"Email provider is not registered: {provider}") from exc


class NotificationChannelRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, Callable[[], NotificationChannelAdapter]] = {}

    def register(self, channel: NotificationChannel | str, factory: Callable[[], NotificationChannelAdapter]) -> None:
        self._factories[str(channel)] = factory

    def get(self, channel: NotificationChannel | str) -> NotificationChannelAdapter:
        try:
            return self._factories[str(channel)]()
        except KeyError as exc:
            raise ValueError(f"Notification channel is not registered: {channel}") from exc


email_provider_registry = EmailProviderRegistry()
email_provider_registry.register(EmailProviderType.GMAIL, GmailProvider)
email_provider_registry.register(EmailProviderType.MICROSOFT, MicrosoftGraphProvider)
