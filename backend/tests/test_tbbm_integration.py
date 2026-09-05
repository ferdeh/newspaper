import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, func, select

from app.database import SessionLocal
from app.models import Incident, MasterTbbm, TbbmDiscoveryJob, TbbmDiscoveryProvenance, TbbmDiscoveryResult
from app.services.geography import assign_nearest_terminal
from app.services.tbbm_discovery import TbbmDiscoveryService, approve_candidate, merge_candidate, point, runtime_tbbm_settings
from app.services.tbbm_runtime import runtime_tbbm_conditions


@pytest.mark.integration
def test_runtime_registry_uses_only_verified_non_deleted_tbbm():
    suffix = uuid.uuid4().hex[:10]
    rows = [
        MasterTbbm(
            id=uuid.uuid4(), tbbm_code=f"RUNTIME-V-{suffix}", name="Runtime Verified",
            normalized_name="runtime verified", terminal_type="TBBM", latitude=-6.2, longitude=106.8,
            source="MANUAL", verification_status="VERIFIED", operational_status="UNKNOWN",
        ),
        MasterTbbm(
            id=uuid.uuid4(), tbbm_code=f"RUNTIME-N-{suffix}", name="Runtime Need Review",
            normalized_name="runtime need review", terminal_type="TBBM", latitude=-6.3, longitude=106.9,
            source="MANUAL", verification_status="NEED_REVIEW", operational_status="UNKNOWN",
        ),
        MasterTbbm(
            id=uuid.uuid4(), tbbm_code=f"RUNTIME-D-{suffix}", name="Runtime Deleted",
            normalized_name="runtime deleted", terminal_type="TBBM", latitude=-6.4, longitude=107.0,
            source="MANUAL", verification_status="VERIFIED", operational_status="UNKNOWN",
            deleted_at=datetime.now(timezone.utc),
        ),
    ]
    try:
        with SessionLocal() as db:
            db.add_all(rows)
            db.commit()
            runtime_ids = set(db.scalars(select(MasterTbbm.id).where(*runtime_tbbm_conditions())))
            assert rows[0].id in runtime_ids
            assert rows[1].id not in runtime_ids
            assert rows[2].id not in runtime_ids
    finally:
        with SessionLocal() as db:
            db.execute(delete(MasterTbbm).where(MasterTbbm.id.in_([row.id for row in rows])))
            db.commit()


@pytest.mark.integration
def test_nearest_tbbm_uses_postgis_and_excludes_unverified_or_deleted_rows():
    suffix = uuid.uuid4().hex[:10]
    incident_id = None
    verified_id = uuid.uuid4()
    tbbm_ids = [verified_id, uuid.uuid4(), uuid.uuid4()]
    try:
        with SessionLocal() as db:
            rows = [
                MasterTbbm(
                    id=verified_id, tbbm_code=f"NEAREST-V-{suffix}", name="Verified nearest",
                    normalized_name="verified nearest", terminal_type="TBBM", latitude=0.0, longitude=0.01,
                    geom=point(0.0, 0.01), source="MANUAL", verification_status="VERIFIED",
                    operational_status="UNKNOWN",
                ),
                MasterTbbm(
                    id=tbbm_ids[1], tbbm_code=f"NEAREST-N-{suffix}", name="Unverified closer",
                    normalized_name="unverified closer", terminal_type="TBBM", latitude=0.0, longitude=0.001,
                    geom=point(0.0, 0.001), source="MANUAL", verification_status="NEED_REVIEW",
                    operational_status="UNKNOWN",
                ),
                MasterTbbm(
                    id=tbbm_ids[2], tbbm_code=f"NEAREST-D-{suffix}", name="Deleted closer",
                    normalized_name="deleted closer", terminal_type="TBBM", latitude=0.0, longitude=0.0005,
                    geom=point(0.0, 0.0005), source="MANUAL", verification_status="VERIFIED",
                    operational_status="UNKNOWN", deleted_at=datetime.now(timezone.utc),
                ),
            ]
            incident = Incident(
                incident_code=f"NEAREST-{suffix}", event_category="SUPPLY_DISRUPTION",
                primary_event_type="FUEL_SCARCITY", products=[], status="OPEN", severity="LOW",
                confidence=0.5, latitude=0.0, longitude=0.0,
                nearest_terminal_distance_source="GOOGLE_ROUTES", nearest_terminal_duration_minutes=90,
                first_signal_at=datetime.now(timezone.utc), last_signal_at=datetime.now(timezone.utc),
            )
            db.add_all([*rows, incident])
            db.flush()
            incident_id = incident.id

            assign_nearest_terminal(db, incident)
            db.commit()

            assert incident.nearest_tbbm_id == verified_id
            assert 1.0 < incident.nearest_terminal_distance_km < 1.2
            assert incident.nearest_terminal_distance_source == "POSTGIS_STRAIGHT_LINE"
            assert incident.nearest_terminal_duration_minutes is None
    finally:
        with SessionLocal() as db:
            if incident_id is not None:
                db.execute(delete(Incident).where(Incident.id == incident_id))
            db.execute(delete(MasterTbbm).where(MasterTbbm.id.in_(tbbm_ids)))
            db.commit()


