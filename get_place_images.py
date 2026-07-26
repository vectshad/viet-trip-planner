"""
get_place_images.py — Playwright script that opens each itinerary stop/option
in Google Maps and saves the first place-photo URL into itinerary.json as
img_url.  After running, photos appear inside the map popup when you tap a pin.

Usage:
    python get_place_images.py              # all stops + options missing img_url
    python get_place_images.py --limit 3    # test on first 3 entries
    python get_place_images.py --options-only
    python get_place_images.py --stops-only
    python get_place_images.py --overwrite  # re-fetch even if already set

Requires:
    pip install playwright
    playwright install chromium
"""

import asyncio, json, re, sys, argparse
from urllib.parse import quote

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

ITIN_FILE = "itinerary.json"


# ---------------------------------------------------------------------------
# Helpers (same pattern as auto_geocode.py)
# ---------------------------------------------------------------------------

async def _dismiss_consent(page):
    try:
        btn = page.get_by_role("button", name=re.compile(r"accept all|agree|setuju|terima", re.I))
        if await btn.count() > 0:
            await btn.first.click()
            await asyncio.sleep(1.5)
    except Exception:
        pass


async def _poll_url(page, check, timeout=10.0, interval=0.4):
    steps = int(timeout / interval)
    for _ in range(steps):
        if check(page.url):
            return page.url
        await asyncio.sleep(interval)
    return page.url


async def _js_click_first_result(page):
    try:
        return await page.evaluate("""() => {
            var sels = [
                'a.hfpxzc',
                'a[href*="/maps/place/"]',
                '.Nv2PK a', '.lI9IFe a',
                '[data-result-index="0"] a',
                'div[role="article"] a'
            ];
            for (var s of sels) {
                var el = document.querySelector(s);
                if (el) { el.click(); return s; }
            }
            return null;
        }""")
    except Exception:
        return None


_PLACE_PHOTO_PATHS = ("/gps-cs-s/", "/grass-cs/", "/geougc/", "/p/")
_prev_photo_urls: set[str] = set()  # URLs captured in the previous navigation (used to filter stale cross-contamination)
_EXCLUDE_PATHS    = ("/a-/",)  # user profile avatars — not place photos

def _is_place_photo(url: str) -> bool:
    return (
        "googleusercontent.com" in url
        and any(p in url for p in _PLACE_PHOTO_PATHS)
        and not any(e in url for e in _EXCLUDE_PATHS)
    )

def _normalize_img_url(url: str) -> str:
    """Standardise the size suffix of a googleusercontent place-photo URL."""
    if "=" in url.rsplit("/", 1)[-1]:
        # Replace existing size params
        return re.sub(r"=\S+$", "=w600-h400-k-no", url)
    # No size suffix — append one
    return url + "=w600-h400-k-no"


# ---------------------------------------------------------------------------
# Core: navigate to a place and grab its photo
# ---------------------------------------------------------------------------

async def get_image_for_place(page, name: str, lat: float, lon: float) -> tuple[str | None, str]:
    """Navigate to the Maps place, intercept network photo requests, return first match."""

    # Strip itinerary option prefixes like "⬡ Opsi A — " before searching Maps
    search_name = re.sub(r"^[⬡⬢●○◆◇\s]*Opsi\s+\w+\s+[—–-]+\s*", "", name).strip() or name

    # Skip generic placeholder stops that will never map to a real place
    if re.search(r"^(Lunch|Dinner|Coffee Shop|Spa Day|Pasar Pagi|Opsi [AB] atau)", search_name):
        return None, "no-place"

    # Register listener BEFORE navigating so we catch all photo requests.
    # We'll discard everything captured before the place URL is confirmed (below).
    captured: list[str] = []

    def _on_response(response):
        if _is_place_photo(response.url):
            captured.append(response.url)

    page.on("response", _on_response)

    # Search URL with coordinate anchor — /search/ works; /place/ drops unknown slugs
    search_q = search_name.replace(" ", "+") + "+Vietnam"
    nav_url = f"https://www.google.com/maps/search/{search_q}/@{lat},{lon},17z"

    try:
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        page.remove_listener("response", _on_response)
        return None, f"nav:{e}"

    await _dismiss_consent(page)

    # Wait for Maps JS to settle
    page_url = await _poll_url(page, lambda u: "@" in u, timeout=10.0)

    # If still on search results, click first result and wait for place page
    if "/place/" not in page_url:
        await _js_click_first_result(page)
        page_url = await _poll_url(page, lambda u: "/place/" in u, timeout=8.0)

    if "/place/" not in page_url:
        page.remove_listener("response", _on_response)
        _prev_photo_urls.clear()
        return None, "no-place"

    # Give the side panel time to load all photos for this place.
    await asyncio.sleep(3.5)

    page.remove_listener("response", _on_response)

    # Filter out URLs that were also present in the PREVIOUS navigation —
    # those are stale in-flight responses from the prior Maps session bleeding in.
    fresh = [u for u in captured if u not in _prev_photo_urls]

    # Update the previous-URL set for the next call
    _prev_photo_urls.clear()
    _prev_photo_urls.update(captured)  # track everything seen this navigation

    if fresh:
        return _normalize_img_url(fresh[0]), "ok"
    return None, "no-img"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only N entries (for testing)")
    parser.add_argument("--overwrite", action="store_true",
                        help="Re-fetch even if img_url already set")
    parser.add_argument("--stops-only", action="store_true",
                        help="Only process main day stops")
    parser.add_argument("--options-only", action="store_true",
                        help="Only process option pins")
    args = parser.parse_args()

    with open(ITIN_FILE, encoding="utf-8") as f:
        data = json.load(f)

    # Collect every stop / option that has coordinates and needs an image.
    # targets: list of (dict_ref, display_label)
    targets: list[tuple[dict, str]] = []

    for day in data:
        day_label = day.get("day", "")
        for stop in day["stops"]:
            if not args.options_only:
                if stop.get("lat") and stop.get("lon"):
                    if args.overwrite or not stop.get("img_url"):
                        targets.append((stop, f'[stop]  {stop["name"]}'))
            if not args.stops_only:
                for opt in stop.get("options") or []:
                    if opt.get("lat") and opt.get("lon"):
                        if args.overwrite or not opt.get("img_url"):
                            targets.append((opt, f'[opt]   {opt["name"]}'))

    if not targets:
        print("Nothing to fetch — all entries already have img_url.")
        print("Use --overwrite to re-fetch everything.")
        return

    if args.limit:
        targets = targets[:args.limit]

    print(f"{len(targets)} places to fetch images for\n")
    hits = misses = 0

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

        for entry, label in targets:
            print(f"  {label} ... ", end="", flush=True)
            img, status = await get_image_for_place(
                page, entry["name"], entry["lat"], entry["lon"]
            )
            if img:
                entry["img_url"] = img
                print(f"✅  {img[:70]}...")
                hits += 1
            else:
                print(f"❌  {status}")
                misses += 1

        await browser.close()

    with open(ITIN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n--- Done ---")
    print(f"  ✅ found:   {hits}")
    print(f"  ❌ missed:  {misses}")
    print(f"\nitinerary.json updated with img_url fields.")


asyncio.run(main())
