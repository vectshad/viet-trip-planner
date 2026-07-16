"""
place_suggester.py — Suggest a specific place for an undecided itinerary stop.

Pulls from the same data/tiktok_places.csv that powers the Popular Places page,
filtered to the stop's city + category and ranked by distance from the
itinerary's adjacent stop (so suggestions cluster near where you'll already
be that day). Same-city/same-category places are never excluded for being
far — they just sort lower — since the caller may still prefer a highly
rated place over a slightly closer one.
"""

import pathlib
import re
import urllib.parse

import pandas as pd

from logic_checker import haversine_km

ROOT = pathlib.Path(__file__).parent

# Same stay points as geocode_places.py / pages/popular_places.py — used to
# infer which city a day belongs to when suggesting places for a stop.
STAY_COORDS = {
    "Da Nang": (16.0828493, 108.2129368),
    "Ho Chi Minh": (10.788235, 106.676557),
}

# Itinerary "category" values -> Popular Places' Category taxonomy
# (see pages/popular_places.py CATEGORY_ORDER).
CATEGORY_MAP = {
    "food": "Food & Drink",
    "hotel": "Accommodation",
    "attraction": "Attraction",
    "market": "Shopping",
    "beach": "Attraction",
    "museum": "Attraction",
    "nightlife": "Attraction",
    "transport": "Transport",
}

# Same trailing OCR icon-glyph noise stripped in popular_places.py.
_NAME_NOISE_RE = re.compile(r"\s+(k[íi]|WV|V[íÍ]|Z|[47]|</?7?|⁄)$")


def clean_name(name: str) -> str:
    return _NAME_NOISE_RE.sub("", name.strip())


def build_maps_url(name: str, district: str, city: str) -> str:
    name = clean_name(name)
    parts = [name]
    if district and district != city:
        parts.append(district)
    parts.append(f"{city}, Vietnam")
    query = ", ".join(p for p in parts if p)
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def infer_city(day: dict) -> str | None:
    """Which of STAY_COORDS this day is closest to, by majority vote across
    the day's stops that already have coordinates. None if no stop in the
    day has coordinates yet (nothing to vote with)."""
    coords = [(s["lat"], s["lon"]) for s in day["stops"] if s.get("lat") and s.get("lon")]
    if not coords:
        return None
    votes = {}
    for lat, lon in coords:
        nearest = min(STAY_COORDS, key=lambda c: haversine_km(lat, lon, *STAY_COORDS[c]))
        votes[nearest] = votes.get(nearest, 0) + 1
    return max(votes, key=votes.get)


def find_anchor(day: dict, stop_idx: int):
    """Nearest-in-schedule stop with coordinates — checked walking backward
    then forward from stop_idx — used as the 'stay near this' reference
    point for suggestions. (lat, lon) or (None, None)."""
    stops = day["stops"]
    for j in range(stop_idx - 1, -1, -1):
        if stops[j].get("lat") and stops[j].get("lon"):
            return stops[j]["lat"], stops[j]["lon"]
    for j in range(stop_idx + 1, len(stops)):
        if stops[j].get("lat") and stops[j].get("lon"):
            return stops[j]["lat"], stops[j]["lon"]
    return None, None


def load_places() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "tiktok_places.csv", dtype=str).fillna("")
    df["rating_sort"] = pd.to_numeric(df["Rating"], errors="coerce")
    df["lat_f"] = pd.to_numeric(df["Lat"], errors="coerce")
    df["lon_f"] = pd.to_numeric(df["Lon"], errors="coerce")
    return df


def suggest_places(city: str, category: str, anchor_lat=None, anchor_lon=None, limit: int = 8) -> list[dict]:
    """Up to `limit` candidates for a stop: same city, same category
    (mapped via CATEGORY_MAP), ranked nearest-to-anchor first when an
    anchor point is available, else by rating."""
    csv_category = CATEGORY_MAP.get(category, category)
    df = load_places()
    matches = df[(df["City"] == city) & (df["Category"] == csv_category)].copy()
    if matches.empty:
        return []

    has_anchor = anchor_lat is not None and anchor_lon is not None
    if has_anchor:
        matches["dist_km"] = matches.apply(
            lambda r: haversine_km(anchor_lat, anchor_lon, r["lat_f"], r["lon_f"])
            if pd.notna(r["lat_f"]) else float("inf"),
            axis=1,
        )
        matches = matches.sort_values(["dist_km", "rating_sort"], ascending=[True, False], na_position="last")
    else:
        matches = matches.sort_values("rating_sort", ascending=False, na_position="last")

    results = []
    for _, r in matches.head(limit).iterrows():
        dist = r["dist_km"] if has_anchor else None
        results.append({
            "name": clean_name(r["Name"]),
            "district": r["District"],
            "rating": r["Rating"],
            "lat": r["lat_f"] if pd.notna(r["lat_f"]) else None,
            "lon": r["lon_f"] if pd.notna(r["lon_f"]) else None,
            "dist_km": None if dist is None or dist == float("inf") else dist,
            "maps_url": build_maps_url(r["Name"], r["District"], city),
        })
    return results
