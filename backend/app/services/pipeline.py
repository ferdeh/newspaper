from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.collectors.news.adapters import canonicalize_url, is_site_root_url
from app.models import (
    Article,
    Event,
    Incident,
    IncidentSignal,
    MasterLocation,
    MasterSpbu,
    NewsSource,
    RawArticle,
    RiskScoreHistory,
    Signal,
    TikTokPost,
)
from app.schemas import NewsIngest, TikTokIngest
from app.services.geography import assign_nearest_terminal, geocode_location_query
from app.services.intelligence import (
    calculate_lead_time,
    calculate_risk,
    calculate_trend,
    classify_text,
    extract_location_phrase,
    geographic_distance_km,
    normalize_text,
    relevance_score,
    resolve_alias,
    spbu_match_score,
)
from app.services.providers import DeterministicEmbeddingProvider, get_llm_provider

SEVERITY_ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
FALSE_POSITIVE_SIGNAL_STATUS = "ARCHIVED_FALSE_POSITIVE"
FALSE_POSITIVE_INCIDENT_STATUS = "FALSE_POSITIVE"


def content_digest(value: str) -> str:
    return sha256(normalize_text(value).encode()).hexdigest()


def ingest_news(db: Session, payload: NewsIngest, process: bool = True) -> tuple[Signal, Incident | None]:
    canonical = canonicalize_url(str(payload.url))
    existing_raw = db.scalar(select(RawArticle).where(RawArticle.canonical_url == canonical))
    if existing_raw:
        signal = db.scalar(select(Signal).where(Signal.source_type == "NEWS", Signal.source_record_id == existing_raw.id))
        return signal, linked_incident(db, signal.id) if signal else None

    domain = payload.source_domain or urlsplit(canonical).netloc
    source = db.scalar(
        select(NewsSource).where(
            NewsSource.domain == domain,
            NewsSource.deleted_at.is_(None),
        ).order_by(NewsSource.is_active.desc(), NewsSource.priority.asc(), NewsSource.id.asc())
    )
    if not source:
        source = NewsSource(name=payload.source_name, domain=domain, source_type="INTERNAL", credibility_score=0.75)
        db.add(source)
        db.flush()

    digest = content_digest(f"{payload.title} {payload.content}")
    raw = RawArticle(
        source_id=source.id,
        url=str(payload.url),
        canonical_url=canonical,
        title=payload.title,
        raw_text=payload.content,
        published_at=payload.published_at,
        content_hash=digest,
        processing_status="NORMALIZED",
    )
    db.add(raw)
    db.flush()
    score = relevance_score(f"{payload.title} {payload.content}")
    article = Article(
        raw_article_id=raw.id,
        title=payload.title,
        clean_text=payload.content,
        summary=payload.content[:280],
        published_at=payload.published_at,
        relevance_score=score,
    )
    db.add(article)
    signal = Signal(
        source_type="NEWS",
        source_record_id=raw.id,
        source_url=canonical,
        title=payload.title,
        content=payload.content,
        published_at=payload.published_at,
        relevance_score=score,
    )
    db.add(signal)
    db.flush()
    incident = process_signal(db, signal) if process else None
    db.commit()
    return signal, incident


def ingest_tiktok(
    db: Session,
    payload: TikTokIngest,
    process: bool = True,
    *,
    analysis_text: str | None = None,
) -> tuple[Signal, Incident | None]:
    post = db.scalar(select(TikTokPost).where((TikTokPost.video_id == payload.video_id) | (TikTokPost.url == str(payload.url))))
    if post:
        signal = db.scalar(select(Signal).where(Signal.source_type == "TIKTOK", Signal.source_record_id == post.id))
        return signal, linked_incident(db, signal.id) if signal else None

    digest = content_digest(payload.caption)
    post = TikTokPost(
        video_id=payload.video_id,
        url=str(payload.url),
        username=payload.username,
        creator_name=payload.creator_name,
        caption=payload.caption,
        hashtags=payload.hashtags,
        published_at=payload.published_at,
        view_count=payload.view_count,
        like_count=payload.like_count,
        comment_count=payload.comment_count,
        share_count=payload.share_count,
        raw_location_text=payload.raw_location_text,
        content_hash=digest,
        processing_status="NORMALIZED",
    )
    db.add(post)
    db.flush()
    content = analysis_text or payload.caption
    score = relevance_score(content)
    signal = Signal(
        source_type="TIKTOK",
        source_record_id=post.id,
        source_url=str(payload.url),
        title=f"TikTok @{payload.username}",
        content=content,
        published_at=payload.published_at,
        relevance_score=score,
    )
    db.add(signal)
    db.flush()
    incident = process_signal(db, signal, payload.raw_location_text) if process else None
    db.commit()
    return signal, incident


