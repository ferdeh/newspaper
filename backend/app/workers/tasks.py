from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from celery import chain, group
from sqlalchemy import select

from app.collectors.news import GenericHTMLAdapter, RSSNewsAdapter
from app.collectors.news.adapters import NewsCandidate, canonicalize_url, matching_news_keywords
from app.config import settings
from app.database import SessionLocal
from app.models import NewsKeyword, NewsSource, RawArticle, Signal, TikTokSearchRun, WorkerHeartbeat
from app.notification.worker import NotificationWorker
from app.schemas import NewsIngest
from app.services.alerts import dispatch_queued_alerts, evaluate_all_alerts, generate_daily_digest
from app.services.analytics import refresh_analytics
from app.services.geography import enrich_all_incidents
from app.services.pipeline import archive_news_false_positives, ingest_news, process_signal, recalculate_all_incidents
from app.services.tbbm_discovery import TbbmDiscoveryService
from app.services.tiktok_discovery import (
    execute_search_run,
    get_tiktok_api_key,
    get_tiktok_settings,
    schedule_due_keywords,
    schedule_refresh_keywords,
)
from app.workers.celery_app import celery_app

logger = logging.getLogger("fuel-intelligence.workers")


@dataclass(frozen=True, slots=True)
class NewsFetchRequest:
    source_id: int
    source_type: str
    feed_url: str


@dataclass(frozen=True, slots=True)
class NewsFetchResult:
    source_id: int
    candidates: list[NewsCandidate]
    error: str | None = None


def fetch_news_source(request: NewsFetchRequest) -> NewsFetchResult:
    """Fetch one source without sharing a database session between threads."""
    try:
        adapter = (
            RSSNewsAdapter(settings.news_fetch_timeout_seconds)
            if request.source_type == "RSS"
            else GenericHTMLAdapter(settings.news_fetch_timeout_seconds)
        )
        return NewsFetchResult(request.source_id, adapter.fetch(request.feed_url))
    except Exception as exc:
        return NewsFetchResult(request.source_id, [], str(exc)[:500])


@celery_app.task(name="fuel.system.heartbeat")
def heartbeat(service: str) -> str:
    with SessionLocal() as db:
        row = db.get(WorkerHeartbeat, service)
        if not row:
            row = WorkerHeartbeat(service=service)
            db.add(row)
        row.status = "HEALTHY"
        row.last_seen_at = datetime.now(timezone.utc)
        db.commit()
    return service


@celery_app.task(name="fuel.news.collect", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def collect_news(max_priority: int = 5) -> dict:
    with SessionLocal() as db:
        sources = db.scalars(select(NewsSource).where(
            NewsSource.is_active.is_(True), NewsSource.deleted_at.is_(None), NewsSource.priority <= max_priority,
        )).all()
        keywords = db.scalars(select(NewsKeyword.keyword).where(
            NewsKeyword.is_active.is_(True), NewsKeyword.deleted_at.is_(None),
        ).order_by(NewsKeyword.keyword)).all()
        created = 0
        candidates_seen = 0
        duplicates = 0
        keyword_matches = 0
        filtered_by_keyword = 0
        source_errors = 0
        if not keywords:
            return {
                "sources_checked": 0,
                "active_keywords": 0,
                "candidates_seen": 0,
                "keyword_matches": 0,
                "filtered_by_keyword": 0,
                "new_signals": 0,
                "duplicates": 0,
                "source_errors": 0,
                "status": "SKIPPED_NO_ACTIVE_KEYWORDS",
            }
        fetch_requests = [
            NewsFetchRequest(source.id, source.source_type, source.feed_url)
            for source in sources if source.feed_url
        ]
        source_by_id = {source.id: source for source in sources}
        worker_count = max(1, min(settings.news_fetch_concurrency, len(fetch_requests)))
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="news-fetch") as executor:
            fetch_results = list(executor.map(fetch_news_source, fetch_requests))

        for fetch_result in fetch_results:
            source = source_by_id[fetch_result.source_id]
            if fetch_result.error:
                source_errors += 1
                source.last_error = fetch_result.error
                continue
            try:
                for candidate in fetch_result.candidates:
                    candidates_seen += 1
                    if not matching_news_keywords(candidate, keywords):
                        filtered_by_keyword += 1
                        continue
                    keyword_matches += 1
                    canonical = canonicalize_url(candidate.url)
                    if db.scalar(select(RawArticle.id).where(RawArticle.canonical_url == canonical)):
                        duplicates += 1
                        continue
                    _, incident = ingest_news(db, NewsIngest(
                        source_name=source.name, source_domain=source.domain, url=candidate.url, title=candidate.title,
                        content=candidate.content, published_at=candidate.published_at,
                    ))
                    created += 1
                source.last_success_at = datetime.now(timezone.utc)
                source.last_error = None
            except Exception as exc:
                source_errors += 1
                source.last_error = str(exc)[:500]
        db.commit()
        return {
            "sources_checked": len(sources),
            "active_keywords": len(keywords),
            "candidates_seen": candidates_seen,
            "keyword_matches": keyword_matches,
            "filtered_by_keyword": filtered_by_keyword,
            "new_signals": created,
            "duplicates": duplicates,
            "source_errors": source_errors,
        }


