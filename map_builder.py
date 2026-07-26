"""
map_builder.py — Build interactive Folium maps from itinerary data
Uses free OpenStreetMap tiles — no API key needed.
"""

import folium
from folium import plugins, MacroElement
from jinja2 import Template

# Color palette per day index
DAY_COLORS = ["#E8593C", "#1D9E75", "#378ADD", "#7F77DD", "#EF9F27", "#D85A30", "#0F6E56"]
ICON_COLORS = ["red", "green", "blue", "purple", "orange", "darkred", "darkgreen"]

# Option pin colors by category.
# Deliberately chosen to NOT overlap with any day color (red/green/blue/purple/orange/darkred/darkgreen)
# so option pins always look distinct from the confirmed-stop markers on any day.
OPT_CAT_COLORS = {
    "food":       "pink",       # warm but clearly different from red/orange
    "attraction": "beige",      # neutral, different from orange/blue
    "market":     "lightblue",  # cool, different from blue (which is darker)
    "beach":      "cadetblue",  # teal, different from all day colors
    "nightlife":  "lightgray",  # neutral, different from purple
    "museum":     "white",      # pale, different from everything
    "hotel":      "lightgreen", # different from green (which is darker)
    "transport":  "gray",
    "airport":    "gray",
    "default":    "lightgray",
}

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


class LayerToggle(MacroElement):
    """Injects All / None buttons + responsive max-height CSS into the layer control."""

    def __init__(self):
        super().__init__()
        self._template = Template("""
            {% macro script(this, kwargs) %}
            (function () {
                /* Cap the expanded layer control so it never covers the whole map on mobile.
                   Also show a small "Layers" label below the collapsed icon so users know
                   what it does without hovering. */
                var s = document.createElement('style');
                s.innerHTML =
                    '.leaflet-control-layers-expanded {'
                    + '  max-height: min(220px, 45vh);'
                    + '  overflow-y: auto;'
                    + '}'
                    + '.leaflet-control-layers:not(.leaflet-control-layers-expanded) {'
                    + '  padding-bottom: 3px;'
                    + '}'
                    + '.leaflet-control-layers:not(.leaflet-control-layers-expanded)::after {'
                    + '  content: "Legend";'
                    + '  display: block;'
                    + '  font-size: 9px;'
                    + '  font-weight: 700;'
                    + '  letter-spacing: 0.4px;'
                    + '  color: #555;'
                    + '  text-align: center;'
                    + '  padding: 0 4px;'
                    + '}';
                document.head.appendChild(s);

                function tryAdd() {
                    var ov = document.querySelector('.leaflet-control-layers-overlays');
                    if (!ov || ov.querySelector('.lc-tb')) return false;
                    var d = document.createElement('div');
                    d.className = 'lc-tb';
                    d.style.cssText = 'display:flex;gap:4px;padding:2px 0 6px;margin-bottom:3px;border-bottom:1px solid #ccc';
                    d.innerHTML =
                        '<button onclick="document.querySelectorAll(\\'.leaflet-control-layers-overlays input\\').forEach(function(c){if(!c.checked)c.click()})"'
                        + ' style="flex:1;font-size:11px;padding:2px 5px;cursor:pointer;border:1px solid #aaa;border-radius:3px;background:#f0f0f0">All</button>'
                        + '<button onclick="document.querySelectorAll(\\'.leaflet-control-layers-overlays input\\').forEach(function(c){if(c.checked)c.click()})"'
                        + ' style="flex:1;font-size:11px;padding:2px 5px;cursor:pointer;border:1px solid #aaa;border-radius:3px;background:#f0f0f0">None</button>';
                    ov.insertBefore(d, ov.firstChild);
                    return true;
                }
                var n = 0, t = setInterval(function () { if (tryAdd() || ++n > 40) clearInterval(t); }, 250);
            })();
            {% endmacro %}
        """)


class CityJump(MacroElement):
    """Adds Da Nang / Hoi An / HCM city-jump buttons to the top-left of the map."""

    def __init__(self):
        super().__init__()
        self._template = Template("""
            {% macro script(this, kwargs) %}
            (function () {
                var map = {{ this._parent.get_name() }};
                var CityCtrl = L.Control.extend({
                    options: { position: 'topleft' },
                    onAdd: function () {
                        var wrap = L.DomUtil.create('div');
                        wrap.style.cssText = 'display:flex;flex-direction:column;gap:3px;margin-top:4px';
                        var cities = [
                            ['Da Nang', 16.068, 108.222, 13],
                            ['Hoi An',  15.877, 108.328, 14],
                            ['HCM',     10.777, 106.700, 13],
                        ];
                        cities.forEach(function (ct) {
                            var btn = L.DomUtil.create('button', '', wrap);
                            btn.textContent = ct[0];
                            btn.style.cssText =
                                'display:block;width:100%;padding:4px 8px;'
                                + 'font-size:11px;font-weight:600;line-height:1.2;'
                                + 'background:white;border:1px solid #aaa;'
                                + 'border-radius:4px;cursor:pointer;'
                                + 'box-shadow:0 1px 3px rgba(0,0,0,.25);'
                                + 'white-space:nowrap;';
                            L.DomEvent.on(btn, 'click', L.DomEvent.stop);
                            L.DomEvent.on(btn, 'click', function () {
                                map.setView([ct[1], ct[2]], ct[3]);
                            });
                        });
                        return wrap;
                    }
                });
                new CityCtrl().addTo(map);
            })();
            {% endmacro %}
        """)


