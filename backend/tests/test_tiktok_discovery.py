import stat
from types import SimpleNamespace

import httpx
from pydantic import SecretStr

from app.api import tiktok_discovery as tiktok_api
from app.collectors.tiktok import ScrapeCreatorsTikTokProvider, TikTokSearchParams
from app.config import settings
from app.models import TikTokSettings
from app.services.encryption import decrypt_secret, encrypt_secret, mask_secret
from app.services.tiktok_discovery import clean_webvtt, credit_guard, fast_relevance_screen


def test_scrapecreators_search_contract_and_trimmed_response(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "success": True,
                "credits_charged": 1,
                "credits_remaining": 99,
                "cursor": 12,
                "search_item_list": [{
                    "aweme_id": "123",
                    "desc": "Pertalite habis di SPBU Pekanbaru #pertalite",
                    "create_time": 1_700_000_000,
                    "author": {"uid": "author-1", "unique_id": "operator", "nickname": "Operator"},
                    "statistics": {"play_count": 50, "digg_count": 4, "comment_count": 3, "share_count": 2},
                    "video": {"duration": 12000, "cover": {"url_list": ["https://image.example/cover.jpg"]}},
                    "url": "https://www.tiktok.com/@operator/video/123",
                }],
            },
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = ScrapeCreatorsTikTokProvider("secret-provider-key")
    result = provider.search_videos(
        TikTokSearchParams(query="pertalite habis", region="ID", date_posted="this-week", sort_by="date-posted")
    )

    assert captured["url"].endswith("/v1/tiktok/search/keyword")
    assert captured["headers"]["x-api-key"] == "secret-provider-key"
    assert captured["params"]["query"] == "pertalite habis"
    assert captured["params"]["trim"] == "true"
    assert result.next_cursor == 12
    assert result.credits_used == 1
    assert result.videos[0].video_id == "123"
    assert result.videos[0].duration_seconds == 12
    assert result.videos[0].hashtags == ["pertalite"]


def test_transcript_defaults_to_no_ai_fallback(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={"success": True, "credits_charged": 1, "transcript": "WEBVTT\n\n00:00.000 --> 00:01.000\nBBM habis"},
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = ScrapeCreatorsTikTokProvider("secret-provider-key").get_transcript("https://www.tiktok.com/@x/video/1")

    assert captured["params"]["use_ai_as_fallback"] == "false"
    assert result.available is True
    assert clean_webvtt(result.transcript_raw) == "BBM habis"


def test_tiktok_secret_is_encrypted_and_masked(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "app_encryption_key", None)
    monkeypatch.setattr(settings, "runtime_secret_dir", str(tmp_path))
    monkeypatch.setattr(settings, "internal_api_token", SecretStr("first-runtime-token"))
    encrypted = encrypt_secret("scrape-key-abcdefgh")
    monkeypatch.setattr(settings, "internal_api_token", SecretStr("rotated-runtime-token"))

    assert "scrape-key-abcdefgh" not in encrypted
    assert decrypt_secret(encrypted) == "scrape-key-abcdefgh"
    assert mask_secret("scrape-key-abcdefgh") == "••••••••efgh"
    assert stat.S_IMODE((tmp_path / "app_encryption_key").stat().st_mode) == 0o600


def test_settings_response_reports_unreadable_credential_without_500(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "app_encryption_key", None)
    monkeypatch.setattr(settings, "runtime_secret_dir", str(tmp_path))
    monkeypatch.setattr(
        tiktok_api,
        "usage_totals",
        lambda _db: {"today": {"requests": 0, "total_credits": 0}, "month": {"total_credits": 0}},
    )
    row = TikTokSettings(api_key_encrypted="not-valid-fernet-ciphertext", enabled=True)

    response = tiktok_api._settings_response(SimpleNamespace(), row)

    assert response["apiKeyConfigured"] is False
    assert response["enabled"] is False
    assert response["health"]["status"] == "CREDENTIAL_ERROR"
    assert "simpan kembali" in response["credentialError"]


def test_fast_screening_and_credit_guard(monkeypatch):
    score, category = fast_relevance_screen("mobil tangki terbakar di Pekanbaru")
    assert score >= 0.9
    assert category == "TANKER_FIRE"

    row = TikTokSettings(monthly_credit_limit=100, warning_threshold_percent=80, critical_threshold_percent=95)
    monkeypatch.setattr(
        "app.services.tiktok_discovery.usage_totals",
        lambda _db: {
            "today": {"total_credits": 0},
            "month": {"total_credits": 96},
        },
    )
    assert credit_guard(SimpleNamespace(), row, "LOW") == (False, "CREDIT_CRITICAL_LOW_DEFERRED")
    assert credit_guard(SimpleNamespace(), row, "HIGH") == (True, "NORMAL")
