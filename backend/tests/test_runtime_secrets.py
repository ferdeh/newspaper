import stat

from app.config import settings
from app.services.secrets import (
    GOOGLE_MAPS_SECRET_NAME,
    delete_runtime_secret,
    get_google_maps_api_key,
    get_google_maps_api_key_source,
    read_runtime_secret,
    write_runtime_secret,
)


def test_runtime_secret_is_persistent_masked_file(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_secret_dir", str(tmp_path))
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    secret_value = "AIza-unit-test-key-that-is-never-returned"

    write_runtime_secret(GOOGLE_MAPS_SECRET_NAME, secret_value)

    secret_path = tmp_path / GOOGLE_MAPS_SECRET_NAME
    assert read_runtime_secret(GOOGLE_MAPS_SECRET_NAME) == secret_value
    assert get_google_maps_api_key() == secret_value
    assert get_google_maps_api_key_source() == "runtime"
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700
    assert delete_runtime_secret(GOOGLE_MAPS_SECRET_NAME) is True
    assert get_google_maps_api_key() is None
