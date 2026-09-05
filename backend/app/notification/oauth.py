from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailAccount, NotificationOAuthState
from app.notification.credentials import email_credentials
from app.notification.enums import ConnectionStatus, EmailProviderType, NotificationChannel
from app.notification.oauth_config import (
    OAuthConfigurationError,
    ResolvedEmailOAuthConfig,
    normalize_email_provider,
    resolve_email_oauth_config,
)

GOOGLE_SCOPES = ("openid", "email", "https://www.googleapis.com/auth/gmail.send")
MICROSOFT_SCOPES = ("openid", "profile", "email", "offline_access", "User.Read", "Mail.Send")


class OAuthFlowError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class OAuthIdentity:
    provider_account_id: str
    email_address: str
    display_name: str | None


class EmailOAuthService:
    def __init__(self, db: Session, client: httpx.Client | None = None) -> None:
        self.db = db
        self.client = client or httpx.Client(timeout=20)

    @staticmethod
    def _digest(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()

    @staticmethod
    def _provider(value: str) -> str:
        try:
            return normalize_email_provider(value)
        except OAuthConfigurationError:
            return value.upper()

    def authorization_url(self, provider: str, redirect_after_success: str = "/settings?tab=notifications-email") -> str:
        provider = self._provider(provider)
        if provider not in {EmailProviderType.GMAIL, EmailProviderType.MICROSOFT}:
            raise OAuthFlowError("Penyedia email tidak didukung.")
        try:
            configuration = resolve_email_oauth_config(provider, self.db)
        except OAuthConfigurationError as exc:
            raise OAuthFlowError(str(exc)) from exc
        if not configuration.configured:
            provider_name = "Google" if provider == EmailProviderType.GMAIL else "Microsoft"
            raise OAuthFlowError(
                f"{provider_name} OAuth belum dikonfigurasi. Buka Provider Setup dan simpan konfigurasi terlebih dahulu."
            )
        if not redirect_after_success.startswith("/") or redirect_after_success.startswith("//"):
            redirect_after_success = "/settings?tab=notifications-email"
        raw_state = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        self.db.add(
            NotificationOAuthState(
                state_digest=self._digest(raw_state),
                provider=provider,
                redirect_after_success=redirect_after_success,
                created_at=now,
                expires_at=now + timedelta(seconds=settings.oauth_state_ttl_seconds),
            )
        )
        self.db.commit()
        if provider == EmailProviderType.GMAIL:
            query = urlencode(
                {
                    "client_id": configuration.client_id,
                    "redirect_uri": configuration.redirect_uri,
                    "response_type": "code",
                    "scope": " ".join(GOOGLE_SCOPES),
                    "access_type": "offline",
                    "prompt": "consent",
                    "include_granted_scopes": "true",
                    "state": raw_state,
                }
            )
            return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"
        query = urlencode(
            {
                "client_id": configuration.client_id,
                "redirect_uri": configuration.redirect_uri,
                "response_type": "code",
                "response_mode": "query",
                "scope": " ".join(MICROSOFT_SCOPES),
                "state": raw_state,
            }
        )
        return f"https://login.microsoftonline.com/{configuration.tenant or 'common'}/oauth2/v2.0/authorize?{query}"

    def consume_state(self, provider: str, raw_state: str) -> NotificationOAuthState:
        now = datetime.now(timezone.utc)
        state = self.db.scalar(
            select(NotificationOAuthState)
            .where(
                NotificationOAuthState.state_digest == self._digest(raw_state),
                NotificationOAuthState.provider == self._provider(provider),
                NotificationOAuthState.consumed_at.is_(None),
                NotificationOAuthState.expires_at > now,
            )
            .with_for_update()
        )
        if not state:
            self.db.rollback()
            raise OAuthFlowError("Sesi koneksi email tidak valid, kedaluwarsa, atau sudah digunakan.")
        state.consumed_at = now
        self.db.commit()
        return state

    def complete(self, provider: str, code: str, state: str) -> tuple[EmailAccount, str]:
        provider = self._provider(provider)
        handshake = self.consume_state(provider, state)
        try:
            configuration = resolve_email_oauth_config(provider, self.db)
            if not configuration.configured:
                raise OAuthFlowError("Konfigurasi OAuth provider tidak lengkap. Simpan ulang melalui Provider Setup.")
            if provider == EmailProviderType.GMAIL:
                token, identity, scopes = self._complete_google(code, configuration)
            elif provider == EmailProviderType.MICROSOFT:
                token, identity, scopes = self._complete_microsoft(code, configuration)
            else:
                raise OAuthFlowError("Penyedia email tidak didukung.")
        except OAuthConfigurationError as exc:
            raise OAuthFlowError(str(exc)) from exc
        except httpx.HTTPError as exc:
            raise OAuthFlowError("Penyedia OAuth tidak dapat dihubungi. Coba lagi.") from exc
        account = self.db.scalar(
            select(EmailAccount).where(
                EmailAccount.provider == provider,
                EmailAccount.oauth_provider_account_id == identity.provider_account_id,
            )
        )
        if not account:
            default_count = self.db.scalar(
                select(func.count(EmailAccount.id)).where(
                    EmailAccount.enabled.is_(True), EmailAccount.is_default.is_(True)
                )
            ) or 0
            account = EmailAccount(
                account_name=f"{identity.display_name or identity.email_address} ({'Gmail' if provider == EmailProviderType.GMAIL else 'Microsoft'})",
                channel=NotificationChannel.EMAIL,
                provider=provider,
                email_address=identity.email_address,
                display_name=identity.display_name,
                is_default=default_count == 0,
                oauth_provider_account_id=identity.provider_account_id,
                oauth_access_token_encrypted=email_credentials.encrypt(token["access_token"]),
                oauth_scope=token.get("scope") or " ".join(scopes),
            )
            self.db.add(account)
        else:
            account.email_address = identity.email_address
            account.display_name = identity.display_name
            account.enabled = True
            account.oauth_access_token_encrypted = email_credentials.encrypt(token["access_token"])
            account.oauth_scope = token.get("scope") or " ".join(scopes)
        if token.get("refresh_token"):
            account.oauth_refresh_token_encrypted = email_credentials.encrypt(token["refresh_token"])
        account.oauth_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))
        account.connection_status = ConnectionStatus.CONNECTED
        account.connected_at = datetime.now(timezone.utc)
        account.last_error = None
        self.db.commit()
        self.db.refresh(account)
        return account, handshake.redirect_after_success

    def _complete_google(
        self, code: str, configuration: ResolvedEmailOAuthConfig
    ) -> tuple[dict, OAuthIdentity, tuple[str, ...]]:
        response = self.client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": configuration.client_id,
                "client_secret": configuration.client_secret,
                "redirect_uri": configuration.redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code >= 400:
            raise OAuthFlowError("Google menolak koneksi akun. Mulai ulang proses koneksi.")
        token = response.json()
        identity_response = self.client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        if identity_response.status_code >= 400:
            raise OAuthFlowError("Identitas akun Google tidak dapat diverifikasi.")
        identity = identity_response.json()
        if not identity.get("sub") or not identity.get("email") or not identity.get("email_verified", False):
            raise OAuthFlowError("Alamat email Google tidak terverifikasi.")
        return token, OAuthIdentity(identity["sub"], identity["email"].lower(), identity.get("name")), GOOGLE_SCOPES

    def _complete_microsoft(
        self, code: str, configuration: ResolvedEmailOAuthConfig
    ) -> tuple[dict, OAuthIdentity, tuple[str, ...]]:
        token_response = self.client.post(
            f"https://login.microsoftonline.com/{configuration.tenant or 'common'}/oauth2/v2.0/token",
            data={
                "code": code,
                "client_id": configuration.client_id,
                "client_secret": configuration.client_secret,
                "redirect_uri": configuration.redirect_uri,
                "grant_type": "authorization_code",
                "scope": " ".join(MICROSOFT_SCOPES),
            },
        )
        if token_response.status_code >= 400:
            raise OAuthFlowError("Microsoft menolak koneksi akun. Mulai ulang proses koneksi.")
        token = token_response.json()
        identity_response = self.client.get(
            "https://graph.microsoft.com/v1.0/me?$select=id,displayName,mail,userPrincipalName",
            headers={"Authorization": f"Bearer {token['access_token']}"},
        )
        if identity_response.status_code >= 400:
            raise OAuthFlowError("Identitas akun Microsoft tidak dapat diverifikasi.")
        identity = identity_response.json()
        email = identity.get("mail") or identity.get("userPrincipalName")
        if not identity.get("id") or not email:
            raise OAuthFlowError("Microsoft tidak mengembalikan identitas email yang valid.")
        return token, OAuthIdentity(identity["id"], email.lower(), identity.get("displayName")), MICROSOFT_SCOPES
