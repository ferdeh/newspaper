from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import asc, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    MasterProvince,
    MasterTbbm,
    TbbmDiscoveryJob,
    TbbmDiscoveryKeyword,
    TbbmDiscoveryProvenance,
    TbbmDiscoveryResult,
)
from app.services.google_places import GooglePlacesAuthenticationError, GooglePlacesConfigurationError, GooglePlacesTextSearchService
from app.services.secrets import get_google_maps_api_key, get_google_maps_api_key_source
from app.services.tbbm_discovery import (
    approve_candidate,
    create_manual_tbbm,
    false_positive_reason,
    merge_candidate,
    normalize_terminal_name,
    point,
    reject_candidate,
    runtime_tbbm_settings,
    update_master_tbbm,
)
from app.tbbm_schemas import (
    BulkReview,
    DiscoveryJobCreate,
    DiscoveryResultUpdate,
    KeywordCreate,
    KeywordUpdate,
    MergeCandidate,
    ReviewReason,
    TbbmCreate,
    TbbmSettingsUpdate,
    TbbmUpdate,
)
from app.workers.celery_app import celery_app

router = APIRouter(prefix="/tbbm", tags=["Master TBBM"])
Db = Annotated[Session, Depends(get_db)]


def require_internal_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
    expected = settings.internal_api_token.get_secret_value()
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(status_code=401, detail="Valid internal token required")


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def province_dict(row: MasterProvince) -> dict[str, Any]:
    return {"id": row.id, "code": row.code, "name": row.name, "is_active": row.is_active}


def master_dict(row: MasterTbbm, *, detail: bool = False, db: Session | None = None) -> dict[str, Any]:
    payload = {
        "id": str(row.id), "tbbm_code": row.tbbm_code, "name": row.name,
        "normalized_name": row.normalized_name, "terminal_type": row.terminal_type,
        "latitude": row.latitude, "longitude": row.longitude, "address": row.address,
        "city": row.city, "regency": row.regency, "province_id": row.province_id,
        "province_name": row.province_name, "postal_code": row.postal_code,
        "google_place_id": row.google_place_id, "google_maps_uri": row.google_maps_uri,
        "google_primary_type": row.google_primary_type, "google_types": row.google_types or [],
        "source": row.source, "verification_status": row.verification_status,
        "operational_status": row.operational_status, "first_discovered_at": iso(row.first_discovered_at),
        "last_discovered_at": iso(row.last_discovered_at), "last_verified_at": iso(row.last_verified_at),
        "created_at": iso(row.created_at), "updated_at": iso(row.updated_at),
    }
    if detail and db:
        provenance = db.scalars(select(TbbmDiscoveryProvenance).where(
            TbbmDiscoveryProvenance.master_tbbm_id == row.id,
        ).order_by(TbbmDiscoveryProvenance.keyword, TbbmDiscoveryProvenance.first_seen_at)).all()
        payload["provenance"] = [{
            "id": str(item.id), "keyword": item.keyword, "query_text": item.query_text,
            "first_seen_at": iso(item.first_seen_at), "last_seen_at": iso(item.last_seen_at),
        } for item in provenance]
        payload["manual_overrides"] = row.manual_overrides or []
    return payload


def job_dict(row: TbbmDiscoveryJob) -> dict[str, Any]:
    progress = round(row.completed_queries / row.total_queries * 100, 1) if row.total_queries else 0
    return {
        "id": str(row.id), "status": row.status, "search_scope": row.search_scope,
        "selected_provinces": row.selected_provinces or [], "selected_keywords": row.selected_keywords or [],
        "existing_data_mode": row.existing_data_mode, "total_queries": row.total_queries,
        "completed_queries": row.completed_queries, "successful_queries": row.successful_queries,
        "failed_queries": row.failed_queries, "failed_query_details": row.failed_query_details or [],
        "raw_result_count": row.raw_result_count, "unique_place_count": row.unique_place_count,
        "existing_match_count": row.existing_match_count, "new_candidate_count": row.new_candidate_count,
        "possible_duplicate_count": row.possible_duplicate_count, "rejected_auto_count": row.rejected_auto_count,
        "current_province": row.current_province, "current_keyword": row.current_keyword,
        "progress": progress, "created_by": row.created_by, "started_at": iso(row.started_at),
        "finished_at": iso(row.finished_at), "created_at": iso(row.created_at), "error_message": row.error_message,
    }


