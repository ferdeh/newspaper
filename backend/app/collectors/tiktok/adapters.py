from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx


@dataclass(slots=True)
class TikTokSearchParams:
    query: str
    region: str | None = None
    date_posted: str | None = None
    sort_by: str | None = None
    cursor: str | int | float | None = None
    trim: bool = True


@dataclass(slots=True)
class TikTokCandidate:
    video_id: str
    url: str
    username: str
    caption: str
    published_at: datetime | None
    author_id: str | None = None
    creator_name: str | None = None
    hashtags: list[str] = field(default_factory=list)
    raw_location_text: str | None = None
    duration_seconds: int | None = None
    thumbnail_url: str | None = None
    metrics: dict[str, int] = field(default_factory=dict)
    raw_response: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class TikTokSearchResult:
    videos: list[TikTokCandidate]
    next_cursor: str | int | float | None = None
    credits_used: int = 0
    credits_remaining: int | None = None


@dataclass(slots=True)
class TikTokVideoInfo:
    video: TikTokCandidate
    credits_used: int = 0
    credits_remaining: int | None = None


@dataclass(slots=True)
class TikTokTranscriptResult:
    available: bool
    transcript_raw: str | None = None
    language: str | None = None
    credits_used: int = 0
    credits_remaining: int | None = None


@dataclass(slots=True)
class ProviderHealth:
    ok: bool
    credits_remaining: int | None = None
    credits_used: int = 0
    message: str | None = None


class TikTokProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class TikTokDiscoveryProvider(ABC):
    name: str

    @abstractmethod
    def search_videos(self, params: TikTokSearchParams) -> TikTokSearchResult: ...

    @abstractmethod
    def get_video_info(self, video_url: str) -> TikTokVideoInfo: ...

    @abstractmethod
    def get_transcript(self, video_url: str, *, use_ai_as_fallback: bool = False) -> TikTokTranscriptResult: ...

    @abstractmethod
    def health_check(self) -> ProviderHealth: ...

    def searchVideos(self, params: TikTokSearchParams) -> TikTokSearchResult:  # noqa: N802
        return self.search_videos(params)

    def getVideoInfo(self, video_url: str) -> TikTokVideoInfo:  # noqa: N802
        return self.get_video_info(video_url)

    def getTranscript(self, video_url: str) -> TikTokTranscriptResult:  # noqa: N802
        return self.get_transcript(video_url)

    def healthCheck(self) -> ProviderHealth:  # noqa: N802
        return self.health_check()


