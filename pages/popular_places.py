"""
pages/popular_places.py — TikTok's own "Places from posts" data, browsable by city.
Structured facts (rating, category, distance, saves) — not narrative tips,
see Place Finder for those.
"""

import pathlib
import re
import urllib.parse
import folium
import pandas as pd
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

ROOT = pathlib.Path(__file__).parent.parent

# folium.Icon only accepts this fixed palette — not arbitrary hex — so each
# Popular Places category gets a named color + a Font Awesome glyph.
CATEGORY_MARKER = {
    "Food & Drink": ("green", "cutlery"),
    "Attraction": ("red", "star"),
    "Accommodation": ("purple", "home"),
    "Activity": ("darkgreen", "bolt"),
    "Shopping": ("orange", "shopping-cart"),
    "Transport": ("gray", "car"),
    "General": ("lightgray", "map-marker"),
}

# Rough city centers for the map's initial view — not exact, just enough to
# frame the right area before markers/clustering take over.
CITY_MAP_CENTER = {
    "Da Nang": (16.047, 108.220),
    "Hoi An": (15.880, 108.330),
    "Ba Na Hills": (15.996, 107.989),
    "Ho Chi Minh": (10.776, 106.700),
}

# Trailing OCR icon-glyph noise on names (e.g. "IconSphere Hotel 4", "...kí") —
# stripped only for the maps search query, the displayed Name is left as-is.
_NAME_NOISE_RE = re.compile(r"\s+(k[íi]|WV|V[íÍ]|Z|[47]|</?7?|⁄)$")

CITY_ORDER = ["Da Nang", "Hoi An", "Ba Na Hills", "Ho Chi Minh"]
CATEGORY_ORDER = [
    "Food & Drink", "Attraction", "Accommodation", "Activity",
    "Shopping", "Transport", "General",
]

