# 🗺️ Trip Planner — Streamlit App

Interactive itinerary planner with map, logic checker, and timeline view.
Similar to Claude's built-in travel tools — **100% free**, no paid API needed.

## Features

| Feature | How it works |
|---|---|
| 🗺️ Interactive Map | Folium + OpenStreetMap (CartoDB tiles) |
| 🔍 Place Search | Nominatim (OpenStreetMap) — no API key |
| ⚠️ Logic Check | Custom distance & timing analyzer |
| 📅 Timeline | Color-coded day-by-day schedule |
| ✏️ Edit Itinerary | Add/edit stops with auto coordinate lookup |

## Setup

### 1. Clone / download this folder

```bash
cd trip_planner
```

### 2. Create virtual environment (recommended)

```bash
python -m venv venv
source venv/bin/activate        # Mac/Linux
venv\Scripts\activate           # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
streamlit run app.py
```

App opens at `http://localhost:8501`

---

## Deploy to Streamlit Cloud (free)

1. Push this folder to a GitHub repo
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set main file: `app.py`
5. Deploy — it's free for public repos

## Deploy to Vercel (optional)

Streamlit doesn't run natively on Vercel (Vercel is for Node/static).
For Vercel, you'd need to rewrite this in Next.js + React.
Streamlit Cloud is the easier free option.

---

## Customizing for your own trip

Edit the `st.session_state.days` block in `app.py` to replace the
Vietnam 2026 demo data with your own itinerary.

Each stop format:
```python
{
    "name": "Place Name",
    "start": "09:00",         # HH:MM format
    "end": "11:00",
    "notes": "Optional notes",
    "category": "attraction", # attraction | food | market | museum |
                              # beach | airport | nightlife | hotel | transport
    "lat": 10.773,            # latitude  (use Place Search tab to find)
    "lon": 106.698,           # longitude
}
```

## APIs Used

| API | Cost | Key needed? |
|---|---|---|
| Nominatim (OpenStreetMap) | Free | No |
| CartoDB Map Tiles | Free | No |
| Folium (map library) | Free (Python) | No |

**Note:** Nominatim has a rate limit of 1 request/second.
For production with many users, consider caching results or
switching to Google Places API ($200/month free credit).

## File Structure

```
trip_planner/
├── app.py              # Main Streamlit app
├── places.py           # Place search via Nominatim
├── map_builder.py      # Folium map construction
├── logic_checker.py    # Itinerary timing & geo analysis
├── requirements.txt    # Python dependencies
└── README.md
```