@pytest.mark.integration
def test_tbbm_discovery_dedup_approval_concurrency_and_merge_contract():
    suffix = uuid.uuid4().hex[:10]
    job_id = uuid.uuid4()
    master_id = uuid.uuid4()
    created_result_ids = []
    created_master_ids = [master_id]
    try:
        with SessionLocal() as db:
            job = TbbmDiscoveryJob(
                id=job_id, status="RUNNING", search_scope="SELECTED_PROVINCE",
                selected_provinces=[], selected_keywords=[], total_queries=3, created_by="pytest",
            )
            master = MasterTbbm(
                id=master_id, tbbm_code=f"TEST-{suffix}", name=f"Fuel Terminal Test {suffix}",
                normalized_name=f"fuel terminal test {suffix}", terminal_type="FUEL_TERMINAL",
                latitude=-6.2, longitude=106.8, source="MANUAL", verification_status="VERIFIED",
                operational_status="UNKNOWN", google_place_id=f"existing-{suffix}", manual_overrides=["name"],
            )
            db.add_all([job, master])
            db.commit()
            service = TbbmDiscoveryService(db)
            configuration = runtime_tbbm_settings(db)
            task_a = {
                "province_id": 31, "province_name": "DKI Jakarta", "keyword_id": 1,
                "keyword": "TBBM Pertamina", "query_text": "TBBM Pertamina DKI Jakarta",
            }
            task_b = {**task_a, "keyword_id": 3, "keyword": "Fuel Terminal Pertamina", "query_text": "Fuel Terminal Pertamina DKI Jakarta"}
            exact_payload = {
                "id": f"existing-{suffix}", "displayName": {"text": f"Fuel Terminal Test {suffix}"},
                "formattedAddress": "Jakarta", "location": {"latitude": -6.2, "longitude": 106.8},
                "types": ["establishment"], "primaryType": "establishment",
            }
            exact = service._store_result(job, task_a, 1, exact_payload, configuration)
            same = service._store_result(job, task_b, 1, exact_payload, configuration)
            assert same.id == exact.id
            assert same.source_keywords == ["Fuel Terminal Pertamina", "TBBM Pertamina"]
            assert len(same.query_provenance) == 2
            assert same.match_status == "EXISTING"
            created_result_ids.append(exact.id)

            fuzzy_payload = {
                "id": f"fuzzy-{suffix}", "displayName": {"text": f"Pertamina Fuel Terminal Test {suffix}"},
                "formattedAddress": "Jakarta Utara", "location": {"latitude": -6.1995, "longitude": 106.8004},
                "types": ["establishment"], "primaryType": "establishment",
            }
            fuzzy = service._store_result(job, task_a, 1, fuzzy_payload, configuration)
            assert fuzzy.match_status == "POSSIBLE_DUPLICATE"
            assert fuzzy.matched_master_tbbm_id == master_id
            created_result_ids.append(fuzzy.id)

            new_payload = {
                "id": f"new-{suffix}", "displayName": {"text": f"TBBM Concurrent {suffix}"},
                "formattedAddress": "Surabaya", "location": {"latitude": -7.25, "longitude": 112.75},
                "types": ["establishment"], "primaryType": "establishment",
            }
            new_result = service._store_result(job, task_a, 1, new_payload, configuration)
            created_result_ids.append(new_result.id)
            db.commit()
            assert new_result.match_status == "NEW"

        def approve_once():
            with SessionLocal() as thread_db:
                return approve_candidate(thread_db, new_result.id).id

        with ThreadPoolExecutor(max_workers=2) as pool:
            approved_ids = list(pool.map(lambda _: approve_once(), range(2)))
        assert approved_ids[0] == approved_ids[1]
        created_master_ids.append(approved_ids[0])

        with SessionLocal() as db:
            assert db.scalar(select(func.count(MasterTbbm.id)).where(MasterTbbm.google_place_id == f"new-{suffix}")) == 1
            merged = merge_candidate(db, fuzzy.id, master_id)
            assert merged.id == master_id
            assert db.get(TbbmDiscoveryResult, fuzzy.id).review_status == "MERGED"
            assert db.scalar(select(func.count(MasterTbbm.id)).where(MasterTbbm.google_place_id == f"fuzzy-{suffix}")) == 0
            assert db.scalar(select(func.count(TbbmDiscoveryProvenance.id)).where(TbbmDiscoveryProvenance.master_tbbm_id == master_id)) >= 1
    finally:
        with SessionLocal() as db:
            db.execute(delete(TbbmDiscoveryProvenance).where(TbbmDiscoveryProvenance.discovery_job_id == job_id))
            db.execute(delete(TbbmDiscoveryResult).where(TbbmDiscoveryResult.id.in_(created_result_ids)))
            db.execute(delete(TbbmDiscoveryJob).where(TbbmDiscoveryJob.id == job_id))
            db.execute(delete(MasterTbbm).where(MasterTbbm.id.in_(created_master_ids)))
            db.commit()


