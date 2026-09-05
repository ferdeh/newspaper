from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated

from celery import states
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from redis import Redis
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.collectors.news.adapters import RSSNewsAdapter
from app.config import settings
from app.database import get_db
from app.models import (
    AlertHistory,
    AlertRule,
    Article,
    EmailAccount,
    Event,
    Incident,
    IncidentSignal,
    MasterLocation,
    MasterSpbu,
    MasterTbbm,
    NewsKeyword,
    NewsSource,
    NotificationJob,
    RawArticle,
    Signal,
    TikTokPost,
    TikTokQuery,
    WorkerHeartbeat,
)
from app.schemas import (
    AlertRuleCreate,
    GoogleMapsCredentialUpdate,
    NewsIngest,
    NewsKeywordCreate,
    NewsKeywordUpdate,
    RSSCollect,
    SourceCreate,
    SourceUpdate,
    TikTokIngest,
)
from app.services import analytics
from app.services.alerts import dispatch_queued_alerts, evaluate_incident_alerts
from app.services.geography import enrich_all_incidents
from app.services.intelligence import risk_band
from app.services.pipeline import ingest_news, ingest_tiktok
from app.services.providers import GoogleGeocodingProvider
from app.services.secrets import (
    GOOGLE_MAPS_SECRET_NAME,
    delete_runtime_secret,
    get_google_maps_api_key,
    get_google_maps_api_key_source,
    write_runtime_secret,
)
from app.services.tbbm_runtime import runtime_tbbm_conditions, verified_tbbm
from app.workers.celery_app import celery_app

router = APIRouter()
Db = Annotated[Session, Depends(get_db)]


def parse_analytics_filters(
    date_from: date | None = None, date_to: date | None = None, province: str | None = None,
    regency: str | None = None, product: str | None = None, event: str | None = None,
    source: str | None = None, severity: str | None = None, terminal: uuid.UUID | None = None,
) -> dict:
    return {key: value for key, value in locals().items() if value not in (None, "")}


AnalyticsFilters = Annotated[dict, Depends(parse_analytics_filters)]


def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings.internal_api_token.get_secret_value()
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Valid internal token required")


def incident_risk(item: Incident) -> float:
    return item.hsse_risk_score if item.event_category == "HSSE" else item.supply_risk_score


