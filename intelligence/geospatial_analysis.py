"""Geospatial helpers (Module D).

Coordinate validation, distance maths and construction of the payloads the
Leaflet map consumes. Coordinates are only ever read from the database -
locations are never invented.
"""

import math
import re

EARTH_RADIUS_KM = 6371.0088

# Pattern produced by SmartWaste 1.x browser geolocation fallback:
# "Latitude: 28.61390, Longitude: 77.20900"
LEGACY_COORD_RE = re.compile(
    r"latitude\s*:\s*(-?\d+(?:\.\d+)?)\s*,?\s*longitude\s*:\s*(-?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two WGS84 points, in kilometres."""
    if None in (lat1, lon1, lat2, lon2):
        return None
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (math.sin(d_phi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2)
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def valid_coords(lat, lon):
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return False
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        return False
    if lat == 0.0 and lon == 0.0:
        return False  # null island - not a real complaint location
    return True


def inside_bounds(lat, lon, bounds):
    if not bounds:
        return True
    min_lat, min_lon, max_lat, max_lon = bounds
    return min_lat <= float(lat) <= max_lat and min_lon <= float(lon) <= max_lon


def parse_legacy_coordinates(location_text):
    """Recover coordinates SmartWaste 1.x wrote into the location string."""
    if not location_text:
        return None
    match = LEGACY_COORD_RE.search(location_text)
    if not match:
        return None
    lat, lon = float(match.group(1)), float(match.group(2))
    return (lat, lon) if valid_coords(lat, lon) else None


def area_from_location(location_text):
    """Area label = first comma-separated segment of the free-text location."""
    if not location_text:
        return None
    area = str(location_text).split(",")[0].strip()
    return area or None


def marker_payload(report, include_ai=True):
    payload = {
        "id": report["id"],
        "tracking_id": report["tracking_id"] or f"SW-{report['id']:05d}",
        "lat": float(report["latitude"]),
        "lng": float(report["longitude"]),
        "location": report["location"],
        "area": report["area"],
        "category": report["waste_type"],
        "status": report["status"],
        "priority": report["priority"],
        "urgency": report["ai_urgency"],
        "created_at": report["created_at"],
    }
    if include_ai:
        payload["ai_category"] = report["ai_category"]
        payload["ai_confidence"] = report["ai_confidence"]
        payload["needs_review"] = bool(report["ai_needs_review"])
    return payload


def cluster_payload(cluster, cluster_reports=None):
    return {
        "label": cluster["label"],
        "lat": cluster["centroid_lat"],
        "lng": cluster["centroid_lng"],
        "count": cluster["complaint_count"],
        "unresolved": cluster["unresolved_count"],
        "top_category": cluster["top_category"],
        "report_ids": cluster["report_ids"],
        "computed_at": cluster["computed_at"],
        "reports": cluster_reports or [],
    }


def nearest_cluster(lat, lon, clusters):
    """Return (cluster, distance_km) of the closest stored cluster centroid."""
    if not valid_coords(lat, lon) or not clusters:
        return None, None
    best, best_distance = None, None
    for cluster in clusters:
        distance = haversine_km(lat, lon, cluster["centroid_lat"], cluster["centroid_lng"])
        if distance is None:
            continue
        if best_distance is None or distance < best_distance:
            best, best_distance = cluster, distance
    return best, best_distance


def describe_filters(filters):
    """Human-readable summary of active map filters (for audit log detail)."""
    active = {k: v for k, v in (filters or {}).items() if v}
    return ", ".join(f"{k}={v}" for k, v in active.items()) or "none"
