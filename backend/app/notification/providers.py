from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage as MimeEmailMessage

import httpx
from sqlalchemy.orm import object_session

from app.database import SessionLocal
from app.models import EmailAccount
from app.notification.credentials import EmailCredentialError, EmailCredentialService, email_credentials
from app.notification.domain import EmailMessage, NotificationDeliveryError, ProviderDeliveryResult
from app.notification.enums import ConnectionStatus, NotificationErrorCode
from app.notification.interfaces import EmailProvider
from app.notification.oauth_config import OAuthConfigurationError, resolve_email_oauth_config


def _oauth_configuration(account: EmailAccount, provider: str):
    try:
        configuration = resolve_email_oauth_config(provider, object_session(account))
    except OAuthConfigurationError as exc:
        raise NotificationDeliveryError(
            NotificationErrorCode.CONFIGURATION_ERROR,
            str(exc),
            reconnect_required=True,
        ) from exc
    if not configuration.client_id or not configuration.client_secret:
        raise NotificationDeliveryError(
            NotificationErrorCode.CONFIGURATION_ERROR,
            "Konfigurasi OAuth provider tidak lengkap. Perbarui melalui Provider Setup.",
            reconnect_required=True,
        )
    return configuration


def _provider_is_configured(provider: str) -> bool:
    with SessionLocal() as db:
        try:
            return resolve_email_oauth_config(provider, db).configured
        except OAuthConfigurationError:
            return False


def _provider_error(response: httpx.Response) -> NotificationDeliveryError:
    if response.status_code == 429:
        return NotificationDeliveryError(
            NotificationErrorCode.PROVIDER_RATE_LIMIT,
            "Penyedia email membatasi sementara pengiriman.",
            retryable=True,
        )
    if response.status_code >= 500:
        return NotificationDeliveryError(
            NotificationErrorCode.PROVIDER_TEMPORARY_ERROR,
            "Layanan penyedia email sedang tidak tersedia.",
            retryable=True,
        )
    if response.status_code == 401:
        return NotificationDeliveryError(
            NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED,
            "Akun email perlu dihubungkan kembali.",
            reconnect_required=True,
        )
    if response.status_code == 400:
        return NotificationDeliveryError(
            NotificationErrorCode.INVALID_RECIPIENT,
            "Penyedia email menolak alamat penerima atau isi pesan.",
        )
    return NotificationDeliveryError(
        NotificationErrorCode.UNKNOWN_ERROR,
        "Penyedia email menolak permintaan pengiriman.",
    )


