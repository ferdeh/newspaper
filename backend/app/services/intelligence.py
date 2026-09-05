from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

from app.config import settings

PRODUCT_TERMS = {
    "PERTALITE": ("pertalite",),
    "PERTAMAX": ("pertamax",),
    "BIOSOLAR": ("biosolar", "bio solar", "solar"),
    "DEXLITE": ("dexlite",),
    "PERTAMINA DEX": ("pertamina dex",),
}

FUEL_TERMS = ("bbm", "pertalite", "pertamax", "solar", "biosolar", "dexlite", "pertamina dex", "mobil tangki", "truk bbm", "spbu", "tbbm")
ISSUE_TERMS = (
    "habis", "langka", "kelangkaan", "sulit didapat", "antre", "antrean", "antrian", "mengular",
    "terguling", "terbakar", "kebakaran", "kecelakaan", "tumpah", "ledakan", "ditutup",
    "terlambat", "banjir", "longsor", "jalan ditutup", "blokade",
)

INDONESIAN_PROVINCES = (
    "Aceh", "Bali", "Bangka Belitung", "Banten", "Bengkulu", "DI Yogyakarta", "DKI Jakarta",
    "Gorontalo", "Jambi", "Jawa Barat", "Jawa Tengah", "Jawa Timur", "Kalimantan Barat",
    "Kalimantan Selatan", "Kalimantan Tengah", "Kalimantan Timur", "Kalimantan Utara",
    "Kepulauan Riau", "Lampung", "Maluku", "Maluku Utara", "Nusa Tenggara Barat",
    "Nusa Tenggara Timur", "Papua", "Papua Barat", "Papua Barat Daya", "Papua Pegunungan",
    "Papua Selatan", "Papua Tengah", "Riau", "Sulawesi Barat", "Sulawesi Selatan",
    "Sulawesi Tengah", "Sulawesi Tenggara", "Sulawesi Utara", "Sumatera Barat",
    "Sumatera Selatan", "Sumatera Utara",
)

LOCATION_STOP_WORDS = {
    "akibat", "api", "awasi", "berhasil", "disorot", "jadi", "kembali", "keluhkan", "langka",
    "mengular", "normal", "pastikan", "pemilik", "pasokan", "teratasi", "terbakar", "terganggu",
    "terguling", "warga",
}


def normalize_text(value: str) -> str:
    value = re.sub(r"[\u2010-\u2015]", " ", value)
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9\s.-]", " ", value.lower())
    return re.sub(r"\s+", " ", value).strip()


def phrase_spans(text: str, terms: Iterable[str]) -> list[tuple[int, int]]:
    """Find complete words or phrases; substrings such as `langka` in `langkah` do not match."""
    normalized = normalize_text(text)
    spans: list[tuple[int, int]] = []
    for term in terms:
        normalized_term = normalize_text(term)
        if not normalized_term:
            continue
        pattern = rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])"
        spans.extend(match.span() for match in re.finditer(pattern, normalized))
    return spans


def contains_phrase(text: str, terms: Iterable[str]) -> bool:
    return bool(phrase_spans(text, terms))


def terms_share_context(text: str, left_terms: Iterable[str], right_terms: Iterable[str], max_gap_words: int = 24) -> bool:
    """Require fuel and issue evidence to occur in the same short textual context."""
    normalized = normalize_text(text)
    left_spans = phrase_spans(normalized, left_terms)
    right_spans = phrase_spans(normalized, right_terms)
    for left_start, left_end in left_spans:
        for right_start, right_end in right_spans:
            if left_end < right_start:
                between = normalized[left_end:right_start]
            elif right_end < left_start:
                between = normalized[right_end:left_start]
            else:
                return True
            if len(between.split()) <= max_gap_words:
                return True
    return False