def result_dict(row: TbbmDiscoveryResult, *, detail: bool = False) -> dict[str, Any]:
    master = row.matched_master
    payload = {
        "id": str(row.id), "discovery_job_id": str(row.discovery_job_id), "province_id": row.province_id,
        "province_name": row.province_name, "keyword_id": row.keyword_id, "keyword": row.keyword,
        "source_keywords": row.source_keywords or [], "query_text": row.query_text, "query_page": row.query_page,
        "google_place_id": row.google_place_id, "place_name": row.place_name,
        "normalized_name": row.normalized_name, "formatted_address": row.formatted_address,
        "latitude": row.latitude, "longitude": row.longitude, "google_maps_uri": row.google_maps_uri,
        "google_types": row.google_types or [], "google_primary_type": row.google_primary_type,
        "terminal_type": row.terminal_type, "match_status": row.match_status,
        "review_status": row.review_status, "rejection_reason": row.rejection_reason,
        "matched_master_tbbm_id": str(row.matched_master_tbbm_id) if row.matched_master_tbbm_id else None,
        "duplicate_group_id": str(row.duplicate_group_id) if row.duplicate_group_id else None,
        "duplicate_distance_meters": row.duplicate_distance_meters, "duplicate_score": row.duplicate_score,
        "address_similarity": row.address_similarity, "discovered_at": iso(row.discovered_at),
        "matched_master": master_dict(master) if master else None,
    }
    if detail:
        payload["query_provenance"] = row.query_provenance or []
        payload["raw_payload"] = row.raw_payload
    return payload


@router.get("/provinces")
def list_provinces(db: Db) -> list[dict[str, Any]]:
    return [province_dict(row) for row in db.scalars(select(MasterProvince).where(MasterProvince.is_active.is_(True)).order_by(MasterProvince.name))]


@router.get("/summary")
def get_summary(db: Db) -> dict[str, int]:
    base = MasterTbbm.deleted_at.is_(None)

    def count(*conditions: Any) -> int:
        return db.scalar(select(func.count(MasterTbbm.id)).where(base, *conditions)) or 0

    return {
        "total_terminal": count(), "verified": count(MasterTbbm.verification_status == "VERIFIED"),
        "need_review": count(MasterTbbm.verification_status == "NEED_REVIEW"),
        "tbbm": count(MasterTbbm.terminal_type == "TBBM"),
        "fuel_terminal": count(MasterTbbm.terminal_type == "FUEL_TERMINAL"),
        "integrated_terminal": count(MasterTbbm.terminal_type == "INTEGRATED_TERMINAL"),
        "depot_bbm": count(MasterTbbm.terminal_type == "DEPOT_BBM"),
        "tlpg": count(MasterTbbm.terminal_type == "TLPG"),
    }


@router.get("/map")
def map_terminals(db: Db) -> list[dict[str, Any]]:
    rows = db.scalars(select(MasterTbbm).where(MasterTbbm.deleted_at.is_(None)).order_by(MasterTbbm.name)).all()
    return [master_dict(row) for row in rows]


