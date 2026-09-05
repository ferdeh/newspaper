from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


class FakeGeocoder:
    def geocode(self, query):
        return object()


class FakeTask:
    id = "geo-task-123"


def test_admin_can_validate_and_save_google_maps_key_without_secret_echo(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "runtime_secret_dir", str(tmp_path))
    monkeypatch.setattr(settings, "google_maps_api_key", None)
    monkeypatch.setattr("app.api.routes.GoogleGeocodingProvider", lambda api_key: FakeGeocoder())
    monkeypatch.setattr("app.api.routes.celery_app.send_task", lambda *args, **kwargs: FakeTask())
    api_key = "AIza-unit-test-key-that-must-not-be-echoed"

    with TestClient(app) as client:
        response = client.put(
            "/api/admin/provider-secrets/google-maps",
            headers={"X-Internal-Token": settings.internal_api_token.get_secret_value()},
            json={"api_key": api_key},
        )

    assert response.status_code == 200
    assert response.json() == {
        "credential": "configured",
        "geocoding": "validated",
        "enrichment_task_id": "geo-task-123",
    }
    assert api_key not in response.text
    assert (tmp_path / "google_maps_api_key").read_text() == api_key
