import httpx
import pytest

from app.services.google_places import GOOGLE_PLACES_FIELD_MASK, GooglePlacesError, GooglePlacesTextSearchService
from app.services.tbbm_discovery import (
    classify_terminal,
    false_positive_reason,
    haversine_distance_meters,
    normalize_google_place,
    normalize_terminal_name,
    similarity,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.request = httpx.Request("POST", "https://places.googleapis.com/v1/places:searchText")

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("failed", request=self.request, response=httpx.Response(self.status_code, request=self.request))


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def google_place(name="PT. Pertamina Fuel Terminal Balongan", place_id="place-123"):
    return {
        "id": place_id,
        "displayName": {"text": name, "languageCode": "id"},
        "formattedAddress": "Balongan, Indramayu, Jawa Barat",
        "location": {"latitude": -6.351, "longitude": 108.394},
        "googleMapsUri": "https://maps.google.com/?cid=123",
        "types": ["establishment"],
        "primaryType": "establishment",
    }


def test_google_response_normalization_preserves_original_and_maps_fields():
    result = normalize_google_place(google_place())
    assert result.place_name == "PT. Pertamina Fuel Terminal Balongan"
    assert result.normalized_name == "pertamina fuel terminal balongan"
    assert result.google_place_id == "place-123"
    assert result.latitude == -6.351
    assert result.longitude == 108.394
    assert result.terminal_type == "FUEL_TERMINAL"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Pertamina Integrated Terminal Jakarta", "INTEGRATED_TERMINAL"),
        ("Fuel Terminal Balongan", "FUEL_TERMINAL"),
        ("TBBM X", "TBBM"),
        ("Depot BBM Y", "DEPOT_BBM"),
        ("TLPG Z", "TLPG"),
        ("Pertamina Regional Office", "OTHER"),
    ],
)
def test_deterministic_terminal_classification(name, expected):
    assert classify_terminal(normalize_terminal_name(name)) == expected


def test_false_positive_filter_is_conservative_for_retail_and_unknown_results():
    assert false_positive_reason("spbu pertamina 31 123", ["gas_station"], "OTHER")
    assert false_positive_reason("gudang pertamina", ["establishment"], "OTHER") is None


def test_geographic_duplicate_threshold_and_name_similarity():
    distance = haversine_distance_meters(-6.351, 108.394, -6.3502, 108.3945)
    score = similarity("Fuel Terminal Balongan", "Pertamina Fuel Terminal Balongan")
    assert distance < 120
    assert score >= 0.80
    assert haversine_distance_meters(-6.351, 108.394, -6.37, 108.394) > 2_000


def test_google_places_new_pagination_keeps_original_query_and_minimal_field_mask():
    client = FakeClient([
        FakeResponse({"places": [google_place()], "nextPageToken": "page-two"}),
        FakeResponse({"places": [google_place("TBBM Balongan 2", "place-456")]}),
    ])
    service = GooglePlacesTextSearchService("secret-test-key", client=client, request_delay_ms=0, sleeper=lambda _: None)
    results = service.search_all_pages("Fuel Terminal Pertamina Jawa Barat")
    assert len(results) == 2
    assert [call[1]["json"]["textQuery"] for call in client.calls] == [
        "Fuel Terminal Pertamina Jawa Barat", "Fuel Terminal Pertamina Jawa Barat",
    ]
    assert client.calls[1][1]["json"]["pageToken"] == "page-two"
    assert client.calls[0][1]["headers"]["X-Goog-FieldMask"] == GOOGLE_PLACES_FIELD_MASK
    assert "*" not in GOOGLE_PLACES_FIELD_MASK
    assert all("secret-test-key" not in str(call[1]["json"]) for call in client.calls)


def test_google_places_retries_only_transient_statuses():
    client = FakeClient([FakeResponse({}, 503), FakeResponse({"places": []})])
    service = GooglePlacesTextSearchService(
        "secret-test-key", client=client, maximum_retry=3, request_delay_ms=0, sleeper=lambda _: None,
    )
    assert service.search_all_pages("TBBM Pertamina Aceh") == []
    assert len(client.calls) == 2

    invalid_client = FakeClient([FakeResponse({}, 400)])
    invalid_service = GooglePlacesTextSearchService(
        "secret-test-key", client=invalid_client, maximum_retry=3, request_delay_ms=0, sleeper=lambda _: None,
    )
    with pytest.raises(GooglePlacesError):
        invalid_service.search_all_pages("invalid")
    assert len(invalid_client.calls) == 1