def linked_incident(db: Session, signal_id: int) -> Incident | None:
    return db.scalar(select(Incident).join(IncidentSignal).where(IncidentSignal.signal_id == signal_id))


def process_signal(db: Session, signal: Signal, location_hint: str | None = None) -> Incident | None:
    existing_event = db.scalar(select(Event).where(Event.signal_id == signal.id))
    if existing_event:
        return linked_incident(db, signal.id)
    if signal.relevance_score < 0.5:
        signal.processing_status = "ARCHIVED_IRRELEVANT"
        return None

    try:
        structured = get_llm_provider().extract(signal.title, signal.content, location_hint)
    except Exception:
        signal.processing_status = "RETRY"
        raise
    if not structured.relevant:
        signal.processing_status = "ARCHIVED_IRRELEVANT"
        return None

    signal.embedding = DeterministicEmbeddingProvider().embed(f"{signal.title} {signal.content}")
    location_query = structured.location_raw or extract_location_phrase(signal.title)
    structured_payload = structured.model_dump()
    structured_payload["location_raw"] = location_query
    event = Event(
        signal_id=signal.id,
        event_category=structured.event_category,
        event_type=structured.event_types[0],
        products=structured.products,
        location_raw=location_query,
        severity=structured.severity,
        confidence=structured.confidence,
        possible_cause=structured.possible_cause,
        accident_type=structured.accident_type,
        fire=structured.fire,
        spill=structured.spill,
        fatalities=structured.fatalities,
        injuries=structured.injuries,
        road_blocked=structured.road_blocked,
        structured_payload=structured_payload,
    )
    db.add(event)
    db.flush()
    signal.processing_status = "EVENT_CREATED"

    searchable_text = f"{location_query or ''} {signal.title} {signal.content}"
    locations = db.scalars(select(MasterLocation)).all()
    location_id, location_confidence = resolve_alias(
        searchable_text,
        ((item.id, item.normalized_name, [item.province, item.regency or "", item.city or "", item.district or "", *item.aliases]) for item in locations),
    )
    spbu_id = resolve_spbu(db, searchable_text)
    if spbu_id and not location_id:
        spbu = db.get(MasterSpbu, spbu_id)
        location_id, location_confidence = resolve_alias(
            f"{spbu.district or ''} {spbu.regency or ''} {spbu.province}",
            ((item.id, item.normalized_name, [item.province, item.regency or "", item.city or "", item.district or "", *item.aliases]) for item in locations),
        )

    latitude = None
    longitude = None
    geocoded_address = None
    geocoding_provider = None
    geocoding_confidence = None
    location_resolution_status = "UNRESOLVED"
    if location_id:
        location = db.get(MasterLocation, location_id)
        if location:
            latitude = location.latitude
            longitude = location.longitude
            geocoded_address = location.normalized_name
            geocoding_provider = "MASTER_LOCATION"
            geocoding_confidence = max(0.95, location_confidence)
            location_resolution_status = "RESOLVED"
    elif spbu_id:
        spbu = db.get(MasterSpbu, spbu_id)
        if spbu:
            latitude = spbu.latitude
            longitude = spbu.longitude
            geocoded_address = spbu.spbu_name
            geocoding_provider = "MASTER_SPBU"
            geocoding_confidence = 0.98
            location_resolution_status = "SPBU_RESOLVED"
    else:
        geocoded = geocode_location_query(location_query)
        if geocoded:
            latitude = geocoded.latitude
            longitude = geocoded.longitude
            geocoded_address = geocoded.normalized_name
            geocoding_provider = "GOOGLE_GEOCODING"
            geocoding_confidence = geocoded.confidence
            location_resolution_status = "GEOCODED"

    incident = find_cluster(db, event, location_id, signal.published_at, latitude, longitude)
    if not incident:
        incident = Incident(
            incident_code=f"TEMP-{signal.id}",
            event_category=event.event_category,
            primary_event_type=event.event_type,
            products=event.products,
            severity=event.severity,
            confidence=event.confidence,
            location_id=location_id,
            location_resolution_status=location_resolution_status,
            latitude=latitude,
            longitude=longitude,
            geocoded_address=geocoded_address,
            geocoding_provider=geocoding_provider,
            geocoding_confidence=geocoding_confidence,
            spbu_id=spbu_id,
            first_signal_at=signal.published_at,
            last_signal_at=signal.published_at,
        )
        db.add(incident)
        db.flush()
        incident.incident_code = f"FDI-{signal.published_at.year}-{incident.id:05d}"
    else:
        if spbu_id and not incident.spbu_id:
            incident.spbu_id = spbu_id
        if incident.latitude is None and latitude is not None:
            incident.location_id = incident.location_id or location_id
            incident.location_resolution_status = location_resolution_status
            incident.latitude = latitude
            incident.longitude = longitude
            incident.geocoded_address = geocoded_address
            incident.geocoding_provider = geocoding_provider
            incident.geocoding_confidence = geocoding_confidence

    db.add(IncidentSignal(incident_id=incident.id, signal_id=signal.id, similarity_score=max(0.6, location_confidence), is_primary_signal=incident.signal_count == 0))
    db.flush()
    recompute_incident(db, incident)
    signal.processing_status = "INCIDENT_LINKED"
    return incident


