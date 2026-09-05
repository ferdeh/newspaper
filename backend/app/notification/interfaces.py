from __future__ import annotations

from abc import ABC, abstractmethod

from app.models import EmailAccount, NotificationJob
from app.notification.domain import EmailMessage, ProviderDeliveryResult


class NotificationChannelAdapter(ABC):
    @abstractmethod
    def validate_configuration(self, job: NotificationJob) -> None: ...

    @abstractmethod
    def prepare(self, job: NotificationJob) -> EmailMessage: ...

    @abstractmethod
    def send(self, job: NotificationJob) -> ProviderDeliveryResult: ...

    @abstractmethod
    def health_check(self) -> dict: ...


class EmailProvider(ABC):
    @abstractmethod
    def validate_account(self, account: EmailAccount) -> bool: ...

    @abstractmethod
    def refresh_credentials(self, account: EmailAccount) -> None: ...

    @abstractmethod
    def send_email(self, account: EmailAccount, message: EmailMessage) -> ProviderDeliveryResult: ...

    @abstractmethod
    def health_check(self) -> dict: ...
