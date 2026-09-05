from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import require_internal_token
from app.database import get_db
from app.models import (
    Event,
    Incident,
    IncidentSignal,
    MasterTikTokKeyword,
    Signal,
    TikTokProviderRequest,
    TikTokSearchRun,
    TikTokSettings,
    TikTokTranscript,
    TikTokVideo,
    TikTokVideoKeywordMatch,
)
from app.services.encryption import SecretDecryptionError, encrypt_secret, mask_secret
from app.services.tiktok_discovery import (
    create_search_run,
    effective_frequency,
    get_tiktok_api_key,
    get_tiktok_settings,
    reprocess_video,
    schedule_due_keywords,
    test_provider_connection,
    usage_totals,
)
from app.tiktok_schemas import (
    TikTokConnectionTest,
    TikTokKeywordCreate,
    TikTokKeywordUpdate,
    TikTokManualSearch,
    TikTokReprocessRequest,
    TikTokSettingsUpdate,
)
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/tiktok", tags=["TikTok Discovery"])
Db = Annotated[Session, Depends(get_db)]
logger = logging.getLogger("fuel-intelligence.tiktok.api")


def _settings_response(db: Session, row: TikTokSettings) -> dict[str, Any]:
    credential_error = None
    try:
        api_key = get_tiktok_api_key(row)
    except SecretDecryptionError:
        api_key = None
        credential_error = "Credential TikTok tersimpan tidak dapat didekripsi. Masukkan dan simpan kembali API key."
        logger.error("tiktok.settings.credential_unreadable", extra={"provider": row.provider})
    usage = usage_totals(db)
    return {
        "provider": row.provider,
        "apiKeyConfigured": bool(api_key),
        "apiKeyMasked": mask_secret(api_key),
        "credentialSource": "database" if row.api_key_encrypted else "environment" if api_key else None,
        "credentialError": credential_error,
        "enabled": row.enabled and credential_error is None,
        "defaultRegion": row.default_region,
        "defaultDateFilter": row.default_date_filter,
        "defaultSortBy": row.default_sort_by,
        "defaultMaxPages": row.default_max_pages,
        "defaultTrim": row.default_trim,
        "transcriptEnabled": row.transcript_enabled,
        "aiTranscriptFallbackEnabled": row.ai_transcript_fallback_enabled,
        "downloadMediaEnabled": row.download_media_enabled,
        "globalDiscoveryIntervalMinutes": row.global_discovery_interval_minutes,
        "dailyCreditLimit": row.daily_credit_limit,
        "monthlyCreditLimit": row.monthly_credit_limit,
        "warningThresholdPercent": row.warning_threshold_percent,
        "criticalThresholdPercent": row.critical_threshold_percent,
        "adaptiveSchedulerEnabled": row.adaptive_scheduler_enabled,
        "health": {
            "status": "CREDENTIAL_ERROR" if credential_error else row.provider_health_status,
            "lastCheckedAt": _iso(row.last_health_checked_at),
            "lastSuccessfulRequestAt": _iso(row.last_successful_request_at),
            "lastError": credential_error or row.last_provider_error,
            "requestsToday": usage["today"]["requests"],
            "creditsToday": usage["today"]["total_credits"],
            "creditsThisMonth": usage["month"]["total_credits"],
        },
    }


@router.get("/settings")
def read_settings(db: Db) -> dict[str, Any]:
    return _settings_response(db, get_tiktok_settings(db))


