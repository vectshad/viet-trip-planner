"""
pages/place_finder.py — Vietnam TikTok notes browser
Browse, filter, and search community travel tips.
"""

import sys
import pathlib
import pandas as pd
import streamlit as st

# Allow importing from project root (storage, places)
ROOT = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from storage import load_itinerary, save_itinerary, is_configured
from places import search_place


# ── CSS — identical palette to main app ───────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');
html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }
.result-count {
    font-size: 13px; color: #718096;
    margin-bottom: 12px; margin-top: -4px;
}
</style>
""", unsafe_allow_html=True)


# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data
def load_notes() -> pd.DataFrame:
    csv_path = ROOT / "data" / "vietnam_trip_notes.csv"
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    df["#"] = pd.to_numeric(df["#"], errors="coerce").astype("Int64")
    return df


df = load_notes()
cities     = sorted(df["City"].unique())
categories = sorted(df["Category"].unique())

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🔍 Place Finder")
    st.markdown("Browse TikTok travel notes for Vietnam.")
    st.divider()

    selected_cities = st.multiselect(
        "City", cities, default=cities, key="pf_cities"
    )
    selected_cats = st.multiselect(
        "Category", categories, default=categories, key="pf_cats"
    )
    st.divider()
    if is_configured():
        st.caption("☁️ GitHub sync: enabled")
    else:
        st.caption("💾 GitHub sync: not configured (local mode)")


# ── Header + Search ───────────────────────────────────────────────────────────
st.markdown("## 🔍 Place Finder")
query = st.text_input(
    "Search",
    placeholder="Search places or tips… e.g. banh mi, coffee, halal",
    label_visibility="collapsed",
)

# ── Filter logic ──────────────────────────────────────────────────────────────
mask = pd.Series(True, index=df.index)

if selected_cities:
    mask &= df["City"].isin(selected_cities)
if selected_cats:
    mask &= df["Category"].isin(selected_cats)
if query.strip():
    q = query.strip()
    mask &= (
        df["Places"].str.contains(q, case=False, na=False) |
        df["Tips / Summary"].str.contains(q, case=False, na=False)
    )

filtered = df[mask].reset_index(drop=True)

st.markdown(
    f'<div class="result-count">{len(filtered)} result{"s" if len(filtered) != 1 else ""}</div>',
    unsafe_allow_html=True,
)

# ── Table ─────────────────────────────────────────────────────────────────────
display_cols = ["#", "Creator", "City", "Category", "Places", "Tips / Summary", "Video URL"]
table = filtered[display_cols].copy()
table = table.rename(columns={"Video URL": "Watch"})

st.dataframe(
    table,
    use_container_width=True,
    hide_index=True,
    column_config={
        "#": st.column_config.NumberColumn("#", width=40),
        "Creator": st.column_config.TextColumn("Creator", width=130),
        "City": st.column_config.TextColumn("City", width=110),
        "Category": st.column_config.TextColumn("Category", width=110),
        "Places": st.column_config.TextColumn("Places", width=180),
        "Tips / Summary": st.column_config.TextColumn(
            "Tips / Summary", width="large"
        ),
        "Watch": st.column_config.LinkColumn(
            "Watch",
            display_text="▶ Watch",
            width=80,
        ),
    },
)

# ── Add to Itinerary (stretch goal) ──────────────────────────────────────────
st.divider()
with st.expander("➕ Add a place from this list to your Itinerary"):
    if filtered.empty:
        st.info("No results to add. Adjust your filters first.")
    else:
        # Load itinerary into session state if not already loaded
        if "days" not in st.session_state:
            loaded = load_itinerary()
            if loaded:
                st.session_state.days = loaded
            else:
                st.warning("Could not load itinerary. Open the main Map page first.")
                st.stop()

        # Row picker
        row_labels = [
            f"#{row['#']} — {row['Creator']} — {row['Places'] or row['Tips / Summary'][:60]}"
            for _, row in filtered.iterrows()
        ]
        chosen_label = st.selectbox("Select a tip/place to add:", row_labels, key="pf_row_pick")
        chosen_idx   = row_labels.index(chosen_label)
        chosen_row   = filtered.iloc[chosen_idx]

        st.caption(f"**Source:** {chosen_row['Creator']} · {chosen_row['City']} · {chosen_row['Category']}")
        if chosen_row["Tips / Summary"]:
            st.info(chosen_row["Tips / Summary"][:300])

        # Form
        col1, col2, col3 = st.columns(3)
        place_name = col1.text_input(
            "Place name",
            value=chosen_row["Places"].split(";")[0].strip() if chosen_row["Places"] else "",
            key="pf_name",
        )
        start_time = col2.text_input("Start (HH:MM)", value="09:00", key="pf_start")
        end_time   = col3.text_input("End (HH:MM)", value="10:00", key="pf_end")

        col4, col5 = st.columns(2)
        day_names   = [d["day"] for d in st.session_state.days]
        target_day  = col4.selectbox("Add to day:", day_names, key="pf_day")
        category    = col5.selectbox(
            "Category",
            ["attraction", "food", "market", "museum", "beach",
             "airport", "nightlife", "hotel", "transport"],
            key="pf_cat",
        )
        notes = st.text_input(
            "Notes",
            value=chosen_row["Tips / Summary"][:120] if chosen_row["Tips / Summary"] else "",
            key="pf_notes",
        )

        if st.button("➕ Add to Itinerary", type="primary", key="pf_add"):
            if not place_name.strip():
                st.warning("Enter a place name first.")
            else:
                with st.spinner(f"Looking up coordinates for '{place_name}'…"):
                    geo = search_place(place_name, "vn")

                day_idx = day_names.index(target_day)
                st.session_state.days[day_idx]["stops"].append({
                    "name":     place_name.strip(),
                    "start":    start_time,
                    "end":      end_time,
                    "notes":    notes[:200],
                    "category": category,
                    "lat":      geo["lat"] if geo else None,
                    "lon":      geo["lon"] if geo else None,
                })

                if save_itinerary(st.session_state.days):
                    st.success(
                        f"Added **{place_name}** to {target_day}"
                        + (f" (📍 {geo['lat']:.4f}, {geo['lon']:.4f})" if geo else " — coordinates not found")
                    )
                else:
                    st.success(f"Added **{place_name}** to {target_day} (saved locally).")
