from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from app.workers.tasks import build_full_refresh_workflow, summarize_tiktok_refresh

TOKEN_HEADER = {"X-Internal-Token": settings.internal_api_token.get_secret_value()}
JOB_ID = "19379bf0-0cb2-42fa-b47b-388a3377169a"


class FakeTask:
    id = JOB_ID


class FakeResult:
    state = "SUCCESS"
    result = {
        "collection": {
            "sources_checked": 2,
            "candidates_seen": 20,
            "new_signals": 3,
            "duplicates": 17,
            "source_errors": 0,
            "tiktok": {
                "status": "SUCCESS",
                "keywords_run": 2,
                "new_videos": 4,
                "runs_failed": 0,
                "runs_partial": 0,
            },
        },
        "incidents_recalculated": 12,
        "analytics_rows": 8,
    }


def test_full_refresh_workflow_runs_news_and_tiktok_before_shared_processing():
    requested_at = datetime(2026, 9, 4, 10, 0, tzinfo=timezone.utc)
    workflow = build_full_refresh_workflow(requested_at)

    assert [task.task for task in workflow.tasks] == [
        "fuel.news.collect",
        "fuel.tiktok.collect-for-refresh",
    ]
    assert [task.options["queue"] for task in workflow.tasks] == ["news", "tiktok"]
    assert workflow.tasks[1].args == (requested_at.isoformat(),)
    assert [task.task for task in workflow.body.tasks] == [
        "fuel.intelligence.recalculate",
        "fuel.intelligence.finalize",
    ]
    assert [task.options["queue"] for task in workflow.body.tasks] == ["incident", "analytics"]


def test_tiktok_refresh_summary_preserves_partial_run_counts():
    summary = summarize_tiktok_refresh([
        {
            "run_id": "run-1", "status": "SUCCESS", "results": 8, "new": 3,
            "duplicates": 5, "relevant": 2, "incidents": 1, "credits": 4,
        },
        {
            "run_id": "run-2", "status": "FAILED", "results": 0, "new": 0,
            "duplicates": 0, "relevant": 0, "incidents": 0, "credits": 1,
        },
    ])

    assert summary == {
        "status": "PARTIAL",
        "keywords_run": 2,
        "runs_successful": 1,
        "runs_partial": 0,
        "runs_failed": 1,
        "results_found": 8,
        "new_videos": 3,
        "duplicates": 5,
        "relevant_videos": 2,
        "incidents_created": 1,
        "credits_used": 5,
        "run_ids": ["run-1", "run-2"],
    }


def test_full_refresh_endpoint_requires_internal_token():
    with TestClient(app) as client:
        response = client.post("/api/internal/intelligence/refresh")

    assert response.status_code == 401


def test_full_refresh_endpoint_queues_coordinator(monkeypatch):
    captured = {}

    def fake_send_task(name, **options):
        captured.update({"name": name, **options})
        return FakeTask()

    monkeypatch.setattr("app.api.routes.celery_app.send_task", fake_send_task)

    with TestClient(app) as client:
        response = client.post("/api/internal/intelligence/refresh", headers=TOKEN_HEADER)

    assert response.status_code == 202
    assert response.json() == {"job_id": JOB_ID, "status": "PENDING", "done": False}
    assert captured == {"name": "fuel.intelligence.refresh", "queue": "analytics"}


def test_full_refresh_status_returns_final_result(monkeypatch):
    monkeypatch.setattr("app.api.routes.celery_app.AsyncResult", lambda task_id: FakeResult())

    with TestClient(app) as client:
        response = client.get(f"/api/internal/intelligence/refresh/{JOB_ID}", headers=TOKEN_HEADER)

    assert response.status_code == 200
    assert response.json() == {
        "job_id": JOB_ID,
        "status": "SUCCESS",
        "done": True,
        "successful": True,
        "result": FakeResult.result,
    }


def test_full_refresh_status_rejects_invalid_job_id():
    with TestClient(app) as client:
        response = client.get("/api/internal/intelligence/refresh/not-a-job", headers=TOKEN_HEADER)

    assert response.status_code == 422