# Same stay points as itinerary.json — distance/directions only make sense
# for the two cities you're actually staying in.
STAY_COORDS = {
    "Da Nang": (16.0828493, 108.2129368),      # Stay Da Nang — 59 Nguyen Tat Thanh
    "Ho Chi Minh": (10.788235, 106.676557),    # Stay HCM — 359/1 Le Van Sy
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
.cat-heading {
    font-size: 13px; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.05em; color: #718096; margin: 18px 0 6px;
}
.result-count { font-size: 13px; color: #718096; margin-bottom: 12px; margin-top: -4px; }
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_places() -> pd.DataFrame:
    df = pd.read_csv(ROOT / "data" / "tiktok_places.csv", dtype=str).fillna("")
    for col in ["Lat", "Lon", "Distance from Stay (km)"]:
        if col not in df.columns:
            df[col] = ""  # not geocoded yet — run geocode_places.py to fill these in
    df["rating_sort"] = pd.to_numeric(df["Rating"], errors="coerce")
    df["save_sort"] = df["Save Count"].apply(_parse_count)
    df["stay_dist_sort"] = pd.to_numeric(df["Distance from Stay (km)"], errors="coerce")
    return df


def _parse_count(s: str) -> float:
    s = s.strip()
    if not s or "attraction" in s.lower():
        return -1
    s = s.replace("+", "").replace(",", "")
    try:
        if s.upper().endswith("K"):
            return float(s[:-1]) * 1000
        return float(s)
    except ValueError:
        return -1


def build_maps_url(name: str, district: str, city: str) -> str:
    """Google Maps text-search link — no API key needed, no coordinates required.
    TikTok's Places panel doesn't expose lat/lon, so this searches by name +
    location instead of linking straight to a pin."""
    clean_name = _NAME_NOISE_RE.sub("", name.strip())
    parts = [clean_name]
    if district and district != city:
        parts.append(district)
    parts.append(f"{city}, Vietnam")
    query = ", ".join(p for p in parts if p)
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)


def build_directions_url(row, city: str) -> str:
    """Google Maps directions from your stay to this place. Uses precise
    coordinates when geocode_places.py has filled them in, otherwise falls
    back to a text-based destination (same query as build_maps_url)."""
    if city not in STAY_COORDS:
        return ""
    origin = f"{STAY_COORDS[city][0]},{STAY_COORDS[city][1]}"
    if row["Lat"] and row["Lon"]:
        destination = f"{row['Lat']},{row['Lon']}"
    else:
        clean = _NAME_NOISE_RE.sub("", row["Name"].strip())
        destination = f"{clean}, {row['District']}, {city}, Vietnam" if row["District"] else f"{clean}, {city}, Vietnam"
    return (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={urllib.parse.quote(origin)}"
        f"&destination={urllib.parse.quote(destination)}"
    )


df_all = load_places()

st.markdown("## 📊 Popular Places")
st.caption(
    "TikTok's own 'Places from posts' data — ratings, categories, distances, and save counts "
    "captured from saved posts. No description text (TikTok doesn't show captions here); "
    "for narrative tips see the Place Finder page."
)
if df_all["stay_dist_sort"].isna().all() and (df_all["City"].isin(STAY_COORDS)).any():
    st.info(
        "💡 'From Stay' distance/directions columns (Da Nang & HCM only) will appear once "
        "`geocode_places.py` has been run — see the script for one-time setup.",
        icon="💡",
    )

cities_present = [c for c in CITY_ORDER if c in df_all["City"].unique()]
tabs = st.tabs(cities_present)

for tab, city in zip(tabs, cities_present):
    with tab:
        city_df = df_all[df_all["City"] == city]

        f_cat, f_search = st.columns([1.4, 2])
        with f_cat:
            cats_present = [c for c in CATEGORY_ORDER if c in city_df["Category"].unique()]
            selected_cats = st.multiselect(
                "Category", cats_present, default=cats_present, key=f"pp_cat_{city}"
            )
        with f_search:
            query = st.text_input(
                "Search", placeholder="Search place names…",
                label_visibility="collapsed", key=f"pp_search_{city}",
            )

        filtered = city_df[city_df["Category"].isin(selected_cats)]
        if query.strip():
            filtered = filtered[filtered["Name"].str.contains(query.strip(), case=False, na=False)]

        st.markdown(
            f'<div class="result-count">{len(filtered)} place{"s" if len(filtered) != 1 else ""} in {city}</div>',
            unsafe_allow_html=True,
        )

        if filtered.empty:
            st.info("No places match these filters.")
            continue

        # Map view — plots whatever the Category/Search filters above have
        # already narrowed down to, so it declutters itself instead of an
        # arbitrary per-category cap; MarkerCluster groups nearby pins until
        # you zoom in for dense spots.
        if st.toggle("🗺️ Show map", key=f"pp_map_toggle_{city}"):
            mappable = filtered[(filtered["Lat"] != "") & (filtered["Lon"] != "")]
            if mappable.empty:
                st.info("None of the currently filtered places have coordinates yet.")
            else:
                if len(mappable) < len(filtered):
                    st.caption(
                        f"Showing {len(mappable)} of {len(filtered)} filtered places that have "
                        "coordinates — the rest haven't been geocoded yet."
                    )
                m = folium.Map(
                    location=CITY_MAP_CENTER.get(city, (16.0, 107.5)),
                    zoom_start=13,
                    tiles="CartoDB positron",
                )
                cluster = MarkerCluster().add_to(m)
                for _, r in mappable.iterrows():
                    color, glyph = CATEGORY_MARKER.get(r["Category"], CATEGORY_MARKER["General"])
                    popup_html = (
                        f"<b>{r['Name']}</b><br>"
                        f"<small>{r['Category']}"
                        + (f" · ⭐{r['Rating']}" if r["Rating"] else "")
                        + f"</small><br>"
                        f'<a href="{build_maps_url(r["Name"], r["District"], city)}" target="_blank">📍 Open in Maps</a>'
                    )
                    folium.Marker(
                        [float(r["Lat"]), float(r["Lon"])],
                        tooltip=r["Name"],
                        popup=folium.Popup(popup_html, max_width=250),
                        icon=folium.Icon(color=color, icon=glyph, prefix="fa"),
                    ).add_to(cluster)
                st_folium(m, width="100%", height=480, key=f"pp_map_{city}", returned_objects=[])

        for cat in [c for c in CATEGORY_ORDER if c in filtered["Category"].unique()]:
            cat_df = filtered[filtered["Category"] == cat].sort_values(
                ["rating_sort", "save_sort"], ascending=False, na_position="last"
            )
            st.markdown(f'<div class="cat-heading">{cat} ({len(cat_df)})</div>', unsafe_allow_html=True)

            table = cat_df[[
                "Name", "Rating", "Review Count", "District",
                "Distance", "Distance Unit", "Landmark", "Save Count",
            ]].copy()
            table["Distance"] = table.apply(
                lambda r: f'{r["Distance"]} {r["Distance Unit"]}' if r["Distance"] else "", axis=1
            )
            table = table.drop(columns=["Distance Unit"])
            table["Maps"] = cat_df.apply(
                lambda r: build_maps_url(r["Name"], r["District"], city), axis=1
            )

            column_config = {
                "Name": st.column_config.TextColumn("Name", width="medium"),
                "Rating": st.column_config.TextColumn("★", width=50),
                "Review Count": st.column_config.TextColumn("Reviews", width=70),
                "District": st.column_config.TextColumn("District", width=110),
                "Distance": st.column_config.TextColumn("Distance", width=90),
                "Landmark": st.column_config.TextColumn("From", width="medium"),
                "Save Count": st.column_config.TextColumn("Saves", width=90),
                "Maps": st.column_config.LinkColumn("Maps", display_text="📍 Open", width=80),
            }

            if city in STAY_COORDS:
                table["From Stay"] = cat_df["stay_dist_sort"].apply(
                    lambda v: f"{v:.1f} km" if pd.notna(v) else ""
                )
                table["Directions"] = cat_df.apply(
                    lambda r: build_directions_url(r, city), axis=1
                )
                column_config["From Stay"] = st.column_config.TextColumn("From Stay", width=90)
                column_config["Directions"] = st.column_config.LinkColumn(
                    "Directions", display_text="🧭 Go", width=80
                )

            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True,
                column_config=column_config,
            )
