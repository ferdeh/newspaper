from datetime import datetime, timezone

import httpx

from app.collectors.news.adapters import (
    GenericHTMLAdapter,
    NewsCandidate,
    RSSNewsAdapter,
    canonicalize_url,
    is_site_root_url,
    matching_news_keywords,
)
from app.services.pipeline import content_digest


def test_news_url_canonicalization_removes_tracking_and_fragment():
    assert canonicalize_url("HTTPS://News.Example/id/1/?utm_source=x&keep=yes#story") == "https://news.example/id/1?keep=yes"
    assert is_site_root_url("https://news.example/") is True
    assert is_site_root_url("https://news.example/berita/1") is False


def test_news_content_digest_is_deterministic_for_normalized_text():
    assert content_digest("Antrean   BBM!") == content_digest("antrean bbm")


def test_tiktok_identity_is_video_id_then_url_contract():
    first = {"video_id": "123", "url": "https://tiktok.example/123"}
    duplicate = {"video_id": "123", "url": "https://tiktok.example/copy"}
    assert first["video_id"] == duplicate["video_id"]


def test_rss_adapter_parses_public_feed(monkeypatch):
    xml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel><title>Live test</title><item>
    <title>Antrean BBM di Kupang</title><link>https://news.example/live/1?utm_source=rss</link>
    <description><![CDATA[<p>Distribusi BBM sedang dipantau.</p>]]></description>
    <pubDate>Wed, 02 Sep 2026 05:00:00 GMT</pubDate>
    </item></channel></rss>"""

    def fake_get(*args, **kwargs):
        return httpx.Response(200, content=xml, request=httpx.Request("GET", "https://news.example/feed.xml"))

    monkeypatch.setattr("app.collectors.news.adapters.httpx.get", fake_get)
    candidates = RSSNewsAdapter().fetch("https://news.example/feed.xml")

    assert len(candidates) == 1
    assert candidates[0].title == "Antrean BBM di Kupang"
    assert candidates[0].content == "Distribusi BBM sedang dipantau."
    assert candidates[0].published_at.tzinfo == timezone.utc


def test_news_keyword_matching_is_case_insensitive_and_phrase_aware():
    candidate = NewsCandidate(
        url="https://news.example/story",
        title="Mobil Tangki BBM Terguling di Kupang",
        content="Tetapi pasokan tetap aman.",
        published_at=datetime.now(timezone.utc),
    )

    assert matching_news_keywords(candidate, ["mobil tangki bbm", "api", "antrean SPBU"]) == ["mobil tangki bbm"]


def test_html_adapter_rejects_homepage_without_fetching(monkeypatch):
    def unexpected_get(*args, **kwargs):
        raise AssertionError("homepage must not be fetched as an article")

    monkeypatch.setattr("app.collectors.news.adapters.httpx.get", unexpected_get)
    assert GenericHTMLAdapter().fetch("https://news.example/") == []


def test_html_adapter_accepts_an_article_page(monkeypatch):
    html = b'''<html><head><meta property="og:type" content="article"><meta property="og:title" content="BBM Langka di Riau"><link rel="canonical" href="/berita/bbm-langka"></head><body><main><p>Warga melaporkan BBM langka di sejumlah SPBU di Riau.</p><p>Pasokan Pertalite sedang dalam perjalanan dan akan segera tiba kembali.</p><p>Petugas meminta masyarakat tidak melakukan pembelian berlebihan.</p></main></body></html>'''

    def fake_get(*args, **kwargs):
        return httpx.Response(200, content=html, request=httpx.Request("GET", "https://news.example/berita/1"))

    monkeypatch.setattr("app.collectors.news.adapters.httpx.get", fake_get)
    candidates = GenericHTMLAdapter().fetch("https://news.example/berita/1")

    assert len(candidates) == 1
    assert candidates[0].title == "BBM Langka di Riau"
    assert candidates[0].url == "https://news.example/berita/bbm-langka"
