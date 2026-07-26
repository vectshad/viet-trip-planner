"""
get_place_images.py — Playwright script that opens each itinerary stop/option
in Google Maps and saves the place's *hero* photo URL into itinerary.json as
img_url.  After running, photos appear inside the map popup when you tap a pin.

Usage:
    python get_place_images.py                    # all stops + options missing img_url
    python get_place_images.py --limit 3          # test on first 3 entries
    python get_place_images.py --name "My Khe"    # only entries matching a substring
    python get_place_images.py --options-only
    python get_place_images.py --stops-only
    python get_place_images.py --overwrite        # re-fetch even if already set
    python get_place_images.py --dry-run          # print search variants, no browser

How it decides what to search
-----------------------------
Itinerary names are written for humans, not for Maps ("My Khe Beach — Morning
Jog", "Bãi Biển Thiên Đường (My Khe Beach)", "⬡ Opsi B — Independence Palace").
`build_query_variants()` turns one name into an ordered list of candidate
queries, tried most-specific first.  Entries that are purely generic
("Lunch Da Nang", "Spa Day") produce no variants and are skipped outright.

How it picks the image
----------------------
The photo is read from the **DOM of the place panel that is actually open**
(`button.aoRNLd img` — the hero/cover photo), not from intercepted network
responses.  Network interception was the old approach and caused two bugs:
photos bled across consecutive navigations, and it grabbed whichever carousel
photo happened to respond first rather than the cover shot.

How it avoids wrong places
--------------------------
Maps will happily resolve a query to something else entirely.  After landing on
a place page, the panel's <h1> is compared against the query
(`_title_matches()`, diacritic-insensitive, token-overlap + character
similarity).  A mismatch is reported as `bad-match` and stores nothing — no
image is better than the wrong place's image.

Requires:
    pip install playwright
    playwright install chromium
"""

import argparse
import asyncio
import difflib
import json
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

ITIN_FILE = "itinerary.json"

# Minimum _title_matches() score to accept a resolved place.
TITLE_MATCH_THRESHOLD = 0.45


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _strip_diacritics(s: str) -> str:
    """'Đà Nẵng' -> 'Da Nang'.  Vietnamese đ/Đ needs handling beyond NFD."""
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def _norm(s: str) -> str:
    """Lowercase, de-accent, collapse everything non-alphanumeric to spaces."""
    s = _strip_diacritics(s).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


# Maps often titles a place in Vietnamese while the itinerary names it in
# English (or vice versa), leaving no shared token: "3T Cà Phê Trứng" resolves
# to "3T Egg Coffee Sài Gòn", "Hoi An Ancient Town" to "Phố Cổ Hội An".
# Folding these generic place-type words onto one language recovers the match.
# Applied to both sides, so identical strings stay identical — only
# cross-language pairs are affected.  Longest phrases first ("pho co" must be
# rewritten before bare "pho", which is also the noodle soup).
_VI_EN = [
    ("pho co", "ancient town"),
    ("nha tho", "church"),
    ("bai bien", "beach"),
    ("ca phe", "coffee"),
    ("cho dem", "night market"),
    ("nha hang", "restaurant"),
    ("cong vien", "park"),
    ("bao tang", "museum"),
    ("trung", "egg"),
    ("cho", "market"),
    ("quan", "shop"),
]


def _fold(s: str) -> str:
    """Normalise, then fold Vietnamese place-type words to their English form."""
    s = _norm(s)
    for vi, en in _VI_EN:
        s = re.sub(rf"\b{vi}\b", en, s)
    return re.sub(r"\s+", " ", s).strip()


# Words that never identify a place on their own.
_GENERIC_WORDS = {
    "lunch", "dinner", "breakfast", "brunch", "makan", "makansiang",
    "coffee", "shop", "cafe", "kopi", "takeaway", "spa", "day",
    "pasar", "pagi", "sore", "malam", "stay", "hotel", "explore",
    "opsi", "atau", "opsional", "optional", "seafood", "dessert",
    "night", "market", "souvenir", "clothing", "building", "mall",
    "sekitarnya", "dan", "and",
}

