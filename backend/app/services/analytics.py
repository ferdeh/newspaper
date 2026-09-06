from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import AnalyticsDaily, Incident, IncidentSignal, MasterLocation, MasterTbbm, Signal
from app.services.intelligence import risk_band
from app.services.tbbm_runtime import runtime_tbbm_conditions, verified_tbbm


def risk_value(incident: Incident) -> float:
    return incident.hsse_risk_score if incident.event_category == "HSSE" else incident.supply_risk_score


def incident_label(incident: Incident) -> str:
    return incident.location.normalized_name if incident.location else incident.geocoded_address or "Lokasi belum terverifikasi"


def incident_map_row(item: Incident) -> dict:
    nearest = verified_tbbm(item.nearest_tbbm)
    serving = verified_tbbm(item.serving_tbbm)
    return {
        "id": item.id,
        "code": item.incident_code,
        "location": incident_label(item),
        "province": item.location.province if item.location else None,
        "lat": item.latitude,
        "lng": item.longitude,
        "category": item.event_category,
        "event": item.primary_event_type,
        "products": item.products,
        "incident_date": item.first_signal_at.date().isoformat(),
        "news_date": item.first_news_at.isoformat() if item.first_news_at else None,
        "risk": risk_value(item),
        "severity": risk_band(risk_value(item)),
        "news": item.news_count,
        "tiktok": item.tiktok_count,
        "nearest_terminal": nearest.name if nearest else None,
        "nearest_terminal_id": str(nearest.id) if nearest else None,
        "nearest_terminal_lat": nearest.latitude if nearest else None,
        "nearest_terminal_lng": nearest.longitude if nearest else None,
        "nearest_terminal_distance_km": item.nearest_terminal_distance_km if nearest else None,
        "nearest_terminal_distance_source": item.nearest_terminal_distance_source if nearest else None,
        "nearest_terminal_duration_minutes": item.nearest_terminal_duration_minutes if nearest else None,
        "serving_terminal": serving.name if serving else None,
        "geocoding_provider": item.geocoding_provider,
        "geocoding_confidence": item.geocoding_confidence,
    }


def province_heatmap_rows(incidents: list[Incident]) -> list[dict]:
    groups: dict[str, list[Incident]] = defaultdict(list)
    for incident in incidents:
        if incident.location and incident.location.province:
            groups[incident.location.province].append(incident)

    rows = []
    for province, items in groups.items():
        risks = [risk_value(item) for item in items]
        mapped = [item for item in items if item.latitude is not None and item.longitude is not None]
        rows.append({
            "province": province,
            "incident_count": len(items),
            "max_risk": round(max(risks), 1),
            "average_risk": round(sum(risks) / len(risks), 1),
            "critical_count": sum(risk_band(value) == "CRITICAL" for value in risks),
            "supply_incidents": sum(item.event_category == "SUPPLY_DISRUPTION" for item in items),
            "hsse_incidents": sum(item.event_category == "HSSE" for item in items),
            "external_incidents": sum(item.event_category == "EXTERNAL_DISRUPTION" for item in items),
            "news_count": sum(item.news_count for item in items),
            "tiktok_count": sum(item.tiktok_count for item in items),
            "mapped_incidents": len(mapped),
            "label_lat": round(sum(item.latitude for item in mapped) / len(mapped), 6) if mapped else None,
            "label_lng": round(sum(item.longitude for item in mapped) / len(mapped), 6) if mapped else None,
            "period_start": min(item.first_signal_at for item in items).date().isoformat(),
            "period_end": max(item.first_signal_at for item in items).date().isoformat(),
        })
    return sorted(rows, key=lambda row: (-row["max_risk"], row["province"]))


