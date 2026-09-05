from __future__ import annotations

import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.config import settings

GOOGLE_MAPS_SECRET_NAME = "google_maps_api_key"


def _secret_path(name: str) -> Path:
    return Path(settings.runtime_secret_dir) / name


def read_runtime_secret(name: str) -> str | None:
    path = _secret_path(name)
    if not path.is_file() or path.is_symlink():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def write_runtime_secret(name: str, value: str) -> None:
    secret_dir = Path(settings.runtime_secret_dir)
    secret_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    secret_dir.chmod(0o700)
    with NamedTemporaryFile("w", encoding="utf-8", dir=secret_dir, delete=False) as temporary:
        temporary.write(value.strip())
        temporary.flush()
        os.fchmod(temporary.fileno(), 0o600)
        temporary_path = Path(temporary.name)
    temporary_path.replace(_secret_path(name))


def delete_runtime_secret(name: str) -> bool:
    path = _secret_path(name)
    if not path.is_file() or path.is_symlink():
        return False
    path.unlink()
    return True


def get_google_maps_api_key() -> str | None:
    runtime_value = read_runtime_secret(GOOGLE_MAPS_SECRET_NAME)
    if runtime_value:
        return runtime_value
    return settings.google_maps_api_key.get_secret_value() if settings.google_maps_api_key else None


def get_google_maps_api_key_source() -> str | None:
    if read_runtime_secret(GOOGLE_MAPS_SECRET_NAME):
        return "runtime"
    if settings.google_maps_api_key:
        return "environment"
    return None