def resolve_spbu(db: Session, text: str) -> int | None:
    best_id = None
    best_score = 0.0
    for spbu in db.scalars(select(MasterSpbu).where(MasterSpbu.is_active.is_(True))):
        score = spbu_match_score(text, spbu.spbu_number, spbu.spbu_name)
        if score > best_score:
            best_id, best_score = spbu.id, score
    return best_id if best_score >= 0.75 else None


def find_cluster(
    db: Session,
    event: Event,
    location_id: int | None,
    published_at: datetime,
    latitude: float | None = None,
    longitude: float | None = None,
) -> Incident | None:
    cutoff = published_at - timedelta(hours=72)
    query = select(Incident).where(
        Incident.event_category == event.event_category,
        Incident.status.in_(["OPEN", "MONITORING"]),
        Incident.last_signal_at >= cutoff,
    )
    if location_id:
        query = query.where(Incident.location_id == location_id)
    elif latitude is not None and longitude is not None:
        query = query.where(
            Incident.location_id.is_(None),
            Incident.latitude.is_not(None),
            Incident.longitude.is_not(None),
        )
    else:
        query = query.where(
            Incident.location_id.is_(None),
            Incident.latitude.is_(None),
            Incident.longitude.is_(None),
        )
    candidates = db.scalars(query.order_by(Incident.last_signal_at.desc())).all()
    event_types = set(event.structured_payload.get("event_types", []))
    for candidate in candidates:
        if latitude is not None and longitude is not None:
            if geographic_distance_km(latitude, longitude, candidate.latitude, candidate.longitude) > 50:
                continue
        product_overlap = bool(set(candidate.products) & set(event.products)) or not candidate.products or not event.products
        type_compatible = candidate.primary_event_type in event_types
        if event.event_category == "SUPPLY_DISRUPTION":
            type_compatible = True
        if product_overlap and type_compatible:
            return candidate
    return None