def filtered_incidents(
    db: Session, *, date_from=None, date_to=None, province: str | None = None, regency: str | None = None,
    product: str | None = None, event: str | None = None, source: str | None = None,
    severity: str | None = None, terminal: uuid.UUID | None = None,
) -> list[Incident]:
    query = select(Incident).options(
        selectinload(Incident.location), selectinload(Incident.nearest_tbbm), selectinload(Incident.serving_tbbm),
    )
    if date_from:
        query = query.where(func.date(Incident.first_signal_at) >= date_from)
    if date_to:
        query = query.where(func.date(Incident.first_signal_at) <= date_to)
    if province or regency:
        query = query.join(Incident.location)
        if province:
            query = query.where(func.lower(MasterLocation.province) == province.lower())
        if regency:
            query = query.where(func.lower(MasterLocation.regency).contains(regency.lower()))
    if product:
        query = query.where(Incident.products.contains([product.upper()]))
    if event:
        query = query.where(Incident.primary_event_type == event.upper())
    if source:
        query = query.join(IncidentSignal).join(Signal).where(Signal.source_type == source.upper()).distinct()
    if terminal:
        allowed = db.scalar(select(MasterTbbm.id).where(MasterTbbm.id == terminal, *runtime_tbbm_conditions()))
        if not allowed:
            return []
        query = query.where((Incident.nearest_tbbm_id == terminal) | (Incident.serving_tbbm_id == terminal))
    items = db.scalars(query).unique().all()
    if severity:
        items = [item for item in items if risk_band(risk_value(item)) == severity.upper()]
    return items


def refresh_analytics(db: Session) -> int:
    db.execute(delete(AnalyticsDaily))
    incidents = db.scalars(
        select(Incident)
        .options(selectinload(Incident.location), selectinload(Incident.nearest_tbbm))
        .where(Incident.status != "FALSE_POSITIVE")
    ).all()
    buckets: dict[tuple, dict] = defaultdict(lambda: {
        "incident_count": 0, "news_count": 0, "tiktok_count": 0, "critical_count": 0, "high_count": 0,
        "supply": [], "hsse": [], "lead": [],
    })
    for incident in incidents:
        nearest = verified_tbbm(incident.nearest_tbbm)
        products = incident.products or [None]
        for product in products:
            key = (
                incident.first_signal_at.date(),
                incident.location.province if incident.location else None,
                incident.location.regency if incident.location else None,
                incident.event_category,
                incident.primary_event_type,
                product,
                nearest.id if nearest else None,
            )
            bucket = buckets[key]
            bucket["incident_count"] += 1
            bucket["news_count"] += incident.news_count
            bucket["tiktok_count"] += incident.tiktok_count
            band = risk_band(risk_value(incident))
            bucket["critical_count"] += band == "CRITICAL"
            bucket["high_count"] += band == "HIGH"
            bucket["supply"].append(incident.supply_risk_score)
            bucket["hsse"].append(incident.hsse_risk_score)
            if incident.tiktok_lead_time_minutes is not None:
                bucket["lead"].append(incident.tiktok_lead_time_minutes)
    for key, bucket in buckets.items():
        db.add(AnalyticsDaily(
            date=key[0], province=key[1], regency=key[2], event_category=key[3], event_type=key[4], product=key[5], tbbm_id=key[6],
            incident_count=bucket["incident_count"], news_count=bucket["news_count"], tiktok_count=bucket["tiktok_count"],
            critical_count=bucket["critical_count"], high_count=bucket["high_count"],
            avg_supply_risk=round(sum(bucket["supply"]) / len(bucket["supply"]), 1),
            avg_hsse_risk=round(sum(bucket["hsse"]) / len(bucket["hsse"]), 1),
            avg_tiktok_lead_time_minutes=round(sum(bucket["lead"]) / len(bucket["lead"]), 1) if bucket["lead"] else None,
        ))
    db.commit()
    return len(buckets)