def get_icon(category: str, day_idx: int) -> folium.Icon:
    icon_name = CATEGORY_ICONS.get(category.lower(), CATEGORY_ICONS["default"])
    color = ICON_COLORS[day_idx % len(ICON_COLORS)]
    return folium.Icon(color=color, icon=icon_name, prefix="fa")


def build_map(days: list[dict], center: list = None) -> folium.Map:
    # Compute center from all valid coordinates
    all_lats = [s["lat"] for d in days for s in d["stops"] if s.get("lat")]
    all_lons = [s["lon"] for d in days for s in d["stops"] if s.get("lon")]

    if not all_lats:
        center = [16.0544, 108.2022]  # Default: Da Nang
    else:
        center = [all_lats[0], all_lons[0]]  # First geocoded stop (Da Nang when all days shown)

    m = folium.Map(
        location=center,
        zoom_start=12,
        tiles="OpenStreetMap",
    )

    plugins.Fullscreen().add_to(m)

    for day_idx, day in enumerate(days):
        day_label = day.get("day", f"Day {day_idx + 1}")
        color = DAY_COLORS[day_idx % len(DAY_COLORS)]

        feature_group = folium.FeatureGroup(name=f"📅 {day_label}")
        valid_stops = [s for s in day["stops"] if s.get("lat") and s.get("lon")]

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

        for stop_idx, stop in enumerate(valid_stops):
            category = stop.get("category", "default")
            icon_name = CATEGORY_ICONS.get(category.lower(), CATEGORY_ICONS["default"])

            time_str = ""
            if stop.get("start") and stop.get("end"):
                time_str = f"<b>⏰ {stop['start']} – {stop['end']}</b><br>"
            elif stop.get("start"):
                time_str = f"<b>⏰ {stop['start']}</b><br>"

            notes_str = f"<p style='color:#666;font-size:12px;margin:4px 0 0'>{stop['notes']}</p>" if stop.get("notes") else ""

            img_html = ""
            header_radius = "6px 6px 0 0"
            if stop.get("img_url"):
                img_html = (
                    f'<img src="{stop["img_url"]}" '
                    f'style="width:100%;height:110px;object-fit:cover;'
                    f'border-radius:6px 6px 0 0;display:block" '
                    f'onerror="this.remove()">'
                )
                header_radius = "0"

            popup_html = f"""
            <div style="font-family:'Segoe UI',sans-serif;min-width:180px;max-width:240px">
                {img_html}
                <div style="background:{color};color:white;padding:8px 10px;border-radius:{header_radius};font-weight:600;font-size:13px">
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

    # --- Option place pins (off by default, colored by category) ---
    opts_group = folium.FeatureGroup(name="📋 Opsi Terlampir", show=False)
    for day_idx, day in enumerate(days):
        day_color = DAY_COLORS[day_idx % len(DAY_COLORS)]
        for stop in day["stops"]:
            cat = stop.get("category", "default")
            pin_color = OPT_CAT_COLORS.get(cat, OPT_CAT_COLORS["default"])
            opts = stop.get("options") or []
            for opt in opts:
                if not (opt.get("lat") and opt.get("lon")):
                    continue
                rate_str = f"⭐ {opt['rate']}" if opt.get("rate") else ""
                rev_str = f"({int(opt['reviews']):,} ulasan)" if opt.get("reviews") else ""
                note_str = f"<br><i style='color:#888'>{opt['note']}</i>" if opt.get("note") else ""
                meta = " &nbsp;·&nbsp; ".join(filter(None, [rate_str, rev_str]))
                maps_q = opt["name"].replace(" ", "+")
                maps_url = f"https://www.google.com/maps/search/?api=1&query={maps_q}+Vietnam"

                opt_img_html = ""
                opt_header_radius = "6px 6px 0 0"
                if opt.get("img_url"):
                    opt_img_html = (
                        f'<img src="{opt["img_url"]}" '
                        f'style="width:100%;height:100px;object-fit:cover;'
                        f'border-radius:6px 6px 0 0;display:block" '
                        f'onerror="this.remove()">'
                    )
                    opt_header_radius = "0"

                popup_html = f"""
                <div style="font-family:'Segoe UI',sans-serif;min-width:160px;max-width:220px">
                    {opt_img_html}
                    <div style="background:{day_color};color:white;padding:6px 10px;border-radius:{opt_header_radius};font-weight:600;font-size:12px">
                        📋 {opt['name']}
                    </div>
                    <div style="padding:6px 10px;border:1px solid #eee;border-radius:0 0 6px 6px;font-size:11px">
                        <span style="color:#555">Opsi untuk: <b>{stop['name']}</b></span><br>
                        <span style="color:#444">{meta}</span>{note_str}<br>
                        <a href="{maps_url}" target="_blank">📍 Google Maps</a>
                    </div>
                </div>
                """
                folium.Marker(
                    location=[opt["lat"], opt["lon"]],
                    popup=folium.Popup(popup_html, max_width=240),
                    tooltip=f"📋 {opt['name']} ({stop['name']})",
                    icon=folium.Icon(
                        color=pin_color,
                        icon="bookmark",
                        prefix="fa",
                    ),
                ).add_to(opts_group)
    opts_group.add_to(m)

    folium.LayerControl(collapsed=True).add_to(m)
    LayerToggle().add_to(m)
    CityJump().add_to(m)
    return m
