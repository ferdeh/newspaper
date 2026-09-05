from __future__ import annotations

import argparse
from dataclasses import dataclass
from urllib.parse import urlencode

from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal
from app.models import NewsSource
from app.workers.celery_app import celery_app


@dataclass(frozen=True, slots=True)
class LiveNewsSource:
    name: str
    domain: str
    feed_url: str
    priority: int
    credibility_score: float
    fetch_frequency_minutes: int


GOOGLE_NEWS_QUERY = '("BBM langka" OR "antrean SPBU" OR "mobil tangki BBM" OR "distribusi BBM") when:14d'
GOOGLE_NEWS_FEED = "https://news.google.com/rss/search?" + urlencode(
    {"q": GOOGLE_NEWS_QUERY, "hl": "id", "gl": "ID", "ceid": "ID:id"}
)

LIVE_NEWS_SOURCES = (
    LiveNewsSource(
        name="Google News Fuel Distribution Watch",
        domain="news.google.com",
        feed_url=GOOGLE_NEWS_FEED,
        priority=1,
        credibility_score=0.70,
        fetch_frequency_minutes=60,
    ),
    LiveNewsSource(
        name="ANTARA News Terkini",
        domain="antaranews.com",
        feed_url="https://www.antaranews.com/rss/terkini.xml",
        priority=2,
        credibility_score=0.88,
        fetch_frequency_minutes=120,
    ),
)


def sync_live_news_sources() -> dict[str, int | str]:
    if not settings.live_news_enabled:
        return {"status": "disabled", "created": 0, "configured": 0}

    created = 0
    configured = 0
    with SessionLocal() as db:
        for definition in LIVE_NEWS_SOURCES:
            source = db.scalar(select(NewsSource).where(NewsSource.feed_url == definition.feed_url))
            if source is None:
                source = db.scalar(
                    select(NewsSource).where(
                        NewsSource.domain == definition.domain,
                        NewsSource.deleted_at.is_(None),
                    ).order_by(NewsSource.priority.asc(), NewsSource.id.asc())
                )
            if source is None:
                source = NewsSource(
                    name=definition.name,
                    domain=definition.domain,
                    source_type="RSS",
                    feed_url=definition.feed_url,
                    priority=definition.priority,
                    credibility_score=definition.credibility_score,
                    fetch_frequency_minutes=definition.fetch_frequency_minutes,
                    is_active=True,
                )
                db.add(source)
                created += 1
            elif not source.feed_url:
                # Complete an existing source record without overriding administrator choices.
                source.feed_url = definition.feed_url
                source.source_type = "RSS"
                configured += 1
        db.commit()
    return {"status": "ready", "created": created, "configured": configured}


def enqueue_priority_collection() -> str | None:
    if not settings.live_news_enabled:
        return None
    result = celery_app.send_task("fuel.news.collect", args=[1], queue="news")
    return result.id


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--enqueue", action="store_true", help="Queue an immediate priority-source collection")
    args = parser.parse_args()
    outcome = sync_live_news_sources()
    if args.enqueue:
        outcome["task_id"] = enqueue_priority_collection() or "disabled"
    print(outcome)
