from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AlertHistory, AlertRule, Incident
from app.notification.service import NotificationService
from app.services.intelligence import risk_band
from app.services.providers import get_whatsapp_provider
from app.services.tbbm_runtime import verified_tbbm

BAND_ORDER = {"NORMAL": 0, "WATCH": 1, "WARNING": 2, "HIGH": 3, "CRITICAL": 4}


def should_send_alert(
    previous_risk: float | None, previous_sent_at: datetime | None, new_risk: float,
    cooldown_minutes: int, now: datetime | None = None,
) -> tuple[bool, bool]:
    if previous_risk is None:
        return True, False
    now = now or datetime.now(timezone.utc)
    previous_band = risk_band(previous_risk)
    new_band = risk_band(new_risk)
    escalated = BAND_ORDER[new_band] > BAND_ORDER[previous_band]
    in_cooldown = bool(previous_sent_at and previous_sent_at > now - timedelta(minutes=cooldown_minutes))
    return escalated or (not in_cooldown and new_band != previous_band), escalated


def incident_risk(incident: Incident) -> float:
    return incident.hsse_risk_score if incident.event_category == "HSSE" else incident.supply_risk_score


def render_alert_message(incident: Incident, band: str) -> str:
    location = incident.location.normalized_name if incident.location else "Lokasi belum terverifikasi"
    nearest_tbbm = verified_tbbm(incident.nearest_tbbm)
    serving_tbbm = verified_tbbm(incident.serving_tbbm)
    nearest = nearest_tbbm.name if nearest_tbbm else "Belum tersedia"
    serving = serving_tbbm.name if serving_tbbm else "Belum terpetakan"
    risk = incident_risk(incident)
    url = f"{settings.app_base_url}/incidents/{incident.id}"
    if incident.event_category == "HSSE":
        return (
            "🔴 MT ACCIDENT ALERT\n\n"
            f"Location: {location}\nIncident: {incident.primary_event_type}\nHSSE Risk: {risk:.0f} — {band}\n"
            f"News: {incident.news_count}\nTikTok: {incident.tiktok_count}\nNearest TBBM: {nearest}\nOpen Incident: {url}"
        )
    return (
        "🔴 FUEL SUPPLY ALERT\n\n"
        f"Location: {location}\nIssue: {incident.primary_event_type}\nProduct: {', '.join(incident.products) or 'BBM'}\n"
        f"Risk: {risk:.0f} — {band}\nTikTok: {incident.tiktok_count}\nNews: {incident.news_count}\n"
        f"Trend: {incident.trend_status}\nNearest TBBM: {nearest}\nServing TBBM: {serving}\nOpen Incident: {url}"
    )


def evaluate_incident_alerts(db: Session, incident: Incident) -> AlertHistory | None:
    risk = incident_risk(incident)
    band = risk_band(risk)
    independent = incident.unique_news_source_count + incident.unique_tiktok_creator_count
    rules = db.scalars(
        select(AlertRule).where(
            AlertRule.is_active.is_(True),
            (AlertRule.event_category.is_(None)) | (AlertRule.event_category == incident.event_category),
        )
    ).all()
    eligible = [rule for rule in rules if risk >= rule.minimum_risk and incident.confidence >= rule.minimum_confidence and independent >= rule.minimum_independent_sources]
    if not eligible:
        return None
    rule = min(eligible, key=lambda item: item.minimum_risk)
    previous = db.scalar(select(AlertHistory).where(AlertHistory.incident_id == incident.id).order_by(AlertHistory.id.desc()))
    if previous:
        send, escalated = should_send_alert(previous.risk_score, previous.sent_at, risk, rule.cooldown_minutes)
        if not send:
            return None
        alert_type = "RISK_ESCALATION" if escalated else "NEW_HIGH_RISK"
    else:
        alert_type = "CRITICAL_HSSE" if incident.event_category == "HSSE" and band == "CRITICAL" else "NEW_HIGH_RISK"
    dedupe_key = f"{alert_type}:{band}"
    existing = db.scalar(select(AlertHistory).where(AlertHistory.incident_id == incident.id, AlertHistory.dedupe_key == dedupe_key))
    if existing:
        return None
    message = render_alert_message(incident, band)
    alert = AlertHistory(
        incident_id=incident.id,
        alert_type=alert_type,
        dedupe_key=dedupe_key,
        recipient=settings.alert_recipient,
        risk_score=risk,
        severity=band,
        message_payload={"text": message, "incident_code": incident.incident_code},
    )
    db.add(alert)
    db.flush()
    notifications = NotificationService(db)
    notifications.handle_alert_created(notifications.event_from_alert(alert, incident))
    return alert


def evaluate_all_alerts(db: Session) -> int:
    count = 0
    for incident in db.scalars(select(Incident).where(Incident.status.in_(["OPEN", "MONITORING"]))):
        if evaluate_incident_alerts(db, incident):
            count += 1
    db.commit()
    return count


def dispatch_queued_alerts(db: Session) -> int:
    provider = get_whatsapp_provider()
    alerts = db.scalars(select(AlertHistory).where(AlertHistory.delivery_status.in_(["QUEUED", "RETRY"]))).all()
    sent = 0
    for alert in alerts:
        try:
            result = provider.send(alert.recipient, alert.message_payload["text"])
            alert.delivery_status = result.status
            alert.provider_message_id = result.provider_message_id
            alert.sent_at = datetime.now(timezone.utc)
            alert.error_message = None
            sent += 1
        except Exception as exc:
            alert.delivery_status = "RETRY"
            alert.error_message = str(exc)[:500]
    db.commit()
    return sent


def generate_daily_digest(db: Session) -> AlertHistory | None:
    incidents = db.scalars(select(Incident).where(Incident.status.in_(["OPEN", "MONITORING"]))).all()
    if not incidents:
        return None
    top = max(incidents, key=incident_risk)
    today = datetime.now(settings.timezone).date().isoformat()
    dedupe_key = f"DAILY_DIGEST:{today}"
    if db.scalar(select(AlertHistory).where(AlertHistory.incident_id == top.id, AlertHistory.dedupe_key == dedupe_key)):
        return None
    critical = sum(risk_band(incident_risk(item)) == "CRITICAL" for item in incidents)
    hsse = sum(item.event_category == "HSSE" for item in incidents)
    tiktok_first = sum(item.first_detection_source == "TIKTOK" for item in incidents)
    text = (
        f"📊 DAILY FUEL INTELLIGENCE — {today}\n\nActive Incidents: {len(incidents)}\nCritical: {critical}\n"
        f"New/Active Supply: {len(incidents) - hsse}\nReported MT Accidents: {hsse}\nTikTok early signals: {tiktok_first}\n"
        f"Top risk: {top.incident_code} — {incident_risk(top):.0f}"
    )
    alert = AlertHistory(
        incident_id=top.id,
        alert_type="DAILY_DIGEST",
        dedupe_key=dedupe_key,
        recipient=settings.alert_recipient,
        risk_score=incident_risk(top),
        severity=risk_band(incident_risk(top)),
        message_payload={"text": text},
    )
    db.add(alert)
    db.commit()
    return alert