class GmailProvider(EmailProvider):
    token_url = "https://oauth2.googleapis.com/token"
    send_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    profile_url = "https://gmail.googleapis.com/gmail/v1/users/me/profile"

    def __init__(self, credentials: EmailCredentialService = email_credentials, client: httpx.Client | None = None) -> None:
        self.credentials = credentials
        self.client = client or httpx.Client(timeout=20)

    def _access_token(self, account: EmailAccount) -> str:
        if not account.oauth_access_token_encrypted:
            raise NotificationDeliveryError(
                NotificationErrorCode.ACCOUNT_DISCONNECTED,
                "Akun Gmail tidak terhubung.",
                reconnect_required=True,
            )
        try:
            return self.credentials.decrypt(account.oauth_access_token_encrypted)
        except EmailCredentialError as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED,
                "Akun Gmail perlu dihubungkan kembali.",
                reconnect_required=True,
            ) from exc

    def refresh_credentials(self, account: EmailAccount) -> None:
        if not account.oauth_refresh_token_encrypted:
            raise NotificationDeliveryError(
                NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED,
                "Akun Gmail perlu dihubungkan kembali.",
                reconnect_required=True,
            )
        configuration = _oauth_configuration(account, "GMAIL")
        try:
            refresh_token = self.credentials.decrypt(account.oauth_refresh_token_encrypted)
            response = self.client.post(
                self.token_url,
                data={
                    "client_id": configuration.client_id,
                    "client_secret": configuration.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
            )
        except (EmailCredentialError, httpx.HTTPError) as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.AUTH_REFRESH_FAILED,
                "Penyegaran autentikasi Gmail gagal.",
                retryable=isinstance(exc, httpx.TransportError),
                reconnect_required=not isinstance(exc, httpx.TransportError),
            ) from exc
        if response.status_code >= 400:
            raise NotificationDeliveryError(
                NotificationErrorCode.AUTH_REFRESH_FAILED,
                "Penyegaran autentikasi Gmail gagal.",
                retryable=response.status_code >= 500 or response.status_code == 429,
                reconnect_required=response.status_code < 500 and response.status_code != 429,
            )
        payload = response.json()
        account.oauth_access_token_encrypted = self.credentials.encrypt(payload["access_token"])
        account.oauth_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        account.connection_status = ConnectionStatus.CONNECTED

    def _authorized_request(self, account: EmailAccount, method: str, url: str, **kwargs) -> httpx.Response:
        if account.oauth_token_expires_at and account.oauth_token_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            self.refresh_credentials(account)
        try:
            response = self.client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self._access_token(account)}"},
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.NETWORK_ERROR,
                "Jaringan ke Gmail sedang bermasalah.",
                retryable=True,
            ) from exc
        if response.status_code == 401:
            self.refresh_credentials(account)
            response = self.client.request(
                method,
                url,
                headers={"Authorization": f"Bearer {self._access_token(account)}"},
                **kwargs,
            )
        return response

    def validate_account(self, account: EmailAccount) -> bool:
        response = self._authorized_request(account, "GET", self.profile_url)
        if response.status_code >= 400:
            raise _provider_error(response)
        return response.json().get("emailAddress", "").lower() == account.email_address.lower()

    def send_email(self, account: EmailAccount, message: EmailMessage) -> ProviderDeliveryResult:
        mime = MimeEmailMessage()
        mime["From"] = f"{account.display_name} <{account.email_address}>" if account.display_name else account.email_address
        mime["To"] = ", ".join(message.to)
        if message.cc:
            mime["Cc"] = ", ".join(message.cc)
        if message.bcc:
            mime["Bcc"] = ", ".join(message.bcc)
        mime["Subject"] = message.subject
        mime.set_content(message.text_body)
        mime.add_alternative(message.html_body, subtype="html")
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode().rstrip("=")
        response = self._authorized_request(account, "POST", self.send_url, json={"raw": raw})
        if response.status_code >= 400:
            raise _provider_error(response)
        payload = response.json()
        return ProviderDeliveryResult(payload.get("id"), {"thread_id": payload.get("threadId")})

    def health_check(self) -> dict:
        return {"provider": "GMAIL", "configured": _provider_is_configured("GMAIL")}


