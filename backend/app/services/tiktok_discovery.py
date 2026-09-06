from __future__ import annotations

import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.collectors.tiktok import (
    MockPublicDiscoveryAdapter,
    ScrapeCreatorsTikTokProvider,
    TikTokCandidate,
    TikTokDiscoveryProvider,
    TikTokProviderError,
    TikTokSearchParams,
)
from app.config import settings
from app.models import (
    MasterTikTokKeyword,
    TikTokProviderRequest,
    TikTokSearchRun,
    TikTokSettings,
    TikTokTranscript,
    TikTokVideo,
    TikTokVideoKeywordMatch,
)
from app.schemas import TikTokIngest
from app.services.alerts import evaluate_incident_alerts
from app.services.encryption import decrypt_secret
from app.services.intelligence import classify_text, normalize_text, relevance_score
from app.services.pipeline import ingest_tiktok, linked_incident, recompute_incident

logger = logging.getLogger("fuel-intelligence.tiktok")
T = TypeVar("T")
SETTINGS_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
ALGORITHM_VERSION = "tiktok-discovery-v1"
STRONG_INCIDENT_PHRASES = (
    "mobil tangki terbalik", "truk tangki terbalik", "mobil tangki terbakar", "truk tangki terbakar",
    "mobil tangki kecelakaan", "truk tangki kecelakaan",
)


def get_tiktok_settings(db: Session) -> TikTokSettings:
    row = db.scalar(select(TikTokSettings).where(TikTokSettings.singleton_key == 1))
    if row:
        return row
    row = TikTokSettings(id=SETTINGS_ID, singleton_key=1)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        row = db.scalar(select(TikTokSettings).where(TikTokSettings.singleton_key == 1))
    return row


def get_tiktok_api_key(row: TikTokSettings) -> str | None:
    if row.api_key_encrypted:
        return decrypt_secret(row.api_key_encrypted)
    return settings.scrapecreators_api_key.get_secret_value() if settings.scrapecreators_api_key else None


def build_provider(row: TikTokSettings, *, api_key: str | None = None) -> TikTokDiscoveryProvider:
    provider_name = (row.provider or settings.tiktok_provider).upper()
    if provider_name == "MOCK":
        return MockPublicDiscoveryAdapter()
    if provider_name == "SCRAPECREATORS":
        key = api_key or get_tiktok_api_key(row)
        if not key:
            raise TikTokProviderError("ScrapeCreators API key belum dikonfigurasi.", status_code=401)
        return ScrapeCreatorsTikTokProvider(
            key,
            base_url=settings.scrapecreators_base_url,
            timeout_seconds=settings.scrapecreators_timeout_seconds,
        )
    raise TikTokProviderError(f"Provider TikTok {provider_name} belum didukung.")


def test_provider_connection(db: Session, row: TikTokSettings, *, api_key: str | None = None) -> dict[str, Any]:
    provider = build_provider(row, api_key=api_key)
    row.last_health_checked_at = datetime.now(timezone.utc)
    try:
        health = _provider_call(db, None, row, provider.name, "HEALTH", provider.health_check)
    except TikTokProviderError as exc:
        row.provider_health_status = "ERROR"
        row.last_provider_error = str(exc)[:500]
        db.commit()
        raise
    db.commit()
    return {
        "provider": provider.name,
        "status": "CONNECTED" if health.ok else "ERROR",
        "credits_remaining": health.credits_remaining,
        "credits_used": health.credits_used,
        "message": health.message,
    }


def effective_frequency(keyword: MasterTikTokKeyword, row: TikTokSettings) -> int:
    return keyword.frequency_minutes or row.global_discovery_interval_minutes