def overview(db: Session, **filters) -> dict:
    now = datetime.now(timezone.utc)
    last_scheduler_update = db.scalar(select(func.max(AnalyticsDaily.created_at)))
    next_scheduler_update = (
        last_scheduler_update + timedelta(minutes=settings.analytics_refresh_minutes)
        if last_scheduler_update else None
    )
    incidents = filtered_incidents(db, **filters)
    active = [item for item in incidents if item.status in ("OPEN", "MONITORING")]
    signal_counts = {"NEWS": sum(item.news_count for item in active if item.last_signal_at >= now - timedelta(hours=24)), "TIKTOK": sum(item.tiktok_count for item in active if item.last_signal_at >= now - timedelta(hours=24))}
    critical = [item for item in active if risk_band(risk_value(item)) == "CRITICAL"]
    regions = Counter(item.location.province for item in active if item.location)
    products = Counter(product for item in active for product in item.products)
    events = Counter(item.primary_event_type for item in active)
    exposed_terminal_ids = {
        terminal.id
        for item in active
        for terminal in (verified_tbbm(item.nearest_tbbm), verified_tbbm(item.serving_tbbm))
        if terminal
    }
    terminal_rows = list(db.scalars(select(MasterTbbm).where(*runtime_tbbm_conditions())))
    trend = []
    for offset in range(6, -1, -1):
        day = (now - timedelta(days=offset)).date()
        day_items = [item for item in active if item.first_signal_at.date() == day]
        trend.append({"date": day.isoformat(), "incidents": len(day_items), "signals": sum(item.signal_count for item in day_items)})
    return {
        "generated_at": now.isoformat(),
        "scheduler_update": {
            "last_update_at": last_scheduler_update.isoformat() if last_scheduler_update else None,
            "next_update_at": next_scheduler_update.isoformat() if next_scheduler_update else None,
            "interval_minutes": settings.analytics_refresh_minutes,
        },
        "kpis": {
            "active_incidents": len(active), "critical_incidents": len(critical), "news_24h": signal_counts.get("NEWS", 0),
            "tiktok_24h": signal_counts.get("TIKTOK", 0), "supply_incidents": sum(item.event_category == "SUPPLY_DISRUPTION" for item in active),
            "reported_mt_accidents": sum(item.event_category == "HSSE" for item in active),
            "provinces_affected": len(regions), "tbbm_exposed": len(exposed_terminal_ids),
        },
        "trend": trend,
        "trending_issues": [{"name": key, "count": value} for key, value in events.most_common(6)],
        "regions": [{"name": key, "count": value} for key, value in regions.most_common(8)],
        "products": [{"name": key, "count": value} for key, value in products.most_common()],
        "events": [{"name": key, "count": value} for key, value in events.most_common()],
        "province_heatmap": province_heatmap_rows(active),
        "unresolved_province_incidents": sum(not item.location or not item.location.province for item in active),
        "map": [incident_map_row(item) for item in active if item.latitude is not None and item.longitude is not None],
        "terminals": [
            {
                "id": str(terminal.id),
                "code": terminal.tbbm_code,
                "name": terminal.name,
                "type": terminal.terminal_type,
                "province": terminal.province_name,
                "city": terminal.city,
                "lat": terminal.latitude,
                "lng": terminal.longitude,
            }
            for terminal in terminal_rows
        ],
    }


def geography(db: Session, **filters) -> list[dict]:
    incidents = filtered_incidents(db, **filters)
    groups: dict[tuple[str, str], list[Incident]] = defaultdict(list)
    for item in incidents:
        if item.location:
            groups[(item.location.province, item.location.regency or item.location.city or "-")].append(item)
    return [
        {
            "province": key[0], "regency": key[1], "incidents": len(items), "news": sum(x.news_count for x in items),
            "tiktok": sum(x.tiktok_count for x in items), "critical": sum(risk_band(risk_value(x)) == "CRITICAL" for x in items),
            "average_risk": round(sum(risk_value(x) for x in items) / len(items), 1),
        }
        for key, items in sorted(groups.items(), key=lambda pair: len(pair[1]), reverse=True)
    ]


def products(db: Session, **filters) -> list[dict]:
    incidents = filtered_incidents(db, **filters)
    groups: dict[str, list[Incident]] = defaultdict(list)
    for item in incidents:
        for product in item.products:
            groups[product].append(item)
    return [{
        "product": key, "incidents": len(items), "news_mentions": sum(x.news_count for x in items),
        "tiktok_mentions": sum(x.tiktok_count for x in items), "critical": sum(risk_band(risk_value(x)) == "CRITICAL" for x in items),
        "average_risk": round(sum(risk_value(x) for x in items) / len(items), 1),
        "trend": "INCREASING" if sum(x.trend_status in ("INCREASING", "RAPIDLY_INCREASING") for x in items) > len(items) / 2 else "STABLE",
    } for key, items in groups.items()]


def events(db: Session, **filters) -> list[dict]:
    incidents = filtered_incidents(db, **filters)
    groups: dict[str, list[Incident]] = defaultdict(list)
    for item in incidents:
        groups[item.primary_event_type].append(item)
    return [{
        "event": key, "current_24h": sum(x.first_signal_at >= datetime.now(timezone.utc) - timedelta(hours=24) for x in items),
        "previous_24h": sum(datetime.now(timezone.utc) - timedelta(hours=48) <= x.first_signal_at < datetime.now(timezone.utc) - timedelta(hours=24) for x in items),
        "current_7d": len(items), "average_risk": round(sum(risk_value(x) for x in items) / len(items), 1),
    } for key, items in groups.items()]