def incident_dict(item: Incident, detail: bool = False) -> dict:
    location_name = item.location.normalized_name if item.location else item.geocoded_address or "Unresolved"
    nearest = verified_tbbm(item.nearest_tbbm)
    serving = verified_tbbm(item.serving_tbbm)
    result = {
        "id": item.id,
        "incident_code": item.incident_code,
        "date": item.first_signal_at.isoformat(),
        "last_signal_at": item.last_signal_at.isoformat(),
        "location": location_name,
        "province": item.location.province if item.location else None,
        "regency": item.location.regency if item.location else None,
        "latitude": item.latitude,
        "longitude": item.longitude,
        "geocoded_address": item.geocoded_address,
        "geocoding_provider": item.geocoding_provider,
        "geocoding_confidence": item.geocoding_confidence,
        "category": item.event_category,
        "event": item.primary_event_type,
        "products": item.products,
        "severity": risk_band(incident_risk(item)),
        "source_severity": item.severity,
        "risk": incident_risk(item),
        "supply_risk": item.supply_risk_score,
        "hsse_risk": item.hsse_risk_score,
        "confidence": item.confidence,
        "news_count": item.news_count,
        "tiktok_count": item.tiktok_count,
        "signal_count": item.signal_count,
        "trend": item.trend_status,
        "status": item.status,
        "first_detection_source": item.first_detection_source,
        "tiktok_lead_time_minutes": item.tiktok_lead_time_minutes,
        "nearest_terminal": nearest.name if nearest else None,
        "nearest_terminal_id": str(nearest.id) if nearest else None,
        "nearest_terminal_code": nearest.tbbm_code if nearest else None,
        "nearest_terminal_latitude": nearest.latitude if nearest else None,
        "nearest_terminal_longitude": nearest.longitude if nearest else None,
        "nearest_terminal_distance_km": item.nearest_terminal_distance_km if nearest else None,
        "nearest_terminal_distance_source": item.nearest_terminal_distance_source if nearest else None,
        "nearest_terminal_duration_minutes": item.nearest_terminal_duration_minutes if nearest else None,
        "serving_terminal": serving.name if serving else None,
        "serving_terminal_id": str(serving.id) if serving else None,
        "serving_terminal_code": serving.tbbm_code if serving else None,
        "serving_terminal_latitude": serving.latitude if serving else None,
        "serving_terminal_longitude": serving.longitude if serving else None,
        "spbu": item.spbu.spbu_name if item.spbu else None,
        "location_resolution_status": item.location_resolution_status,
    }
    if detail:
        signals = []
        event_types: set[str] = set()
        for link in sorted(item.signal_links, key=lambda value: value.signal.published_at):
            signal = link.signal
            event = signal.event
            false_positive = signal.processing_status == "ARCHIVED_FALSE_POSITIVE"
            if event and not false_positive:
                event_types.update(event.structured_payload.get("event_types", [event.event_type]))
            signals.append({
                "id": signal.id, "source_type": signal.source_type, "title": signal.title, "content": signal.content,
                "url": signal.source_url, "published_at": signal.published_at.isoformat(), "relevance": signal.relevance_score,
                "event_types": event.structured_payload.get("event_types", []) if event else [],
                "confidence": event.confidence if event else None, "is_primary": link.is_primary_signal,
                "processing_status": signal.processing_status,
                "false_positive_reason": event.structured_payload.get("false_positive_reason") if event else None,
            })
        result["event_types"] = sorted(event_types)
        result["signals"] = signals
        result["risk_history"] = [
            {"supply_risk": row.supply_risk_score, "hsse_risk": row.hsse_risk_score, "severity": row.severity, "calculated_at": row.calculated_at.isoformat()}
            for row in sorted(item.risk_history, key=lambda value: value.calculated_at)
        ]
    return result


INCIDENT_OPTIONS = (
    selectinload(Incident.location),
    selectinload(Incident.spbu),
    selectinload(Incident.nearest_tbbm),
    selectinload(Incident.serving_tbbm),
)


@router.get("/health")
def api_health() -> dict:
    return {"status": "healthy", "service": "api"}