def usage_totals(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    local_now = now.astimezone(settings.timezone)
    day_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    month_start = local_now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

    def summarize(since: datetime) -> dict[str, int]:
        rows = db.execute(
            select(TikTokProviderRequest.operation, func.coalesce(func.sum(TikTokProviderRequest.credits_used), 0), func.count())
            .where(TikTokProviderRequest.requested_at >= since)
            .group_by(TikTokProviderRequest.operation)
        ).all()
        by_operation = {operation: int(credits) for operation, credits, _ in rows}
        return {
            "search_credits": by_operation.get("SEARCH", 0),
            "transcript_credits": by_operation.get("TRANSCRIPT", 0),
            "video_info_credits": by_operation.get("VIDEO_INFO", 0),
            "health_credits": by_operation.get("HEALTH", 0),
            "total_credits": sum(int(credits) for _, credits, _ in rows),
            "requests": sum(int(count) for _, _, count in rows),
        }

    return {"today": summarize(day_start), "month": summarize(month_start)}


def credit_guard(db: Session, row: TikTokSettings, priority: str) -> tuple[bool, str]:
    usage = usage_totals(db)
    daily = usage["today"]["total_credits"]
    monthly = usage["month"]["total_credits"]
    daily_percent = daily / row.daily_credit_limit * 100 if row.daily_credit_limit else 0
    monthly_percent = monthly / row.monthly_credit_limit * 100 if row.monthly_credit_limit else 0
    percent = max(daily_percent, monthly_percent)
    at_limit = bool(
        (row.daily_credit_limit and daily >= row.daily_credit_limit)
        or (row.monthly_credit_limit and monthly >= row.monthly_credit_limit)
    )
    if at_limit and priority != "HIGH":
        return False, "CREDIT_LIMIT_HIGH_ONLY"
    if percent >= row.critical_threshold_percent and priority == "LOW":
        return False, "CREDIT_CRITICAL_LOW_DEFERRED"
    return True, "NORMAL"


def create_search_run(
    db: Session,
    *,
    query: str,
    provider: str,
    keyword_id: uuid.UUID | None = None,
    search_params: dict[str, Any] | None = None,
) -> TikTokSearchRun:
    run = TikTokSearchRun(
        keyword_id=keyword_id,
        query_text=query,
        search_params=search_params or {},
        provider=provider,
        status="RUNNING",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def schedule_due_keywords(db: Session, now: datetime | None = None) -> list[uuid.UUID]:
    return _schedule_keywords(db, now=now, due_only=True)


def schedule_refresh_keywords(
    db: Session,
    now: datetime | None = None,
    *,
    completed_since: datetime | None = None,
) -> list[uuid.UUID]:
    """Create runs for every active keyword during an operator-requested refresh."""
    return _schedule_keywords(db, now=now, due_only=False, completed_since=completed_since)


def recover_stale_search_runs(
    db: Session,
    *,
    now: datetime | None = None,
    stale_after_minutes: int | None = None,
) -> int:
    """Release keywords blocked by search runs abandoned by a stopped worker."""
    now = now or datetime.now(timezone.utc)
    recovery_minutes = max(
        1,
        stale_after_minutes if stale_after_minutes is not None else settings.tiktok_stale_run_minutes,
    )
    stale_before = now - timedelta(minutes=recovery_minutes)
    stale_runs = db.scalars(
        select(TikTokSearchRun)
        .where(
            TikTokSearchRun.status == "RUNNING",
            TikTokSearchRun.started_at < stale_before,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for run in stale_runs:
        run.status = "FAILED"
        run.finished_at = now
        run.error_message = f"STALE_RUN_RECOVERED_AFTER_{recovery_minutes}_MINUTES"
        if run.keyword_id:
            keyword = db.get(MasterTikTokKeyword, run.keyword_id)
            if keyword and keyword.active and (keyword.next_run_at is None or keyword.next_run_at > now):
                keyword.next_run_at = now
    if stale_runs:
        db.flush()
        logger.warning(
            "tiktok.search.stale_recovered",
            extra={"runs_recovered": len(stale_runs), "stale_after_minutes": recovery_minutes},
        )
    return len(stale_runs)


def _schedule_keywords(
    db: Session,
    *,
    now: datetime | None,
    due_only: bool,
    completed_since: datetime | None = None,
) -> list[uuid.UUID]:
    now = now or datetime.now(timezone.utc)
    row = get_tiktok_settings(db)
    if not row.enabled or not get_tiktok_api_key(row):
        return []

    recover_stale_search_runs(db, now=now)
    running_keyword_ids = set(db.scalars(
        select(TikTokSearchRun.keyword_id).where(
            TikTokSearchRun.keyword_id.is_not(None),
            TikTokSearchRun.status == "RUNNING",
        )
    ).all())
    filters = [MasterTikTokKeyword.active.is_(True)]
    if due_only:
        filters.append((MasterTikTokKeyword.next_run_at.is_(None)) | (MasterTikTokKeyword.next_run_at <= now))
    elif completed_since:
        filters.append(
            (MasterTikTokKeyword.last_run_at.is_(None)) | (MasterTikTokKeyword.last_run_at < completed_since)
        )
    keywords = db.scalars(
        select(MasterTikTokKeyword)
        .where(*filters)
        .order_by(MasterTikTokKeyword.next_run_at.asc().nullsfirst(), MasterTikTokKeyword.priority.asc())
        .with_for_update(skip_locked=True)
    ).all()
    run_ids: list[uuid.UUID] = []
    for keyword in keywords:
        if keyword.id in running_keyword_ids:
            continue
        allowed, _ = credit_guard(db, row, keyword.priority)
        if not allowed:
            keyword.next_run_at = now + timedelta(minutes=effective_frequency(keyword, row))
            continue
        run = TikTokSearchRun(
            keyword_id=keyword.id,
            query_text=keyword.keyword,
            search_params={},
            provider=row.provider,
            status="RUNNING",
        )
        db.add(run)
        db.flush()
        keyword.next_run_at = now + timedelta(minutes=effective_frequency(keyword, row))
        run_ids.append(run.id)
    db.commit()
    return run_ids


def execute_search_run(db: Session, run_id: uuid.UUID, provider: TikTokDiscoveryProvider | None = None) -> dict[str, Any]:
    run = db.get(TikTokSearchRun, run_id)
    if not run:
        return {"run_id": str(run_id), "status": "NOT_FOUND"}
    if run.status != "RUNNING":
        logger.info(
            "tiktok.search.skipped_non_running",
            extra={"run_id": str(run.id), "status": run.status},
        )
        return run_summary(run)
    row = get_tiktok_settings(db)
    keyword = db.get(MasterTikTokKeyword, run.keyword_id) if run.keyword_id else None
    priority = keyword.priority if keyword else "HIGH"
    allowed, guard_reason = credit_guard(db, row, priority)
    if not allowed:
        run.status = "FAILED"
        run.finished_at = datetime.now(timezone.utc)
        run.error_message = guard_reason
        db.commit()
        return run_summary(run)

    provider = provider or build_provider(row)
    params_override = run.search_params or {}
    max_pages = int(params_override.get("max_pages") or (keyword.max_pages if keyword else 0) or row.default_max_pages)
    search_params = TikTokSearchParams(
        query=run.query_text,
        region=params_override.get("region") or (keyword.region if keyword else None) or row.default_region,
        date_posted=params_override.get("date_posted") or (keyword.date_filter if keyword else None) or row.default_date_filter,
        sort_by=params_override.get("sort_by") or (keyword.sort_by if keyword else None) or row.default_sort_by,
        trim=row.default_trim,
    )
    logger.info("tiktok.search.started", extra={"run_id": str(run.id), "keyword": run.query_text, "provider": provider.name})
    cursor: str | int | float | None = None
    errors: list[str] = []
    try:
        for _ in range(max_pages):
            search_params.cursor = cursor
            result = _provider_call(db, run, row, provider.name, "SEARCH", lambda: provider.search_videos(search_params))
            run.pages_requested += 1
            run.search_credits += result.credits_used
            page_new = 0
            page_duplicate = 0
            for candidate in result.videos:
                run.results_found += 1
                is_new, is_relevant, uncertain = _upsert_and_process_candidate(db, run, row, provider, candidate, keyword)
                if is_new:
                    page_new += 1
                    run.new_videos += 1
                else:
                    page_duplicate += 1
                    run.duplicate_videos += 1
                if is_relevant:
                    run.relevant_videos += 1
                elif uncertain:
                    run.uncertain_videos += 1
                else:
                    run.irrelevant_videos += 1
            db.commit()
            cursor = result.next_cursor
            if not cursor or (page_new == 0 and page_duplicate > len(result.videos) / 2):
                break
        run.status = "PARTIAL" if errors else "SUCCESS"
    except Exception as exc:
        errors.append(str(exc)[:500])
        run.status = "PARTIAL" if run.results_found else "FAILED"
        row.provider_health_status = "ERROR"
        row.last_provider_error = errors[-1]
        logger.exception("tiktok.search.failed", extra={"run_id": str(run.id), "provider": provider.name})
    finally:
        finished = datetime.now(timezone.utc)
        run.finished_at = finished
        run.error_message = "; ".join(errors) or None
        if keyword:
            keyword.last_run_at = finished
            keyword.last_result_count = run.results_found
            keyword.last_new_video_count = run.new_videos
            keyword.last_relevant_count = run.relevant_videos
            if row.adaptive_scheduler_enabled and run.relevant_videos >= 3:
                temporary_interval = max(15, effective_frequency(keyword, row) // 3)
                accelerated = finished + timedelta(minutes=temporary_interval)
                if keyword.next_run_at is None or accelerated < keyword.next_run_at:
                    keyword.next_run_at = accelerated
        db.commit()
    logger.info("tiktok.search.completed", extra=run_summary(run))
    return run_summary(run)


def _provider_call(
    db: Session,
    run: TikTokSearchRun | None,
    row: TikTokSettings,
    provider_name: str,
    operation: str,
    call: Callable[[], T],
) -> T:
    delays = (0, 2, 5)
    last_error: Exception | None = None
    for attempt, delay in enumerate(delays):
        if delay:
            time.sleep(delay)
        started = time.perf_counter()
        request = TikTokProviderRequest(search_run_id=run.id if run else None, provider=provider_name, operation=operation)
        db.add(request)
        if run:
            run.api_requests += 1
        try:
            result = call()
            credits = int(getattr(result, "credits_used", 0) or 0)
            request.succeeded = True
            request.credits_used = credits
            request.duration_ms = round((time.perf_counter() - started) * 1000)
            if run:
                run.credits_used += credits
            row.provider_health_status = "CONNECTED"
            row.last_successful_request_at = datetime.now(timezone.utc)
            row.last_provider_error = None
            db.commit()
            return result
        except TikTokProviderError as exc:
            last_error = exc
            request.status_code = exc.status_code
            request.error_message = str(exc)[:500]
            request.duration_ms = round((time.perf_counter() - started) * 1000)
            db.commit()
            if not exc.retryable or attempt == len(delays) - 1:
                break
    raise last_error or TikTokProviderError("TikTok provider request failed")


def _upsert_and_process_candidate(
    db: Session,
    run: TikTokSearchRun,
    row: TikTokSettings,
    provider: TikTokDiscoveryProvider,
    candidate: TikTokCandidate,
    keyword: MasterTikTokKeyword | None,
) -> tuple[bool, bool, bool]:
    now = datetime.now(timezone.utc)
    video = db.scalar(
        select(TikTokVideo).where(
            TikTokVideo.provider == provider.name,
            TikTokVideo.provider_video_id == candidate.video_id,
        )
    )
    is_new = video is None
    if video is None:
        video = TikTokVideo(
            provider=provider.name,
            provider_video_id=candidate.video_id,
            video_url=candidate.url,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(video)
        logger.info("tiktok.video.discovered", extra={"video_id": candidate.video_id, "run_id": str(run.id)})
    else:
        video.last_seen_at = now
        logger.info("tiktok.video.duplicate", extra={"video_id": candidate.video_id, "run_id": str(run.id)})
    _copy_candidate(video, candidate)
    db.flush()

    if keyword:
        match = db.scalar(
            select(TikTokVideoKeywordMatch).where(
                TikTokVideoKeywordMatch.video_id == video.id,
                TikTokVideoKeywordMatch.keyword_id == keyword.id,
            )
        )
        if not match:
            db.add(TikTokVideoKeywordMatch(video_id=video.id, keyword_id=keyword.id, search_run_id=run.id))

    if not is_new and video.canonical_tiktok_post_id and video.algorithm_version == ALGORITHM_VERSION:
        incident = _incident_for_video(db, video)
        return False, incident is not None, False

    initial_text = " ".join([video.caption or "", " ".join(f"#{tag}" for tag in video.hashtags or [])]).strip()
    score, category = fast_relevance_screen(initial_text)
    video.relevance_score = score
    video.relevance_category = category
    video.algorithm_version = ALGORITHM_VERSION
    if score < 0.35:
        video.processing_status = "IRRELEVANT"
        video.needs_transcript = False
        db.flush()
        return is_new, False, False

    uncertain = score <= 0.70
    transcript_text = _available_transcript(db, video)
    video.needs_transcript = row.transcript_enabled and transcript_text is None
    if video.needs_transcript:
        video.processing_status = "TRANSCRIPT_PENDING"
        run.transcripts_requested += 1
        transcript = db.scalar(select(TikTokTranscript).where(TikTokTranscript.video_id == video.id))
        if not transcript:
            transcript = TikTokTranscript(video_id=video.id, provider=provider.name, status="PENDING")
            db.add(transcript)
            db.flush()
        try:
            result = _provider_call(
                db,
                run,
                row,
                provider.name,
                "TRANSCRIPT",
                lambda: provider.get_transcript(
                    video.video_url,
                    use_ai_as_fallback=row.ai_transcript_fallback_enabled,
                ),
            )
            run.transcript_credits += result.credits_used
            transcript.credits_used += result.credits_used
            transcript.transcript_raw = result.transcript_raw
            transcript.transcript_text = clean_webvtt(result.transcript_raw) if result.available else None
            transcript.language = result.language
            transcript.status = "AVAILABLE" if result.available else "NOT_AVAILABLE"
            transcript_text = transcript.transcript_text
            if result.available:
                run.transcripts_found += 1
            else:
                logger.info("tiktok.transcript.unavailable", extra={"video_id": candidate.video_id})
        except TikTokProviderError as exc:
            transcript.status = "FAILED"
            logger.warning("tiktok.transcript.unavailable", extra={"video_id": candidate.video_id, "error": str(exc)})

    analysis_text = "\n".join(part for part in (initial_text, transcript_text) if part).strip()
    video.processing_status = "AI_ANALYSIS"
    payload = TikTokIngest(
        video_id=video.provider_video_id,
        url=video.video_url,
        username=video.author_username or "unknown",
        creator_name=video.author_display_name,
        caption=video.caption or "TikTok public signal",
        hashtags=video.hashtags or [],
        published_at=video.tiktok_created_at or video.first_seen_at,
        view_count=video.view_count or 0,
        like_count=video.like_count or 0,
        comment_count=video.comment_count or 0,
        share_count=video.share_count or 0,
        raw_location_text=candidate.raw_location_text,
    )
    signal, incident = ingest_tiktok(db, payload, analysis_text=analysis_text)
    video.canonical_tiktok_post_id = signal.source_record_id
    if incident:
        video.processing_status = "PROCESSED"
        video.relevance_category = category
        video.relevance_score = max(score, signal.relevance_score)
        if incident.signal_count == 1:
            run.incidents_created += 1
            logger.info("tiktok.incident.created", extra={"video_id": candidate.video_id, "incident_id": incident.id})
        evaluate_incident_alerts(db, incident)
        db.commit()
        return is_new, True, uncertain
    video.processing_status = "IRRELEVANT" if signal.processing_status == "ARCHIVED_IRRELEVANT" else "ERROR_RETRYABLE"
    db.commit()
    return is_new, False, uncertain


def _copy_candidate(video: TikTokVideo, candidate: TikTokCandidate) -> None:
    video.video_url = candidate.url
    video.thumbnail_url = candidate.thumbnail_url
    video.author_id = candidate.author_id
    video.author_username = candidate.username
    video.author_display_name = candidate.creator_name
    video.caption = candidate.caption
    video.hashtags = candidate.hashtags
    video.tiktok_created_at = candidate.published_at
    video.duration_seconds = candidate.duration_seconds
    video.view_count = max(video.view_count or 0, candidate.metrics.get("views", 0))
    video.like_count = max(video.like_count or 0, candidate.metrics.get("likes", 0))
    video.comment_count = max(video.comment_count or 0, candidate.metrics.get("comments", 0))
    video.share_count = max(video.share_count or 0, candidate.metrics.get("shares", 0))
    video.raw_response = candidate.raw_response


def fast_relevance_screen(text: str) -> tuple[float, str]:
    normalized = normalize_text(text)
    score = relevance_score(text)
    if any(phrase in normalized for phrase in STRONG_INCIDENT_PHRASES):
        score = max(score, 0.92)
    if score < 0.35:
        return score, "NOT_RELEVANT"
    classified = classify_text(text)
    if "terbakar" in normalized:
        category = "TANKER_FIRE"
    elif any(term in normalized for term in ("terbalik", "kecelakaan")) and "tangki" in normalized:
        category = "TANKER_ACCIDENT"
    elif any(term in normalized for term in ("habis", "kosong")):
        category = "FUEL_STOCKOUT"
    elif any(term in normalized for term in ("antre", "antrian", "antrean")):
        category = "SPBU_QUEUE"
    elif any(term in normalized for term in ("dibatasi", "pembatasan")):
        category = "FUEL_RESTRICTION"
    elif classified.get("relevant"):
        category = "OTHER_RELEVANT"
    else:
        category = "OTHER_RELEVANT"
    return score, category


def clean_webvtt(value: str | None) -> str | None:
    if not value:
        return None
    lines: list[str] = []
    for line in value.replace("\ufeff", "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper() == "WEBVTT" or "-->" in stripped or stripped.isdigit():
            continue
        cleaned = re.sub(r"<[^>]+>", "", stripped)
        if cleaned and (not lines or lines[-1] != cleaned):
            lines.append(cleaned)
    return " ".join(lines) or None


def _available_transcript(db: Session, video: TikTokVideo) -> str | None:
    transcript = db.scalar(select(TikTokTranscript).where(TikTokTranscript.video_id == video.id))
    return transcript.transcript_text if transcript and transcript.status == "AVAILABLE" else None


def _incident_for_video(db: Session, video: TikTokVideo):
    if not video.canonical_tiktok_post_id:
        return None
    from app.models import Signal

    signal = db.scalar(
        select(Signal).where(Signal.source_type == "TIKTOK", Signal.source_record_id == video.canonical_tiktok_post_id)
    )
    return linked_incident(db, signal.id) if signal else None


def reprocess_video(db: Session, video: TikTokVideo) -> dict[str, Any]:
    video.algorithm_version = None
    video.canonical_tiktok_post_id = video.canonical_tiktok_post_id
    incident = _incident_for_video(db, video)
    if incident:
        recompute_incident(db, incident)
        video.algorithm_version = ALGORITHM_VERSION
        video.processing_status = "PROCESSED"
        db.commit()
        return {"video_id": str(video.id), "status": video.processing_status, "incident_id": incident.id}
    video.processing_status = "DISCOVERED"
    db.commit()
    return {"video_id": str(video.id), "status": video.processing_status, "incident_id": None}


def run_summary(run: TikTokSearchRun) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "status": run.status,
        "pages": run.pages_requested,
        "api_requests": run.api_requests,
        "credits": run.credits_used,
        "results": run.results_found,
        "new": run.new_videos,
        "duplicates": run.duplicate_videos,
        "relevant": run.relevant_videos,
        "uncertain": run.uncertain_videos,
        "transcripts": run.transcripts_found,
        "incidents": run.incidents_created,
        "error": run.error_message,
    }