# City / country tokens — present in many names but not identifying.
_PLACE_WORDS = {
    "da", "nang", "danang", "hoi", "an", "hoian", "hcm", "saigon",
    "ho", "chi", "minh", "vietnam", "viet", "nam", "ba", "hills",
}

# Parenthetical contents that are descriptors, not alternate place names.
_DESCRIPTOR_PARENS = {
    "opsional", "optional", "souvenir", "clothing", "building", "mall",
    "kopi pagi", "dessert pagi", "traditional market", "gereja pink",
    "night market",
}


def _is_pure_generic(s: str) -> bool:
    """True if `s` is only generic words, city names and digits."""
    toks = _norm(s).split()
    if not toks:
        return True
    return all(t in _GENERIC_WORDS or t in _PLACE_WORDS or t.isdigit()
               or len(t) == 1  # "Opsi A atau B" — bare option letters
               for t in toks)


# ---------------------------------------------------------------------------
# Query variant construction
# ---------------------------------------------------------------------------

def build_query_variants(name: str) -> list[str]:
    """Turn one itinerary name into ordered Maps queries, best guess first."""
    n = name

    # "⬡ Opsi B — Independence Palace" -> "Independence Palace"
    n = re.sub(r"^[⬡⬢●○◆◇\s]*Opsi\s+\w+\s*[—–-]+\s*", "", n).strip()
    # "D5 - Thien Hau Pagoda" -> "Thien Hau Pagoda"
    n = re.sub(r"^D\d+\s*[-—–]\s*", "", n).strip()
    # "Explore Tan Dinh" -> "Tan Dinh"
    n = re.sub(r"^(Explore|Jalan|Keliling)\s+", "", n, flags=re.I).strip()
    # "The Cafe Apartment & Sekitarnya" -> "The Cafe Apartment"
    n = re.sub(r"\s*&\s*Sekitarnya\s*$", "", n, flags=re.I).strip()

    cands: list[str] = [n]

    # Name with all parentheticals removed.
    cands.append(re.sub(r"\s*\([^)]*\)", "", n))

    # Parenthetical is sometimes the well-known English name:
    #   "Bãi Biển Thiên Đường (My Khe Beach)" -> "My Khe Beach"
    # Tried after the bare name — a paren can also hold a street ("(Yersin)").
    for inner in re.findall(r"\(([^)]+)\)", n):
        if _norm(inner) not in {_norm(d) for d in _DESCRIPTOR_PARENS}:
            cands.append(inner)

    # Em-dash split. Normally the head is the place and the tail is an activity
    # ("My Khe Beach — Morning Jog"); when the head is generic the tail carries
    # the real target instead ("Stay HCM — 359/1 Le Van Sy").
    parts = re.split(r"\s+[—–]\s+", n)
    if len(parts) > 1:
        cands.append(parts[0])
        if _is_pure_generic(parts[0]):
            cands.append(parts[-1])

    # Keep the tail after "+": "Dinner + Son Tra Night Market".
    if "+" in n:
        cands.append(n.split("+", 1)[1])

    # Drop a trailing " - <address/branch>" segment.
    cands.append(re.split(r"\s+-\s+", n)[0])

    # Dedupe (normalised), keep order, drop junk and pure-generic queries.
    out: list[str] = []
    seen: set[str] = set()
    for c in cands:
        c = c.strip(" -—–,")
        key = _norm(c)
        if not key or key in seen or len(key) < 3:
            continue
        if _is_pure_generic(c):
            continue
        seen.add(key)
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# Result verification
# ---------------------------------------------------------------------------

