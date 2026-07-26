"""
auto_geocode.py — Playwright script that searches each missing place on
Google Maps and extracts coordinates from the URL automatically.

Skips rows that already have a Maps URL or Lat/Lon filled in.
After running, execute:  python import_coords.py

Requires:
    pip install playwright
    playwright install chromium
"""

import asyncio, csv, re, sys, argparse
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from playwright.async_api import async_playwright

CSV_FILE = "missing_coords.csv"
COORD_RE = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")


def _coords(url: str):
    m = COORD_RE.search(url)
    return (round(float(m.group(1)), 6), round(float(m.group(2)), 6)) if m else (None, None)


async def _dismiss_consent(page):
    try:
        btn = page.get_by_role("button", name=re.compile(r"accept all|agree|setuju|terima", re.I))
        if await btn.count() > 0:
            await btn.first.click()
            await asyncio.sleep(1.5)
    except Exception:
        pass


async def _poll_url(page, check, timeout=10.0, interval=0.4):
    """Poll page.url every `interval` seconds until `check(url)` is True or timeout."""
    steps = int(timeout / interval)
    for _ in range(steps):
        url = page.url
        if check(url):
            return url
        await asyncio.sleep(interval)
    return page.url


async def _js_click_first_result(page) -> str | None:
    """Click the first search result via JavaScript. Returns the selector used or None."""
    try:
        return await page.evaluate("""() => {
            var sels = [
                'a.hfpxzc',
                'a[href*=\"/maps/place/\"]',
                '.Nv2PK a',
                '.lI9IFe a',
                '[data-result-index=\"0\"] a',
                'div[role=\"article\"] a'
            ];
            for (var s of sels) {
                var el = document.querySelector(s);
                if (el) { el.click(); return s; }
            }
            return null;
        }""")
    except Exception:
        return None


async def geocode_one(page, name: str, city: str):
    query = f"{name} {city} Vietnam"
    search_url = "https://www.google.com/maps/search/" + query.replace(" ", "+")

    try:
        await page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        return None, None, f"nav:{e}"

    await _dismiss_consent(page)

    # Wait for Google Maps JS to add @lat,lon to the URL (up to 10s)
    url = await _poll_url(page, lambda u: "@" in u, timeout=10.0)

    # Already redirected to a specific place
    if "/place/" in url and "@" in url:
        return *_coords(url), "place"

    # On search results — click first result via JS and wait for URL to change
    sel_used = await _js_click_first_result(page)
    if sel_used:
        url = await _poll_url(page, lambda u: "/place/" in u and "@" in u, timeout=8.0)
        if "/place/" in url and "@" in url:
            return *_coords(url), f"clicked({sel_used})"

    # Search-center fallback — the @lat,lon is the map center, close enough
    url = page.url
    if "@" in url:
        return *_coords(url), "search-center"

    return None, None, f"stuck:{url[:60]}"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only process N rows (for testing)")
    args = parser.parse_args()

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

    if args.limit:
        pending_idx = pending_idx[:args.limit]

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
                if "place" == status:
                    print(f"✅  {lat}, {lon}")
                    place_hits += 1
                elif status.startswith("clicked"):
                    print(f"✅ (clicked)  {lat}, {lon}")
                    click_hits += 1
                else:
                    print(f"⚠️  search-center  {lat}, {lon}")
                    center_hits += 1
            else:
                print(f"❌  {status}")
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