class ScrapeCreatorsTikTokProvider(TikTokDiscoveryProvider):
    name = "SCRAPECREATORS"

    def __init__(self, api_key: str, base_url: str = "https://api.scrapecreators.com", timeout_seconds: int = 30):
        if not api_key.strip():
            raise ValueError("ScrapeCreators API key is required")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = httpx.get(
                f"{self._base_url}{path}",
                headers={"Accept": "application/json", "x-api-key": self._api_key},
                params={key: value for key, value in (params or {}).items() if value is not None},
                timeout=self._timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise TikTokProviderError("ScrapeCreators tidak dapat dijangkau.", retryable=True) from exc
        if response.status_code >= 400:
            retryable = response.status_code == 429 or response.status_code >= 500
            if response.status_code in {401, 403}:
                message = "ScrapeCreators API key tidak valid atau tidak berizin."
            elif response.status_code == 429:
                message = "ScrapeCreators rate limit tercapai."
            else:
                message = f"ScrapeCreators mengembalikan HTTP {response.status_code}."
            raise TikTokProviderError(message, status_code=response.status_code, retryable=retryable)
        try:
            payload = response.json()
        except ValueError as exc:
            raise TikTokProviderError("Respons ScrapeCreators bukan JSON yang valid.", status_code=response.status_code) from exc
        if not isinstance(payload, dict) or payload.get("success") is False:
            raise TikTokProviderError("ScrapeCreators menolak permintaan.", status_code=response.status_code)
        return payload

    def search_videos(self, params: TikTokSearchParams) -> TikTokSearchResult:
        payload = self._get(
            "/v1/tiktok/search/keyword",
            {
                "query": params.query,
                "region": params.region,
                "date_posted": params.date_posted,
                "sort_by": params.sort_by,
                "cursor": params.cursor,
                "trim": str(params.trim).lower(),
            },
        )
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        raw_items = payload.get("search_item_list") or data.get("search_item_list") or []
        videos = [candidate for item in raw_items if (candidate := self._candidate(item)) is not None]
        return TikTokSearchResult(
            videos=videos,
            next_cursor=payload.get("cursor") or payload.get("next_cursor") or data.get("cursor"),
            credits_used=_int(payload.get("credits_charged")) or 0,
            credits_remaining=_int(payload.get("credits_remaining")),
        )

    def get_video_info(self, video_url: str) -> TikTokVideoInfo:
        payload = self._get("/v2/tiktok/video", {"url": video_url, "trim": "true", "download_media": "false"})
        detail = payload.get("aweme_detail") or payload.get("video") or payload
        candidate = self._candidate(detail)
        if candidate is None:
            raise TikTokProviderError("Metadata video TikTok tidak ditemukan.", status_code=404)
        return TikTokVideoInfo(
            video=candidate,
            credits_used=_int(payload.get("credits_charged")) or 0,
            credits_remaining=_int(payload.get("credits_remaining")),
        )

    def get_transcript(self, video_url: str, *, use_ai_as_fallback: bool = False) -> TikTokTranscriptResult:
        payload = self._get(
            "/v1/tiktok/video/transcript",
            {"url": video_url, "language": "id", "use_ai_as_fallback": str(use_ai_as_fallback).lower()},
        )
        raw = payload.get("transcript")
        return TikTokTranscriptResult(
            available=bool(raw),
            transcript_raw=raw if isinstance(raw, str) else None,
            language=payload.get("language") or "id",
            credits_used=_int(payload.get("credits_charged")) or 0,
            credits_remaining=_int(payload.get("credits_remaining")),
        )

    def health_check(self) -> ProviderHealth:
        payload = self._get("/v1/account/credit-balance")
        return ProviderHealth(
            ok=True,
            credits_remaining=_int(payload.get("credits_remaining") or payload.get("creditCount")),
            credits_used=_int(payload.get("credits_charged")) or 0,
            message="Connected",
        )

    @staticmethod
    def _candidate(item: Any) -> TikTokCandidate | None:
        if not isinstance(item, dict):
            return None
        raw = item.get("aweme_info") if isinstance(item.get("aweme_info"), dict) else item
        video_id = str(raw.get("aweme_id") or raw.get("id") or raw.get("id_str") or "").strip()
        if not video_id:
            return None
        author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
        username = str(author.get("unique_id") or author.get("uniqueId") or raw.get("author_username") or "unknown")
        stats = raw.get("statistics") if isinstance(raw.get("statistics"), dict) else raw.get("stats") or {}
        video = raw.get("video") if isinstance(raw.get("video"), dict) else {}
        caption = str(raw.get("desc") or raw.get("caption") or "")
        hashtags = _hashtags(raw, caption)
        created = _timestamp(raw.get("create_time") or raw.get("createTime") or raw.get("create_time_utc"))
        duration = _int(video.get("duration") or raw.get("duration"))
        if duration and duration > 1000:
            duration = round(duration / 1000)
        thumbnail = _first_url(video.get("cover") or raw.get("cover"))
        url = str(raw.get("url") or f"https://www.tiktok.com/@{username}/video/{video_id}")
        return TikTokCandidate(
            video_id=video_id,
            url=url,
            username=username,
            caption=caption,
            published_at=created,
            author_id=str(author.get("uid") or author.get("id") or "") or None,
            creator_name=author.get("nickname") or author.get("display_name"),
            hashtags=hashtags,
            raw_location_text=raw.get("location") or raw.get("poi_name"),
            duration_seconds=duration,
            thumbnail_url=thumbnail,
            metrics={
                "views": _int(stats.get("play_count") or stats.get("playCount")) or 0,
                "likes": _int(stats.get("digg_count") or stats.get("likeCount")) or 0,
                "comments": _int(stats.get("comment_count") or stats.get("commentCount")) or 0,
                "shares": _int(stats.get("share_count") or stats.get("shareCount")) or 0,
            },
            raw_response=raw,
        )


class PublicDiscoveryAdapter(TikTokDiscoveryProvider):
    """Extension point for another approved public-discovery provider."""

    name = "PUBLIC_DISCOVERY"

    def search_videos(self, params: TikTokSearchParams) -> TikTokSearchResult:
        raise TikTokProviderError("No public discovery provider configured")

    def get_video_info(self, video_url: str) -> TikTokVideoInfo:
        raise TikTokProviderError("No public discovery provider configured")

    def get_transcript(self, video_url: str, *, use_ai_as_fallback: bool = False) -> TikTokTranscriptResult:
        raise TikTokProviderError("No public discovery provider configured")

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=False, message="No public discovery provider configured")


class ResearchAPIAdapter(PublicDiscoveryAdapter):
    name = "RESEARCH_API"


class MockPublicDiscoveryAdapter(PublicDiscoveryAdapter):
    name = "MOCK"

    def search_videos(self, params: TikTokSearchParams) -> TikTokSearchResult:
        return TikTokSearchResult(videos=[])

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(ok=True, credits_remaining=None, message="Mock provider")


TikTokSourceAdapter = TikTokDiscoveryProvider


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _first_url(value: Any) -> str | None:
    if isinstance(value, dict):
        urls = value.get("url_list") or value.get("urlList")
        if isinstance(urls, list) and urls:
            return str(urls[0])
        return value.get("url")
    if isinstance(value, str):
        return value
    return None


def _hashtags(raw: dict[str, Any], caption: str) -> list[str]:
    values: list[str] = []
    for item in raw.get("text_extra") or raw.get("textExtra") or []:
        if isinstance(item, dict) and (tag := item.get("hashtag_name") or item.get("hashtagName")):
            values.append(str(tag))
    if not values:
        values = [token[1:].strip(".,;:!?") for token in caption.split() if token.startswith("#") and len(token) > 1]
    return list(dict.fromkeys(values))
