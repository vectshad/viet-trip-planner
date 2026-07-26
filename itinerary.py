"""
app.py — Trip Planner Streamlit App
Similar functionality to Claude's built-in travel tools:
  - Interactive map with day-by-day routing (Folium + OpenStreetMap, free)
  - Place search (Nominatim, free)
  - Itinerary logic checker
  - Timeline view
"""

import streamlit as st
import pandas as pd
from streamlit_folium import st_folium

from places import search_place
from map_builder import build_map, DAY_COLORS
from logic_checker import check_itinerary
from storage import load_itinerary, save_itinerary, is_configured
from place_suggester import suggest_places, CATEGORY_MAP, infer_city, find_anchor

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=DM+Mono:wght@400;500&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

.block-container { padding-top: 1.5rem; padding-bottom: 2rem; }

.day-header {
    padding: 10px 16px;
    border-radius: 10px;
    color: white;
    font-weight: 600;
    font-size: 15px;
    margin-bottom: 10px;
}

.stop-card {
    background: #f8f9fa;
    border-left: 4px solid #ccc;
    border-radius: 0 8px 8px 0;
    padding: 10px 14px;
    margin-bottom: 8px;
    font-size: 14px;
    color: #1a202c;
}

.stop-time {
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    color: #555;
}

.issue-error {
    background: #fff5f5;
    border-left: 4px solid #E53E3E;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 6px;
    font-size: 13px;
    color: #1a202c;
}
.issue-warning {
    background: #fffbeb;
    border-left: 4px solid #D69E2E;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 6px;
    font-size: 13px;
    color: #1a202c;
}
.issue-info {
    background: #ebf8ff;
    border-left: 4px solid #3182CE;
    padding: 10px 14px;
    border-radius: 0 8px 8px 0;
    margin-bottom: 6px;
    font-size: 13px;
    color: #1a202c;
}

