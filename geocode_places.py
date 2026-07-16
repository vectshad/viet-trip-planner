"""
Geocode Da Nang / Ho Chi Minh places in tiktok_places.csv and compute
distance from your stay in each city.

Run this locally (needs real internet — Nominatim isn't reachable from
some sandboxed dev environments). One-time cost: ~157 places at 1 request/sec
(Nominatim's rate limit) is roughly 2.5-3 minutes.

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

NEW_FIELDS = ["Lat", "Lon", "Distance from Stay (km)"]

# Same trailing OCR icon-glyph noise stripped for maps links in popular_places.py
_NAME_NOISE_RE = re.compile(r"\s+(k[íi]|WV|V[íÍ]|Z|[47]|</?7?|⁄)$")


def clean_name(name: str) -> str:
    return _NAME_NOISE_RE.sub("", name.strip())


def geocode(name: str, district: str, city: str) -> tuple:
    """Returns (lat, lon) or (None, None) if not found."""
    query_parts = [clean_name(name)]
    if district and district != city:
        query_parts.append(district)
    query_parts.append(f"{city}, Vietnam")
    query = ", ".join(query_parts)

    params = {"q": query, "format": "json", "limit": 1, "countrycodes": "vn"}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except Exception as e:
        print(f"   ⚠️  Error geocoding '{query}': {e}")
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
