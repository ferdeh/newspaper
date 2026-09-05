from __future__ import annotations

import logging
import math
import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any

from geoalchemy2.elements import WKTElement
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    MasterProvince,
    MasterTbbm,
    TbbmDiscoveryJob,
    TbbmDiscoveryProvenance,
    TbbmDiscoveryResult,
    TbbmSetting,
)
from app.services.google_places import GooglePlacesTextSearchService

logger = logging.getLogger("fuel-intelligence.tbbm.discovery")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_terminal_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    normalized = re.sub(r"\b(?:pt|persero)\b", " ", normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    aliases = {
        r"\bterminal bahan bakar minyak\b": "terminal bbm",
        r"\bdepot bahan bakar minyak\b": "depot bbm",
        r"\bterminal lpg\b": "tlpg",
    }
    for pattern, replacement in aliases.items():
        normalized = re.sub(pattern, replacement, normalized)
    return " ".join(normalized.split())


def classify_terminal(normalized_name: str) -> str:
    if "integrated terminal" in normalized_name:
        return "INTEGRATED_TERMINAL"
    if "fuel terminal" in normalized_name:
        return "FUEL_TERMINAL"
    if re.search(r"\btbbm\b", normalized_name):
        return "TBBM"
    if "depot bbm" in normalized_name or "depot pertamina" in normalized_name:
        return "DEPOT_BBM"
    if re.search(r"\btlpg\b", normalized_name):
        return "TLPG"
    return "OTHER"


def false_positive_reason(normalized_name: str, google_types: list[str], terminal_type: str) -> str | None:
    if terminal_type != "OTHER":
        return None
    retail_signals = ("spbu", "pertashop", "pom bensin", "gas station", "stasiun pengisian")
    office_signals = ("kantor pertamina", "office pertamina", "kantor pemasaran", "agen lpg", "pangkalan lpg")
    if any(signal in normalized_name for signal in retail_signals) or "gas_station" in google_types:
        return "Lokasi terindikasi sebagai SPBU/ritel, bukan terminal BBM."
    if any(signal in normalized_name for signal in office_signals):
        return "Lokasi terindikasi sebagai kantor atau agen, bukan terminal BBM."
    return None


def haversine_distance_meters(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius = 6_371_008.8
    lat1, lat2 = math.radians(lat_a), math.radians(lat_b)
    delta_lat = math.radians(lat_b - lat_a)
    delta_lon = math.radians(lon_b - lon_a)
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def similarity(left: str | None, right: str | None) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, normalize_terminal_name(left), normalize_terminal_name(right)).ratio()


@dataclass(slots=True)
class NormalizedPlace:
    google_place_id: str | None
    place_name: str
    normalized_name: str
    formatted_address: str | None
    latitude: float
    longitude: float
    google_maps_uri: str | None
    google_types: list[str]
    google_primary_type: str | None
    terminal_type: str
    raw_payload: dict[str, Any]


def normalize_google_place(payload: dict[str, Any]) -> NormalizedPlace:
    display_name = payload.get("displayName", {})
    name = display_name.get("text") if isinstance(display_name, dict) else display_name
    location = payload.get("location") or {}
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Google place result has no display name")
    try:
        latitude = float(location["latitude"])
        longitude = float(location["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Google place result has no valid coordinates") from exc
    normalized_name = normalize_terminal_name(name)
    google_types = [str(value) for value in payload.get("types", [])]
    return NormalizedPlace(
        google_place_id=str(payload["id"]) if payload.get("id") else None,
        place_name=name.strip(),
        normalized_name=normalized_name,
        formatted_address=payload.get("formattedAddress"),
        latitude=latitude,
        longitude=longitude,
        google_maps_uri=payload.get("googleMapsUri"),
        google_types=google_types,
        google_primary_type=payload.get("primaryType"),
        terminal_type=classify_terminal(normalized_name),
        raw_payload=payload,
    )


def point(latitude: float, longitude: float) -> WKTElement:
    return WKTElement(f"POINT({longitude} {latitude})", srid=4326)


def runtime_tbbm_settings(db: Session) -> TbbmSetting:
    row = db.get(TbbmSetting, 1)
    if row:
        return row
    row = TbbmSetting(
        id=1,
        request_delay_ms=settings.google_places_request_delay_ms,
        maximum_retry=settings.google_places_max_retry,
        timeout_seconds=settings.google_places_timeout_seconds,
        duplicate_radius_meters=settings.tbbm_duplicate_radius_meters,
        name_similarity_threshold=settings.tbbm_name_similarity_threshold,
    )
    db.add(row)
    db.flush()
    return row


def next_tbbm_code(db: Session) -> str:
    db.execute(text("SELECT pg_advisory_xact_lock(8042001)"))
    current = db.scalar(select(func.max(MasterTbbm.tbbm_code)).where(MasterTbbm.tbbm_code.like("TBBM-%")))
    try:
        number = int((current or "TBBM-000000").split("-")[-1]) + 1
    except ValueError:
        number = (db.scalar(select(func.count(MasterTbbm.id))) or 0) + 1
    return f"TBBM-{number:06d}"


def create_manual_tbbm(db: Session, values: dict[str, Any], actor: str = "admin") -> MasterTbbm:
    province = db.get(MasterProvince, values.get("province_id")) if values.get("province_id") else None
    name = values["name"]
    row = MasterTbbm(
        id=uuid.uuid4(),
        tbbm_code=next_tbbm_code(db),
        name=name,
        normalized_name=normalize_terminal_name(name),
        terminal_type=values["terminal_type"],
        latitude=values["latitude"],
        longitude=values["longitude"],
        geom=point(values["latitude"], values["longitude"]),
        address=values.get("address"),
        city=values.get("city"),
        regency=values.get("regency"),
        province_id=province.id if province else None,
        province_name=province.name if province else None,
        postal_code=values.get("postal_code"),
        google_place_id=values.get("google_place_id") or None,
        google_maps_uri=str(values["google_maps_uri"]) if values.get("google_maps_uri") else None,
        source="MANUAL",
        verification_status=values.get("verification_status", "NEED_REVIEW"),
        operational_status=values.get("operational_status", "UNKNOWN"),
        manual_overrides=sorted(values.keys()),
        last_verified_at=utcnow() if values.get("verification_status") == "VERIFIED" else None,
        created_by=actor,
        updated_by=actor,
    )
    db.add(row)
    db.commit()
    return row


def update_master_tbbm(db: Session, row: MasterTbbm, values: dict[str, Any], actor: str = "admin") -> MasterTbbm:
    province = db.get(MasterProvince, values["province_id"]) if values.get("province_id") else None
    for field, value in values.items():
        if field == "google_maps_uri" and value:
            value = str(value)
        setattr(row, field, value)
    if "name" in values:
        row.normalized_name = normalize_terminal_name(row.name)
    if "province_id" in values:
        row.province_name = province.name if province else None
    if "latitude" in values or "longitude" in values:
        row.geom = point(row.latitude, row.longitude)
    if values.get("verification_status") == "VERIFIED":
        row.last_verified_at = utcnow()
    row.manual_overrides = sorted(set(row.manual_overrides or []) | set(values.keys()))
    row.updated_by = actor
    db.commit()
    return row


class TbbmDiscoveryService:
    def __init__(self, db: Session):
        self.db = db

    def _query_tasks(self, job: TbbmDiscoveryJob) -> list[dict[str, Any]]:
        if job.retry_queries:
            return list(job.retry_queries)
        return [
            {
                "province_id": province["id"],
                "province_name": province["name"],
                "keyword_id": keyword["id"],
                "keyword": keyword["keyword"],
                "query_text": f"{keyword['keyword']} {province['name']}",
            }
            for province in job.selected_provinces
            for keyword in job.selected_keywords
        ]

    def run(self, job_id: uuid.UUID) -> dict[str, Any]:
        job = self.db.get(TbbmDiscoveryJob, job_id)
        if not job:
            return {"status": "NOT_FOUND", "job_id": str(job_id)}
        if job.status == "CANCELLED":
            return {"status": job.status, "job_id": str(job.id)}
        job.status = "RUNNING"
        job.started_at = job.started_at or utcnow()
        job.error_message = None
        self.db.commit()
        configuration = runtime_tbbm_settings(self.db)
        client = GooglePlacesTextSearchService(
            timeout_seconds=configuration.timeout_seconds,
            maximum_retry=configuration.maximum_retry,
            request_delay_ms=configuration.request_delay_ms,
        )
        tasks = self._query_tasks(job)
        logger.info("tbbm.discovery.started", extra={"job_id": str(job.id), "total_queries": len(tasks)})
        try:
            for task in tasks:
                self.db.refresh(job)
                if job.status == "CANCELLED":
                    job.finished_at = utcnow()
                    self.db.commit()
                    return {"status": job.status, "job_id": str(job.id)}
                job.current_province = task["province_name"]
                job.current_keyword = task["keyword"]
                self.db.commit()
                logger.info("tbbm.discovery.query.started", extra={"job_id": str(job.id), "query": task["query_text"]})
                try:
                    for page_number, places in client.iter_pages(task["query_text"], configuration.language_code):
                        for raw_place in places:
                            job.raw_result_count += 1
                            try:
                                self._store_result(job, task, page_number, raw_place, configuration)
                            except ValueError as exc:
                                logger.warning("tbbm.discovery.result.invalid", extra={"job_id": str(job.id), "reason": str(exc)})
                        self.db.commit()
                    job.successful_queries += 1
                except Exception as exc:
                    job.failed_queries += 1
                    detail = {**task, "error": str(exc)[:500]}
                    job.failed_query_details = [*(job.failed_query_details or []), detail]
                    logger.exception("tbbm.discovery.query.failed", extra={"job_id": str(job.id), "query": task["query_text"]})
                job.completed_queries += 1
                self.db.commit()
            job.current_province = None
            job.current_keyword = None
            job.finished_at = utcnow()
            if job.failed_queries and not job.successful_queries:
                job.status = "FAILED"
                job.error_message = "Semua request Google Places gagal."
            elif job.failed_queries:
                job.status = "COMPLETED_WITH_ERRORS"
                job.error_message = "Discovery selesai dengan beberapa request gagal."
            else:
                job.status = "COMPLETED"
            self.db.commit()
        except Exception as exc:
            self.db.rollback()
            job = self.db.get(TbbmDiscoveryJob, job_id)
            if job:
                job.status = "FAILED"
                job.error_message = str(exc)[:1000]
                job.finished_at = utcnow()
                self.db.commit()
            logger.exception("tbbm.discovery.failed", extra={"job_id": str(job_id)})
        logger.info("tbbm.discovery.finished", extra={"job_id": str(job_id), "status": job.status if job else "FAILED"})
        return {"status": job.status if job else "FAILED", "job_id": str(job_id)}

    def _store_result(
        self,
        job: TbbmDiscoveryJob,
        task: dict[str, Any],
        page_number: int,
        raw_place: dict[str, Any],
        configuration: TbbmSetting,
    ) -> TbbmDiscoveryResult:
        place = normalize_google_place(raw_place)
        provenance = {
            "keyword_id": task["keyword_id"], "keyword": task["keyword"],
            "province_id": task["province_id"], "province_name": task["province_name"],
            "query_text": task["query_text"], "query_page": page_number,
        }
        if place.google_place_id:
            existing_result = self.db.scalar(select(TbbmDiscoveryResult).where(
                TbbmDiscoveryResult.discovery_job_id == job.id,
                TbbmDiscoveryResult.google_place_id == place.google_place_id,
            ))
            if existing_result:
                existing_result.source_keywords = sorted(set(existing_result.source_keywords or []) | {task["keyword"]})
                existing_result.query_provenance = [*(existing_result.query_provenance or []), provenance]
                return existing_result

        match_status = "NEW"
        matched_master: MasterTbbm | None = None
        duplicate_group_id: uuid.UUID | None = None
        duplicate_distance: float | None = None
        duplicate_score: float | None = None
        address_score: float | None = None
        rejection_reason: str | None = None

        if place.google_place_id:
            matched_master = self.db.scalar(select(MasterTbbm).where(
                MasterTbbm.google_place_id == place.google_place_id,
                MasterTbbm.deleted_at.is_(None),
            ))
        if matched_master:
            match_status = "EXISTING"
        else:
            best: tuple[float, float, MasterTbbm] | None = None
            masters = self.db.scalars(select(MasterTbbm).where(MasterTbbm.deleted_at.is_(None))).all()
            for master in masters:
                distance = haversine_distance_meters(place.latitude, place.longitude, master.latitude, master.longitude)
                name_score = similarity(place.normalized_name, master.normalized_name)
                if distance <= configuration.duplicate_radius_meters and name_score >= configuration.name_similarity_threshold:
                    if best is None or (name_score, -distance) > (best[1], -best[0]):
                        best = (distance, name_score, master)
            if best:
                duplicate_distance, duplicate_score, matched_master = best
                address_score = similarity(place.formatted_address, matched_master.address)
                match_status = "POSSIBLE_DUPLICATE"
            else:
                candidates = self.db.scalars(select(TbbmDiscoveryResult).where(
                    TbbmDiscoveryResult.discovery_job_id == job.id,
                    TbbmDiscoveryResult.review_status == "PENDING_REVIEW",
                )).all()
                for candidate in candidates:
                    distance = haversine_distance_meters(place.latitude, place.longitude, candidate.latitude, candidate.longitude)
                    name_score = similarity(place.normalized_name, candidate.normalized_name)
                    if distance <= configuration.duplicate_radius_meters and name_score >= configuration.name_similarity_threshold:
                        match_status = "POSSIBLE_DUPLICATE"
                        duplicate_group_id = candidate.duplicate_group_id or candidate.id
                        candidate.duplicate_group_id = duplicate_group_id
                        duplicate_distance = distance
                        duplicate_score = name_score
                        address_score = similarity(place.formatted_address, candidate.formatted_address)
                        break
        if match_status == "NEW":
            rejection_reason = false_positive_reason(place.normalized_name, place.google_types, place.terminal_type)
            if rejection_reason:
                match_status = "AUTO_REJECTED"

        row = TbbmDiscoveryResult(
            id=uuid.uuid4(), discovery_job_id=job.id, province_id=task["province_id"],
            province_name=task["province_name"], keyword_id=task["keyword_id"], keyword=task["keyword"],
            source_keywords=[task["keyword"]], query_text=task["query_text"], query_provenance=[provenance],
            query_page=page_number, google_place_id=place.google_place_id, place_name=place.place_name,
            normalized_name=place.normalized_name, formatted_address=place.formatted_address,
            latitude=place.latitude, longitude=place.longitude, geom=point(place.latitude, place.longitude),
            google_maps_uri=place.google_maps_uri, google_types=place.google_types,
            google_primary_type=place.google_primary_type, terminal_type=place.terminal_type,
            match_status=match_status, matched_master_tbbm_id=matched_master.id if matched_master else None,
            duplicate_group_id=duplicate_group_id, duplicate_distance_meters=duplicate_distance,
            duplicate_score=duplicate_score, address_similarity=address_score,
            review_status="PENDING_REVIEW", rejection_reason=rejection_reason, raw_payload=place.raw_payload,
        )
        self.db.add(row)
        self.db.flush()
        job.unique_place_count += 1
        if match_status == "EXISTING":
            job.existing_match_count += 1
        elif match_status == "POSSIBLE_DUPLICATE":
            job.possible_duplicate_count += 1
        elif match_status == "AUTO_REJECTED":
            job.rejected_auto_count += 1
        else:
            job.new_candidate_count += 1
        return row


def _attach_provenance(db: Session, result: TbbmDiscoveryResult, master: MasterTbbm) -> None:
    for item in result.query_provenance or []:
        existing = db.scalar(select(TbbmDiscoveryProvenance).where(
            TbbmDiscoveryProvenance.master_tbbm_id == master.id,
            TbbmDiscoveryProvenance.discovery_result_id == result.id,
            TbbmDiscoveryProvenance.keyword_id == item.get("keyword_id"),
            TbbmDiscoveryProvenance.province_id == item.get("province_id"),
            TbbmDiscoveryProvenance.query_text == item.get("query_text"),
        ))
        if existing:
            existing.last_seen_at = utcnow()
            continue
        db.add(TbbmDiscoveryProvenance(
            id=uuid.uuid4(), master_tbbm_id=master.id, discovery_result_id=result.id,
            discovery_job_id=result.discovery_job_id, keyword_id=item.get("keyword_id"),
            keyword=item.get("keyword") or result.keyword, province_id=item.get("province_id"),
            query_text=item.get("query_text") or result.query_text,
        ))


def _merge_google_metadata(master: MasterTbbm, result: TbbmDiscoveryResult) -> None:
    overrides = set(master.manual_overrides or [])
    for field, value in {
        "address": result.formatted_address,
        "google_place_id": result.google_place_id,
        "google_maps_uri": result.google_maps_uri,
        "google_primary_type": result.google_primary_type,
        "google_types": result.google_types,
    }.items():
        if value and field not in overrides and not getattr(master, field):
            setattr(master, field, value)
    master.last_discovered_at = utcnow()


def approve_candidate(db: Session, result_id: uuid.UUID, *, allow_possible_duplicate: bool = False, actor: str = "admin") -> MasterTbbm:
    db.execute(text("SELECT pg_advisory_xact_lock(8042002)"))
    result = db.scalar(select(TbbmDiscoveryResult).where(TbbmDiscoveryResult.id == result_id).with_for_update())
    if not result:
        raise LookupError("Candidate not found")
    if result.review_status in {"APPROVED", "MERGED"} and result.matched_master_tbbm_id:
        master = db.get(MasterTbbm, result.matched_master_tbbm_id)
        if master:
            return master
    if result.match_status == "AUTO_REJECTED":
        raise ValueError("Kandidat auto-rejected harus diedit sebelum disetujui.")
    if result.match_status == "POSSIBLE_DUPLICATE" and not allow_possible_duplicate:
        raise ValueError("Possible duplicate harus di-merge atau dikonfirmasi Keep Both.")
    master = None
    if result.google_place_id:
        master = db.scalar(select(MasterTbbm).where(MasterTbbm.google_place_id == result.google_place_id, MasterTbbm.deleted_at.is_(None)))
    if not master and result.match_status == "EXISTING" and result.matched_master_tbbm_id:
        master = db.get(MasterTbbm, result.matched_master_tbbm_id)
    if master:
        _merge_google_metadata(master, result)
        result.review_status = "MERGED"
    else:
        now = utcnow()
        master = MasterTbbm(
            id=uuid.uuid4(), tbbm_code=next_tbbm_code(db), name=result.place_name,
            normalized_name=normalize_terminal_name(result.place_name), terminal_type=result.terminal_type,
            latitude=result.latitude, longitude=result.longitude, geom=point(result.latitude, result.longitude),
            address=result.formatted_address, province_id=result.province_id, province_name=result.province_name,
            google_place_id=result.google_place_id, google_maps_uri=result.google_maps_uri,
            google_primary_type=result.google_primary_type, google_types=result.google_types,
            source="GOOGLE_PLACES", verification_status="VERIFIED", operational_status="UNKNOWN",
            first_discovered_at=now, last_discovered_at=now, last_verified_at=now,
            created_by=actor, updated_by=actor,
        )
        db.add(master)
        db.flush()
        result.review_status = "APPROVED"
    result.matched_master_tbbm_id = master.id
    _attach_provenance(db, result, master)
    db.commit()
    logger.info("tbbm.candidate.approved", extra={"result_id": str(result.id), "master_tbbm_id": str(master.id)})
    return master


def merge_candidate(db: Session, result_id: uuid.UUID, master_id: uuid.UUID, actor: str = "admin") -> MasterTbbm:
    db.execute(text("SELECT pg_advisory_xact_lock(8042002)"))
    result = db.scalar(select(TbbmDiscoveryResult).where(TbbmDiscoveryResult.id == result_id).with_for_update())
    master = db.scalar(select(MasterTbbm).where(MasterTbbm.id == master_id, MasterTbbm.deleted_at.is_(None)).with_for_update())
    if not result or not master:
        raise LookupError("Candidate or master terminal not found")
    _merge_google_metadata(master, result)
    master.updated_by = actor
    result.matched_master_tbbm_id = master.id
    result.review_status = "MERGED"
    _attach_provenance(db, result, master)
    db.commit()
    logger.info("tbbm.candidate.merged", extra={"result_id": str(result.id), "master_tbbm_id": str(master.id)})
    return master


def reject_candidate(db: Session, result_id: uuid.UUID, reason: str) -> TbbmDiscoveryResult:
    result = db.scalar(select(TbbmDiscoveryResult).where(TbbmDiscoveryResult.id == result_id).with_for_update())
    if not result:
        raise LookupError("Candidate not found")
    result.review_status = "REJECTED"
    result.rejection_reason = reason
    db.commit()
    logger.info("tbbm.candidate.rejected", extra={"result_id": str(result.id), "reason": reason})
    return result
