"""
import_coords.py — Read missing_coords.csv (after you fill Maps URL or Lat/Lon)
and patch those coordinates back into itinerary.json.

Accepts either:
  - A Google Maps URL in the "Maps URL" column  (e.g. paste the full URL from the
    address bar — the script extracts @lat,lon from it automatically)
  - Plain numbers in the "Lat" and "Lon" columns (original fallback)

Run after filling the CSV:
    python import_coords.py
"""

import json, csv, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSV_FILE  = "missing_coords.csv"
JSON_FILE = "itinerary.json"

# Extracts @lat,lon from any Google Maps URL
_COORD_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")


def _parse_url(url: str):
    m = _COORD_RE.search(url)
    if m:
        return float(m.group(1)), float(m.group(2))
    return None, None


def main():
    updates = {}  # option_name (lower) -> (lat, lon)

    with open(CSV_FILE, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            name = row["Option Name"].strip()
            url  = row.get("Maps URL (paste from Google Maps)", "").strip()
            lat_s = row.get("Lat", "").strip()
            lon_s = row.get("Lon", "").strip()

            lat = lon = None

            # Priority 1: extract from Maps URL
            if url:
                lat, lon = _parse_url(url)
                if lat is None:
                    print(f"  [warn] could not parse URL for: {name}")

            # Priority 2: manual Lat/Lon columns
            if lat is None and lat_s and lon_s:
                try:
                    lat, lon = float(lat_s), float(lon_s)
                except ValueError:
                    print(f"  [skip] bad number for: {name}")

            if lat is not None:
                updates[name.lower()] = (round(lat, 6), round(lon, 6))

    print(f"Loaded {len(updates)} filled coordinates from {CSV_FILE}\n")

    with open(JSON_FILE, encoding="utf-8") as f:
        days = json.load(f)

    patched = 0
    for day in days:
        for stop in day["stops"]:
            for opt in stop.get("options") or []:
                if opt.get("lat") and opt.get("lon"):
                    continue  # already has coords
                key = opt["name"].strip().lower()
                if key in updates:
                    opt["lat"], opt["lon"] = updates[key]
                    print(f"  ✅ {opt['name']} → {opt['lat']}, {opt['lon']}")
                    patched += 1

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(days, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {patched} options patched into {JSON_FILE}.")
    print("Restart Streamlit to see the new pins on the map.")


if __name__ == "__main__":
    main()