@pytest.mark.integration
def test_partial_google_failure_keeps_successful_results_and_marks_job(monkeypatch):
    job_id = uuid.uuid4()

    class PartialGoogleClient:
        def __init__(self, **kwargs):
            pass

        def iter_pages(self, query, language_code):
            if query.startswith("Fail"):
                raise RuntimeError("simulated transient failure after retries")
            yield 1, [{
                "id": f"partial-{job_id}", "displayName": {"text": "TBBM Partial Test"},
                "formattedAddress": "Aceh", "location": {"latitude": 5.55, "longitude": 95.32},
                "types": ["establishment"], "primaryType": "establishment",
            }]

    monkeypatch.setattr("app.services.tbbm_discovery.GooglePlacesTextSearchService", PartialGoogleClient)
    retry_queries = [
        {"province_id": 11, "province_name": "Aceh", "keyword_id": 1, "keyword": "TBBM Pertamina", "query_text": "Success Aceh"},
        {"province_id": 11, "province_name": "Aceh", "keyword_id": 1, "keyword": "TBBM Pertamina", "query_text": "Fail Aceh"},
    ]
    try:
        with SessionLocal() as db:
            db.add(TbbmDiscoveryJob(
                id=job_id, status="PENDING", search_scope="RETRY_FAILED", selected_provinces=[],
                selected_keywords=[], retry_queries=retry_queries, total_queries=2, created_by="pytest",
            ))
            db.commit()
            result = TbbmDiscoveryService(db).run(job_id)
            job = db.get(TbbmDiscoveryJob, job_id)
            assert result["status"] == "COMPLETED_WITH_ERRORS"
            assert job.completed_queries == 2
            assert job.successful_queries == 1
            assert job.failed_queries == 1
            assert job.raw_result_count == 1
            assert job.unique_place_count == 1
            assert db.scalar(select(func.count(TbbmDiscoveryResult.id)).where(TbbmDiscoveryResult.discovery_job_id == job_id)) == 1
    finally:
        with SessionLocal() as db:
            db.execute(delete(TbbmDiscoveryResult).where(TbbmDiscoveryResult.discovery_job_id == job_id))
            db.execute(delete(TbbmDiscoveryJob).where(TbbmDiscoveryJob.id == job_id))
            db.commit()
