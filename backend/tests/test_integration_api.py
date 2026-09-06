import os

import httpx
import pytest

BASE_URL = os.getenv("INTEGRATION_BASE_URL", "http://api:8000")


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10) as value:
        yield value


@pytest.mark.integration
def test_live_news_is_available_without_demo_records(client):
    news = client.get("/api/news", params={"limit": 500}).json()
    tiktok = client.get("/api/tiktok", params={"limit": 500}).json()
    assert news["total"] > 0
    assert all(not row["demo"] for row in news["items"])
    assert all(not row["demo"] for row in tiktok["items"])


@pytest.mark.integration
def test_incident_detail_matches_retained_live_evidence(client):
    items = client.get("/api/incidents").json()["items"]
    assert items
    item = items[0]
    detail = client.get(f"/api/incidents/{item['id']}").json()
    assert detail["signal_count"] == len(detail["signals"])
    assert detail["news_count"] == sum(row["source_type"] == "NEWS" for row in detail["signals"])
    assert detail["tiktok_count"] == sum(row["source_type"] == "TIKTOK" for row in detail["signals"])
    assert all("demo" not in row["url"].lower() for row in detail["signals"])


@pytest.mark.integration
def test_incident_categories_and_risk_contract(client):
    items = client.get("/api/incidents").json()["items"]
    assert items
    assert all(item["category"] in {"SUPPLY_DISRUPTION", "HSSE", "EXTERNAL_DISRUPTION"} for item in items)
    assert all(0 <= item["supply_risk"] <= 100 and 0 <= item["hsse_risk"] <= 100 for item in items)


@pytest.mark.integration
def test_leaflet_map_contract_contains_terminals_and_auditable_geo_sources(client):
    overview = client.get("/api/analytics/overview").json()
    assert overview["scheduler_update"]["interval_minutes"] > 0
    assert overview["scheduler_update"]["last_update_at"]
    assert overview["scheduler_update"]["next_update_at"] > overview["scheduler_update"]["last_update_at"]
    assert all({"date", "incidents", "signals"} <= set(row) for row in overview["trend"])
    assert all(row["signals"] >= row["incidents"] for row in overview["trend"])
    verified = client.get(
        "/api/tbbm", params={"verification_status": "VERIFIED", "per_page": 200}
    ).json()["items"]
    verified_ids = {row["id"] for row in verified}
    assert overview["terminals"]
    assert {row["id"] for row in overview["terminals"]} == verified_ids
    assert {
        row["nearest_terminal_id"] for row in overview["map"] if row["nearest_terminal_id"]
    } <= verified_ids
    assert all(row["lat"] is not None and row["lng"] is not None for row in overview["terminals"])
    assert all(row["lat"] is not None and row["lng"] is not None for row in overview["map"])
    assert all("province" in row for row in overview["map"])
    assert all(row["incident_date"] for row in overview["map"])
    assert all("news_date" in row for row in overview["map"])
    assert all(row["news_date"] is not None for row in overview["map"] if row["news"] > 0)
    allowed_sources = {"POSTGIS_STRAIGHT_LINE", None}
    assert all(row["nearest_terminal_distance_source"] in allowed_sources for row in overview["map"])
    heatmap_keys = {
        "province", "incident_count", "max_risk", "average_risk", "critical_count",
        "supply_incidents", "hsse_incidents", "external_incidents", "news_count", "tiktok_count",
        "mapped_incidents", "label_lat", "label_lng", "period_start", "period_end",
    }
    assert all(heatmap_keys <= set(row) for row in overview["province_heatmap"])
    assert all(row["max_risk"] >= row["average_risk"] for row in overview["province_heatmap"])
    assert all(row["critical_count"] <= row["incident_count"] for row in overview["province_heatmap"])
    assert all(
        row["supply_incidents"] + row["hsse_incidents"] + row["external_incidents"] == row["incident_count"]
        for row in overview["province_heatmap"]
    )


