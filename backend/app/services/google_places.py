from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any, Callable

import httpx

from app.config import settings
from app.services.secrets import get_google_maps_api_key

logger = logging.getLogger("fuel-intelligence.tbbm.google-places")

GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.googleMapsUri",
    "places.types",
    "places.primaryType",
    "nextPageToken",
])
TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}


class GooglePlacesError(RuntimeError):
    pass


class GooglePlacesConfigurationError(GooglePlacesError):
    pass


class GooglePlacesAuthenticationError(GooglePlacesError):
    pass


class GooglePlacesTextSearchService:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        timeout_seconds: int | None = None,
        maximum_retry: int | None = None,
        request_delay_ms: int | None = None,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.api_key = api_key or get_google_maps_api_key()
        self.timeout_seconds = timeout_seconds or settings.google_places_timeout_seconds
        self.maximum_retry = settings.google_places_max_retry if maximum_retry is None else maximum_retry
        self.request_delay_ms = settings.google_places_request_delay_ms if request_delay_ms is None else request_delay_ms
        self.client = client or httpx.Client()
        self.sleeper = sleeper

    def _request(self, query: str, language_code: str, page_token: str | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise GooglePlacesConfigurationError("Google Places API key belum dikonfigurasi.")
        payload: dict[str, Any] = {"textQuery": query, "pageSize": 20, "languageCode": language_code}
        if page_token:
            payload["pageToken"] = page_token
        for attempt in range(self.maximum_retry + 1):
            if self.request_delay_ms:
                self.sleeper(self.request_delay_ms / 1000)
            try:
                response = self.client.post(
                    GOOGLE_PLACES_TEXT_SEARCH_URL,
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": self.api_key,
                        "X-Goog-FieldMask": GOOGLE_PLACES_FIELD_MASK,
                    },
                    json=payload,
                    timeout=self.timeout_seconds,
                )
                if response.status_code in {401, 403}:
                    raise GooglePlacesAuthenticationError(
                        "Google Places API menolak request. Periksa API key, API restriction, dan billing."
                    )
                if response.status_code in TRANSIENT_STATUS_CODES and attempt < self.maximum_retry:
                    delay = min(2**attempt, 8)
                    logger.warning("google_places.retry", extra={"query": query, "attempt": attempt + 1, "status_code": response.status_code})
                    self.sleeper(delay)
                    continue
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise GooglePlacesError("Google Places API returned an unexpected response")
                return result
            except GooglePlacesAuthenticationError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.maximum_retry:
                    raise GooglePlacesError(f"Google Places request failed after retries: {type(exc).__name__}") from exc
                delay = min(2**attempt, 8)
                logger.warning("google_places.retry", extra={"query": query, "attempt": attempt + 1, "error_type": type(exc).__name__})
                self.sleeper(delay)
            except httpx.HTTPStatusError as exc:
                raise GooglePlacesError(f"Google Places request failed with HTTP {exc.response.status_code}") from exc
        raise GooglePlacesError("Google Places request failed")

    def iter_pages(self, query: str, language_code: str = "id", max_pages: int = 20) -> Iterator[tuple[int, list[dict[str, Any]]]]:
        page_token: str | None = None
        for page_number in range(1, max_pages + 1):
            payload = self._request(query, language_code, page_token)
            places = payload.get("places", [])
            if not isinstance(places, list):
                raise GooglePlacesError("Google Places response contains invalid places data")
            logger.info("google_places.page", extra={"query": query, "page": page_number, "result_count": len(places)})
            yield page_number, [item for item in places if isinstance(item, dict)]
            next_token = payload.get("nextPageToken")
            if not isinstance(next_token, str) or not next_token:
                break
            page_token = next_token

    def search_all_pages(self, query: str, language_code: str = "id") -> list[dict[str, Any]]:
        return [place for _, places in self.iter_pages(query, language_code) for place in places]

    def test_connection(self) -> dict[str, Any]:
        payload = self._request("TBBM Pertamina Jakarta", "id")
        return {"status": "connected", "result_count": len(payload.get("places", []))}