.metric-card {
    background: white;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 16px 20px;
    text-align: center;
    color: #1a202c;
}
.metric-number { font-size: 28px; font-weight: 600; color: #1a202c; }
.metric-label { font-size: 12px; color: #555; margin-top: 2px; }
</style>
""", unsafe_allow_html=True)


# ── Session state defaults ────────────────────────────────────────────────────
if "days" not in st.session_state:
    _loaded = load_itinerary()
    if _loaded:
        st.session_state.days = _loaded
    else:
        st.error("Could not load itinerary.json. Make sure the file exists in the project folder.")
        st.stop()

if "search_results" not in st.session_state:
    st.session_state.search_results = {}


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_all_stops():
    return [stop for day in st.session_state.days for stop in day["stops"]]


def severity_icon(s):
    return {"error": "🔴", "warning": "🟡", "info": "🔵"}.get(s, "⚪")


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🗺️ Aku Turis Vietnam")
    st.markdown("Interactive itinerary with map, logic check & timeline.")
    st.divider()

    tab = st.radio(
        "Navigation",
        ["🗺️ Map View", "📅 Timeline", "⚠️ Logic Check", "✏️ Edit Itinerary", "🔍 Place Search"],
        label_visibility="collapsed",
    )

    st.divider()
    st.markdown("**Trip Summary**")
    total_stops = len(get_all_stops())
    total_days = len(st.session_state.days)
    cities = list({s["name"].split(",")[-1].strip() for d in st.session_state.days for s in d["stops"]})

    col1, col2 = st.columns(2)
    with col1:
        st.metric("Days", total_days)
    with col2:
        st.metric("Stops", total_stops)

    st.caption("Powered by OpenStreetMap (Nominatim) + Folium — 100% free")
    if is_configured():
        st.caption("☁️ GitHub sync: enabled")
    else:
        st.caption("💾 GitHub sync: not configured (local mode)")


# Shared across Map View and Timeline
_CAT_COLORS = {
    "flight": "#378ADD", "food": "#1D9E75", "hotel": "#7F77DD",
    "attraction": "#E8593C", "market": "#EF9F27", "beach": "#0F6E56",
    "transport": "#888780", "museum": "#533ab7", "nightlife": "#D85A30",
    "airport": "#378ADD", "default": "#888780",
}

def _render_excel_opts(opts, cat_color, default_open=True):
    """Return HTML <details> block for Excel options."""
    rows = ""
    for opt in opts:
        name_o   = opt.get("name", "")
        rate     = opt.get("rate")
        rev      = opt.get("reviews")
        note_o   = opt.get("note") or ""
        star_str = f"⭐ {rate}" if rate else ""
        rev_str  = f"({int(rev):,} reviews)" if rev else ""
        note_str = f" &nbsp;·&nbsp; <i style='color:#777'>{note_o}</i>" if note_o else ""
        maps_q   = name_o.replace(" ", "+")
        maps_url = f"https://www.google.com/maps/search/?api=1&query={maps_q}+Vietnam"
        meta     = " &nbsp;·&nbsp; ".join(filter(None, [star_str, rev_str]))
        rows += (
            f'<div style="padding:5px 0;border-bottom:1px solid #e2e8f0;color:#1a202c">'
            f'<b style="color:#1a202c">{name_o}</b>{note_str}'
            f'<br><small style="color:#555">{meta}'
            f' &nbsp;·&nbsp; <a href="{maps_url}" target="_blank">📍 Google Maps</a>'
            f'</small></div>'
        )
    open_attr = "open" if default_open else ""
    return (
        f'<details {open_attr} style="background:#f8f9fa;border-left:4px solid {cat_color};'
        f'border-radius:0 8px 8px 0;padding:8px 14px;margin:6px 0">'
        f'<summary style="cursor:pointer;font-size:12.5px;color:#555;'
        f'font-weight:600;list-style:none">&#9654; 📋 {len(opts)} opsi dari rencana</summary>'
        f'<div style="margin-top:6px">{rows}</div>'
        f'</details>'
    )

def _render_tiktok_opts(suggestions):
    """Return HTML <details> block for TikTok suggestions (collapsed by default)."""
    rows = ""
    for s in suggestions:
        rating_str = f' &nbsp;·&nbsp; ⭐{s["rating"]}' if s["rating"] else ""
        dist_str   = f'{s["dist_km"]:.1f} km' if s["dist_km"] is not None else "jarak ?"
        rows += (
            f'<div style="font-size:12.5px;padding:3px 0;border-bottom:1px solid #e2e8f0">'
            f'• <b>{s["name"]}</b>{rating_str} &nbsp;·&nbsp; {dist_str}'
            f' &nbsp;·&nbsp; <a href="{s["maps_url"]}" target="_blank">📍 Maps</a></div>'
        )
    return (
        f'<details style="border-left:4px solid #a0aec0;'
        f'border-radius:0 8px 8px 0;padding:8px 14px;margin:4px 0">'
        f'<summary style="cursor:pointer;font-size:12.5px;color:#718096;'
        f'font-weight:600;list-style:none">&#9654; 💡 {len(suggestions)} opsi dari TikTok data</summary>'
        f'<div style="margin-top:6px">{rows}</div>'
        f'</details>'
    )


# ══════════════════════════════════════════════════════════════════════════════
# MAP VIEW
# ══════════════════════════════════════════════════════════════════════════════
if tab == "🗺️ Map View":
    st.markdown("## 🗺️ Interactive Map")

    # Day filter
    day_options = ["All Days"] + [d["day"] for d in st.session_state.days]
    selected_day = st.selectbox("Filter by day:", day_options)

    if selected_day == "All Days":
        days_to_show = st.session_state.days
    else:
        days_to_show = [d for d in st.session_state.days if d["day"] == selected_day]

    # Build and display map
    m = build_map(days_to_show)
    map_data = st_folium(m, width="100%", height=560, returned_objects=["last_object_clicked"])

    # Show clicked marker info
    if map_data and map_data.get("last_object_clicked"):
        clicked = map_data["last_object_clicked"]
        lat, lon = clicked.get("lat"), clicked.get("lng")
        if lat and lon:
            # Find closest stop — store full day dict for city inference
            closest = None
            min_dist = float("inf")
            for day in days_to_show:
                for stop in day["stops"]:
                    if stop.get("lat") and stop.get("lon"):
                        d = abs(stop["lat"] - lat) + abs(stop["lon"] - lon)
                        if d < min_dist:
                            min_dist = d
                            closest = (day, stop)
            if closest and min_dist < 0.01:
                day_obj, stop = closest
                cat_color = _CAT_COLORS.get(stop.get("category", "default"), "#888780")
                with st.expander(f"📍 {stop['name']}", expanded=True):
                    col1, col2, col3 = st.columns(3)
                    col1.markdown(f"**Day**\n\n{day_obj['day']}")
                    col2.markdown(f"**Time**\n\n{stop.get('start', '—')} – {stop.get('end', '—')}")
                    col3.markdown(f"**Category**\n\n{stop.get('category', '—').title()}")
                    if stop.get("notes"):
                        st.info(stop["notes"])

                    # Excel options — open by default (not many, easy to scan)
                    opts = stop.get("options")
                    if opts:
                        st.markdown(
                            _render_excel_opts(opts, cat_color, default_open=True),
                            unsafe_allow_html=True,
                        )

                    # TikTok suggestions — collapsed by default to avoid clutter
                    _MAP_SUGGEST_CATS = {"food", "market", "attraction", "nightlife", "museum", "beach"}
                    city = infer_city(day_obj)
                    if city and stop.get("category") in _MAP_SUGGEST_CATS:
                        suggestions = suggest_places(
                            city, stop.get("category", ""),
                            stop.get("lat"), stop.get("lon"),
                        )
                        if suggestions:
                            st.markdown(
                                _render_tiktok_opts(suggestions),
                                unsafe_allow_html=True,
                            )

    # Legend
    st.markdown("---")
    st.markdown("**Day Legend**")
    cols = st.columns(min(len(st.session_state.days), 3))
    for i, day in enumerate(st.session_state.days):
        color = DAY_COLORS[i % len(DAY_COLORS)]
        cols[i % 3].markdown(
            f'<span style="display:inline-block;width:12px;height:12px;'
            f'border-radius:50%;background:{color};margin-right:6px"></span>'
            f'<small>{day["day"]}</small>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════════════════════
# TIMELINE VIEW
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "📅 Timeline":
    st.markdown("## 📅 Day-by-Day Timeline")

    _SUGGEST_CATS = {"food", "market", "attraction", "nightlife", "museum", "beach"}

    for day_idx, day in enumerate(st.session_state.days):
        color = DAY_COLORS[day_idx % len(DAY_COLORS)]
        st.markdown(
            f'<div class="day-header" style="background:{color}">'
            f'📅 {day["day"]}</div>',
            unsafe_allow_html=True,
        )

        city = infer_city(day)

        for stop_idx, stop in enumerate(day["stops"]):
            cat_color = _CAT_COLORS.get(stop.get("category", "default"), "#888780")
            time_str = ""
            if stop.get("start") and stop.get("end"):
                time_str = f'<span class="stop-time">⏰ {stop["start"]} – {stop["end"]}</span> &nbsp;'
            elif stop.get("start"):
                time_str = f'<span class="stop-time">⏰ {stop["start"]}</span> &nbsp;'

            notes_str = f'<br><small style="color:#666">{stop["notes"]}</small>' if stop.get("notes") else ""
            coord_str = ""
            if stop.get("lat"):
                coord_str = f'<small style="color:#aaa;font-size:11px"> · {stop["lat"]:.3f}, {stop["lon"]:.3f}</small>'

            st.markdown(
                f'<div class="stop-card" style="border-left-color:{cat_color}">'
                f'{time_str}<b>{stop["name"]}</b>{coord_str}{notes_str}'
                f'</div>',
                unsafe_allow_html=True,
            )

            # Excel options — collapsed by default in Timeline (not too cluttered)
            opts = stop.get("options")
            if opts:
                st.markdown(
                    _render_excel_opts(opts, cat_color, default_open=False),
                    unsafe_allow_html=True,
                )

            # TikTok suggestions — collapsed by default
            if city and stop.get("category") in _SUGGEST_CATS:
                anchor_lat, anchor_lon, anchor_name = find_anchor(day, stop_idx)
                suggestions = suggest_places(city, stop.get("category", ""), anchor_lat, anchor_lon)
                if suggestions:
                    dist_note = f" · dari '{anchor_name}'" if anchor_name else ""
                    with st.expander(
                        f"💡 {len(suggestions)} opsi dari TikTok data{dist_note}",
                        expanded=False,
                    ):
                        st.markdown(_render_tiktok_opts(suggestions), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

    # Belum Masuk Rundown — unscheduled HCM places from the Excel options table
    _unscheduled = [
        {"name": "Gian Saigon",                    "rate": 4.7, "reviews": 104,  "note": "Restaurant/Cafe"},
        {"name": "Film Drugs",                      "rate": 4.9, "reviews": 496,  "note": "Photo/Creative space"},
        {"name": "Golden Lotus Healing Spa",        "rate": 4.5, "reviews": 2591, "note": "Spa HCM"},
        {"name": "Tinh Thuc Spa - Spa Quan 3",      "rate": 4.9, "reviews": 830,  "note": "Spa HCM"},
        {"name": "Rasa Buffet",                     "rate": 4.6, "reviews": 257,  "note": "Buffet restaurant"},
        {"name": "V Private Gym",                   "rate": 5.0, "reviews": 1166, "note": "Gym"},
        {"name": "The New Gym",                     "rate": 4.4, "reviews": 1073, "note": "Gym"},
    ]
    unscheduled_rows = ""
    for u in _unscheduled:
        maps_q   = u["name"].replace(" ", "+")
        maps_url = f"https://www.google.com/maps/search/?api=1&query={maps_q}+Ho+Chi+Minh+Vietnam"
        unscheduled_rows += (
            f'<div style="padding:6px 0;border-bottom:1px solid #eee;color:#1a202c">'
            f'<b style="color:#1a202c">{u["name"]}</b>'
            f' &nbsp;·&nbsp; <i style="color:#777">{u["note"]}</i>'
            f'<br><small style="color:#666">⭐ {u["rate"]} ({u["reviews"]:,} reviews)'
            f' &nbsp;·&nbsp; <a href="{maps_url}" target="_blank">📍 Google Maps</a>'
            f'</small></div>'
        )
    st.markdown(
        f'<details style="background:#f8f9fa;border-left:4px solid #888;'
        f'border-radius:0 8px 8px 0;padding:8px 14px;margin-top:8px">'
        f'<summary style="cursor:pointer;font-size:12.5px;color:#555;'
        f'font-weight:600;list-style:none">&#9654; 🗒️ Belum Masuk Rundown — '
        f'tempat di HCM yang belum dijadwalkan ({len(_unscheduled)})</summary>'
        f'<div style="margin-top:4px;font-size:12px;color:#888;margin-bottom:6px">'
        f'Ada di daftar Excel tapi belum masuk rundown — tambahkan ke hari HCM jika perlu.</div>'
        f'<div>{unscheduled_rows}</div>'
        f'</details>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# LOGIC CHECK
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "⚠️ Logic Check":
    st.markdown("## ⚠️ Itinerary Logic Check")
    st.markdown("Pengecekan otomatis: timing overlap, jarak geografis, durasi terlalu singkat.")

    issues = check_itinerary(st.session_state.days)

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]
    infos = [i for i in issues if i["severity"] == "info"]

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown(
            f'<div class="metric-card"><div class="metric-number" style="color:#E53E3E">{len(errors)}</div>'
            f'<div class="metric-label">🔴 Errors</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(
            f'<div class="metric-card"><div class="metric-number" style="color:#D69E2E">{len(warnings)}</div>'
            f'<div class="metric-label">🟡 Warnings</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(
            f'<div class="metric-card"><div class="metric-number" style="color:#3182CE">{len(infos)}</div>'
            f'<div class="metric-label">🔵 Info</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    for issue in issues:
        css_class = f"issue-{issue['severity']}"
        icon = severity_icon(issue["severity"])
        st.markdown(
            f'<div class="{css_class}">'
            f'{icon} <b>{issue["day"]}</b> — {issue["message"]}'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.divider()
    st.markdown("**Export Issues**")
    df = pd.DataFrame(issues)
    df.columns = ["Severity", "Day", "Message"]
    st.download_button(
        "⬇️ Download as CSV",
        data=df.to_csv(index=False),
        file_name="itinerary_issues.csv",
        mime="text/csv",
    )


# ══════════════════════════════════════════════════════════════════════════════
# EDIT ITINERARY
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "✏️ Edit Itinerary":
    st.markdown("## ✏️ Edit Itinerary")

    # Select day to edit
    day_names = [d["day"] for d in st.session_state.days]
    selected = st.selectbox("Select day to edit:", day_names)
    day_idx = day_names.index(selected)
    day = st.session_state.days[day_idx]

    st.markdown(f"### {day['day']}")

    # Edit stops
    updated_stops = []
    for i, stop in enumerate(day["stops"]):
        with st.expander(f"Stop {i+1}: {stop['name']}", expanded=False):
            cols = st.columns([3, 1, 1])
            name = cols[0].text_input("Name", value=stop["name"], key=f"name_{day_idx}_{i}")
            start = cols[1].text_input("Start", value=stop.get("start", ""), key=f"start_{day_idx}_{i}")
            end = cols[2].text_input("End", value=stop.get("end", ""), key=f"end_{day_idx}_{i}")

            cols2 = st.columns([2, 1, 1, 1])
            notes = cols2[0].text_input("Notes", value=stop.get("notes", ""), key=f"notes_{day_idx}_{i}")
            category = cols2[1].selectbox(
                "Category",
                ["attraction", "food", "market", "museum", "beach", "airport", "nightlife", "hotel", "transport"],
                index=["attraction", "food", "market", "museum", "beach", "airport", "nightlife", "hotel", "transport"].index(stop.get("category", "attraction"))
                if stop.get("category", "attraction") in ["attraction", "food", "market", "museum", "beach", "airport", "nightlife", "hotel", "transport"] else 0,
                key=f"cat_{day_idx}_{i}",
            )
            lat = cols2[2].number_input("Lat", value=stop.get("lat") or 0.0, format="%.4f", key=f"lat_{day_idx}_{i}")
            lon = cols2[3].number_input("Lon", value=stop.get("lon") or 0.0, format="%.4f", key=f"lon_{day_idx}_{i}")

            # Search coordinates button
            if st.button(f"🔍 Auto-search coordinates for '{name}'", key=f"search_{day_idx}_{i}"):
                with st.spinner(f"Searching '{name}'..."):
                    result = search_place(name)
                    if result and result.get("lat"):
                        st.success(f"Found: {result['display_name']}")
                        st.info(f"Lat: {result['lat']}, Lon: {result['lon']} — update the fields above manually.")
                    else:
                        st.warning("Place not found. Try a more specific name.")

            # Suggest from Popular Places — for undecided stops, or just to swap
            # a fixed pick for a better-rated / closer option in the same category.
            show_sugg = st.checkbox("💡 Show place suggestions from Popular Places", key=f"show_sugg_{day_idx}_{i}")
            if show_sugg:
                city = infer_city(day)
                if not city:
                    st.caption(
                        "Can't tell which city this day is in yet — no other stop "
                        "in this day has coordinates to infer from."
                    )
                else:
                    cat_options = list(CATEGORY_MAP.keys())
                    sugg_cat = st.selectbox(
                        "Category to search",
                        cat_options,
                        index=cat_options.index(category) if category in cat_options else 0,
                        key=f"sugg_cat_{day_idx}_{i}",
                    )
                    anchor_lat, anchor_lon, anchor_name = find_anchor(day, i)
                    suggestions = suggest_places(city, sugg_cat, anchor_lat, anchor_lon)
                    if not suggestions:
                        st.caption(f"No {sugg_cat} places found in {city} in the Popular Places data.")
                    else:
                        if anchor_lat is None:
                            st.caption("No nearby stop with coordinates yet — ranked by rating instead of distance.")
                        else:
                            st.caption(f"Distance below is measured from the nearest scheduled stop: **{anchor_name}** (not always the hotel).")
                        st.caption(f"{len(suggestions)} option(s) found.")
                        for s_idx, s in enumerate(suggestions):
                            row = st.columns([3, 1.2, 1, 1])
                            label = s["name"] + (f" · {s['district']}" if s["district"] else "")
                            row[0].markdown(label + (f" ⭐{s['rating']}" if s["rating"] else ""))
                            row[1].caption(f"{s['dist_km']:.1f} km away" if s["dist_km"] is not None else "—")
                            row[2].markdown(f"[📍 Maps]({s['maps_url']})")
                            if row[3].button("Use this", key=f"use_{day_idx}_{i}_{s_idx}"):
                                st.session_state[f"name_{day_idx}_{i}"] = s["name"]
                                st.session_state[f"cat_{day_idx}_{i}"] = sugg_cat
                                if s["lat"] is not None:
                                    st.session_state[f"lat_{day_idx}_{i}"] = s["lat"]
                                    st.session_state[f"lon_{day_idx}_{i}"] = s["lon"]
                                st.rerun()

            updated_stop = {
                "name": name, "start": start, "end": end,
                "notes": notes, "category": category,
                "lat": lat if lat != 0.0 else None,
                "lon": lon if lon != 0.0 else None,
            }
            if stop.get("options"):
                updated_stop["options"] = stop["options"]
            updated_stops.append(updated_stop)

    if st.button("💾 Save Changes", type="primary"):
        st.session_state.days[day_idx]["stops"] = updated_stops
        if save_itinerary(st.session_state.days):
            st.success("Itinerary updated and saved to Google Sheets!")
        else:
            st.success("Itinerary updated (local only — Sheets not configured).")
        st.rerun()

    st.divider()
    st.markdown("### ➕ Add New Stop")
    with st.form("add_stop"):
        cols = st.columns([3, 1, 1])
        new_name = cols[0].text_input("Place name")
        new_start = cols[1].text_input("Start time (HH:MM)")
        new_end = cols[2].text_input("End time (HH:MM)")
        new_notes = st.text_input("Notes")
        new_cat = st.selectbox("Category", ["attraction", "food", "market", "museum", "beach", "airport", "nightlife", "hotel", "transport"])
        submitted = st.form_submit_button("Add Stop")
        if submitted and new_name:
            with st.spinner(f"Looking up '{new_name}'..."):
                place = search_place(new_name)
            new_stop = {
                "name": new_name, "start": new_start, "end": new_end,
                "notes": new_notes, "category": new_cat,
                "lat": place["lat"] if place else None,
                "lon": place["lon"] if place else None,
            }
            st.session_state.days[day_idx]["stops"].append(new_stop)
            save_itinerary(st.session_state.days)
            st.success(f"Added '{new_name}'" + (f" at {place['lat']:.4f}, {place['lon']:.4f}" if place and place.get("lat") else " (coordinates not found)"))
            st.rerun()


# ══════════════════════════════════════════════════════════════════════════════
# PLACE SEARCH
# ══════════════════════════════════════════════════════════════════════════════
elif tab == "🔍 Place Search":
    st.markdown("## 🔍 Place Search")
    st.markdown("Search any place in Vietnam using OpenStreetMap (Nominatim) — free, no API key.")

    with st.form("place_search"):
        col1, col2 = st.columns([4, 1])
        query = col1.text_input("Search place", placeholder="e.g. Hoi An Ancient Town, Ba Na Hills Da Nang")
        country = col2.selectbox("Country", ["vn", "id", "th", "sg", "my"])
        search_btn = st.form_submit_button("🔍 Search")

    if search_btn and query:
        with st.spinner(f"Searching '{query}'..."):
            result = search_place(query, country)

        if result and result.get("lat"):
            st.success(f"**{result['name']}** found!")

            cols = st.columns(3)
            cols[0].metric("Latitude", f"{result['lat']:.5f}")
            cols[1].metric("Longitude", f"{result['lon']:.5f}")
            cols[2].metric("Type", result.get("type", "—").title())

            st.info(f"📍 {result['display_name']}")

            # Mini map for this result
            import folium
            from streamlit_folium import st_folium as sf

            mini = folium.Map(location=[result["lat"], result["lon"]], zoom_start=15, tiles="OpenStreetMap")
            folium.Marker(
                [result["lat"], result["lon"]],
                tooltip=result["name"],
                icon=folium.Icon(color="red", icon="star", prefix="fa"),
            ).add_to(mini)
            sf(mini, width="100%", height=300, key="mini_map")

            # Add to itinerary button
            st.markdown("---")
            st.markdown("**Add this place to itinerary:**")
            col1, col2, col3 = st.columns(3)
            target_day = col1.selectbox("Day", [d["day"] for d in st.session_state.days])
            add_start = col2.text_input("Start time", "09:00")
            add_end = col3.text_input("End time", "10:00")
            add_notes = st.text_input("Notes (optional)")
            add_cat = st.selectbox("Category", ["attraction", "food", "market", "museum", "beach", "airport", "nightlife", "hotel", "transport"])

            if st.button("➕ Add to Itinerary", type="primary"):
                day_idx = [d["day"] for d in st.session_state.days].index(target_day)
                st.session_state.days[day_idx]["stops"].append({
                    "name": result["name"],
                    "start": add_start,
                    "end": add_end,
                    "notes": add_notes,
                    "category": add_cat,
                    "lat": result["lat"],
                    "lon": result["lon"],
                })
                save_itinerary(st.session_state.days)
                st.success(f"Added '{result['name']}' to {target_day}!")
        else:
            st.warning("Place not found. Try a more specific name or add the country/city.")
