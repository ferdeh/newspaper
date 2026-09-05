from __future__ import annotations

import logging

from geoalchemy2 import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.orm import Session

from app.models import Event, Incident, IncidentSignal, MasterLocation, MasterSpbu, MasterTbbm, Signal
from app.services.intelligence import extract_location_phrase
from app.services.providers import GeocodingResult, get_geocoding_provider
from app.services.tbbm_runtime import runtime_tbbm_conditions, verified_tbbm

logger = logging.getLogger("fuel-intelligence-geography")


def copy_master_location_coordinates(db: Session, incident: Incident) -> bool:
    if not incident.location_id:
        return False
    location = db.get(MasterLocation, incident.location_id)
    if not location:
        return False
    incident.latitude = location.latitude
    incident.longitude = location.longitude
    incident.geocoded_address = location.normalized_name
    incident.geocoding_provider = "MASTER_LOCATION"
    incident.geocoding_confidence = max(incident.geocoding_confidence or 0, 0.95)
    incident.location_resolution_status = "RESOLVED"
    return True


def copy_spbu_coordinates(db: Session, incident: Incident) -> bool:
    if not incident.spbu_id:
        return False
    spbu = db.get(MasterSpbu, incident.spbu_id)
    if not spbu:
        return False
    incident.latitude = spbu.latitude
    incident.longitude = spbu.longitude
    incident.geocoded_address = spbu.spbu_name
    incident.geocoding_provider = "MASTER_SPBU"
    incident.geocoding_confidence = 0.98
    incident.location_resolution_status = "SPBU_RESOLVED"
    return True


def geocode_location_query(location_query: str | None, *, incident_id: int | None = None) -> GeocodingResult | None:
    if not location_query:
        return None
    try:
        return get_geocoding_provider().geocode(f"{location_query}, Indonesia")
    except Exception as exc:
        logger.warning("google.geocode.failed", extra={"incident_id": incident_id, "error_type": type(exc).__name__})
        return None


def google_geocode_incident(incident: Incident, location_query: str | None) -> bool:
    result = geocode_location_query(location_query, incident_id=incident.id)
    if not result:
        return False
    incident.latitude = result.latitude
    incident.longitude = result.longitude
    incident.geocoded_address = result.normalized_name
    incident.geocoding_provider = "GOOGLE_GEOCODING"
    incident.geocoding_confidence = result.confidence
    incident.location_resolution_status = "GEOCODED"
    return True


def incident_location_query(db: Session, incident_id: int) -> str | None:
    rows = db.execute(
        select(Event.location_raw, Signal.title)
        .join(Signal, Signal.id == Event.signal_id)
        .join(IncidentSignal, IncidentSignal.signal_id == Signal.id)
        .where(IncidentSignal.incident_id == incident_id)
        .order_by(Signal.published_at)
    ).all()
    for location_raw, title in rows:
        candidate = location_raw or extract_location_phrase(title)
        if candidate:
            return candidate
    return None


def assign_nearest_terminal(db: Session, incident: Incident) -> None:
    """Assign the geographically nearest verified TBBM using local PostGIS only."""
    if incident.spbu_id:
        spbu = db.get(MasterSpbu, incident.spbu_id)
        incident.serving_tbbm_id = spbu.serving_tbbm_id if spbu and verified_tbbm(spbu.serving_tbbm) else None
    incident.nearest_terminal_duration_minutes = None
    if incident.latitude is None or incident.longitude is None:
        incident.nearest_tbbm_id = None
        incident.nearest_terminal_distance_km = None
        incident.nearest_terminal_distance_source = None
        return

    origin = cast(
        func.ST_SetSRID(func.ST_MakePoint(incident.longitude, incident.latitude), 4326),
        Geography(geometry_type="POINT", srid=4326),
    )
    distance = (func.ST_Distance(MasterTbbm.geom, origin) / 1000.0).label("distance_km")
    nearest = db.execute(
        select(MasterTbbm, distance)
        .where(*runtime_tbbm_conditions(), MasterTbbm.geom.is_not(None))
        .order_by(distance)
        .limit(1)
    ).first()
    if nearest:
        incident.nearest_tbbm_id = nearest[0].id
        incident.nearest_terminal_distance_km = round(float(nearest[1]), 2)
        incident.nearest_terminal_distance_source = "POSTGIS_STRAIGHT_LINE"
    else:
        incident.nearest_tbbm_id = None
        incident.nearest_terminal_distance_km = None
        incident.nearest_terminal_distance_source = None


def enrich_incident_geography(db: Session, incident: Incident, *, force_google: bool = False) -> bool:
    changed = False
    if incident.location_id:
        changed = copy_master_location_coordinates(db, incident)
    elif incident.spbu_id:
        changed = copy_spbu_coordinates(db, incident)
    elif incident.latitude is None or incident.longitude is None or force_google:
        changed = google_geocode_incident(incident, incident_location_query(db, incident.id))
    assign_nearest_terminal(db, incident)
    return changed


def enrich_all_incidents(db: Session, *, force_google: bool = True) -> dict[str, int]:
    incidents = list(db.scalars(select(Incident).where(Incident.status.in_(["OPEN", "MONITORING"]))))
    geocoded = 0
    postgis_matched = 0
    for incident in incidents:
        if enrich_incident_geography(db, incident, force_google=force_google):
            geocoded += 1
        if incident.nearest_terminal_distance_source == "POSTGIS_STRAIGHT_LINE":
            postgis_matched += 1
    db.commit()
    return {"incidents": len(incidents), "geocoded": geocoded, "postgis_matched": postgis_matched}
