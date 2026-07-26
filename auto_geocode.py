"""
auto_geocode.py — Playwright script that searches each missing place on
Google Maps and extracts coordinates from the URL automatically.

Skips rows that already have a Maps URL or Lat/Lon filled in.
After running, execute:  python import_coords.py

Requires:
    pip install playwright
    playwright install chromium
"""

import asyncio, csv, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

CSV_FILE  = "missing_coords.csv"
COORD_RE  = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")
DELAY     = 2.5  # seconds between searches


def _coords(url: str):
    m = COORD_RE.search(url)
    return (round(float(m.group(1)), 6), round(float(m.group(2)), 6)) if m else (None, None)


async def _dismiss_consent(page):
    """Click 'Accept all' if Google shows a cookie/consent dialog."""
    try:
        btn = page.get_by_role("button", name=re.compile(r"accept all|agree", re.I))
        if await btn.count() > 0:
            await btn.first.click()
            await asyncio.sleep(1)
    except Exception:
        pass


async def geocode_one(page, name: str, city: str):
    query = f"{name} {city} Vietnam"
    search_url = "https://www.google.com/maps/search/" + query.replace(" ", "+")

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        await _dismiss_consent(page)
        await asyncio.sleep(DELAY)
    except Exception as e:
        return None, None, f"nav error: {e}"

    url = page.url

    # Best case: Google already redirected to the specific place page
    if "/place/" in url and "@" in url:
        lat, lon = _coords(url)
        return lat, lon, "place"

    # On search results — click the first result to open the place
    try:
        first = page.locator('a[href*="/maps/place/"]').first
        await first.click(timeout=6000)
        await asyncio.sleep(DELAY)
        url = page.url
        if "/place/" in url and "@" in url:
            lat, lon = _coords(url)
            return lat, lon, "clicked"
    except Exception:
        pass

    # Last resort: use the map-center coords from the search URL (less precise)
    if "@" in url:
        lat, lon = _coords(url)
        return lat, lon, "search-center"

    return None, None, "not found"


async def main():
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    url_col = "Maps URL (paste from Google Maps)"

    pending_idx = [
        i for i, r in enumerate(rows)
        if not r.get(url_col, "").strip()
        and not r.get("Lat", "").strip()
        and not r.get("Lon", "").strip()
    ]

    if not pending_idx:
        print("Nothing to geocode — all rows already have a URL or coords.")
        return

    print(f"{len(pending_idx)} rows to geocode\n")

    place_hits = click_hits = center_hits = misses = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        for i in pending_idx:
            row = rows[i]
            name, city = row["Option Name"], row["City"]
            print(f"  [{i:02d}] {name} ({city}) ... ", end="", flush=True)

            lat, lon, status = await geocode_one(page, name, city)

            if lat is not None:
                rows[i]["Lat"] = str(lat)
                rows[i]["Lon"] = str(lon)
                if status == "place":
                    print(f"✅  {lat}, {lon}")
                    place_hits += 1
                elif status == "clicked":
                    print(f"✅ (clicked)  {lat}, {lon}")
                    click_hits += 1
                else:
                    print(f"⚠️  search-center  {lat}, {lon}")
                    center_hits += 1
            else:
                print("❌  not found")
                misses += 1

        await browser.close()

    with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\n--- Done ---")
    print(f"  ✅ precise:  {place_hits + click_hits}")
    print(f"  ⚠️  approx:  {center_hits}  (check these manually)")
    print(f"  ❌ missed:   {misses}")
    print(f"\nCSV updated. Now run:  python import_coords.py")


asyncio.run(main())
