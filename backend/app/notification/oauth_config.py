from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import EmailOAuthProviderConfig
from app.notification.credentials import EmailCredentialError, email_credentials
from app.notification.enums import EmailProviderType


class OAuthConfigurationError(RuntimeError):
    pass


def normalize_email_provider(value: EmailProviderType | str) -> str:
    normalized = str(value).upper()
    mapped = {"GOOGLE": EmailProviderType.GMAIL, "OUTLOOK": EmailProviderType.MICROSOFT}.get(
        normalized, normalized
    )
    if mapped not in {EmailProviderType.GMAIL, EmailProviderType.MICROSOFT}:
        raise OAuthConfigurationError("Penyedia email tidak didukung.")
    return str(mapped)


@dataclass(frozen=True, slots=True)
class ResolvedEmailOAuthConfig:
    provider: str
    client_id: str | None
    client_secret: str | None
    tenant: str | None
    redirect_uri: str | None
    source: str | None

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)


def _environment_config(provider: str) -> ResolvedEmailOAuthConfig:
    if provider == EmailProviderType.GMAIL:
        return ResolvedEmailOAuthConfig(
            provider=provider,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret.get_secret_value() if settings.google_client_secret else None,
            tenant=None,
            redirect_uri=settings.google_oauth_redirect_uri,
            source="environment" if settings.google_client_id or settings.google_client_secret else None,
        )
    return ResolvedEmailOAuthConfig(
        provider=provider,
        client_id=settings.microsoft_client_id,
        client_secret=settings.microsoft_client_secret.get_secret_value() if settings.microsoft_client_secret else None,
        tenant=settings.microsoft_tenant or "common",
        redirect_uri=settings.microsoft_oauth_redirect_uri,
        source="environment" if settings.microsoft_client_id or settings.microsoft_client_secret else None,
    )


def resolve_email_oauth_config(
    provider: EmailProviderType | str,
    db: Session | None = None,
) -> ResolvedEmailOAuthConfig:
    normalized = normalize_email_provider(provider)
    environment = _environment_config(normalized)
    if db is None:
        return environment
    row = db.scalar(
        select(EmailOAuthProviderConfig).where(EmailOAuthProviderConfig.provider == normalized)
    )
    if not row:
        return environment
    secret = environment.client_secret
    if row.client_secret_encrypted:
        try:
            secret = email_credentials.decrypt(row.client_secret_encrypted)
        except EmailCredentialError as exc:
            raise OAuthConfigurationError(
                "Client secret OAuth tersimpan tidak dapat didekripsi. Simpan ulang melalui UI."
            ) from exc
    source = "database" if row.client_secret_encrypted or not environment.client_secret else "database + environment"
    return ResolvedEmailOAuthConfig(
        provider=normalized,
        client_id=row.client_id,
        client_secret=secret,
        tenant=(row.tenant or "common") if normalized == EmailProviderType.MICROSOFT else None,
        redirect_uri=row.redirect_uri,
        source=source,
    )