def extract_location_phrase(text: str) -> str | None:
    """Extract a short address-like phrase without sending an entire headline to a geocoder."""
    headline = re.split(r"\s+-\s+", text, maxsplit=1)[0].strip()
    proper_token = r"[A-Z][A-Za-z0-9.-]*"
    patterns = (
        rf"\b(?:di|ke|dari|wilayah|sekitar)\s+((?:{proper_token})(?:\s+{proper_token}){{0,3}})",
        rf"\b(?:Pemkab|Pemkot|Polres|Bupati)\s+((?:{proper_token})(?:\s+{proper_token}){{0,2}})",
        rf"\b((?:Kabupaten|Kota|Kecamatan|Desa|Kelurahan|Tol)\s+{proper_token}(?:\s+{proper_token}){{0,2}})",
        rf"\bWarga\s+({proper_token})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, headline)
        if not match:
            continue
        tokens = match.group(1).strip(" ,.;:-").split()
        stop_index = next((index for index, token in enumerate(tokens) if token.lower() in LOCATION_STOP_WORDS), None)
        if stop_index is not None:
            tokens = tokens[:stop_index]
        while tokens and tokens[-1].lower() in LOCATION_STOP_WORDS:
            tokens.pop()
        while tokens and tokens[0].lower() in {"sejumlah", "wilayah"}:
            tokens.pop(0)
        if tokens and tokens[0].upper() == "SPBU" and len(tokens) > 1:
            tokens.pop(0)
        candidate = " ".join(tokens)
        if candidate.lower() not in {"indonesia", "sejumlah daerah", "suatu tempat"}:
            return candidate or None

    normalized = normalize_text(headline)
    for province in sorted(INDONESIAN_PROVINCES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(normalize_text(province))}\b", normalized):
            return province
    return None


def geographic_distance_km(left_lat: float, left_lng: float, right_lat: float, right_lng: float) -> float:
    radius_km = 6371.0088
    lat_1, lat_2 = math.radians(left_lat), math.radians(right_lat)
    delta_lat = math.radians(right_lat - left_lat)
    delta_lng = math.radians(right_lng - left_lng)
    haversine = math.sin(delta_lat / 2) ** 2 + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lng / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def relevance_score(text: str) -> float:
    normalized = normalize_text(text)
    fuel_hits = sum(contains_phrase(normalized, (term,)) for term in FUEL_TERMS)
    issue_hits = sum(contains_phrase(normalized, (term,)) for term in ISSUE_TERMS)
    if fuel_hits and issue_hits and terms_share_context(normalized, FUEL_TERMS, ISSUE_TERMS):
        return min(0.98, 0.55 + 0.08 * fuel_hits + 0.07 * issue_hits)
    return min(0.45, 0.08 * fuel_hits + 0.06 * issue_hits)


def classify_text(text: str, location_hint: str | None = None) -> dict:
    value = normalize_text(text)
    score = relevance_score(value)
    products = [product for product, terms in PRODUCT_TERMS.items() if contains_phrase(value, terms)]
    if not products and contains_phrase(value, ("bbm",)):
        products = ["BBM"]

    def contextual(terms: Iterable[str]) -> bool:
        return terms_share_context(value, FUEL_TERMS, terms)

    hsse_context = contains_phrase(value, ("mobil tangki", "truk bbm", "tangki bbm", "mt")) or (
        contains_phrase(value, ("bbm",)) and contextual(("kebakaran", "tumpahan"))
    )
    event_types: list[str] = []
    category = "SUPPLY_DISRUPTION"
    fire = contains_phrase(value, ("terbakar", "kebakaran", "api"))
    spill = contains_phrase(value, ("tumpah", "ceceran", "fuel spill"))
    road_blocked = contains_phrase(value, ("jalan tertutup", "jalan ditutup", "road blocked", "kemacetan total"))
    fatalities = 1 if contains_phrase(value, ("meninggal", "tewas", "fatality")) else 0
    injuries = 1 if contains_phrase(value, ("terluka", "korban luka", "injury")) else 0

    if hsse_context and contextual(("kecelakaan", "terguling", "tabrakan", "terbakar", "tumpah", "ledakan")):
        category = "HSSE"
        event_types.append("TANK_TRUCK_ACCIDENT")
        if contextual(("terguling",)):
            event_types.append("TANK_TRUCK_ROLLOVER")
        if contextual(("tabrakan", "bertumbukan")):
            event_types.append("COLLISION")
        if fire:
            event_types.append("FIRE")
        if spill:
            event_types.append("FUEL_SPILL")
        if contextual(("ledakan",)):
            event_types.append("EXPLOSION")
        if road_blocked:
            event_types.append("ROAD_BLOCKAGE")
        if fatalities:
            event_types.append("FATALITY")
        if injuries:
            event_types.append("INJURY")
    else:
        if contextual(("antre", "antrean", "antrian", "mengular", "antri")):
            event_types.append("QUEUE")
        if contextual(("stok kosong", "stock out", "habis")):
            event_types.append("STOCK_OUT")
        if contextual(("langka", "kelangkaan", "sulit didapat")):
            event_types.append("FUEL_SHORTAGE")
        if contextual(("pengiriman terlambat", "keterlambatan distribusi", "delivery delay")):
            event_types.append("DELIVERY_DELAY")
        if contextual(("spbu tutup", "spbu ditutup", "penutupan spbu", "tutup", "ditutup")):
            event_types.append("SPBU_CLOSURE")
        if contextual(("lonjakan permintaan", "permintaan meningkat")):
            event_types.append("DEMAND_SURGE")
        external = {
            "banjir": "FLOOD", "longsor": "LANDSLIDE", "gempa": "EARTHQUAKE",
            "jalan ditutup": "ROAD_CLOSURE", "pelabuhan terganggu": "PORT_DISRUPTION",
        }
        external_events = [code for phrase, code in external.items() if contextual((phrase,))]
        if external_events:
            category = "EXTERNAL_DISRUPTION"
            event_types.extend(external_events)

    relevant = bool(event_types) and score >= 0.5
    severity = "LOW"
    if relevant:
        severity = "MEDIUM"
        if category == "HSSE" or len(event_types) >= 2 or "STOCK_OUT" in event_types:
            severity = "HIGH"
        if fatalities or "EXPLOSION" in event_types or (fire and spill):
            severity = "CRITICAL"
    return {
        "relevant": relevant,
        "event_category": category,
        "event_types": list(dict.fromkeys(event_types)),
        "products": products,
        "location_raw": location_hint,
        "severity": severity,
        "possible_cause": "DELIVERY_DELAY" if "DELIVERY_DELAY" in event_types else None,
        "accident_type": "ROLLOVER" if "TANK_TRUCK_ROLLOVER" in event_types else None,
        "fire": fire,
        "spill": spill,
        "fatalities": fatalities,
        "injuries": injuries,
        "road_blocked": road_blocked,
        "environmental_impact": spill,
        "confidence": round(max(0.55, score), 2) if relevant else round(score, 2),
    }


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0


def resolve_alias(text: str, candidates: Iterable[tuple[int, str, list[str]]]) -> tuple[int | None, float]:
    value = normalize_text(text)
    matches: list[tuple[int, int]] = []
    for candidate_id, name, aliases in candidates:
        names = [name, *aliases]
        best = max((len(normalize_text(item)) for item in names if normalize_text(item) in value), default=0)
        if best:
            matches.append((candidate_id, best))
    if not matches:
        return None, 0
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[0][0], min(0.98, 0.65 + matches[0][1] / 100)


def spbu_match_score(text: str, number: str, name: str) -> float:
    value = normalize_text(text)
    normalized_number = normalize_text(number)
    normalized_name = normalize_text(name)
    if normalized_number and normalized_number in value:
        return 0.99
    name_tokens = set(normalized_name.split())
    text_tokens = set(value.split())
    overlap = len(name_tokens & text_tokens) / max(1, len(name_tokens))
    return round(0.5 + overlap * 0.45, 2) if overlap >= 0.6 else 0


def calculate_lead_time(first_tiktok: datetime | None, first_news: datetime | None) -> tuple[str | None, int | None]:
    if first_tiktok and first_news:
        delta = int((first_news - first_tiktok).total_seconds() / 60)
        if abs(delta) <= 5:
            return "SIMULTANEOUS", delta
        return ("TIKTOK" if delta > 0 else "NEWS"), delta
    if first_tiktok:
        return "TIKTOK", None
    if first_news:
        return "NEWS", None
    return None, None


def calculate_trend(timestamps: list[datetime], now: datetime | None = None) -> tuple[str, dict[str, float | int]]:
    now = now or datetime.now(timezone.utc)
    counts = {hours: sum((now - stamp).total_seconds() <= hours * 3600 for stamp in timestamps) for hours in (1, 3, 6, 24)}
    recent = counts[3]
    prior = max(0, counts[6] - counts[3])
    growth = (recent - prior) / max(1, prior)
    if growth >= 1 and recent >= 3:
        trend = "RAPIDLY_INCREASING"
    elif growth > 0.2:
        trend = "INCREASING"
    elif growth < -0.2:
        trend = "DECLINING"
    else:
        trend = "STABLE"
    return trend, {"mentions_1h": counts[1], "mentions_3h": counts[3], "mentions_6h": counts[6], "mentions_24h": counts[24], "growth_rate": round(growth, 2)}


def risk_band(score: float) -> str:
    if score >= 80:
        return "CRITICAL"
    if score >= 65:
        return "HIGH"
    if score >= 45:
        return "WARNING"
    if score >= 25:
        return "WATCH"
    return "NORMAL"


def calculate_risk(
    *, category: str, severity: str, confidence: float, independent_sources: int,
    mentions_24h: int, location_resolved: bool, cross_source: bool,
    fatalities: int = 0, injuries: int = 0, fire: bool = False, spill: bool = False, road_blocked: bool = False,
) -> tuple[float, float]:
    severity_value = {"LOW": 18, "MEDIUM": 38, "HIGH": 68, "CRITICAL": 92}.get(severity, 30)
    source_value = min(14, independent_sources * 4)
    velocity_value = min(10, mentions_24h * 1.5)
    confidence_value = confidence * 10
    location_value = 6 if location_resolved else 1
    corroboration_value = 10 if cross_source else 2
    if category == "HSSE":
        consequence = min(45, fatalities * 30 + injuries * 8 + fire * 14 + spill * 12 + road_blocked * 7)
        weights = settings.hsse_risk_weights
        hsse = min(100, severity_value * weights["severity"] + consequence * weights["consequence"] + confidence_value * weights["confidence"] + source_value * weights["sources"] + corroboration_value * weights["corroboration"])
        return 0.0, round(hsse, 1)
    weights = settings.supply_risk_weights
    supply = min(100, severity_value * weights["severity"] + source_value * weights["sources"] + velocity_value * weights["velocity"] + confidence_value * weights["confidence"] + location_value * weights["location"] + corroboration_value * weights["corroboration"])
    return round(supply, 1), 0.0