@router.get("/incidents")
def list_incidents(
    db: Db,
    date_from: date | None = None,
    date_to: date | None = None,
    province: str | None = None,
    regency: str | None = None,
    product: str | None = None,
    event: str | None = None,
    source: str | None = None,
    severity: str | None = None,
    terminal: uuid.UUID | None = None,
    status: str | None = None,
    sort_by: str = Query("date", pattern="^(date|risk|signals)$"),
    sort_dir: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    query = select(Incident).options(*INCIDENT_OPTIONS)
    if date_from:
        query = query.where(Incident.first_signal_at >= datetime.combine(date_from, datetime.min.time()).astimezone())
    if date_to:
        query = query.where(Incident.first_signal_at < datetime.combine(date_to, datetime.max.time()).astimezone())
    if province or regency:
        query = query.join(Incident.location)
        if province:
            query = query.where(func.lower(MasterLocation.province) == province.lower())
        if regency:
            query = query.where(func.lower(MasterLocation.regency) == regency.lower())
    if product:
        query = query.where(Incident.products.contains([product.upper()]))
    if event:
        query = query.where(Incident.primary_event_type == event.upper())
    if source:
        query = query.join(IncidentSignal).join(Signal).where(Signal.source_type == source.upper()).distinct()
    if terminal:
        allowed = db.scalar(select(MasterTbbm.id).where(MasterTbbm.id == terminal, *runtime_tbbm_conditions()))
        if not allowed:
            return {"items": [], "total": 0, "limit": limit, "offset": offset}
        query = query.where((Incident.nearest_tbbm_id == terminal) | (Incident.serving_tbbm_id == terminal))
    if status:
        query = query.where(Incident.status == status.upper())
    items = db.scalars(query).unique().all()
    if severity:
        items = [item for item in items if risk_band(incident_risk(item)) == severity.upper()]
    key = {
        "date": lambda item: item.first_signal_at,
        "risk": incident_risk,
        "signals": lambda item: item.signal_count,
    }[sort_by]
    items.sort(key=key, reverse=sort_dir == "desc")
    total = len(items)
    return {"items": [incident_dict(item) for item in items[offset:offset + limit]], "total": total, "limit": limit, "offset": offset}


@router.get("/incidents/{incident_id}")
def get_incident(incident_id: int, db: Db) -> dict:
    item = db.scalar(
        select(Incident).options(
            *INCIDENT_OPTIONS,
            selectinload(Incident.signal_links).selectinload(IncidentSignal.signal).selectinload(Signal.event),
            selectinload(Incident.risk_history),
        ).where(Incident.id == incident_id)
    )
    if not item:
        raise HTTPException(404, "Incident not found")
    result = incident_dict(item, detail=True)
    jobs = db.scalars(
        select(NotificationJob)
        .where(NotificationJob.incident_id == incident_id, NotificationJob.channel == "EMAIL")
        .order_by(NotificationJob.created_at.desc())
    ).all()
    result["notifications"] = [
        {
            "id": str(job.id),
            "channel": job.channel,
            "provider": job.provider,
            "sender": (db.get(EmailAccount, job.sender_account_id).account_name if job.sender_account_id and db.get(EmailAccount, job.sender_account_id) else None),
            "status": job.status,
            "attempts": job.attempt_count,
            "max_attempts": job.max_attempts,
            "sent_at": job.sent_at.isoformat() if job.sent_at else None,
            "error_code": job.error_code,
            "reconnect_required": job.error_code == "EMAIL_ACCOUNT_RECONNECT_REQUIRED",
        }
        for job in jobs
    ]
    return result


@router.get("/news")
def list_news(db: Db, source_id: int | None = None, date_from: date | None = None, limit: int = Query(100, le=500)) -> dict:
    query = (
        select(Article, RawArticle, NewsSource, Signal, Event, Incident)
        .join(RawArticle, Article.raw_article_id == RawArticle.id)
        .join(NewsSource, RawArticle.source_id == NewsSource.id)
        .join(Signal, (Signal.source_type == "NEWS") & (Signal.source_record_id == RawArticle.id))
        .outerjoin(Event, Event.signal_id == Signal.id)
        .outerjoin(IncidentSignal, IncidentSignal.signal_id == Signal.id)
        .outerjoin(Incident, Incident.id == IncidentSignal.incident_id)
        .order_by(Article.published_at.desc())
        .limit(limit)
    )
    if source_id:
        query = query.where(NewsSource.id == source_id)
    if date_from:
        query = query.where(Article.published_at >= datetime.combine(date_from, datetime.min.time()).astimezone())
    rows = db.execute(query).all()
    return {"items": [{
        "id": article.id, "published_at": article.published_at.isoformat(), "source": source.name, "title": article.title,
        "url": raw.canonical_url, "relevance": article.relevance_score, "event": event.event_type if event else None,
        "location": event.location_raw if event else None, "incident_id": incident.id if incident else None,
        "incident_code": incident.incident_code if incident else None, "demo": raw.canonical_url.startswith("https://demo."),
    } for article, raw, source, signal, event, incident in rows], "total": len(rows)}


@router.get("/tiktok")
def list_tiktok(db: Db, limit: int = Query(100, le=500)) -> dict:
    rows = db.execute(
        select(TikTokPost, Signal, Event, Incident)
        .join(Signal, (Signal.source_type == "TIKTOK") & (Signal.source_record_id == TikTokPost.id))
        .outerjoin(Event, Event.signal_id == Signal.id)
        .outerjoin(IncidentSignal, IncidentSignal.signal_id == Signal.id)
        .outerjoin(Incident, Incident.id == IncidentSignal.incident_id)
        .order_by(TikTokPost.published_at.desc()).limit(limit)
    ).all()
    return {"items": [{
        "id": post.id, "published_at": post.published_at.isoformat(), "creator": f"@{post.username}", "caption": post.caption,
        "hashtags": post.hashtags, "views": post.view_count, "url": post.url, "event": event.event_type if event else None,
        "location": event.location_raw if event else post.raw_location_text, "confidence": event.confidence if event else None,
        "incident_id": incident.id if incident else None, "incident_code": incident.incident_code if incident else None, "demo": post.url.startswith("https://www.tiktok.com/@demo"),
    } for post, signal, event, incident in rows], "total": len(rows), "disclaimer": "Public TikTok posts are early signals, not verified facts."}


@router.get("/analytics/overview")
def analytics_overview(db: Db, filters: AnalyticsFilters) -> dict:
    return analytics.overview(db, **filters)


@router.get("/analytics/geography")
def analytics_geography(db: Db, filters: AnalyticsFilters) -> list[dict]:
    return analytics.geography(db, **filters)


@router.get("/analytics/products")
def analytics_products(db: Db, filters: AnalyticsFilters) -> list[dict]:
    return analytics.products(db, **filters)


@router.get("/analytics/events")
def analytics_events(db: Db, filters: AnalyticsFilters) -> list[dict]:
    return analytics.events(db, **filters)


@router.get("/analytics/terminals")
def analytics_terminals(db: Db, filters: AnalyticsFilters) -> list[dict]:
    return analytics.terminals(db, **filters)


@router.get("/analytics/tiktok")
def analytics_tiktok(db: Db, filters: AnalyticsFilters) -> dict:
    return analytics.tiktok_early_warning(db, **filters)


@router.get("/analytics/hsse")
def analytics_hsse(db: Db, filters: AnalyticsFilters) -> dict:
    return analytics.hsse(db, **filters)


@router.get("/analytics/executive-summary")
def analytics_executive_summary(db: Db, filters: AnalyticsFilters) -> dict:
    return analytics.executive_summary(db, **filters)


@router.get("/alerts")
def list_alerts(db: Db, limit: int = Query(100, le=500)) -> dict:
    rows = db.scalars(select(AlertHistory).order_by(AlertHistory.id.desc()).limit(limit)).all()
    return {"items": [{
        "id": row.id, "incident_id": row.incident_id, "alert_type": row.alert_type, "recipient": row.recipient,
        "risk": row.risk_score, "severity": row.severity, "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "delivery_status": row.delivery_status, "provider_message_id": row.provider_message_id,
    } for row in rows], "total": len(rows)}


@router.get("/system/status")
def system_status(db: Db) -> dict:
    database_ok = False
    redis_ok = False
    try:
        database_ok = db.execute(text("SELECT 1")).scalar() == 1
    except Exception:
        pass
    try:
        redis_ok = bool(Redis.from_url(settings.redis_url, socket_timeout=1).ping())
    except Exception:
        pass
    heartbeats = {row.service: row for row in db.scalars(select(WorkerHeartbeat)).all()}
    names = [
        "news-worker", "tiktok-worker", "nlp-worker", "geo-worker", "incident-worker", "analytics-worker",
        "alert-worker", "notification-worker", "whatsapp-worker", "scheduler",
    ]
    services = [{
        "name": name, "status": heartbeats[name].status if name in heartbeats else "STARTING",
        "last_seen_at": heartbeats[name].last_seen_at.isoformat() if name in heartbeats else None,
        "queue_depth": heartbeats[name].queue_depth if name in heartbeats else 0,
    } for name in names]
    pending_nlp = db.scalar(select(func.count(Signal.id)).where(Signal.processing_status.in_(["PENDING", "RETRY"]))) or 0
    unresolved = db.scalar(select(func.count(Incident.id)).where(Incident.location_resolution_status == "UNRESOLVED")) or 0
    pending_alerts = db.scalar(select(func.count(AlertHistory.id)).where(AlertHistory.delivery_status.in_(["QUEUED", "RETRY"]))) or 0
    pending_notifications = db.scalar(
        select(func.count(NotificationJob.id)).where(NotificationJob.status.in_(["PENDING", "RETRY", "PROCESSING"]))
    ) or 0
    sent = db.scalar(select(func.count(AlertHistory.id)).where(AlertHistory.sent_at.is_not(None))) or 0
    successful = db.scalar(select(func.count(AlertHistory.id)).where(AlertHistory.delivery_status.in_(["SENT", "MOCK_SENT"]))) or 0
    return {
        "api": "HEALTHY", "database": "HEALTHY" if database_ok else "UNHEALTHY", "redis": "HEALTHY" if redis_ok else "UNHEALTHY",
        "services": services, "queues": {
            "pending_nlp": pending_nlp, "pending_geo": 0, "unresolved_locations": unresolved,
            "alert_queue": pending_alerts, "notification_queue": pending_notifications,
        },
        "whatsapp_delivery_success_rate": round(successful / sent * 100, 1) if sent else 100.0,
        "last_analytics_refresh": db.scalar(select(func.max(analytics.AnalyticsDaily.created_at))).isoformat() if db.scalar(select(func.max(analytics.AnalyticsDaily.created_at))) else None,
    }


@router.post("/internal/signals/news", dependencies=[Depends(require_internal_token)])
def internal_news(payload: NewsIngest, db: Db) -> dict:
    signal, incident = ingest_news(db, payload)
    if incident:
        evaluate_incident_alerts(db, incident)
        db.commit()
    return {"signal_id": signal.id, "incident_id": incident.id if incident else None, "status": signal.processing_status}


@router.post("/internal/signals/tiktok", dependencies=[Depends(require_internal_token)])
def internal_tiktok(payload: TikTokIngest, db: Db) -> dict:
    signal, incident = ingest_tiktok(db, payload)
    if incident:
        evaluate_incident_alerts(db, incident)
        db.commit()
    return {"signal_id": signal.id, "incident_id": incident.id if incident else None, "status": signal.processing_status}


@router.post("/internal/collectors/rss", dependencies=[Depends(require_internal_token)])
def internal_rss(payload: RSSCollect, db: Db) -> dict:
    candidates = RSSNewsAdapter().fetch(str(payload.feed_url))
    created = []
    for candidate in candidates:
        signal, incident = ingest_news(db, NewsIngest(
            source_name=payload.source_name, source_domain=payload.source_domain, url=candidate.url,
            title=candidate.title, content=candidate.content, published_at=candidate.published_at,
        ))
        created.append({"signal_id": signal.id, "incident_id": incident.id if incident else None})
    return {"fetched": len(candidates), "created": created}


@router.post(
    "/internal/intelligence/refresh",
    dependencies=[Depends(require_internal_token)],
    status_code=status.HTTP_202_ACCEPTED,
)
def start_intelligence_refresh() -> dict:
    task = celery_app.send_task("fuel.intelligence.refresh", queue="analytics")
    return {"job_id": task.id, "status": states.PENDING, "done": False}


@router.get("/internal/intelligence/refresh/{job_id}", dependencies=[Depends(require_internal_token)])
def intelligence_refresh_status(job_id: uuid.UUID) -> dict:
    result = celery_app.AsyncResult(str(job_id))
    task_status = result.state
    payload = {
        "job_id": str(job_id),
        "status": task_status,
        "done": task_status in states.READY_STATES,
        "successful": task_status == states.SUCCESS,
    }
    if task_status == states.SUCCESS and isinstance(result.result, dict):
        payload["result"] = result.result
    elif task_status in states.EXCEPTION_STATES:
        payload["detail"] = "Pembaruan intelligence gagal. Periksa log worker untuk detail."
    return payload


@router.post("/internal/alerts/dispatch", dependencies=[Depends(require_internal_token)])
def internal_dispatch_alerts(db: Db) -> dict:
    return {"sent": dispatch_queued_alerts(db)}


@router.post("/internal/geography/enrich", dependencies=[Depends(require_internal_token)])
def internal_enrich_geography(db: Db, force_google: bool = True) -> dict:
    return enrich_all_incidents(db, force_google=force_google)


def news_source_dict(row: NewsSource) -> dict:
    return {
        "id": row.id, "name": row.name, "coverage_area": row.coverage_area, "domain": row.domain,
        "source_type": row.source_type, "feed_url": row.feed_url, "priority": row.priority,
        "credibility": row.credibility_score, "fetch_frequency_minutes": row.fetch_frequency_minutes,
        "active": row.is_active, "last_success": row.last_success_at.isoformat() if row.last_success_at else None,
        "last_error": row.last_error,
    }


@router.get("/admin/news-sources")
def admin_news_sources(
    db: Db,
    search: str | None = Query(None, max_length=200),
    sort_by: str = Query("priority"),
    sort_order: str = Query("asc", pattern="^(asc|desc)$"),
    page: int | None = Query(None, ge=1),
    per_page: int = Query(25, ge=10, le=100),
) -> list[dict] | dict:
    query = select(NewsSource).where(NewsSource.deleted_at.is_(None))
    normalized_search = search.strip() if search else ""
    if normalized_search:
        escaped = normalized_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        query = query.where(or_(
            NewsSource.name.ilike(pattern, escape="\\"),
            NewsSource.coverage_area.ilike(pattern, escape="\\"),
            NewsSource.domain.ilike(pattern, escape="\\"),
            NewsSource.source_type.ilike(pattern, escape="\\"),
            NewsSource.feed_url.ilike(pattern, escape="\\"),
            NewsSource.last_error.ilike(pattern, escape="\\"),
        ))

    sort_columns = {
        "name": NewsSource.name,
        "coverage_area": NewsSource.coverage_area,
        "domain": NewsSource.domain,
        "source_type": NewsSource.source_type,
        "feed_url": NewsSource.feed_url,
        "priority": NewsSource.priority,
        "credibility": NewsSource.credibility_score,
        "fetch_frequency_minutes": NewsSource.fetch_frequency_minutes,
        "active": NewsSource.is_active,
        "last_success": NewsSource.last_success_at,
        "last_error": NewsSource.last_error,
    }
    if sort_by not in sort_columns:
        raise HTTPException(status_code=422, detail="Kolom sort News Sources tidak valid.")
    sort_column = sort_columns[sort_by]
    order_expression = sort_column.desc().nullslast() if sort_order == "desc" else sort_column.asc().nullslast()
    query = query.order_by(order_expression, NewsSource.name.asc(), NewsSource.id.asc())

    if page is None:
        return [news_source_dict(row) for row in db.scalars(query).all()]

    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0
    rows = db.scalars(query.offset((page - 1) * per_page).limit(per_page)).all()
    return {
        "items": [news_source_dict(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
    }


@router.post("/admin/news-sources", dependencies=[Depends(require_internal_token)], status_code=status.HTTP_201_CREATED)
def create_news_source(payload: SourceCreate, db: Db) -> dict:
    values = payload.model_dump(mode="json")
    feed_url = values.get("feed_url")
    identity = NewsSource.feed_url == feed_url if feed_url else (
        (func.lower(NewsSource.domain) == payload.domain) & (NewsSource.source_type == "INTERNAL")
    )
    row = db.scalar(select(NewsSource).where(identity))
    if row and row.deleted_at is None:
        raise HTTPException(status_code=409, detail="Feed URL source sudah digunakan.")
    if row:
        for key, value in values.items():
            setattr(row, key, value)
        row.deleted_at = None
        row.last_error = None
    else:
        row = NewsSource(**values)
        db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Feed URL source sudah digunakan.") from exc
    return news_source_dict(row)


@router.patch("/admin/news-sources/{source_id}", dependencies=[Depends(require_internal_token)])
def update_news_source(source_id: int, payload: SourceUpdate, db: Db) -> dict:
    row = db.get(NewsSource, source_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="News source tidak ditemukan.")
    values = payload.model_dump(mode="json", exclude_unset=True)
    source_type = values.get("source_type", row.source_type)
    feed_url = values.get("feed_url", row.feed_url)
    is_active = values.get("is_active", row.is_active)
    if source_type != "INTERNAL" and is_active and not feed_url:
        raise HTTPException(status_code=422, detail="Source RSS/HTML yang aktif wajib memiliki feed URL.")
    if "feed_url" in values and values["feed_url"] and values["feed_url"] != row.feed_url:
        duplicate_id = db.scalar(
            select(NewsSource.id).where(
                NewsSource.feed_url == values["feed_url"],
                NewsSource.id != source_id,
            )
        )
        if duplicate_id:
            raise HTTPException(status_code=409, detail="Feed URL source sudah digunakan.")
    for key, value in values.items():
        setattr(row, key, value)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Feed URL source sudah digunakan.") from exc
    return news_source_dict(row)


@router.delete("/admin/news-sources/{source_id}", dependencies=[Depends(require_internal_token)])
def delete_news_source(source_id: int, db: Db) -> dict:
    row = db.get(NewsSource, source_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="News source tidak ditemukan.")
    row.is_active = False
    row.deleted_at = datetime.now(settings.timezone)
    db.commit()
    return {"id": row.id, "deleted": True}


def news_keyword_dict(row: NewsKeyword) -> dict:
    return {
        "id": row.id,
        "keyword": row.keyword,
        "active": row.is_active,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("/admin/news-keywords")
def admin_news_keywords(db: Db) -> list[dict]:
    rows = db.scalars(select(NewsKeyword).where(
        NewsKeyword.deleted_at.is_(None),
    ).order_by(NewsKeyword.keyword, NewsKeyword.id)).all()
    return [news_keyword_dict(row) for row in rows]


@router.post("/admin/news-keywords", dependencies=[Depends(require_internal_token)], status_code=status.HTTP_201_CREATED)
def create_news_keyword(payload: NewsKeywordCreate, db: Db) -> dict:
    values = payload.model_dump()
    row = db.scalar(select(NewsKeyword).where(func.lower(NewsKeyword.keyword) == payload.keyword.lower()))
    if row and row.deleted_at is None:
        raise HTTPException(status_code=409, detail="News keyword sudah digunakan.")
    if row:
        for key, value in values.items():
            setattr(row, key, value)
        row.deleted_at = None
    else:
        row = NewsKeyword(**values)
        db.add(row)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="News keyword sudah digunakan.") from exc
    return news_keyword_dict(row)


@router.patch("/admin/news-keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def update_news_keyword(keyword_id: int, payload: NewsKeywordUpdate, db: Db) -> dict:
    row = db.get(NewsKeyword, keyword_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="News keyword tidak ditemukan.")
    values = payload.model_dump(exclude_unset=True)
    if "keyword" in values and values["keyword"].lower() != row.keyword.lower():
        duplicate_id = db.scalar(select(NewsKeyword.id).where(
            func.lower(NewsKeyword.keyword) == values["keyword"].lower(),
            NewsKeyword.id != keyword_id,
        ))
        if duplicate_id:
            raise HTTPException(status_code=409, detail="News keyword sudah digunakan.")
    for key, value in values.items():
        setattr(row, key, value)
    try:
        db.commit()
        db.refresh(row)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="News keyword sudah digunakan.") from exc
    return news_keyword_dict(row)


@router.delete("/admin/news-keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def delete_news_keyword(keyword_id: int, db: Db) -> dict:
    row = db.get(NewsKeyword, keyword_id)
    if not row or row.deleted_at is not None:
        raise HTTPException(status_code=404, detail="News keyword tidak ditemukan.")
    row.is_active = False
    row.deleted_at = datetime.now(settings.timezone)
    db.commit()
    return {"id": row.id, "deleted": True}


@router.get("/admin/tiktok-queries")
def admin_tiktok_queries(db: Db) -> list[dict]:
    return [{"id": row.id, "keyword": row.keyword, "location_scope": row.location_scope, "location_name": row.location_name, "priority": row.priority, "active": row.is_active, "last_run": row.last_run_at.isoformat() if row.last_run_at else None} for row in db.scalars(select(TikTokQuery).order_by(TikTokQuery.priority, TikTokQuery.keyword))]


@router.get("/admin/alert-rules")
def admin_alert_rules(db: Db) -> list[dict]:
    return [{"id": row.id, "name": row.name, "event_category": row.event_category, "minimum_risk": row.minimum_risk, "minimum_confidence": row.minimum_confidence, "minimum_independent_sources": row.minimum_independent_sources, "cooldown_minutes": row.cooldown_minutes, "active": row.is_active} for row in db.scalars(select(AlertRule))]


@router.post("/admin/alert-rules", dependencies=[Depends(require_internal_token)])
def create_alert_rule(payload: AlertRuleCreate, db: Db) -> dict:
    row = AlertRule(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id}


@router.get("/admin/master-data")
def admin_master_data(db: Db) -> dict:
    return {
        "locations": [{"id": row.id, "name": row.normalized_name, "province": row.province} for row in db.scalars(select(MasterLocation))],
        "spbu": [
            {
                "id": row.id,
                "number": row.spbu_number,
                "name": row.spbu_name,
                "serving_tbbm_id": str(row.serving_tbbm_id) if row.serving_tbbm_id else None,
            }
            for row in db.scalars(select(MasterSpbu))
        ],
    }


@router.get("/admin/config")
def admin_config() -> dict:
    google_maps_source = get_google_maps_api_key_source()
    return {
        "timezone": settings.app_timezone, "llm": {"provider": settings.llm_provider, "credential": "configured" if settings.llm_api_key else "not configured"},
        "geocoding": {
            "provider": settings.geocoding_provider,
            "credential": "configured" if get_google_maps_api_key() else "not configured",
            "source": google_maps_source,
            "apis": ["GEOCODING", "PLACES_TEXT_SEARCH"],
        },
        "whatsapp": {"provider": settings.whatsapp_provider, "credential": "configured" if settings.whatsapp_access_token else "not configured"},
        "tiktok": {"provider": settings.tiktok_provider},
        "risk": {"supply_weights": settings.supply_risk_weights, "hsse_weights": settings.hsse_risk_weights},
    }


@router.put("/admin/provider-secrets/google-maps", dependencies=[Depends(require_internal_token)])
def save_google_maps_credential(payload: GoogleMapsCredentialUpdate) -> dict:
    api_key = payload.api_key.get_secret_value()
    try:
        geocoded = GoogleGeocodingProvider(api_key).geocode("Jakarta, Indonesia")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Validasi Geocoding API gagal. Periksa API key, billing, pembatasan key, dan aktivasi Geocoding API.",
        ) from exc
    if not geocoded:
        raise HTTPException(status_code=400, detail="Geocoding API aktif tetapi tidak mengembalikan hasil validasi.")

    write_runtime_secret(GOOGLE_MAPS_SECRET_NAME, api_key)
    task = celery_app.send_task("fuel.geo.enrich", queue="geo")
    return {
        "credential": "configured",
        "geocoding": "validated",
        "enrichment_task_id": task.id,
    }


@router.delete("/admin/provider-secrets/google-maps", dependencies=[Depends(require_internal_token)])
def remove_google_maps_credential() -> dict:
    removed = delete_runtime_secret(GOOGLE_MAPS_SECRET_NAME)
    return {
        "removed": removed,
        "credential": "configured" if get_google_maps_api_key() else "not configured",
        "source": get_google_maps_api_key_source(),
    }