@celery_app.task(name="fuel.tiktok.discover")
def discover_tiktok() -> dict:
    with SessionLocal() as db:
        run_ids = schedule_due_keywords(db)
    task_ids = [celery_app.send_task("fuel.tiktok.search", args=[str(run_id)], queue="tiktok").id for run_id in run_ids]
    return {"due_keywords": len(run_ids), "run_ids": [str(run_id) for run_id in run_ids], "task_ids": task_ids}


@celery_app.task(name="fuel.tiktok.search")
def search_tiktok(run_id: str) -> dict:
    with SessionLocal() as db:
        return execute_search_run(db, uuid.UUID(run_id))


def _empty_tiktok_refresh(status: str) -> dict:
    return {
        "status": status,
        "keywords_run": 0,
        "runs_successful": 0,
        "runs_partial": 0,
        "runs_failed": 0,
        "results_found": 0,
        "new_videos": 0,
        "duplicates": 0,
        "relevant_videos": 0,
        "incidents_created": 0,
        "credits_used": 0,
        "run_ids": [],
    }


def summarize_tiktok_refresh(summaries: list[dict]) -> dict:
    statuses = [summary.get("status") for summary in summaries]
    failed = statuses.count("FAILED")
    partial = statuses.count("PARTIAL")
    successful = statuses.count("SUCCESS")
    overall_status = "FAILED" if failed == len(summaries) else "PARTIAL" if failed or partial else "SUCCESS"
    return {
        "status": overall_status,
        "keywords_run": len(summaries),
        "runs_successful": successful,
        "runs_partial": partial,
        "runs_failed": failed,
        "results_found": sum(int(item.get("results", 0)) for item in summaries),
        "new_videos": sum(int(item.get("new", 0)) for item in summaries),
        "duplicates": sum(int(item.get("duplicates", 0)) for item in summaries),
        "relevant_videos": sum(int(item.get("relevant", 0)) for item in summaries),
        "incidents_created": sum(int(item.get("incidents", 0)) for item in summaries),
        "credits_used": sum(int(item.get("credits", 0)) for item in summaries),
        "run_ids": [item["run_id"] for item in summaries],
    }


@celery_app.task(name="fuel.tiktok.collect-for-refresh")
def collect_tiktok_for_refresh(requested_at: str | None = None) -> dict:
    """Run all active TikTok keywords and wait for their results before final analytics."""
    with SessionLocal() as db:
        settings_row = get_tiktok_settings(db)
        if not settings_row.enabled:
            return _empty_tiktok_refresh("SKIPPED_DISABLED")
        if not get_tiktok_api_key(settings_row):
            return _empty_tiktok_refresh("SKIPPED_NOT_CONFIGURED")
        if requested_at:
            refresh_started_at = datetime.fromisoformat(requested_at)
        else:
            refresh_started_at = datetime.now(timezone.utc) - timedelta(
                minutes=settings_row.global_discovery_interval_minutes
            )
        run_ids = schedule_refresh_keywords(db, completed_since=refresh_started_at)
        if not run_ids:
            return _empty_tiktok_refresh("UP_TO_DATE")

        summaries: list[dict] = []
        for run_id in run_ids:
            try:
                summaries.append(execute_search_run(db, run_id))
            except Exception as exc:
                db.rollback()
                logger.exception("tiktok.refresh.run_failed", extra={"run_id": str(run_id)})
                failed_run = db.get(TikTokSearchRun, run_id)
                if failed_run:
                    failed_run.status = "FAILED"
                    failed_run.finished_at = datetime.now(timezone.utc)
                    failed_run.error_message = str(exc)[:500]
                    db.commit()
                summaries.append(
                    {
                        "run_id": str(run_id),
                        "status": "FAILED",
                        "results": 0,
                        "new": 0,
                        "duplicates": 0,
                        "relevant": 0,
                        "incidents": 0,
                        "credits": 0,
                        "error": str(exc)[:500],
                    }
                )

    return summarize_tiktok_refresh(summaries)


