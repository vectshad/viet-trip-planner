"""
places.py — Free place search using Nominatim (OpenStreetMap)
No API key required. Rate limit: 1 request/second.
"""

import requests
import time

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
HEADERS = {"User-Agent": "TripPlannerApp/1.0 (ekasunandikaa@gmail.com)"}


def search_place(query: str, country_codes: str = "vn") -> dict | None:
    """
    Search for a place by name. Returns dict with name, lat, lon, display_name.
    Uses Nominatim (OpenStreetMap) - completely free.
    """
    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": country_codes,
        "addressdetails": 1,
    }
    try:
        time.sleep(1)  # Nominatim rate limit: 1 req/sec
        resp = requests.get(NOMINATIM_URL, params=params, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        results = resp.json()
        if results:
            r = results[0]
            return {
                "name": query,
                "display_name": r.get("display_name", query),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "type": r.get("type", ""),
            }
    except Exception as e:
        print(f"Error searching '{query}': {e}")
    return None


def batch_search(queries: list[str], country_codes: str = "vn") -> list[dict]:
    """Search multiple places, skipping any that fail."""
    results = []
    for q in queries:
        place = search_place(q, country_codes)
        if place:
            results.append(place)
        else:
            # Fallback: return placeholder so the app doesn't break
            results.append({"name": q, "display_name": q, "lat": None, "lon": None, "type": ""})
    return results