def recompute_incident(db: Session, incident: Incident) -> None:
    incident = db.scalar(
        select(Incident)
        .options(selectinload(Incident.signal_links).selectinload(IncidentSignal.signal).selectinload(Signal.event))
        .where(Incident.id == incident.id)
    )
    signals = [
        link.signal for link in incident.signal_links
        if link.signal.processing_status != FALSE_POSITIVE_SIGNAL_STATUS
    ]
    events = [item.event for item in signals if item.event]
    if not signals:
        incident.status = FALSE_POSITIVE_INCIDENT_STATUS
        incident.signal_count = 0
        incident.news_count = 0
        incident.tiktok_count = 0
        incident.unique_news_source_count = 0
        incident.unique_tiktok_creator_count = 0
        incident.supply_risk_score = 0
        incident.hsse_risk_score = 0
        incident.confidence = 0
        incident.severity = "LOW"
        return

    timestamps = [item.published_at for item in signals]
    news = [item for item in signals if item.source_type == "NEWS"]
    tiktok = [item for item in signals if item.source_type == "TIKTOK"]
    incident.first_signal_at = min(timestamps)
    incident.last_signal_at = max(timestamps)
    incident.first_news_at = min((item.published_at for item in news), default=None)
    incident.first_tiktok_at = min((item.published_at for item in tiktok), default=None)
    incident.first_detection_source, incident.tiktok_lead_time_minutes = calculate_lead_time(incident.first_tiktok_at, incident.first_news_at)
    incident.signal_count = len(signals)
    incident.news_count = len(news)
    incident.tiktok_count = len(tiktok)
    incident.unique_news_source_count = count_unique_news_sources(db, news)
    incident.unique_tiktok_creator_count = count_unique_tiktok_creators(db, tiktok)
    incident.products = sorted({product for event in events for product in event.products})
    incident.confidence = round(sum(event.confidence for event in events) / len(events), 2)
    incident.severity = max((event.severity for event in events), key=lambda value: SEVERITY_ORDER.get(value, 0))
    event_counts = Counter(event_type for event in events for event_type in event.structured_payload.get("event_types", [event.event_type]))
    incident.primary_event_type = event_counts.most_common(1)[0][0]
    incident.trend_status, metrics = calculate_trend(timestamps)
    for key, value in metrics.items():
        setattr(incident, key, value)

    assign_nearest_terminal(db, incident)
    independent = incident.unique_news_source_count + incident.unique_tiktok_creator_count
    supply, hsse = calculate_risk(
        category=incident.event_category,
        severity=incident.severity,
        confidence=incident.confidence,
        independent_sources=independent,
        mentions_24h=incident.mentions_24h,
        location_resolved=incident.latitude is not None and incident.longitude is not None,
        cross_source=bool(news and tiktok),
        fatalities=sum(event.fatalities for event in events),
        injuries=sum(event.injuries for event in events),
        fire=any(event.fire for event in events),
        spill=any(event.spill for event in events),
        road_blocked=any(event.road_blocked for event in events),
    )
    incident.supply_risk_score = supply
    incident.hsse_risk_score = hsse
    db.add(RiskScoreHistory(incident_id=incident.id, supply_risk_score=supply, hsse_risk_score=hsse, severity=incident.severity))
    db.flush()


def count_unique_news_sources(db: Session, signals: list[Signal]) -> int:
    source_ids = set()
    for signal in signals:
        raw = db.get(RawArticle, signal.source_record_id)
        if raw:
            source_ids.add(raw.source_id)
    return len(source_ids)


def count_unique_tiktok_creators(db: Session, signals: list[Signal]) -> int:
    creators = set()
    for signal in signals:
        post = db.get(TikTokPost, signal.source_record_id)
        if post:
            creators.add(post.username.lower())
    return len(creators)


def recalculate_all_incidents(db: Session) -> int:
    incidents = db.scalars(select(Incident).where(Incident.status.in_(["OPEN", "MONITORING"]))).all()
    for incident in incidents:
        recompute_incident(db, incident)
    db.commit()
    return len(incidents)


def archive_news_false_positives(db: Session) -> dict[str, int]:
    """Re-evaluate persisted News evidence and retain rejected records for audit."""
    signals = db.scalars(
        select(Signal)
        .join(Event, Event.signal_id == Signal.id)
        .where(
            Signal.source_type == "NEWS",
            Signal.processing_status != FALSE_POSITIVE_SIGNAL_STATUS,
        )
    ).all()
    archived_signals = 0
    affected_incident_ids: set[int] = set()
    reclassified_at = datetime.now(timezone.utc).isoformat()

    for signal in signals:
        result = classify_text(f"{signal.title} {signal.content}")
        homepage_signal = is_site_root_url(signal.source_url)
        if result["relevant"] and not homepage_signal:
            continue
        signal.relevance_score = result["confidence"]
        signal.processing_status = FALSE_POSITIVE_SIGNAL_STATUS
        event = signal.event
        if event:
            event.structured_payload = {
                **event.structured_payload,
                "classification_status": "FALSE_POSITIVE",
                "false_positive_reason": (
                    "HOMEPAGE_NOT_ARTICLE" if homepage_signal else "NO_CONTEXTUAL_FUEL_ISSUE_MATCH"
                ),
                "reclassified_at": reclassified_at,
            }
        links = db.scalars(select(IncidentSignal).where(IncidentSignal.signal_id == signal.id)).all()
        affected_incident_ids.update(link.incident_id for link in links)
        archived_signals += 1

    false_positive_incidents = 0
    for incident_id in affected_incident_ids:
        incident = db.get(Incident, incident_id)
        if not incident:
            continue
        recompute_incident(db, incident)
        if incident.status == FALSE_POSITIVE_INCIDENT_STATUS:
            false_positive_incidents += 1

    db.commit()
    return {
        "signals_archived": archived_signals,
        "incidents_classified_false_positive": false_positive_incidents,
    }
