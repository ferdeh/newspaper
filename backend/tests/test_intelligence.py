from datetime import datetime, timedelta, timezone

from app.services.intelligence import (
    calculate_lead_time,
    calculate_risk,
    calculate_trend,
    classify_text,
    extract_location_phrase,
    geographic_distance_km,
    normalize_text,
    resolve_alias,
    risk_band,
    spbu_match_score,
)


def test_location_normalization_and_alias_resolution():
    assert normalize_text("  Kota  Kupang—NTT ") == "kota kupang ntt"
    location_id, confidence = resolve_alias("Antrean di SPBU Oesapa Kupang", [(1, "Oesapa, Kupang", ["oesapa", "kelapa lima"]), (2, "Waingapu", [])])
    assert location_id == 1
    assert confidence > 0.7


def test_spbu_matching_requires_strong_evidence():
    assert spbu_match_score("Antrean di SPBU 54.851.01 Oesapa", "54.851.01", "SPBU Oesapa Kupang") == 0.99
    assert spbu_match_score("Antrean terjadi di suatu tempat", "54.851.01", "SPBU Oesapa Kupang") == 0


def test_headline_location_extraction_for_live_news():
    assert extract_location_phrase("Kelangkaan BBM Meluas di Putussibau, Warga Antre Panjang") == "Putussibau"
    assert extract_location_phrase("Truk Tangki BBM Terguling di Tol Weleri-Semarang") == "Tol Weleri-Semarang"
    assert extract_location_phrase("Antrean Mengular di Sejumlah SPBU Bone") == "Bone"
    assert extract_location_phrase("Warga Sampang Keluhkan Sulitnya Mendapat Solar") == "Sampang"
    assert extract_location_phrase("Distribusi BBM di Mimika Terganggu Akibat Banjir") == "Mimika"


def test_geographic_distance_is_auditable_fallback():
    assert geographic_distance_km(-6.2, 106.8, -6.2, 106.8) == 0
    assert 104 < geographic_distance_km(-6.2, 106.8, -6.9, 107.6) < 130


def test_structured_supply_and_hsse_classification():
    supply = classify_text("Pertalite habis dan antrean SPBU Oesapa")
    hsse = classify_text("Mobil tangki BBM terguling dan BBM tumpah di Kabupaten X")
    assert supply["event_category"] == "SUPPLY_DISRUPTION"
    assert {"QUEUE", "STOCK_OUT"} <= set(supply["event_types"])
    assert hsse["event_category"] == "HSSE"
    assert {"TANK_TRUCK_ACCIDENT", "TANK_TRUCK_ROLLOVER", "FUEL_SPILL"} <= set(hsse["event_types"])


def test_classification_uses_word_boundaries_and_shared_context():
    homepage = classify_text("Gurindam Pay Jadi Langkah Baru Digitalisasi Pajak. Penertiban BBM ilegal diperketat.")
    separated = classify_text("BBM tersedia normal. " + "berita umum " * 30 + "komoditas lain mulai langka.")
    genuine = classify_text("BBM langka di Riau dan warga sulit mendapat Pertalite.")

    assert homepage["relevant"] is False
    assert "FUEL_SHORTAGE" not in homepage["event_types"]
    assert separated["relevant"] is False
    assert genuine["relevant"] is True
    assert "FUEL_SHORTAGE" in genuine["event_types"]


def test_tiktok_lead_time_positive_and_negative():
    tiktok = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)
    news = datetime(2026, 9, 1, 8, 0, tzinfo=timezone.utc)
    assert calculate_lead_time(tiktok, news) == ("TIKTOK", 90)
    assert calculate_lead_time(news, tiktok) == ("NEWS", -90)


def test_signal_velocity_trend():
    now = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
    timestamps = [now - timedelta(minutes=10), now - timedelta(minutes=20), now - timedelta(minutes=40), now - timedelta(hours=5)]
    trend, metrics = calculate_trend(timestamps, now)
    assert trend == "RAPIDLY_INCREASING"
    assert metrics["mentions_1h"] == 3


def test_supply_and_hsse_risk_remain_separate():
    supply, hsse = calculate_risk(category="SUPPLY_DISRUPTION", severity="HIGH", confidence=.9, independent_sources=4, mentions_24h=6, location_resolved=True, cross_source=True)
    assert supply >= 65 and hsse == 0
    supply, hsse = calculate_risk(category="HSSE", severity="CRITICAL", confidence=.9, independent_sources=3, mentions_24h=4, location_resolved=True, cross_source=True, fire=True, spill=True, injuries=1)
    assert supply == 0 and hsse >= 80
    assert risk_band(hsse) == "CRITICAL"
