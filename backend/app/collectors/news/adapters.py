import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.services.intelligence import normalize_text


@dataclass(slots=True)
class NewsCandidate:
    url: str
    title: str
    content: str
    published_at: datetime


def matching_news_keywords(candidate: NewsCandidate, keywords: list[str]) -> list[str]:
    """Return configured phrases found in a candidate using normalized word boundaries."""
    searchable = normalize_text(f"{candidate.title} {candidate.content}")
    matches: list[str] = []
    for keyword in keywords:
        normalized_keyword = normalize_text(keyword)
        if not normalized_keyword:
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized_keyword)}(?![a-z0-9])", searchable):
            matches.append(keyword)
    return matches


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith(("utm_", "fbclid", "gclid"))]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))


def is_site_root_url(url: str) -> bool:
    """Return true when a URL identifies a site index rather than an article path."""
    return not urlsplit(url).path.strip("/")


class NewsSourceAdapter(ABC):
    @abstractmethod
    def fetch(self, endpoint: str) -> list[NewsCandidate]: ...


class RSSNewsAdapter(NewsSourceAdapter):
    def __init__(self, timeout_seconds: float = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, endpoint: str) -> list[NewsCandidate]:
        response = httpx.get(
            endpoint,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "FuelDistributionIntelligence/1.0 (public RSS monitor)"},
        )
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"Invalid or empty RSS/Atom feed: {feed.bozo_exception}")
        candidates: list[NewsCandidate] = []
        for entry in feed.entries[:50]:
            if not entry.get("link") or not entry.get("title"):
                continue
            stamp = entry.get("published_parsed") or entry.get("updated_parsed")
            published = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else datetime.now(timezone.utc)
            content = entry.get("summary", "")
            candidates.append(NewsCandidate(entry.link, entry.title, BeautifulSoup(content, "html.parser").get_text(" "), published))
        return candidates


class GenericHTMLAdapter(NewsSourceAdapter):
    def __init__(self, timeout_seconds: float = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch(self, endpoint: str) -> list[NewsCandidate]:
        # A site root is an index containing unrelated stories, not one evidence item.
        if is_site_root_url(endpoint):
            return []
        response = httpx.get(endpoint, timeout=self.timeout_seconds, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.select_one("article")
        og_type = soup.select_one('meta[property="og:type"]')
        if article is None and (og_type is None or og_type.get("content", "").lower() != "article"):
            return []
        container = article or soup.select_one("main")
        paragraphs = container.select("p") if container else []
        text = " ".join(node.get_text(" ", strip=True) for node in paragraphs)
        if len(text) < 120:
            return []
        heading = soup.select_one('meta[property="og:title"]')
        title = heading.get("content", "").strip() if heading else ""
        if not title:
            title_node = (container or soup).select_one("h1")
            title = title_node.get_text(" ", strip=True) if title_node else ""
        if not title:
            return []
        canonical_node = soup.select_one('link[rel="canonical"]')
        candidate_url = urljoin(str(response.url), canonical_node.get("href")) if canonical_node and canonical_node.get("href") else str(response.url)
        return [NewsCandidate(candidate_url, title, text, datetime.now(timezone.utc))]
