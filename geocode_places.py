"""
Geocode Da Nang / Ho Chi Minh places in tiktok_places.csv and compute
distance from your stay in each city.

Run this locally (needs real internet — Nominatim isn't reachable from
some sandboxed dev environments). One-time cost: ~136 remaining places at
1 request/sec (Nominatim's rate limit), each tried at up to 5 query
specificities, so a full run from scratch can take 10-15 minutes.

Each place is tried, in order: name+city, name+district+city, core-name
(text before a " - " subtitle)+city, name+Vietnam (city dropped), and
core-name+Vietnam — stopping at the first candidate that geocodes within
MAX_DISTANCE_KM of the stay. Name+city (no district) is tried first because
testing showed including the district in the query — which is how the
original version of this script queried — actively hurts Nominatim's
freeform parser far more often than it helps ("X, District 1, Ho Chi Minh
City, Vietnam" regularly fails where "X, Ho Chi Minh City, Vietnam"
succeeds). The last two attempts drop the city entirely to maximize recall,
which risks matching a same-named place in a different city (e.g. a generic
"Gem Cafe" hit in Hue, 640km from the Ho Chi Minh stay) — every candidate,
from every attempt, is distance-checked against the stay before being
accepted so those wrong-city matches are rejected instead of silently
producing a wrong pin.

Even after all five attempts, a meaningful chunk will still fail —
Nominatim is OpenStreetMap data, which has much sparser coverage of small
Vietnamese restaurants/cafes than Google's own database. This is expected,
not a bug: the Maps and Directions links elsewhere in the app already use
Google's own search under the hood and work fine regardless of whether a
place geocodes here — this script only affects the "From Stay" distance
number and whether Directions links use an exact pin vs. a text search.

Setup:
    pip install requests

Usage:
    1. Put this script in the same folder as data/tiktok_places.csv
       (i.e. run it from the viet-trip-planner repo root).
    2. python geocode_places.py
    3. It overwrites data/tiktok_places.csv in place, adding Lat, Lon,
       and "Distance from Stay (km)" columns for Da Nang/HCM rows only
       (Hoi An/Ba Na Hills rows are left blank in those columns, per scope).
    4. Re-running is safe — already-geocoded rows are skipped.
"""

import csv
import re
import time
from math import radians, sin, cos, sqrt, atan2
from pathlib import Path

import requests

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
CSV_PATH = Path("data/tiktok_places.csv")
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TripPlannerApp/1.0 (ekasunandikaa@gmail.com)"}
RATE_LIMIT_SECONDS = 1.1  # Nominatim allows 1 req/sec — pad slightly

# Same stay points already in itinerary.json
STAY_COORDS = {
    "Da Nang": (16.0828493, 108.2129368),      # Stay Da Nang — 59 Nguyen Tat Thanh
    "Ho Chi Minh": (10.788235, 106.676557),    # Stay HCM — 359/1 Le Van Sy
}

# Nominatim resolves "Ho Chi Minh City" far more reliably than "Ho Chi Minh"
# alone (tested: bare "Ho Chi Minh" as a city qualifier fails on many
# otherwise-findable places that succeed once "City" is appended). "Da Nang"
# needs no such rewrite.
CITY_QUERY_NAME = {
    "Da Nang": "Da Nang",
    "Ho Chi Minh": "Ho Chi Minh City",
}

# Sanity-check radius around each stay: a geocode result further than this
# is almost certainly a same-named place in the wrong city (e.g. a "Gem
# Cafe" match in Hue, 640km away) rather than the actual venue, especially
# once the fallback attempts below drop the city qualifier entirely. Sized
# to comfortably cover in-scope outlying areas — Ba Na Hills/Hoa Vang for Da
# Nang (~35km out), Cu Chi Tunnels for Ho Chi Minh (~35km out) — while still
# excluding the nearest other major cities.
MAX_DISTANCE_KM = {
    "Da Nang": 45,
    "Ho Chi Minh": 60,
}

NEW_FIELDS = ["Lat", "Lon", "Distance from Stay (km)"]

_ELLIPSIS_RE = re.compile(r"\.{2,}")
# OCR sometimes prefixes a stray "7`"/"4`"-style glyph before the real name.
_LEADING_NOISE_RE = re.compile(r"^[0-9]{1,2}[`´]\s+")
# Trailing OCR icon-glyph noise (misread UI icons at the end of each card).
# Stripped iteratively below since some names carry more than one.
_NOISE_TOKENS = {
    "4", "7", "z", "ki", "kí", "wv", "vi", "ví", "v4",
    "</7", "<7", "</", "<", "⁄", "`",
}