def _title_matches(query: str, title: str) -> float:
    """
    Score 0..1 for "is `title` the place `query` asked for".

    Combines token overlap (handles reordering/extra words) with character
    similarity (handles 'Da Nang' vs 'Danang'), taking the best signal.
    """
    q, t = _fold(query), _fold(title)
    if not q or not t:
        return 0.0

    qc, tc = q.replace(" ", ""), t.replace(" ", "")
    if qc in tc or tc in qc:
        return 1.0

    qt, tt = set(q.split()), set(t.split())
    # Ignore city/country tokens — they inflate the score for any nearby place.
    qs, ts = qt - _PLACE_WORDS, tt - _PLACE_WORDS
    if qs and ts:
        inter = len(qs & ts)
        # No word in common (after dropping city names) means a different
        # place. Character similarity alone must not carry a match: short
        # unrelated names collide by coincidence ("Ngam Cafe" vs "Ben Thanh
        # Market" scores 0.45 on characters). Genuine spelling/diacritic
        # variants are caught by the substring check above.
        if inter == 0:
            return 0.0
        # A short query's tokens can all appear inside a long, unrelated title
        # ("Tan Coffee" vs "Thom's Sourdough Bakery & Coffee - Tan Thanh
        # beach"), which plain coverage scores as a perfect match. When the
        # query is short and the title carries several extra significant words,
        # require overlap in both directions instead.
        if len(qs) <= 2 and len(ts) > len(qs) + 2:
            token_score = 2 * inter / (len(qs) + len(ts))
        else:
            token_score = max(inter / len(qs), inter / len(ts))
    else:
        inter = len(qt & tt)
        token_score = inter / max(len(qt), len(tt)) if (qt and tt) else 0.0

    char_score = difflib.SequenceMatcher(None, qc, tc).ratio()
    return max(token_score, char_score)


def _normalize_img_url(url: str) -> str:
    """Standardise the size suffix of a googleusercontent place-photo URL."""
    if "=" in url.rsplit("/", 1)[-1]:
        return re.sub(r"=[^=/]*$", "=w600-h400-k-no", url)
    return url + "=w600-h400-k-no"


# ---------------------------------------------------------------------------
# Browser interaction
# ---------------------------------------------------------------------------

async def _dismiss_consent(page):
    try:
        btn = page.get_by_role(
            "button", name=re.compile(r"accept all|agree|setuju|terima", re.I))
        if await btn.count() > 0:
            await btn.first.click()
            await asyncio.sleep(1.0)
    except Exception:
        pass


async def _poll_url(page, check, timeout=10.0, interval=0.4):
    for _ in range(int(timeout / interval)):
        if check(page.url):
            return page.url
        await asyncio.sleep(interval)
    return page.url


_RESULT_LINK_SEL = (
    'a.hfpxzc, div[role="feed"] a[href*="/maps/place/"], '
    '.Nv2PK a, .lI9IFe a, div[role="article"] a'
)


async def _open_first_result(page) -> bool:
    """
    We're on a results list — open the top result.

    Retried: the old single-shot click fired before the feed had rendered,
    which is what produced most of the spurious `no-place` misses.
    """
    for _ in range(3):
        try:
            await page.wait_for_selector(_RESULT_LINK_SEL, timeout=4000)
        except Exception:
            pass
        # Always take the topmost result. Trying to skip "sponsored" cards by
        # scanning ancestor text was tested and reverted: closest() can resolve
        # to a wrapper holding several cards, so one sponsored card in the group
        # caused valid results to be skipped in favour of worse ones further
        # down (searching "Tan Coffee" reached a bakery 4 km away that way).
        # A paid result that slips through is caught by the title check instead.
        try:
            clicked = await page.evaluate(
                """(sel) => {
                    const el = document.querySelector(sel);
                    if (el) { el.click(); return true; }
                    return false;
                }""", _RESULT_LINK_SEL)
        except Exception:
            clicked = False
        if clicked:
            url = await _poll_url(page, lambda u: "/place/" in u, timeout=6.0)
            if "/place/" in url:
                return True
        await asyncio.sleep(0.8)
    return "/place/" in page.url