@router.put("/settings", dependencies=[Depends(require_internal_token)])
def update_settings(payload: TikTokSettingsUpdate, db: Db) -> dict[str, Any]:
    row = get_tiktok_settings(db)
    changes = payload.model_dump(exclude_unset=True, exclude={"api_key", "clear_api_key"})
    key_changed = payload.api_key is not None or payload.clear_api_key
    submitted_key = payload.api_key.get_secret_value() if payload.api_key is not None else None
    will_enable = False if payload.clear_api_key else bool(changes.get("enabled", row.enabled))
    try:
        existing_key = None if submitted_key or payload.clear_api_key else get_tiktok_api_key(row)
    except SecretDecryptionError:
        existing_key = None
    candidate_key = submitted_key or existing_key
    if will_enable and not candidate_key:
        raise HTTPException(status_code=422, detail="API key valid harus dikonfigurasi sebelum discovery diaktifkan.")
    if will_enable and (submitted_key or row.provider_health_status != "CONNECTED"):
        try:
            test_provider_connection(db, row, api_key=submitted_key)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"API key gagal divalidasi: {exc}") from exc
    field_map = {
        "default_region": "default_region", "default_date_filter": "default_date_filter",
        "default_sort_by": "default_sort_by", "default_max_pages": "default_max_pages",
        "default_trim": "default_trim", "transcript_enabled": "transcript_enabled",
        "ai_transcript_fallback_enabled": "ai_transcript_fallback_enabled",
        "download_media_enabled": "download_media_enabled",
        "global_discovery_interval_minutes": "global_discovery_interval_minutes",
        "daily_credit_limit": "daily_credit_limit", "monthly_credit_limit": "monthly_credit_limit",
        "warning_threshold_percent": "warning_threshold_percent",
        "critical_threshold_percent": "critical_threshold_percent",
        "adaptive_scheduler_enabled": "adaptive_scheduler_enabled", "enabled": "enabled", "provider": "provider",
    }
    for incoming, target in field_map.items():
        if incoming in changes and (changes[incoming] is not None or incoming in {"daily_credit_limit", "monthly_credit_limit"}):
            setattr(row, target, changes[incoming])
    if payload.api_key is not None:
        row.api_key_encrypted = encrypt_secret(submitted_key)
        if not will_enable:
            row.provider_health_status = "UNKNOWN"
        row.last_provider_error = None
    elif payload.clear_api_key:
        row.api_key_encrypted = None
        row.enabled = False
        row.provider_health_status = "NOT_CONFIGURED"
        row.last_provider_error = None
    if row.warning_threshold_percent >= row.critical_threshold_percent:
        raise HTTPException(status_code=422, detail="Warning threshold harus lebih kecil daripada critical threshold.")
    db.commit()
    db.refresh(row)
    logger.info(
        "tiktok.settings.updated",
        extra={"provider": row.provider, "key_changed": key_changed, "enabled": row.enabled},
    )
    return _settings_response(db, row)


@router.post("/settings/test-connection", dependencies=[Depends(require_internal_token)])
def test_connection(payload: TikTokConnectionTest, db: Db) -> dict[str, Any]:
    row = get_tiktok_settings(db)
    key = payload.api_key.get_secret_value() if payload.api_key else None
    try:
        return test_provider_connection(db, row, api_key=key)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/keywords")
def list_keywords(db: Db, include_inactive: bool = True) -> list[dict[str, Any]]:
    row = get_tiktok_settings(db)
    query = select(MasterTikTokKeyword)
    if not include_inactive:
        query = query.where(MasterTikTokKeyword.active.is_(True))
    keywords = db.scalars(query.order_by(MasterTikTokKeyword.priority, MasterTikTokKeyword.keyword)).all()
    return [_keyword_response(item, row) for item in keywords]


@router.post("/keywords", dependencies=[Depends(require_internal_token)], status_code=status.HTTP_201_CREATED)
def create_keyword(payload: TikTokKeywordCreate, db: Db) -> dict[str, Any]:
    duplicate = db.scalar(select(MasterTikTokKeyword).where(func.lower(MasterTikTokKeyword.keyword) == payload.keyword.lower()))
    if duplicate:
        if duplicate.active:
            raise HTTPException(status_code=409, detail="Keyword TikTok sudah digunakan.")
        for key, value in payload.model_dump().items():
            setattr(duplicate, key, value)
        row = duplicate
    else:
        row = MasterTikTokKeyword(**payload.model_dump())
        db.add(row)
    row.next_run_at = datetime.now(timezone.utc) if row.active else None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Keyword TikTok sudah digunakan.") from exc
    db.refresh(row)
    return _keyword_response(row, get_tiktok_settings(db))