@router.get("")
def list_tbbm(
    db: Db,
    page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=200), search: str | None = None,
    province_id: int | None = None, terminal_type: str | None = None, verification_status: str | None = None,
    operational_status: str | None = None, source: str | None = None,
    sort_by: str = "name", sort_order: str = "asc",
) -> dict[str, Any]:
    statement = select(MasterTbbm).where(MasterTbbm.deleted_at.is_(None))
    if search:
        term = f"%{search.strip()}%"
        statement = statement.where(or_(MasterTbbm.name.ilike(term), MasterTbbm.address.ilike(term), MasterTbbm.tbbm_code.ilike(term)))
    for column, value in [
        (MasterTbbm.province_id, province_id), (MasterTbbm.terminal_type, terminal_type),
        (MasterTbbm.verification_status, verification_status), (MasterTbbm.operational_status, operational_status),
        (MasterTbbm.source, source),
    ]:
        if value not in (None, ""):
            statement = statement.where(column == value)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    sortable = {
        "code": MasterTbbm.tbbm_code, "name": MasterTbbm.name, "terminal_type": MasterTbbm.terminal_type,
        "province": MasterTbbm.province_name, "verification": MasterTbbm.verification_status,
        "operational": MasterTbbm.operational_status, "last_verified": MasterTbbm.last_verified_at,
    }
    column = sortable.get(sort_by, MasterTbbm.name)
    ordering = desc(column) if sort_order.lower() == "desc" else asc(column)
    rows = db.scalars(statement.order_by(ordering).offset((page - 1) * per_page).limit(per_page)).all()
    return {"items": [master_dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/settings")
def get_settings(db: Db) -> dict[str, Any]:
    row = runtime_tbbm_settings(db)
    return {
        "api": "Places API (New)", "api_key_status": "CONFIGURED" if get_google_maps_api_key() else "NOT_CONFIGURED",
        "api_key_source": get_google_maps_api_key_source(), "country": row.country,
        "language_code": row.language_code, "search_strategy": row.search_strategy,
        "request_delay_ms": row.request_delay_ms, "maximum_retry": row.maximum_retry,
        "timeout_seconds": row.timeout_seconds, "duplicate_radius_meters": row.duplicate_radius_meters,
        "name_similarity_threshold": row.name_similarity_threshold,
    }


@router.patch("/settings", dependencies=[Depends(require_internal_token)])
def patch_settings(payload: TbbmSettingsUpdate, db: Db) -> dict[str, Any]:
    row = runtime_tbbm_settings(db)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    db.commit()
    return get_settings(db)


@router.post("/settings/test-google-places", dependencies=[Depends(require_internal_token)])
def test_google_places(db: Db) -> dict[str, Any]:
    row = runtime_tbbm_settings(db)
    try:
        return GooglePlacesTextSearchService(
            timeout_seconds=row.timeout_seconds, maximum_retry=row.maximum_retry, request_delay_ms=row.request_delay_ms,
        ).test_connection()
    except GooglePlacesConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GooglePlacesAuthenticationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Google Places API tidak dapat dihubungi.") from exc


@router.get("/discovery/keywords")
def list_keywords(db: Db, active_only: bool = False) -> list[dict[str, Any]]:
    statement = select(TbbmDiscoveryKeyword)
    if active_only:
        statement = statement.where(TbbmDiscoveryKeyword.is_active.is_(True))
    rows = db.scalars(statement.order_by(TbbmDiscoveryKeyword.sort_order, TbbmDiscoveryKeyword.keyword)).all()
    return [{"id": row.id, "keyword": row.keyword, "is_active": row.is_active, "sort_order": row.sort_order} for row in rows]


@router.post("/discovery/keywords", dependencies=[Depends(require_internal_token)])
def create_keyword(payload: KeywordCreate, db: Db) -> dict[str, Any]:
    if db.scalar(select(TbbmDiscoveryKeyword.id).where(func.lower(TbbmDiscoveryKeyword.keyword) == payload.keyword.lower())):
        raise HTTPException(status_code=409, detail="Keyword sudah digunakan.")
    row = TbbmDiscoveryKeyword(**payload.model_dump())
    db.add(row)
    db.commit()
    return {"id": row.id, "keyword": row.keyword, "is_active": row.is_active, "sort_order": row.sort_order}


@router.patch("/discovery/keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def patch_keyword(keyword_id: int, payload: KeywordUpdate, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryKeyword, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(row, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Keyword sudah digunakan.") from exc
    return {"id": row.id, "keyword": row.keyword, "is_active": row.is_active, "sort_order": row.sort_order}


@router.delete("/discovery/keywords/{keyword_id}", dependencies=[Depends(require_internal_token)])
def deactivate_keyword(keyword_id: int, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryKeyword, keyword_id)
    if not row:
        raise HTTPException(status_code=404, detail="Keyword not found")
    row.is_active = False
    db.commit()
    return {"id": row.id, "is_active": False, "message": "Keyword dinonaktifkan untuk menjaga histori."}


@router.post("/discovery/jobs", dependencies=[Depends(require_internal_token)])
def create_discovery_job(payload: DiscoveryJobCreate, db: Db) -> dict[str, Any]:
    if not get_google_maps_api_key():
        raise HTTPException(status_code=503, detail="Google Places API key belum dikonfigurasi.")
    keywords = db.scalars(select(TbbmDiscoveryKeyword).where(
        TbbmDiscoveryKeyword.id.in_(payload.selected_keyword_ids), TbbmDiscoveryKeyword.is_active.is_(True),
    ).order_by(TbbmDiscoveryKeyword.sort_order)).all()
    if len(keywords) != len(set(payload.selected_keyword_ids)):
        raise HTTPException(status_code=422, detail="Satu atau lebih keyword tidak aktif atau tidak ditemukan.")
    province_statement = select(MasterProvince).where(MasterProvince.is_active.is_(True))
    if payload.search_scope == "SELECTED_PROVINCE":
        province_statement = province_statement.where(MasterProvince.id.in_(payload.selected_province_ids))
    provinces = db.scalars(province_statement.order_by(MasterProvince.name)).all()
    if not provinces:
        raise HTTPException(status_code=422, detail="Tidak ada provinsi aktif yang dipilih.")
    job = TbbmDiscoveryJob(
        id=uuid.uuid4(), status="PENDING", search_scope=payload.search_scope,
        selected_provinces=[province_dict(row) for row in provinces],
        selected_keywords=[{"id": row.id, "keyword": row.keyword} for row in keywords],
        existing_data_mode=payload.existing_data_mode, total_queries=len(provinces) * len(keywords), created_by="admin",
    )
    db.add(job)
    db.commit()
    try:
        task = celery_app.send_task("fuel.tbbm.discover", args=[str(job.id)], queue="tbbm")
    except Exception as exc:
        job.status = "FAILED"
        job.error_message = "Discovery worker tidak dapat dijadwalkan."
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        raise HTTPException(status_code=503, detail=job.error_message) from exc
    return {**job_dict(job), "task_id": task.id}


@router.get("/discovery/jobs")
def list_jobs(db: Db, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)) -> dict[str, Any]:
    total = db.scalar(select(func.count(TbbmDiscoveryJob.id))) or 0
    rows = db.scalars(select(TbbmDiscoveryJob).order_by(TbbmDiscoveryJob.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return {"items": [job_dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/discovery/jobs/{job_id}")
def get_job(job_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    return job_dict(row)


@router.post("/discovery/jobs/{job_id}/cancel", dependencies=[Depends(require_internal_token)])
def cancel_job(job_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryJob, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    if row.status not in {"PENDING", "RUNNING"}:
        raise HTTPException(status_code=409, detail="Job sudah selesai dan tidak dapat dibatalkan.")
    row.status = "CANCELLED"
    row.finished_at = datetime.now(timezone.utc)
    db.commit()
    return job_dict(row)


@router.post("/discovery/jobs/{job_id}/retry-failed", dependencies=[Depends(require_internal_token)])
def retry_failed_queries(job_id: uuid.UUID, db: Db) -> dict[str, Any]:
    source = db.get(TbbmDiscoveryJob, job_id)
    if not source:
        raise HTTPException(status_code=404, detail="Discovery job not found")
    if not source.failed_query_details:
        raise HTTPException(status_code=409, detail="Job tidak memiliki request gagal untuk diulang.")
    retry_queries = [{key: item.get(key) for key in ["province_id", "province_name", "keyword_id", "keyword", "query_text"]} for item in source.failed_query_details]
    job = TbbmDiscoveryJob(
        id=uuid.uuid4(), status="PENDING", search_scope="RETRY_FAILED",
        selected_provinces=source.selected_provinces, selected_keywords=source.selected_keywords,
        retry_queries=retry_queries, existing_data_mode=source.existing_data_mode,
        total_queries=len(retry_queries), created_by="admin",
    )
    db.add(job)
    db.commit()
    task = celery_app.send_task("fuel.tbbm.discover", args=[str(job.id)], queue="tbbm")
    return {**job_dict(job), "task_id": task.id}


@router.get("/discovery/jobs/{job_id}/results")
def list_results(
    job_id: uuid.UUID, db: Db, page: int = Query(1, ge=1), per_page: int = Query(25, ge=1, le=200),
    province_id: int | None = None, keyword_id: int | None = None, terminal_type: str | None = None,
    match_status: str | None = None, review_status: str | None = None,
) -> dict[str, Any]:
    statement = select(TbbmDiscoveryResult).where(TbbmDiscoveryResult.discovery_job_id == job_id)
    for column, value in [
        (TbbmDiscoveryResult.province_id, province_id), (TbbmDiscoveryResult.keyword_id, keyword_id),
        (TbbmDiscoveryResult.terminal_type, terminal_type), (TbbmDiscoveryResult.match_status, match_status),
        (TbbmDiscoveryResult.review_status, review_status),
    ]:
        if value not in (None, ""):
            statement = statement.where(column == value)
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    rows = db.scalars(statement.order_by(TbbmDiscoveryResult.created_at.desc()).offset((page - 1) * per_page).limit(per_page)).all()
    return {"items": [result_dict(row) for row in rows], "total": total, "page": page, "per_page": per_page}


@router.get("/discovery/results/{result_id}")
def get_result(result_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryResult, result_id)
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    return result_dict(row, detail=True)


@router.patch("/discovery/results/{result_id}", dependencies=[Depends(require_internal_token)])
def patch_result(result_id: uuid.UUID, payload: DiscoveryResultUpdate, db: Db) -> dict[str, Any]:
    row = db.get(TbbmDiscoveryResult, result_id)
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if row.review_status != "PENDING_REVIEW":
        raise HTTPException(status_code=409, detail="Candidate yang sudah direview tidak dapat diedit.")
    values = payload.model_dump(exclude_unset=True)
    province = db.get(MasterProvince, values["province_id"]) if values.get("province_id") else None
    for key, value in values.items():
        setattr(row, key, value)
    if "place_name" in values:
        row.normalized_name = normalize_terminal_name(row.place_name)
    if "province_id" in values:
        row.province_name = province.name if province else None
    if "latitude" in values or "longitude" in values:
        row.geom = point(row.latitude, row.longitude)
    reason = false_positive_reason(row.normalized_name, row.google_types or [], row.terminal_type)
    row.rejection_reason = reason
    if row.match_status == "AUTO_REJECTED" and not reason:
        row.match_status = "NEW"
    db.commit()
    return result_dict(row, detail=True)


@router.post("/discovery/results/{result_id}/approve", dependencies=[Depends(require_internal_token)])
def approve_result(result_id: uuid.UUID, db: Db, keep_both: bool = False) -> dict[str, Any]:
    try:
        row = approve_candidate(db, result_id, allow_possible_duplicate=keep_both)
        return master_dict(row, detail=True, db=db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Google Place ID sudah digunakan oleh Master TBBM lain.") from exc


@router.post("/discovery/results/{result_id}/reject", dependencies=[Depends(require_internal_token)])
def reject_result(result_id: uuid.UUID, payload: ReviewReason, db: Db) -> dict[str, Any]:
    try:
        return result_dict(reject_candidate(db, result_id, payload.reason), detail=True)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/discovery/results/{result_id}/merge", dependencies=[Depends(require_internal_token)])
def merge_result(result_id: uuid.UUID, payload: MergeCandidate, db: Db) -> dict[str, Any]:
    try:
        return master_dict(merge_candidate(db, result_id, payload.master_tbbm_id), detail=True, db=db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Google Place ID sudah digunakan oleh Master TBBM lain.") from exc


@router.post("/discovery/results/bulk-approve", dependencies=[Depends(require_internal_token)])
def bulk_approve(payload: BulkReview, db: Db) -> dict[str, Any]:
    rows = db.scalars(select(TbbmDiscoveryResult).where(TbbmDiscoveryResult.id.in_(payload.result_ids))).all()
    blocked = [row for row in rows if row.match_status in {"POSSIBLE_DUPLICATE", "AUTO_REJECTED"}]
    if blocked:
        raise HTTPException(status_code=409, detail="Bulk approval tidak boleh mencakup possible duplicate atau auto-rejected.")
    approved = []
    for row in rows:
        approved.append(str(approve_candidate(db, row.id).id))
    return {"approved": len(approved), "master_tbbm_ids": approved}


@router.post("/discovery/results/bulk-reject", dependencies=[Depends(require_internal_token)])
def bulk_reject(payload: BulkReview, db: Db) -> dict[str, Any]:
    reason = payload.reason or "Ditolak melalui bulk review."
    count = 0
    for result_id in payload.result_ids:
        reject_candidate(db, result_id, reason)
        count += 1
    return {"rejected": count}


@router.get("/discovery/analytics/keywords")
def keyword_performance(db: Db) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            TbbmDiscoveryKeyword.id, TbbmDiscoveryKeyword.keyword,
            func.count(func.distinct(TbbmDiscoveryResult.id)).label("raw_places"),
            func.count(func.distinct(TbbmDiscoveryProvenance.discovery_result_id)).label("unique_candidates"),
            func.count(func.distinct(TbbmDiscoveryProvenance.master_tbbm_id)).label("approved_terminals"),
        )
        .outerjoin(TbbmDiscoveryResult, TbbmDiscoveryResult.keyword_id == TbbmDiscoveryKeyword.id)
        .outerjoin(TbbmDiscoveryProvenance, TbbmDiscoveryProvenance.keyword_id == TbbmDiscoveryKeyword.id)
        .group_by(TbbmDiscoveryKeyword.id, TbbmDiscoveryKeyword.keyword)
        .order_by(desc("approved_terminals"), TbbmDiscoveryKeyword.sort_order)
    ).all()
    return [{
        "keyword_id": row.id, "keyword": row.keyword, "raw_places": row.raw_places,
        "unique_candidates": row.unique_candidates, "approved_terminals": row.approved_terminals,
    } for row in rows]


@router.post("", dependencies=[Depends(require_internal_token)])
def create_tbbm(payload: TbbmCreate, db: Db) -> dict[str, Any]:
    try:
        row = create_manual_tbbm(db, payload.model_dump(mode="python"))
        return master_dict(row, detail=True, db=db)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Google Place ID sudah digunakan oleh Master TBBM lain.") from exc


@router.get("/{tbbm_id}")
def get_tbbm(tbbm_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.scalar(select(MasterTbbm).where(MasterTbbm.id == tbbm_id, MasterTbbm.deleted_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Master TBBM not found")
    return master_dict(row, detail=True, db=db)


@router.patch("/{tbbm_id}", dependencies=[Depends(require_internal_token)])
def patch_tbbm(tbbm_id: uuid.UUID, payload: TbbmUpdate, db: Db) -> dict[str, Any]:
    row = db.scalar(select(MasterTbbm).where(MasterTbbm.id == tbbm_id, MasterTbbm.deleted_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Master TBBM not found")
    try:
        return master_dict(update_master_tbbm(db, row, payload.model_dump(exclude_unset=True, mode="python")), detail=True, db=db)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Google Place ID sudah digunakan oleh Master TBBM lain.") from exc


@router.delete("/{tbbm_id}", dependencies=[Depends(require_internal_token)])
def deactivate_tbbm(tbbm_id: uuid.UUID, db: Db) -> dict[str, Any]:
    row = db.scalar(select(MasterTbbm).where(MasterTbbm.id == tbbm_id, MasterTbbm.deleted_at.is_(None)))
    if not row:
        raise HTTPException(status_code=404, detail="Master TBBM not found")
    row.operational_status = "INACTIVE"
    row.deleted_at = datetime.now(timezone.utc)
    row.updated_by = "admin"
    db.commit()
    return {"id": str(row.id), "deactivated": True}