@pytest.mark.integration
def test_terminal_and_spbu_fields_do_not_reference_demo_master_data(client):
    items = client.get("/api/incidents").json()["items"]
    assert all(not item["spbu"] or "demo" not in item["spbu"].lower() for item in items)
    masters = client.get("/api/admin/master-data").json()
    assert "terminals" not in masters
    assert all("demo" not in row["name"].lower() for row in masters["spbu"])


@pytest.mark.integration
def test_alert_dedupe_contract_if_alerts_exist(client):
    alerts = client.get("/api/alerts").json()["items"]
    # Daily digests intentionally repeat on a new calendar day; incident-band alerts do not.
    operational_alerts = [row for row in alerts if row["alert_type"] != "DAILY_DIGEST"]
    pairs = [(row["incident_id"], row["alert_type"], row["severity"]) for row in operational_alerts]
    assert len(pairs) == len(set(pairs))


@pytest.mark.integration
def test_news_sources_are_live_or_operator_configured(client):
    sources = client.get("/api/admin/news-sources").json()
    assert any(row["last_success"] and not row["last_error"] for row in sources)
    assert all(not row["domain"].endswith(".demo") and not row["name"].lower().startswith("demo ") for row in sources)


@pytest.mark.integration
def test_news_sources_support_search_sort_and_pagination(client):
    first_page = client.get(
        "/api/admin/news-sources",
        params={"page": 1, "per_page": 10, "sort_by": "name", "sort_order": "asc"},
    ).json()
    assert first_page["page"] == 1
    assert first_page["per_page"] == 10
    assert first_page["total"] >= len(first_page["items"]) > 0
    assert first_page["pages"] >= 1
    assert len(first_page["items"]) <= 10
    assert [row["name"] for row in first_page["items"]] == sorted(row["name"] for row in first_page["items"])

    searched = client.get(
        "/api/admin/news-sources",
        params={"search": "Aceh", "page": 1, "per_page": 100, "sort_by": "coverage_area", "sort_order": "asc"},
    ).json()
    assert searched["total"] > 0
    assert all(
        "aceh" in " ".join(
            str(row.get(key) or "") for key in ("name", "coverage_area", "domain", "source_type", "feed_url", "last_error")
        ).lower()
        for row in searched["items"]
    )

    invalid_sort = client.get(
        "/api/admin/news-sources",
        params={"page": 1, "per_page": 10, "sort_by": "not_a_column"},
    )
    assert invalid_sort.status_code == 422


@pytest.mark.integration
def test_system_reports_independent_workers(client):
    status = client.get("/api/system/status").json()
    names = {item["name"] for item in status["services"]}
    assert {"news-worker", "tiktok-worker", "whatsapp-worker", "scheduler"} <= names
    assert status["database"] == "HEALTHY" and status["redis"] == "HEALTHY"


@pytest.mark.integration
def test_google_maps_secret_endpoint_requires_internal_token_and_never_returns_key(client):
    response = client.put("/api/admin/provider-secrets/google-maps", json={"api_key": "AIza-not-a-real-key-value"})
    assert response.status_code == 401
    geocoding = client.get("/api/admin/config").json()["geocoding"]
    assert set(geocoding) == {"provider", "credential", "source", "apis"}
    assert geocoding["apis"] == ["GEOCODING", "PLACES_TEXT_SEARCH"]
    assert "api_key" not in geocoding


@pytest.mark.integration
def test_email_provider_config_contract_never_returns_client_secret(client):
    response = client.get("/api/email/provider-configs")
    assert response.status_code == 200
    payload = response.json()
    assert {item["provider"] for item in payload["items"]} == {"GMAIL", "MICROSOFT"}
    for item in payload["items"]:
        assert "client_secret" not in item
        assert isinstance(item["client_secret_configured"], bool)
        assert item["redirect_uri"].endswith(
            f"/api/email/oauth/{'google' if item['provider'] == 'GMAIL' else 'microsoft'}/callback"
        )

    protected = client.put(
        "/api/email/provider-configs/MICROSOFT",
        json={
            "client_id": "not-authorized",
            "client_secret": "not-authorized-secret",
            "tenant": "common",
            "redirect_uri": "http://localhost/api/email/oauth/microsoft/callback",
        },
    )
    assert protected.status_code == 401
