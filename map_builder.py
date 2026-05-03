"""
map_builder.py — Build interactive Folium maps from itinerary data
Uses free OpenStreetMap tiles — no API key needed.
"""

import folium
from folium import plugins

# Color palette per day index
DAY_COLORS = ["#E8593C", "#1D9E75", "#378ADD", "#7F77DD", "#EF9F27", "#D85A30", "#0F6E56"]
ICON_COLORS = ["red", "green", "blue", "purple", "orange", "darkred", "darkgreen"]

CATEGORY_ICONS = {
    "flight": "plane",
    "food": "cutlery",
    "hotel": "home",
    "attraction": "star",
    "market": "shopping-cart",
    "beach": "tint",
    "transport": "car",
    "museum": "university",
    "nightlife": "music",
    "airport": "plane",
    "default": "map-marker",
}


def get_icon(category: str, day_idx: int) -> folium.Icon:
    icon_name = CATEGORY_ICONS.get(category.lower(), CATEGORY_ICONS["default"])
    color = ICON_COLORS[day_idx % len(ICON_COLORS)]
    return folium.Icon(color=color, icon=icon_name, prefix="fa")


def build_map(days: list[dict], center: list = None) -> folium.Map:
    """
    Build a Folium map from itinerary days.

    Each day: {
        "day": str,
        "stops": [{
            "name": str, "lat": float, "lon": float,
            "start": str, "end": str, "notes": str,
            "category": str  # optional
        }]
    }
    """
    # Compute center from all valid coordinates
    all_lats = [s["lat"] for d in days for s in d["stops"] if s.get("lat")]
    all_lons = [s["lon"] for d in days for s in d["stops"] if s.get("lon")]

    if not all_lats:
        center = [16.0544, 108.2022]  # Default: Da Nang
    else:
        center = [sum(all_lats) / len(all_lats), sum(all_lons) / len(all_lons)]

    m = folium.Map(
        location=center,
        zoom_start=12,
        tiles="OpenStreetMap",
    )

    # Add a fullscreen button
    plugins.Fullscreen().add_to(m)

    # Layer control — one layer per day
    for day_idx, day in enumerate(days):
        day_label = day.get("day", f"Day {day_idx + 1}")
        color = DAY_COLORS[day_idx % len(DAY_COLORS)]

        feature_group = folium.FeatureGroup(name=f"📅 {day_label}")
        valid_stops = [s for s in day["stops"] if s.get("lat") and s.get("lon")]

        # Draw route line between stops
        if len(valid_stops) >= 2:
            route_coords = [[s["lat"], s["lon"]] for s in valid_stops]
            folium.PolyLine(
                route_coords,
                color=color,
                weight=3,
                opacity=0.7,
                dash_array="8 4",
                tooltip=day_label,
            ).add_to(feature_group)

        # Draw markers for each stop
        for stop_idx, stop in enumerate(valid_stops):
            category = stop.get("category", "default")
            icon_name = CATEGORY_ICONS.get(category.lower(), CATEGORY_ICONS["default"])

            # Build popup HTML
            time_str = ""
            if stop.get("start") and stop.get("end"):
                time_str = f"<b>⏰ {stop['start']} – {stop['end']}</b><br>"
            elif stop.get("start"):
                time_str = f"<b>⏰ {stop['start']}</b><br>"

            notes_str = f"<p style='color:#666;font-size:12px;margin:4px 0 0'>{stop['notes']}</p>" if stop.get("notes") else ""

            popup_html = f"""
            <div style="font-family:'Segoe UI',sans-serif;min-width:180px;max-width:240px">
                <div style="background:{color};color:white;padding:8px 10px;border-radius:6px 6px 0 0;font-weight:600;font-size:13px">
                    {stop_idx + 1}. {stop['name']}
                </div>
                <div style="padding:8px 10px;border:1px solid #eee;border-radius:0 0 6px 6px">
                    {time_str}
                    <span style="font-size:11px;color:#888">{day_label}</span>
                    {notes_str}
                </div>
            </div>
            """

            folium.Marker(
                location=[stop["lat"], stop["lon"]],
                popup=folium.Popup(popup_html, max_width=260),
                tooltip=f"{stop_idx + 1}. {stop['name']}",
                icon=folium.Icon(
                    color=ICON_COLORS[day_idx % len(ICON_COLORS)],
                    icon=icon_name,
                    prefix="fa",
                ),
            ).add_to(feature_group)

            # Number circle label on map
            folium.Marker(
                location=[stop["lat"], stop["lon"]],
                icon=folium.DivIcon(
                    html=f"""<div style="
                        background:{color};color:white;
                        width:20px;height:20px;border-radius:50%;
                        display:flex;align-items:center;justify-content:center;
                        font-size:11px;font-weight:700;
                        border:2px solid white;
                        box-shadow:0 2px 4px rgba(0,0,0,.3);
                        margin-top:-30px;margin-left:10px;
                    ">{stop_idx + 1}</div>""",
                    icon_size=(20, 20),
                    icon_anchor=(0, 0),
                ),
            ).add_to(feature_group)

        feature_group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    return m
