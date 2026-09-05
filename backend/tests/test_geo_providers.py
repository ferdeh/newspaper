from app.services.providers import GoogleGeocodingProvider


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_google_geocoder_is_country_biased_and_returns_confidence(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({
            "status": "OK",
            "results": [{
                "formatted_address": "Mimika, Papua Tengah, Indonesia",
                "place_id": "place-123",
                "geometry": {"location": {"lat": -4.5468, "lng": 136.8837}, "location_type": "APPROXIMATE"},
            }],
        })

    monkeypatch.setattr("app.services.providers.httpx.get", fake_get)
    result = GoogleGeocodingProvider("test-key").geocode("Mimika, Indonesia")

    assert result is not None
    assert result.place_id == "place-123"
    assert result.confidence == 0.65
    assert captured["params"]["components"] == "country:ID"
    assert captured["params"]["region"] == "id"
    assert captured["params"]["key"] == "test-key"
