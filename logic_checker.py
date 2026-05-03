"""
logic_checker.py — Itinerary logic analysis
Checks for timing issues, geographic inefficiencies, and missing info.
"""

from datetime import datetime, time
from math import radians, sin, cos, sqrt, atan2


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Calculate distance in km between two coordinates."""
    R = 6371
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def parse_time(t) -> datetime | None:
    """Parse a time string like '09:00' or '2:30 PM' into a datetime."""
    if t is None:
        return None
    if isinstance(t, datetime):
        return t
    formats = ["%H:%M", "%I:%M %p", "%I:%M%p"]
    for fmt in formats:
        try:
            return datetime.strptime(str(t).strip(), fmt)
        except ValueError:
            continue
    return None


def check_itinerary(days: list[dict]) -> list[dict]:
    """
    Analyze a list of days for issues.
    Each day: {"day": str, "stops": [{"name": str, "start": str, "end": str, "lat": float, "lon": float, "notes": str}]}
    Returns list of issues: {"severity": "warning"|"error"|"info", "day": str, "message": str}
    """
    issues = []

    for day in days:
        day_label = day.get("day", "Unknown day")
        stops = day.get("stops", [])

        for i, stop in enumerate(stops):
            start = parse_time(stop.get("start"))
            end = parse_time(stop.get("end"))

            # Check for missing times
            if not stop.get("start"):
                issues.append({"severity": "info", "day": day_label,
                                "message": f"'{stop['name']}' tidak ada waktu mulai."})

            # Check end before start
            if start and end and end < start:
                issues.append({"severity": "error", "day": day_label,
                                "message": f"'{stop['name']}': waktu selesai ({stop['end']}) lebih awal dari waktu mulai ({stop['start']})."})

            # Check very short durations (< 15 min)
            if start and end:
                duration_min = (end - start).seconds / 60
                if 0 < duration_min < 15:
                    issues.append({"severity": "warning", "day": day_label,
                                   "message": f"'{stop['name']}': durasi hanya {int(duration_min)} menit — mungkin terlalu singkat?"})

            # Check gap / overlap with next stop
            if i < len(stops) - 1:
                next_stop = stops[i + 1]
                next_start = parse_time(next_stop.get("start"))

                if end and next_start:
                    gap_min = (next_start - end).seconds / 60
                    # Negative gap = overlap
                    if gap_min < 0 and abs(gap_min) > 5:
                        issues.append({"severity": "error", "day": day_label,
                                       "message": f"'{stop['name']}' dan '{next_stop['name']}' overlap {abs(int(gap_min))} menit."})

                # Geographic jump check
                lat1, lon1 = stop.get("lat"), stop.get("lon")
                lat2, lon2 = next_stop.get("lat"), next_stop.get("lon")
                if all(v is not None for v in [lat1, lon1, lat2, lon2]):
                    dist = haversine_km(lat1, lon1, lat2, lon2)
                    # Estimate drive time: ~30 km/h in city traffic
                    est_drive_min = (dist / 30) * 60
                    if end and next_start:
                        gap_min = (next_start - end).seconds / 60
                        if gap_min >= 0 and est_drive_min > gap_min + 10:
                            issues.append({
                                "severity": "warning",
                                "day": day_label,
                                "message": (
                                    f"'{stop['name']}' → '{next_stop['name']}': "
                                    f"jarak ~{dist:.1f} km, estimasi ~{int(est_drive_min)} menit berkendara, "
                                    f"tapi gap waktu hanya {int(gap_min)} menit."
                                ),
                            })

    if not issues:
        issues.append({"severity": "info", "day": "All days",
                        "message": "Tidak ada masalah besar ditemukan di itinerary kamu! ✅"})

    return issues
