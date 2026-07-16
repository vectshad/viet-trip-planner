# Aku Turis Vietnam — Trip Planner (viet-trip-planner)

Streamlit itinerary + place-browsing app for a 5-person Vietnam trip:
**Da Nang/Hoi An 29–31 Jul 2026 → Ho Chi Minh City 31 Jul–3 Aug 2026.**
Deployed on Streamlit Cloud. No paid APIs anywhere (Nominatim/OpenStreetMap
for geocoding, CartoDB for map tiles).

## Read this first if you're picking this up cold

This repo has a **sibling repo**, `vectshad/viet-stay-picker` — a separate
Airbnb/stay picker app. They are NOT the same project. A previous session
accidentally built a feature in `viet-stay-picker` that was meant for this
repo (both have a Streamlit multipage structure and both apps can plausibly
host a "Place Finder"-shaped feature — easy to mix up). Double-check which
repo you're in before making changes. `viet-stay-picker` is Cards/Compare/
Map/Vote for choosing an Airbnb; `viet-trip-planner` (this repo) is the
itinerary + "what to eat/see" browsing tool.

## Architecture

```
app.py                    # st.navigation entry point — Itinerary, Place Finder, Popular Places
itinerary.py               # Main itinerary page: map view, timeline, logic checker, edit, place search
itinerary_data.csv         # (legacy/reference — itinerary.json is the live source now)
itinerary.json             # Live itinerary data. Loaded/saved via storage.py
storage.py                 # Persistence: GitHub API if st.secrets["github"] is configured
                            #   (Streamlit Cloud), else local itinerary.json (local dev)
places.py                  # Nominatim (OpenStreetMap) place search — free, 1 req/sec, no API key
map_builder.py              # Folium map construction for the Itinerary page
logic_checker.py            # Flags itinerary timing/geography issues (e.g. backtracking, overlaps)
geocode_places.py           # One-time/idempotent script: geocodes Da Nang/HCM places in
                            #   data/tiktok_places.csv, computes distance from your stay
pages/
  place_finder.py           # Browses data/vietnam_trip_notes.csv (caption-derived TikTok notes)
  popular_places.py         # Browses data/tiktok_places.csv (TikTok's own structured POI data)
data/
  vietnam_trip_notes.csv    # 70 rows — TikTok captions/tips, has narrative text, no ratings
  tiktok_places.csv         # 204 rows — TikTok's "Places from posts" data: ratings, categories,
                            #   districts, distances, save counts. No narrative text.
```

## The two place-browsing pages are intentionally separate

They come from different TikTok features and have different strengths —
merging them would lose one or the other:

| | Place Finder | Popular Places |
|---|---|---|
| Source data | `vietnam_trip_notes.csv` | `tiktok_places.csv` |
| Where it came from | Playwright-scraped captions of ~87 saved TikTok posts | OCR'd from 35 phone screenshots of TikTok's "Places from posts" panel (an app-only feature — not on tiktok.com desktop web, confirmed by testing) |
| Has | Narrative tips/captions, creator handle, video link | Rating, review count, category, district, distance-from-landmark, save count |
| Doesn't have | Ratings, structured categories | Any description text — TikTok never showed captions in that panel |
| City/Category taxonomy | 5 cities / 8 categories (original) | Normalized onto the *same* 5-city/8-category taxonomy so both pages feel consistent, but the underlying TikTok category was much finer-grained (78 values) — kept as a `TikTok Category` column in the raw CSV for reference |

## How `tiktok_places.csv` was built (context for reproducing/extending)

1. TikTok's "Places from posts" panel (app-only) was screenshotted — 35
   images, scrolling through ~220 places TikTok's app had already extracted
   from the user's saved Collection.
2. OCR'd locally with Tesseract (`--psm 3`, `eng+vie` language packs — the
   Vietnamese pack is required for diacritics). The OCR parser (not
   committed to this repo — it was a one-off transform script) used a
   state-machine over cleaned OCR lines to split each card into
   name/rating/category/district/distance/landmark/save-count, with several
   rounds of fixes for real bugs found by testing against actual screenshots:
   - PSM 6 (forced single text block) badly garbled this card-grid UI; PSM 3
     (auto full-page segmentation) was dramatically cleaner.
   - Stray 1-2 char OCR noise (misread icons) between fields caused
     cascading misalignment — filtered by length and a chrome-line denylist.
   - Cards truncated at the bottom of the screen sometimes had their
     district/distance line read *out of order*, appearing as if it were the
     next card's name — detected and reattached to the correct record
     instead of becoming a phantom row.
   - Some locations have no "X km from landmark" distance at all (islands,
     outer districts) — just "District · Subdistrict" or free-text
     "Province, Vietnam" — the parser has fallback patterns for both.