@celery_app.task(name="fuel.signal.process", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def process_signal_task(signal_id: int) -> dict:
    with SessionLocal() as db:
        signal = db.get(Signal, signal_id)
        if not signal:
            return {"signal_id": signal_id, "status": "NOT_FOUND"}
        incident = process_signal(db, signal)
        db.commit()
        return {"signal_id": signal_id, "incident_id": incident.id if incident else None, "status": signal.processing_status}


@celery_app.task(name="fuel.incident.recalculate", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def recalculate_incidents() -> dict:
    with SessionLocal() as db:
        return {"incidents": recalculate_all_incidents(db)}


@celery_app.task(name="fuel.geo.enrich", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def enrich_incident_geography_task() -> dict:
    with SessionLocal() as db:
        return enrich_all_incidents(db, force_google=True)


@celery_app.task(name="fuel.tbbm.discover")
def discover_tbbm_task(job_id: str) -> dict:
    with SessionLocal() as db:
        return TbbmDiscoveryService(db).run(uuid.UUID(job_id))


@celery_app.task(name="fuel.analytics.refresh", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def refresh_analytics_task() -> dict:
    with SessionLocal() as db:
        return {"aggregation_rows": refresh_analytics(db)}


@celery_app.task(name="fuel.alerts.evaluate", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 4})
def evaluate_alerts_task() -> dict:
    with SessionLocal() as db:
        return {"queued": evaluate_all_alerts(db)}


@celery_app.task(name="fuel.whatsapp.dispatch", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 6})
def dispatch_whatsapp() -> dict:
    with SessionLocal() as db:
        return {"sent": dispatch_queued_alerts(db)}


@celery_app.task(name="fuel.notifications.dispatch")
def dispatch_notifications() -> dict:
    with SessionLocal() as db:
        return NotificationWorker(db).run_batch()


@celery_app.task(name="fuel.whatsapp.digest", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 6})
def daily_digest() -> dict:
    with SessionLocal() as db:
        alert = generate_daily_digest(db)
        sent = dispatch_queued_alerts(db) if alert else 0
        return {"created": bool(alert), "sent": sent}


@celery_app.task(name="fuel.intelligence.recalculate")
def full_refresh_recalculate(collections: list[dict]) -> dict:
    """Continue only after the News and TikTok collection branches have both completed."""
    news_collection, tiktok_collection = collections
    with SessionLocal() as db:
        false_positives = archive_news_false_positives(db)
        incidents = recalculate_all_incidents(db)
    return {
        "collection": {**news_collection, "news": news_collection, "tiktok": tiktok_collection},
        **false_positives,
        "incidents_recalculated": incidents,
    }


@celery_app.task(name="fuel.intelligence.finalize")
def full_refresh_finalize(context: dict) -> dict:
    """Refresh persisted analytics and return one result for the full workflow."""
    with SessionLocal() as db:
        analytics_rows = refresh_analytics(db)
    return {**context, "analytics_rows": analytics_rows}


def build_full_refresh_workflow(requested_at: datetime | None = None):
    refresh_started_at = requested_at or datetime.now(timezone.utc)
    return chain(
        group(
            collect_news.s(5).set(queue="news"),
            collect_tiktok_for_refresh.s(refresh_started_at.isoformat()).set(queue="tiktok"),
        ),
        full_refresh_recalculate.s().set(queue="incident"),
        full_refresh_finalize.s().set(queue="analytics"),
    )


@celery_app.task(bind=True, name="fuel.intelligence.refresh")
def refresh_intelligence(self) -> dict:
    """Refresh News and TikTok in parallel, then rebuild shared intelligence."""
    return self.replace(build_full_refresh_workflow(datetime.now(timezone.utc)))