# Reads the hero photo + title from the panel currently open.  Selector chain
# confirmed against live Maps DOM: button.aoRNLd is the cover-photo button,
# div.ZKCDEc its header container; the final branch is a size-ranked fallback.
#
# Title must come from h1.DUwDvf (the place panel), NOT the first h1 on the
# page: when Maps keeps the results feed open beside the panel, the feed's own
# heading ("Hasil" / "Results") and any sponsored-card headings come first in
# document order, and reading those rejected 17 valid places as bad-match.
_EXTRACT_JS = """() => {
  const ok = s => s && s.includes('googleusercontent') && !s.includes('/a-/');
  const CHROME = new Set(['hasil','results','resultats','ergebnisse',
                          'resultaten','bersponsor','sponsored','iklan']);
  const isChrome = t => CHROME.has(t.replace(/[^a-zA-Z]/g, '').toLowerCase());

  let title = null;
  const panel = document.querySelector('h1.DUwDvf');
  if (panel && panel.textContent.trim()) {
    title = panel.textContent.trim();
  } else {
    // Fallbacks: the place panel's own role=main carries the name as
    // aria-label; failing that, the last non-chrome h1 on the page.
    const mains = [...document.querySelectorAll('div[role="main"][aria-label]')];
    for (let i = mains.length - 1; i >= 0 && !title; i--) {
      const al = (mains[i].getAttribute('aria-label') || '').trim();
      if (al && !isChrome(al)) title = al;
    }
    if (!title) {
      const hs = [...document.querySelectorAll('h1')]
        .map(h => h.textContent.trim())
        .filter(t => t && !isChrome(t));
      if (hs.length) title = hs[hs.length - 1];
    }
  }

  const hero = document.querySelector('button.aoRNLd img');
  if (hero && ok(hero.src)) return {title, img: hero.src, how: 'hero'};

  const hdr = document.querySelector('div.ZKCDEc');
  if (hdr) {
    let best = null;
    hdr.querySelectorAll('img').forEach(im => {
      if (ok(im.src) && im.naturalWidth >= 200 &&
          (!best || im.naturalWidth > best.naturalWidth)) best = im;
    });
    if (best) return {title, img: best.src, how: 'header'};
  }

  let best = null;
  document.querySelectorAll('img').forEach(im => {
    if (!ok(im.src) || im.naturalWidth < 200) return;
    const a = im.naturalWidth * im.naturalHeight;
    if (!best || a > best.naturalWidth * best.naturalHeight) best = im;
  });
  return {title, img: best ? best.src : null, how: best ? 'largest' : 'none'};
}"""


async def _try_query(page, query: str, lat: float, lon: float):
    """Search one query. Returns (img_url, status, title, score)."""
    q = re.sub(r"\s+", "+", query.strip()) + "+Vietnam"
    nav = f"https://www.google.com/maps/search/{q}/@{lat},{lon},17z"

    try:
        await page.goto(nav, wait_until="domcontentloaded", timeout=25000)
    except Exception as e:
        return None, f"nav:{type(e).__name__}", None, 0.0

    await _dismiss_consent(page)
    await _poll_url(page, lambda u: "@" in u, timeout=8.0)

    if "/place/" not in page.url:
        if not await _open_first_result(page):
            return None, "no-place", None, 0.0

    # Let the panel render its hero image.
    try:
        await page.wait_for_selector("button.aoRNLd img", timeout=6000)
    except Exception:
        await asyncio.sleep(1.5)

    try:
        res = await page.evaluate(_EXTRACT_JS)
    except Exception as e:
        return None, f"eval:{type(e).__name__}", None, 0.0

    title = (res or {}).get("title")
    img = (res or {}).get("img")

    if not title:
        return None, "no-title", None, 0.0

    score = _title_matches(query, title)
    if score < TITLE_MATCH_THRESHOLD:
        return None, "bad-match", title, score
    if not img:
        return None, "no-img", title, score
    return _normalize_img_url(img), "ok", title, score