class MicrosoftGraphProvider(EmailProvider):
    graph_base_url = "https://graph.microsoft.com/v1.0"

    def __init__(self, credentials: EmailCredentialService = email_credentials, client: httpx.Client | None = None) -> None:
        self.credentials = credentials
        self.client = client or httpx.Client(timeout=20)

    def _access_token(self, account: EmailAccount) -> str:
        if not account.oauth_access_token_encrypted:
            raise NotificationDeliveryError(
                NotificationErrorCode.ACCOUNT_DISCONNECTED,
                "Akun Microsoft tidak terhubung.",
                reconnect_required=True,
            )
        try:
            return self.credentials.decrypt(account.oauth_access_token_encrypted)
        except EmailCredentialError as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED,
                "Akun Microsoft perlu dihubungkan kembali.",
                reconnect_required=True,
            ) from exc

    def refresh_credentials(self, account: EmailAccount) -> None:
        if not account.oauth_refresh_token_encrypted:
            raise NotificationDeliveryError(
                NotificationErrorCode.EMAIL_ACCOUNT_RECONNECT_REQUIRED,
                "Akun Microsoft perlu dihubungkan kembali.",
                reconnect_required=True,
            )
        configuration = _oauth_configuration(account, "MICROSOFT")
        try:
            refresh_token = self.credentials.decrypt(account.oauth_refresh_token_encrypted)
            response = self.client.post(
                f"https://login.microsoftonline.com/{configuration.tenant or 'common'}/oauth2/v2.0/token",
                data={
                    "client_id": configuration.client_id,
                    "client_secret": configuration.client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                    "scope": "openid profile email offline_access User.Read Mail.Send",
                },
            )
        except (EmailCredentialError, httpx.HTTPError) as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.AUTH_REFRESH_FAILED,
                "Penyegaran autentikasi Microsoft gagal.",
                retryable=isinstance(exc, httpx.TransportError),
                reconnect_required=not isinstance(exc, httpx.TransportError),
            ) from exc
        if response.status_code >= 400:
            raise NotificationDeliveryError(
                NotificationErrorCode.AUTH_REFRESH_FAILED,
                "Penyegaran autentikasi Microsoft gagal.",
                retryable=response.status_code >= 500 or response.status_code == 429,
                reconnect_required=response.status_code < 500 and response.status_code != 429,
            )
        payload = response.json()
        account.oauth_access_token_encrypted = self.credentials.encrypt(payload["access_token"])
        if payload.get("refresh_token"):
            account.oauth_refresh_token_encrypted = self.credentials.encrypt(payload["refresh_token"])
        account.oauth_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(payload.get("expires_in", 3600)))
        account.connection_status = ConnectionStatus.CONNECTED

    def _authorized_request(self, account: EmailAccount, method: str, path: str, **kwargs) -> httpx.Response:
        if account.oauth_token_expires_at and account.oauth_token_expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
            self.refresh_credentials(account)
        try:
            response = self.client.request(
                method,
                f"{self.graph_base_url}{path}",
                headers={"Authorization": f"Bearer {self._access_token(account)}"},
                **kwargs,
            )
        except httpx.TransportError as exc:
            raise NotificationDeliveryError(
                NotificationErrorCode.NETWORK_ERROR,
                "Jaringan ke Microsoft Graph sedang bermasalah.",
                retryable=True,
            ) from exc
        if response.status_code == 401:
            self.refresh_credentials(account)
            response = self.client.request(
                method,
                f"{self.graph_base_url}{path}",
                headers={"Authorization": f"Bearer {self._access_token(account)}"},
                **kwargs,
            )
        return response

    def validate_account(self, account: EmailAccount) -> bool:
        response = self._authorized_request(account, "GET", "/me?$select=id,mail,userPrincipalName")
        if response.status_code >= 400:
            raise _provider_error(response)
        payload = response.json()
        actual = payload.get("mail") or payload.get("userPrincipalName") or ""
        return actual.lower() == account.email_address.lower()

    def send_email(self, account: EmailAccount, message: EmailMessage) -> ProviderDeliveryResult:
        def recipients(values: tuple[str, ...]) -> list[dict]:
            return [{"emailAddress": {"address": value}} for value in values]

        payload = {
            "message": {
                "subject": message.subject,
                "body": {"contentType": "HTML", "content": message.html_body},
                "toRecipients": recipients(message.to),
                "ccRecipients": recipients(message.cc),
                "bccRecipients": recipients(message.bcc),
            },
            "saveToSentItems": True,
        }
        response = self._authorized_request(account, "POST", "/me/sendMail", json=payload)
        if response.status_code >= 400:
            raise _provider_error(response)
        return ProviderDeliveryResult(response.headers.get("request-id"), {"status_code": response.status_code})

    def health_check(self) -> dict:
        return {
            "provider": "MICROSOFT",
            "configured": _provider_is_configured("MICROSOFT"),
        }