@router.put("/keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def update_keyword(keyword_id: uuid.UUID, payload: TikTokKeywordUpdate, db: Db) -> dict[str, Any]:
    row = db.get(MasterTikTokKeyword, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword TikTok tidak ditemukan.")
    changes = payload.model_dump(exclude_unset=True)
    if changes.pop("use_global_interval", False):
        changes["frequency_minutes"] = None
    for key, value in changes.items():
        setattr(row, key, value)
    if row.active and row.next_run_at is None:
        row.next_run_at = datetime.now(timezone.utc)
    if not row.active:
        row.next_run_at = None
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Keyword TikTok sudah digunakan.") from exc
    db.refresh(row)
    return _keyword_response(row, get_tiktok_settings(db))


@router.delete("/keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def delete_keyword(keyword_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(MasterTikTokKeyword, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword TikTok tidak ditemukan.")
    row.active = False
    row.next_run_at = None
    db.commit()
    return {"id": str(row.id), "deleted": True}


@router.post("/keywords/{keyword_id}/run", dependencies=[Depends(require_internal_token)])
def run_keyword(keyword_id: uuid.UUID, db: Db) -> dict[str, Any]:
    keyword = db.get(MasterTikTokKeyword, keyword_id)
    if not keyword:
        raise HTTPException(status_code=404, detail="Keyword TikTok tidak ditemukan.")
    settings_row = get_tiktok_settings(db)
    _require_discovery_ready(settings_row)
    run = create_search_run(db, query=keyword.keyword, provider=settings_row.provider, keyword_id=keyword.id)
    keyword.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=effective_frequency(keyword, settings_row))
    db.commit()
    task = celery_app.send_task("fuel.tiktok.search", args=[str(run.id)], queue="tiktok")
    return {"run_id": str(run.id), "task_id": task.id, "status": run.status}


@router.post("/run-due", dependencies=[Depends(require_internal_token)])
def run_due_keywords(db: Db) -> dict[str, Any]:
    run_ids = schedule_due_keywords(db)
    tasks = [celery_app.send_task("fuel.tiktok.search", args=[str(run_id)], queue="tiktok") for run_id in run_ids]
    return {"runs": [str(item) for item in run_ids], "tasks": [task.id for task in tasks]}


@router.post("/manual-search", dependencies=[Depends(require_internal_token)])
def manual_search(payload: TikTokManualSearch, db: Db) -> dict[str, Any]:
    settings_row = get_tiktok_settings(db)
    _require_discovery_ready(settings_row)
    run = create_search_run(
        db,
        query=payload.query,
        provider=settings_row.provider,
        search_params=payload.model_dump(exclude={"query"}),
    )
    task = celery_app.send_task("fuel.tiktok.search", args=[str(run.id)], queue="tiktok")
    return {"run_id": str(run.id), "task_id": task.id, "status": run.status}


@router.get("/search-runs")
def list_search_runs(db: Db, limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    rows = db.scalars(select(TikTokSearchRun).order_by(TikTokSearchRun.started_at.desc()).limit(limit)).all()
    return {"items": [_run_response(db, row) for row in rows], "total": len(rows)}


@router.get("/search-runs/{run_id}")
def search_run_detail(run_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(TikTokSearchRun, run_id)
    if not row:
        raise HTTPException(status_code=404, detail="TikTok search run tidak ditemukan.")
    result = _run_response(db, row)
    requests = db.scalars(
        select(TikTokProviderRequest)
        .where(TikTokProviderRequest.search_run_id == row.id)
        .order_by(TikTokProviderRequest.requested_at)
    ).all()
    result["timeline"] = [
        {
            "operation": request.operation,
            "at": _iso(request.requested_at),
            "succeeded": request.succeeded,
            "statusCode": request.status_code,
            "credits": request.credits_used,
            "durationMs": request.duration_ms,
            "error": request.error_message,
        }
        for request in requests
    ]
    return result


@router.get("/videos")
def list_videos(
    db: Db,
    limit: int = Query(100, ge=1, le=500),
    status_filter: str | None = Query(None, alias="status"),
) -> dict[str, Any]:
    query = select(TikTokVideo)
    if status_filter:
        query = query.where(TikTokVideo.processing_status == status_filter)
    rows = db.scalars(query.order_by(TikTokVideo.first_seen_at.desc()).limit(limit)).all()
    return {"items": [_video_response(db, row) for row in rows], "total": len(rows)}


@router.get("/videos/{video_id}")
def video_detail(video_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(TikTokVideo, video_id)
    if not row:
        raise HTTPException(status_code=404, detail="Video TikTok tidak ditemukan.")
    result = _video_response(db, row)
    transcript = db.scalar(select(TikTokTranscript).where(TikTokTranscript.video_id == row.id))
    result["transcript"] = None if not transcript else {
        "status": transcript.status,
        "language": transcript.language,
        "text": transcript.transcript_text,
        "credits": transcript.credits_used,
    }
    result["rawResponse"] = row.raw_response
    return result


@router.post("/videos/{video_id}/reprocess", dependencies=[Depends(require_internal_token)])
def reprocess(video_id: uuid.UUID, payload: TikTokReprocessRequest, db: Db) -> dict[str, Any]:
    row = db.get(TikTokVideo, video_id)
    if not row:
        raise HTTPException(status_code=404, detail="Video TikTok tidak ditemukan.")
    return reprocess_video(db, row)


@router.get("/dashboard")
def dashboard(db: Db, period: str = Query("24h", pattern="^(24h|7d|30d)$")) -> dict[str, Any]:
    days = {"24h": 1, "7d": 7, "30d": 30}[period]
    since = datetime.now(timezone.utc) - timedelta(days=days)
    videos = db.scalars(select(TikTokVideo).where(TikTokVideo.first_seen_at >= since)).all()
    runs = db.scalars(select(TikTokSearchRun).where(TikTokSearchRun.started_at >= since)).all()
    incident_ids = {
        item[0]
        for item in db.execute(
            select(IncidentSignal.incident_id)
            .join(Signal, Signal.id == IncidentSignal.signal_id)
            .join(TikTokVideo, TikTokVideo.canonical_tiktok_post_id == Signal.source_record_id)
            .where(Signal.source_type == "TIKTOK", TikTokVideo.first_seen_at >= since)
        ).all()
    }
    usage = usage_totals(db)
    discovered_by_day: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    location_counts: dict[str, int] = {}
    for video in videos:
        day = video.first_seen_at.date().isoformat()
        discovered_by_day[day] = discovered_by_day.get(day, 0) + 1
        category = video.relevance_category or "UNCLASSIFIED"
        category_counts[category] = category_counts.get(category, 0) + 1
        detail = _video_response(db, video)
        if detail["location"]:
            location_counts[detail["location"]] = location_counts.get(detail["location"], 0) + 1
    keyword_rows = db.execute(
        select(MasterTikTokKeyword.keyword, func.count(TikTokVideoKeywordMatch.id))
        .join(TikTokVideoKeywordMatch, TikTokVideoKeywordMatch.keyword_id == MasterTikTokKeyword.id)
        .join(TikTokVideo, TikTokVideo.id == TikTokVideoKeywordMatch.video_id)
        .where(TikTokVideo.first_seen_at >= since)
        .group_by(MasterTikTokKeyword.keyword)
        .order_by(func.count(TikTokVideoKeywordMatch.id).desc())
        .limit(10)
    ).all()
    return {
        "period": period,
        "kpis": {
            "videosDiscovered": len(videos),
            "newVideos": sum(run.new_videos for run in runs),
            "relevantVideos": sum(video.processing_status == "PROCESSED" for video in videos),
            "tiktokIncidents": len(incident_ids),
            "creditsToday": usage["today"]["total_credits"],
            "creditsThisMonth": usage["month"]["total_credits"],
        },
        "videosOverTime": [{"date": key, "count": value} for key, value in sorted(discovered_by_day.items())],
        "byCategory": [{"category": key, "count": value} for key, value in sorted(category_counts.items(), key=lambda item: -item[1])],
        "byKeyword": [{"keyword": key, "count": value} for key, value in keyword_rows],
        "topLocations": [{"location": key, "count": value} for key, value in sorted(location_counts.items(), key=lambda item: -item[1])[:10]],
        "recentVideos": [_video_response(db, row) for row in videos[:20]],
    }


@router.get("/usage")
def usage(db: Db) -> dict[str, Any]:
    settings_row = get_tiktok_settings(db)
    totals = usage_totals(db)
    now = datetime.now(settings_row.created_at.tzinfo or timezone.utc)
    days_elapsed = max(1, now.day)
    projected = round(totals["month"]["total_credits"] / days_elapsed * 30)
    relevant = db.scalar(select(func.count()).select_from(TikTokVideo).where(TikTokVideo.processing_status == "PROCESSED")) or 0
    incidents = db.scalar(select(func.coalesce(func.sum(TikTokSearchRun.incidents_created), 0))) or 0
    monthly_limit = settings_row.monthly_credit_limit
    return {
        **totals,
        "monthlyLimit": monthly_limit,
        "remainingBudget": max(0, monthly_limit - totals["month"]["total_credits"]) if monthly_limit else None,
        "projectedMonthEndUsage": projected,
        "creditsPerRelevantVideo": round(totals["month"]["total_credits"] / relevant, 2) if relevant else None,
        "creditsPerIncident": round(totals["month"]["total_credits"] / incidents, 2) if incidents else None,
    }


def _keyword_response(item: MasterTikTokKeyword, settings_row: TikTokSettings) -> dict[str, Any]:
    return {
        "id": str(item.id), "keyword": item.keyword, "category": item.category, "priority": item.priority,
        "frequencyMinutes": item.frequency_minutes, "effectiveFrequencyMinutes": effective_frequency(item, settings_row),
        "usesGlobalInterval": item.frequency_minutes is None, "active": item.active, "dateFilter": item.date_filter,
        "sortBy": item.sort_by, "region": item.region, "maxPages": item.max_pages,
        "lastRunAt": _iso(item.last_run_at), "nextRunAt": _iso(item.next_run_at),
        "lastResultCount": item.last_result_count, "lastNewVideoCount": item.last_new_video_count,
        "lastRelevantCount": item.last_relevant_count,
    }


def _run_response(db: Session, item: TikTokSearchRun) -> dict[str, Any]:
    keyword = db.get(MasterTikTokKeyword, item.keyword_id) if item.keyword_id else None
    duration = (item.finished_at - item.started_at).total_seconds() if item.finished_at else None
    return {
        "id": str(item.id), "keywordId": str(item.keyword_id) if item.keyword_id else None,
        "keyword": keyword.keyword if keyword else item.query_text, "provider": item.provider,
        "startedAt": _iso(item.started_at), "finishedAt": _iso(item.finished_at), "durationSeconds": duration,
        "status": item.status, "pages": item.pages_requested, "apiRequests": item.api_requests,
        "credits": item.credits_used, "results": item.results_found, "newVideos": item.new_videos,
        "duplicates": item.duplicate_videos, "relevant": item.relevant_videos,
        "irrelevant": item.irrelevant_videos, "uncertain": item.uncertain_videos,
        "transcriptsRequested": item.transcripts_requested, "transcriptsFound": item.transcripts_found,
        "incidents": item.incidents_created, "error": item.error_message,
    }


def _video_response(db: Session, item: TikTokVideo) -> dict[str, Any]:
    matches = db.execute(
        select(MasterTikTokKeyword.keyword)
        .join(TikTokVideoKeywordMatch, TikTokVideoKeywordMatch.keyword_id == MasterTikTokKeyword.id)
        .where(TikTokVideoKeywordMatch.video_id == item.id)
    ).scalars().all()
    event = None
    incident = None
    if item.canonical_tiktok_post_id:
        signal = db.scalar(
            select(Signal).where(Signal.source_type == "TIKTOK", Signal.source_record_id == item.canonical_tiktok_post_id)
        )
        if signal:
            event = db.scalar(select(Event).where(Event.signal_id == signal.id))
            incident = db.scalar(select(Incident).join(IncidentSignal).where(IncidentSignal.signal_id == signal.id))
    nearest_tbbm = incident.nearest_tbbm.name if incident and incident.nearest_tbbm else None
    location = event.location_raw if event else None
    return {
        "id": str(item.id), "providerVideoId": item.provider_video_id, "url": item.video_url,
        "thumbnailUrl": item.thumbnail_url, "author": f"@{item.author_username}" if item.author_username else "—",
        "authorDisplayName": item.author_display_name, "caption": item.caption, "hashtags": item.hashtags or [],
        "createdAt": _iso(item.tiktok_created_at), "firstSeenAt": _iso(item.first_seen_at),
        "views": item.view_count or 0, "likes": item.like_count or 0, "comments": item.comment_count or 0,
        "shares": item.share_count or 0, "matchedKeywords": matches, "relevanceScore": item.relevance_score,
        "category": item.relevance_category, "location": location, "nearestTbbm": nearest_tbbm,
        "processingStatus": item.processing_status, "incidentId": incident.id if incident else None,
        "incidentCode": incident.incident_code if incident else None,
    }


def _require_discovery_ready(settings_row: TikTokSettings) -> None:
    if not settings_row.enabled:
        raise HTTPException(status_code=409, detail="TikTok Discovery belum diaktifkan.")
    try:
        api_key = get_tiktok_api_key(settings_row)
    except SecretDecryptionError as exc:
        raise HTTPException(
            status_code=409,
            detail="Credential TikTok tidak dapat didekripsi. Simpan kembali API key melalui Settings.",
        ) from exc
    if not api_key:
        raise HTTPException(status_code=409, detail="ScrapeCreators API key belum dikonfigurasi.")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None