def terminals(db: Session, **filters) -> list[dict]:
    terminal_list = db.scalars(select(MasterTbbm).where(*runtime_tbbm_conditions())).all()
    incidents = filtered_incidents(db, **filters)
    result = []
    for terminal in terminal_list:
        items = [item for item in incidents if item.nearest_tbbm_id == terminal.id or item.serving_tbbm_id == terminal.id]
        result.append({
            "id": str(terminal.id), "terminal": terminal.name, "code": terminal.tbbm_code, "incidents": len(items),
            "critical": sum(risk_band(risk_value(x)) == "CRITICAL" for x in items),
            "affected_spbu": len({x.spbu_id for x in items if x.spbu_id}), "news_mentions": sum(x.news_count for x in items),
            "tiktok_signals": sum(x.tiktok_count for x in items),
            "average_risk": round(sum(risk_value(x) for x in items) / len(items), 1) if items else 0,
        })
    return sorted(result, key=lambda item: item["average_risk"], reverse=True)


def tiktok_early_warning(db: Session, **filters) -> dict:
    incidents = filtered_incidents(db, **filters)
    lead = [item.tiktok_lead_time_minutes for item in incidents if item.tiktok_lead_time_minutes is not None]
    total = len(lead) or 1
    by_event: dict[str, list[int]] = defaultdict(list)
    for item in incidents:
        if item.tiktok_lead_time_minutes is not None:
            by_event[item.primary_event_type].append(item.tiktok_lead_time_minutes)
    return {
        "average_lead_time": round(sum(lead) / len(lead), 1) if lead else None,
        "median_lead_time": median(lead) if lead else None,
        "tiktok_first_percent": round(sum(value > 5 for value in lead) / total * 100, 1),
        "news_first_percent": round(sum(value < -5 for value in lead) / total * 100, 1),
        "simultaneous_percent": round(sum(abs(value) <= 5 for value in lead) / total * 100, 1),
        "by_event": [{"event": key, "minutes": round(sum(values) / len(values), 1)} for key, values in by_event.items()],
    }


def hsse(db: Session, **filters) -> dict:
    incidents = [item for item in filtered_incidents(db, **filters) if item.event_category == "HSSE"]
    return {
        "reported_mt_accidents": len(incidents),
        "fatalities": sum(any(link.signal.event and link.signal.event.fatalities for link in item.signal_links) for item in incidents),
        "injuries": sum(any(link.signal.event and link.signal.event.injuries for link in item.signal_links) for item in incidents),
        "fire": sum(any(link.signal.event and link.signal.event.fire for link in item.signal_links) for item in incidents),
        "fuel_spill": sum(any(link.signal.event and link.signal.event.spill for link in item.signal_links) for item in incidents),
        "road_blockage": sum(any(link.signal.event and link.signal.event.road_blocked for link in item.signal_links) for item in incidents),
        "incidents": [{"code": item.incident_code, "event": item.primary_event_type, "risk": item.hsse_risk_score, "severity": risk_band(item.hsse_risk_score)} for item in incidents],
    }


def executive_summary(db: Session, **filters) -> dict:
    data = overview(db, **filters)
    tiktok = tiktok_early_warning(db, **filters)
    top_region = data["regions"][0]["name"] if data["regions"] else "belum ada wilayah dominan"
    top_product = data["products"][0]["name"] if data["products"] else "belum ada produk dominan"
    text = (
        f"Terdapat {data['kpis']['active_incidents']} incident aktif, termasuk {data['kpis']['critical_incidents']} berstatus kritis. "
        f"Paparan tertinggi saat ini berada di {top_region}, dengan {top_product} sebagai produk paling banyak disebut. "
        f"TikTok mendahului News pada {tiktok['tiktok_first_percent']}% incident yang memiliki bukti lintas sumber. "
        "Ringkasan ini dibentuk hanya dari analytics terstruktur yang tersimpan dari sumber live."
    )
    return {"summary": text, "generated_by": "deterministic-template", "generated_at": data["generated_at"]}
