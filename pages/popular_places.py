"""
pages/popular_places.py — TikTok's own "Places from posts" data, browsable by city.
Structured facts (rating, category, distance, saves) — not narrative tips,
see Place Finder for those.
"""

import pathlib
import pandas as pd
import streamlit as st

ROOT = pathlib.Path(__file__).parent.parent

CITY_ORDER = ["Da Nang", "Hoi An", "Ba Na Hills", "Ho Chi Minh"]
CATEGORY_ORDER = [
    "Food & Drink", "Attraction", "Accommodation", "Activity",
    "Shopping", "Transport", "General",
]

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
    df["rating_sort"] = pd.to_numeric(df["Rating"], errors="coerce")
    df["save_sort"] = df["Save Count"].apply(_parse_count)
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


df_all = load_places()

st.markdown("## 📊 Popular Places")
st.caption(
    "TikTok's own 'Places from posts' data — ratings, categories, distances, and save counts "
    "captured from saved posts. No description text (TikTok doesn't show captions here); "
    "for narrative tips see the Place Finder page."
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

            st.dataframe(
                table,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Name": st.column_config.TextColumn("Name", width="medium"),
                    "Rating": st.column_config.TextColumn("★", width=50),
                    "Review Count": st.column_config.TextColumn("Reviews", width=70),
                    "District": st.column_config.TextColumn("District", width=110),
                    "Distance": st.column_config.TextColumn("Distance", width=90),
                    "Landmark": st.column_config.TextColumn("From", width="medium"),
                    "Save Count": st.column_config.TextColumn("Saves", width=90),
                },
            )
