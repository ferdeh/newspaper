from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class EmailCredentialError(RuntimeError):
    pass


class EmailCredentialService:
    """The only component allowed to encrypt or decrypt provider OAuth tokens."""

    def _fernet(self) -> Fernet:
        configured = (
            settings.email_token_encryption_key.get_secret_value()
            if settings.email_token_encryption_key
            else settings.app_encryption_key.get_secret_value()
            if settings.app_encryption_key
            else None
        )
        if not configured:
            if settings.app_env.lower() in {"production", "prod"}:
                raise EmailCredentialError("EMAIL_TOKEN_ENCRYPTION_KEY must be configured in production")
            configured = settings.internal_api_token.get_secret_value()
        try:
            return Fernet(configured.encode())
        except (TypeError, ValueError):
            return Fernet(base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest()))

    def encrypt(self, token: str) -> str:
        if not token:
            raise EmailCredentialError("OAuth token cannot be empty")
        return self._fernet().encrypt(token.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet().decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise EmailCredentialError("Stored email credential cannot be decrypted") from exc


email_credentials = EmailCredentialService()
