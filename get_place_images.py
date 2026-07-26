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


async def _extract_image(page) -> str | None:
    """Find the first place-photo URL in the current Maps page."""
    return await page.evaluate(r"""() => {
        function normalize(src) {
            // Bump to a display-friendly resolution
            return src.replace(/=w\d+-h\d+[^"']*/g, '=w600-h400-k-no');
        }
        // 1) Prefer photos in the hero section (sidebar top image)
        var hero = document.querySelector(
            'button[jsaction*="heroHeaderImage"] img, '
            + 'div[jsaction*="heroHeaderImage"] img'
        );
        if (hero && hero.src && hero.src.includes('googleusercontent.com')) {
            return normalize(hero.src);
        }
        // 2) Any img whose src is a Google place photo (/p/ path = place photo)
        var imgs = document.querySelectorAll('img[src*="googleusercontent.com"]');
        for (var img of imgs) {
            var src = img.src || '';
            if (src.includes('/p/')) {
                return normalize(src);
            }
        }
        // 3) Lazy-loaded photos stored in data-src
        imgs = document.querySelectorAll('img[data-src*="googleusercontent.com"]');
        for (var img of imgs) {
            var src = img.getAttribute('data-src') || '';
            if (src.includes('/p/')) {
                return normalize(src);
            }
        }
        return null;
    }""")


# ---------------------------------------------------------------------------
# Core: navigate to a place and grab its photo
# ---------------------------------------------------------------------------

async def get_image_for_place(page, name: str, lat: float, lon: float) -> tuple[str | None, str]:
    # Coordinates-anchored URL → Maps opens near the right place
    nav_url = (
        "https://www.google.com/maps/place/"
        + quote(name)
        + f"/@{lat},{lon},17z"
    )

    try:
        await page.goto(nav_url, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        return None, f"nav:{e}"

    await _dismiss_consent(page)

    # Wait for Maps JS to settle (URL gets @lat,lon)
    page_url = await _poll_url(page, lambda u: "@" in u, timeout=10.0)

    # If still on search results, click first result
    if "/place/" not in page_url:
        await _js_click_first_result(page)
        page_url = await _poll_url(page, lambda u: "/place/" in u, timeout=8.0)

    if "/place/" not in page_url:
        return None, "no-place"

    # Give the side panel time to load photos
    await asyncio.sleep(2.5)

    img = await _extract_image(page)
    return img, ("ok" if img else "no-img")


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
