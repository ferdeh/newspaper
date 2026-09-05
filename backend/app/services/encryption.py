from __future__ import annotations

import base64
import fcntl
import hashlib
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings
from app.services.secrets import read_runtime_secret, write_runtime_secret

APP_ENCRYPTION_SECRET_NAME = "app_encryption_key"


class SecretDecryptionError(RuntimeError):
    pass


def _persistent_development_key() -> str:
    """Create one host-volume key so container recreation cannot invalidate ciphertext."""
    secret_dir = Path(settings.runtime_secret_dir)
    secret_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_dir.chmod(0o700)
    lock_path = secret_dir / f".{APP_ENCRYPTION_SECRET_NAME}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        os.fchmod(lock_file.fileno(), 0o600)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        configured = read_runtime_secret(APP_ENCRYPTION_SECRET_NAME)
        if not configured:
            configured = Fernet.generate_key().decode()
            write_runtime_secret(APP_ENCRYPTION_SECRET_NAME, configured)
        return configured


def _fernet() -> Fernet:
    configured = settings.app_encryption_key.get_secret_value() if settings.app_encryption_key else None
    if not configured:
        if settings.app_env.lower() in {"production", "prod"}:
            raise RuntimeError("APP_ENCRYPTION_KEY must be configured in production")
        configured = _persistent_development_key()
    try:
        return Fernet(configured.encode())
    except (TypeError, ValueError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(configured.encode()).digest())
        return Fernet(derived)


def encrypt_secret(value: str) -> str:
    return _fernet().encrypt(value.strip().encode()).decode()


def decrypt_secret(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as exc:
        raise SecretDecryptionError("Stored credential cannot be decrypted with APP_ENCRYPTION_KEY") from exc


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    return f"••••••••{value[-4:]}"