async def get_image_for_place(page, name: str, lat: float, lon: float):
    """Try each query variant until one yields a verified hero photo."""
    variants = build_query_variants(name)
    if not variants:
        return None, "generic-skip", None, 0.0

    last = (None, "no-place", None, 0.0)
    for q in variants:
        img, status, title, score = await _try_query(page, q, lat, lon)
        if status == "ok":
            return img, "ok", title, score
        # Keep the most informative failure for reporting.
        if status in ("bad-match", "no-img"):
            last = (img, status, title, score)
        await asyncio.sleep(0.6)
    return last


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def collect_targets(data, args):
    filters = [s.strip().lower() for s in args.name.split(",")] if args.name else None
    targets = []
    for day in data:
        for stop in day["stops"]:
            rows = []
            if not args.options_only:
                rows.append((stop, "stop"))
            if not args.stops_only:
                rows += [(o, "opt") for o in (stop.get("options") or [])]
            for entry, kind in rows:
                if not (entry.get("lat") and entry.get("lon")):
                    continue
                if entry.get("img_url") and not args.overwrite:
                    continue
                if filters and not any(f in entry["name"].lower() for f in filters):
                    continue
                targets.append((entry, f'[{kind}]'.ljust(7) + entry["name"]))
    return targets


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--stops-only", action="store_true")
    ap.add_argument("--options-only", action="store_true")
    ap.add_argument("--name", type=str, default=None,
                    help="Only entries matching this substring (comma-separated for several)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print search variants and exit (no browser)")
    args = ap.parse_args()

    with open(ITIN_FILE, encoding="utf-8") as f:
        data = json.load(f)

    targets = collect_targets(data, args)
    if not targets:
        print("Nothing to fetch. Use --overwrite to re-fetch existing.")
        return
    if args.limit:
        targets = targets[:args.limit]

    if args.dry_run:
        skipped = 0
        for entry, label in targets:
            v = build_query_variants(entry["name"])
            if not v:
                skipped += 1
                print(f"  SKIP  {label}")
            else:
                print(f"  {label}\n          -> {v}")
        print(f"\n{len(targets)} entries, {skipped} generic-skip, "
              f"{len(targets) - skipped} searchable")
        return

    print(f"{len(targets)} places to fetch images for\n")
    stats: dict[str, int] = {}

    def save():
        with open(ITIN_FILE, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"))
        page = await ctx.new_page()

        try:
            for i, (entry, label) in enumerate(targets, 1):
                print(f"  [{i}/{len(targets)}] {label} ... ", end="", flush=True)
                img, status, title, score = await get_image_for_place(
                    page, entry["name"], entry["lat"], entry["lon"])
                stats[status] = stats.get(status, 0) + 1

                if status == "ok":
                    entry["img_url"] = img
                    print(f"OK   [{score:.2f}] {title}")
                elif status == "bad-match":
                    # Definitive wrong place — drop any previously stored image
                    # rather than leave an unverified one behind. Transient
                    # failures (nav/eval) deliberately keep what's there.
                    dropped = entry.pop("img_url", None)
                    print(f"SKIP bad-match [{score:.2f}] got {title!r}"
                          + ("  (cleared old image)" if dropped else ""))
                else:
                    print(f"MISS {status}" + (f" ({title})" if title else ""))

                # Checkpoint: a full pass takes ~20 min, don't lose it all
                # if the run is interrupted partway.
                if i % 10 == 0:
                    save()
        finally:
            save()
            await browser.close()

    print("\n--- Done ---")
    for k in sorted(stats, key=lambda k: -stats[k]):
        print(f"  {k:<14} {stats[k]}")
    print(f"\n{ITIN_FILE} updated.")


asyncio.run(main())