3. Raw OCR extraction: 233 places. Normalized: district → City (same 5
   buckets as `vietnam_trip_notes.csv`, including treating Ba Na Hills as
   its own city even though it's technically in Hoa Vang district — matches
   the existing convention), TikTok's 78 fine-grained categories → the
   8-value Category scheme. Dropped 3 unrecoverable garbage rows and 13
   out-of-trip-scope rows (Hue, Da Lat, Phu Quoc, Hanoi, etc. — same spirit
   as the original notes CSV's scope filtering). **Final: 204 rows.**
4. Known residual data quality issues (~a handful of rows, not systemic):
   - Some `Name` values carry a trailing 1-2 character OCR icon-glyph
     artifact (e.g. "IconSphere Hotel 4", "...kí", "...WV") — cosmetic,
     `popular_places.py` strips a known set of these patterns before
     building Maps/Directions query strings, but the *displayed* Name is
     left as-is.
   - Vietnamese diacritics occasionally flatten (e.g. "Mặn Mòi" → "Man
     Moi").
   - A few rows have an empty `Category` where that field itself got
     OCR-scrambled — name/city are still valid, just uncategorized.
   - A few known real places (Cua Dai Beach, Moments Hoi An cafe) were lost
     to OCR scrambling entirely and aren't in the 204 rows — could be
     manually re-added if noticed missing.

If you want to add more places later: re-screenshot the Places panel
(scroll with slight overlap between shots so near-duplicates can be
deduped), OCR, and re-run the same normalization approach. Or extend
`data/tiktok_places.csv` by hand — it's just a CSV.

## `geocode_places.py` — distance from your stay

`popular_places.py`'s "From Stay" (km) and "Directions" columns, shown only
on the Da Nang and Ho Chi Minh tabs, need place coordinates. TikTok's Places
panel never exposed lat/lon, so a separate geocoding pass is needed:

```bash
pip install requests
python geocode_places.py
```

This calls Nominatim (OpenStreetMap's free geocoder, 1 req/sec rate limit,
so ~157 places takes a few minutes) and writes `Lat`, `Lon`, and `Distance
from Stay (km)` back into `data/tiktok_places.csv`. It's idempotent — safe
to re-run, already-geocoded rows are skipped.

**Expect a meaningful "not found" rate.** Nominatim/OpenStreetMap has much
sparser coverage of small Vietnamese restaurants/cafes than Google's own
database — this is a real data-source gap, not a bug. The script already
retries each place at 3 query specificities (name+district+city → name+city
→ name alone) before giving up. Importantly, **this doesn't break the core
feature**: the "Maps" link and the "Directions" fallback elsewhere in
`popular_places.py` search Google Maps directly by name/text and work fine
regardless of whether a place geocoded here — only the numeric "From Stay"
distance and whether Directions uses an exact pin (vs. a text search) depend
on this script succeeding.

Stay coordinates are hardcoded in both `geocode_places.py` and
`popular_places.py` (`STAY_COORDS`), matching the `"hotel"`-category stops
already in `itinerary.json`:
- Da Nang: 59 Nguyen Tat Thanh — `16.0828493, 108.2129368`
- HCM: 359/1 Le Van Sy — `10.788235, 106.676557`

If those stays change, update `STAY_COORDS` in both files (and re-run
`geocode_places.py` to recompute distances — it'll skip rows that already
have `Lat` set, so you'd need to clear those two columns first, or add a
`--force` flag if that becomes a recurring need).

## Local dev

```bash
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

No secrets needed for local dev — `storage.py` and `is_configured()` fall
back to reading/writing local `itinerary.json` when `st.secrets["github"]`
isn't set. GitHub-backed persistence (so multiple people's edits sync via
the deployed app) only activates on Streamlit Cloud with secrets configured
as `[github] token = "..."`, `repo = "owner/repo"`.

## Known open items / backlog

- [ ] Run `geocode_places.py` (or re-run after this fallback-retry
      improvement) and check the resulting hit rate.
- [ ] Consider whether Hoi An/Ba Na Hills should also get a "from stay"
      distance — currently out of scope since there's no dedicated stay
      point for those (the trip only overnights in Da Nang and HCM).
- [ ] Consider a "sort by distance from stay" option in Popular Places
      (currently sorted by rating/save count only).
- [ ] The few known-real-but-OCR-lost places (Cua Dai Beach, Moments Hoi An)
      could be manually added to `data/tiktok_places.csv`.
- [ ] `itinerary_data.csv` at repo root looks like it may predate
      `itinerary.json` as the itinerary's source of truth — worth confirming
      it's still needed, or removing if stale.