def _strip_trailing_noise(name: str) -> str:
    tokens = name.split()
    while tokens:
        candidate = tokens[-1].strip("\"'“”‘’.,")
        if candidate.lower() in _NOISE_TOKENS:
            tokens.pop()
            continue
        break
    return " ".join(tokens)


def clean_name(name: str) -> str:
    name = _ELLIPSIS_RE.sub("", name.strip())
    name = _LEADING_NOISE_RE.sub("", name)
    return _strip_trailing_noise(name).strip()


def core_name(name: str) -> str:
    """Text before a " - "/" – " subtitle separator, e.g. "Designer Coffee"
    out of "Designer Coffee - Specialty Vietnamese...". Several OCR'd names
    were truncated mid-subtitle by the screenshot's card width; querying
    just the core business name recovers some of those."""
    for sep in (" - ", " – "):
        if sep in name:
            return name.split(sep)[0].strip()
    return name


def _try_query(query: str, limit: int = 3) -> list:
    params = {"q": query, "format": "json", "limit": limit, "countrycodes": "vn"}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"   ⚠️  Error geocoding '{query}': {e}")
        return []


def _build_attempts(name: str, district: str, city_query: str) -> list:
    core = core_name(name)
    attempts = [f"{name}, {city_query}, Vietnam"]
    if district and district != city_query:
        attempts.append(f"{name}, {district}, {city_query}, Vietnam")
    if core != name:
        attempts.append(f"{core}, {city_query}, Vietnam")
    attempts.append(f"{name}, Vietnam")  # drop city — last resort
    if core != name:
        attempts.append(f"{core}, Vietnam")

    seen = set()
    deduped = []
    for a in attempts:
        if a not in seen:
            seen.add(a)
            deduped.append(a)
    return deduped


def geocode(name: str, district: str, city: str) -> tuple:
    """Returns (lat, lon) or (None, None) if not found. Tries a specific
    query first, then falls back to broader ones — Nominatim (OpenStreetMap)
    has much sparser coverage of small Vietnamese businesses than Google, so
    a fair number of places genuinely aren't in its database at any
    specificity. Each attempt costs one rate-limited request.

    The last two (city-dropping) attempts trade precision for recall, so
    every candidate — from every attempt — is checked against
    MAX_DISTANCE_KM before being accepted, rejecting same-named matches in
    the wrong city instead of silently returning a wrong pin."""
    name = clean_name(name)
    city_query = CITY_QUERY_NAME.get(city, city)
    stay_lat, stay_lon = STAY_COORDS[city]
    max_dist = MAX_DISTANCE_KM[city]

    attempts = _build_attempts(name, district, city_query)

    for i, query in enumerate(attempts):
        for result in _try_query(query):
            lat, lon = float(result["lat"]), float(result["lon"])
            if haversine_km(stay_lat, stay_lon, lat, lon) <= max_dist:
                return lat, lon
        if i < len(attempts) - 1:
            time.sleep(RATE_LIMIT_SECONDS)
    return None, None


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def main():
    if not CSV_PATH.exists():
        print(f"❌ {CSV_PATH} not found — run this from the viet-trip-planner repo root.")
        return

    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    fieldnames = list(rows[0].keys())
    for field in NEW_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    todo = [r for r in rows if r["City"] in STAY_COORDS and not r.get("Lat")]
    print(f"📍 {len(todo)} places to geocode (Da Nang + Ho Chi Minh, skipping already-done rows)")

    for i, row in enumerate(todo, 1):
        lat, lon = geocode(row["Name"], row["District"], row["City"])
        if lat is not None:
            row["Lat"] = lat
            row["Lon"] = lon
            stay_lat, stay_lon = STAY_COORDS[row["City"]]
            row["Distance from Stay (km)"] = round(haversine_km(stay_lat, stay_lon, lat, lon), 1)
            print(f"   [{i}/{len(todo)}] ✅ {row['Name']} → {row['Distance from Stay (km)']} km")
        else:
            row["Lat"] = ""
            row["Lon"] = ""
            row["Distance from Stay (km)"] = ""
            print(f"   [{i}/{len(todo)}] ❌ {row['Name']} — not found")
        time.sleep(RATE_LIMIT_SECONDS)

    for field in NEW_FIELDS:
        for row in rows:
            row.setdefault(field, "")

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    found = sum(1 for r in rows if r.get("Lat"))
    print(f"\n🎉 Done! {found}/{len(rows)} total rows now have coordinates.")
    print(f"💾 Saved: {CSV_PATH}")


if __name__ == "__main__":
    main()
