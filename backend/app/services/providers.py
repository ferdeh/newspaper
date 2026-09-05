from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

import httpx

from app.config import settings
from app.schemas import StructuredEvent
from app.services.secrets import get_google_maps_api_key


class LLMProvider(ABC):
    @abstractmethod
    def extract(self, title: str, content: str, location_hint: str | None = None) -> StructuredEvent: ...


class MockLLMProvider(LLMProvider):
    def extract(self, title: str, content: str, location_hint: str | None = None) -> StructuredEvent:
        from app.services.intelligence import classify_text

        result = classify_text(f"{title} {content}", location_hint)
        return StructuredEvent.model_validate(result)


class ConfiguredLLMProvider(LLMProvider):
    """Safe extension boundary for OpenAI, Gemini, Claude, or a local model."""

    def __init__(self, name: str):
        self.name = name

    def extract(self, title: str, content: str, location_hint: str | None = None) -> StructuredEvent:
        raise RuntimeError(f"LLM provider '{self.name}' requires a deployment-specific client")


class EmbeddingProvider(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]: ...


class DeterministicEmbeddingProvider(EmbeddingProvider):
    dimensions = 64

    def embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimensions
        tokens = text.lower().split()
        for token in tokens:
            digest = sha256(token.encode()).digest()
            index = int.from_bytes(digest[:2], "big") % self.dimensions
            values[index] += 1.0 if digest[2] % 2 else -1.0
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        return [round(value / norm, 6) for value in values]


@dataclass(slots=True)
class GeocodingResult:
    latitude: float
    longitude: float
    confidence: float
    normalized_name: str
    place_id: str | None = None


class GeocodingProvider(ABC):
    @abstractmethod
    def geocode(self, query: str) -> GeocodingResult | None: ...


class MockGeocodingProvider(GeocodingProvider):
    def geocode(self, query: str) -> GeocodingResult | None:
        return None


class GoogleGeocodingProvider(GeocodingProvider):
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    def geocode(self, query: str) -> GeocodingResult | None:
        api_key = self.api_key or get_google_maps_api_key()
        if not api_key:
            return None
        response = httpx.get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={
                "address": query,
                "components": "country:ID",
                "region": "id",
                "language": "id",
                "key": api_key,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        status = payload.get("status")
        if status == "ZERO_RESULTS":
            return None
        if status != "OK":
            raise RuntimeError(f"Google Geocoding API returned {status}: {payload.get('error_message', 'unknown error')}")
        results = payload.get("results", [])
        if not results:
            return None
        item = results[0]
        point = item["geometry"]["location"]
        confidence_by_type = {
            "ROOFTOP": 0.95,
            "RANGE_INTERPOLATED": 0.85,
            "GEOMETRIC_CENTER": 0.75,
            "APPROXIMATE": 0.65,
        }
        confidence = confidence_by_type.get(item["geometry"].get("location_type"), 0.65)
        if item.get("partial_match"):
            confidence = max(0.5, confidence - 0.1)
        return GeocodingResult(
            point["lat"], point["lng"], confidence, item["formatted_address"], item.get("place_id")
        )


@dataclass(slots=True)
class DeliveryResult:
    status: str
    provider_message_id: str | None = None
    detail: dict[str, Any] | None = None


class WhatsAppProvider(ABC):
    @abstractmethod
    def send(self, recipient: str, message: str) -> DeliveryResult: ...


class MockWhatsAppProvider(WhatsAppProvider):
    def send(self, recipient: str, message: str) -> DeliveryResult:
        digest = sha256(f"{recipient}:{message}".encode()).hexdigest()[:16]
        return DeliveryResult("MOCK_SENT", f"mock-{digest}")


class MetaWhatsAppCloudProvider(WhatsAppProvider):
    def send(self, recipient: str, message: str) -> DeliveryResult:
        if not settings.whatsapp_access_token or not settings.whatsapp_phone_number_id:
            raise RuntimeError("Meta WhatsApp Cloud credentials are incomplete")
        endpoint = f"https://graph.facebook.com/v22.0/{settings.whatsapp_phone_number_id}/messages"
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.whatsapp_access_token.get_secret_value()}"},
            json={"messaging_product": "whatsapp", "to": recipient, "type": "text", "text": {"body": message}},
            timeout=20,
        )
        response.raise_for_status()
        message_id = response.json().get("messages", [{}])[0].get("id")
        return DeliveryResult("SENT", message_id)


def get_llm_provider() -> LLMProvider:
    return MockLLMProvider() if settings.llm_provider == "mock" else ConfiguredLLMProvider(settings.llm_provider)


def get_geocoding_provider() -> GeocodingProvider:
    return GoogleGeocodingProvider() if settings.geocoding_provider == "google" else MockGeocodingProvider()


def get_whatsapp_provider() -> WhatsAppProvider:
    return MetaWhatsAppCloudProvider() if settings.whatsapp_provider == "meta" else MockWhatsAppProvider()
