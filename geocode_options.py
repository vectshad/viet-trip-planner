"""
geocode_options.py — One-time script to geocode Excel option places in itinerary.json.

Adds "lat" and "lon" to each option in each stop's "options" array.
Idempotent — skips options that already have coordinates.

Run locally:
    python geocode_options.py

Uses Nominatim (OpenStreetMap, free, 1 req/sec). Expect ~50% hit rate for
small Vietnamese restaurants — missing coordinates just means that option
won't show as a map pin, the text list still works fine.
"""

import json, time, requests, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NOMINATIM = "https://nominatim.openstreetmap.org/search"
HEADERS   = {"User-Agent": "viet-trip-planner/1.0 (danpediayuk@gmail.com)"}
DELAY     = 1.1  # seconds between requests

# City → (lat, lon, search city string, max distance km)
CITY_HINTS = {
    "Da Nang":     (16.068, 108.212, "Da Nang, Vietnam",          30),
    "Hoi An":      (15.877, 108.329, "Hoi An, Vietnam",           20),
    "Ho Chi Minh": (10.780, 106.700, "Ho Chi Minh City, Vietnam", 30),
    "Ba Na Hills": (15.996, 107.989, "Da Nang, Vietnam",          40),
}

def _dist_km(a_lat, a_lon, b_lat, b_lon):
    import math
    R = 6371
    dlat = math.radians(b_lat - a_lat)
    dlon = math.radians(b_lon - a_lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(a_lat))*math.cos(math.radians(b_lat))*math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def _infer_city(day_label):
    label = day_label.lower()
    if "hoi an" in label:
        return "Hoi An"
    if "ba na" in label:
        return "Ba Na Hills"
    if "hcm" in label or "ho chi minh" in label or "saigon" in label:
        return "Ho Chi Minh"
    if "da nang" in label or "agu" not in label:
        return "Da Nang"
    return None

def geocode(name, city_str, anchor_lat, anchor_lon, max_km):
    queries = [
        f"{name}, {city_str}",
        f"{name}, Vietnam",
        name,
    ]
    for q in queries:
        try:
            r = requests.get(NOMINATIM, params={"q": q, "format": "json", "limit": 5}, headers=HEADERS, timeout=10)
            r.raise_for_status()
            results = r.json()
            time.sleep(DELAY)
            for res in results:
                lat, lon = float(res["lat"]), float(res["lon"])
                if _dist_km(anchor_lat, anchor_lon, lat, lon) <= max_km:
                    return lat, lon
        except Exception as e:
            print(f"    [error] {e}")
            time.sleep(DELAY)
    return None, None


def main():
    with open("itinerary.json", encoding="utf-8") as f:
        days = json.load(f)

    total = skipped = found = missed = 0

    for day in days:
        city_key = _infer_city(day["day"])
        if not city_key or city_key not in CITY_HINTS:
            continue
        anchor_lat, anchor_lon, city_str, max_km = CITY_HINTS[city_key]

        for stop in day["stops"]:
            opts = stop.get("options")
            if not opts:
                continue
            for opt in opts:
                total += 1
                if opt.get("lat") and opt.get("lon"):
                    skipped += 1
                    continue
                name = opt["name"]
                # Strip leading markers like "⬡ Opsi A — "
                clean = name.split("—")[-1].strip() if "—" in name else name
                print(f"  Geocoding: {clean} ({city_key}) ...", end=" ", flush=True)
                lat, lon = geocode(clean, city_str, anchor_lat, anchor_lon, max_km)
                if lat:
                    opt["lat"] = round(lat, 6)
                    opt["lon"] = round(lon, 6)
                    print(f"✅ {lat:.4f}, {lon:.4f}")
                    found += 1
                else:
                    print("❌ not found")
                    missed += 1

    with open("itinerary.json", "w", encoding="utf-8") as f:
        json.dump(days, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {found} geocoded, {missed} not found, {skipped} skipped (already had coords).")
    print("Restart the Streamlit app to see option pins on the map.")


if __name__ == "__main__":
    main()
