"""Geospatial helpers (Module D).

Coordinate validation, distance maths and location parsing. Coordinates are
only ever read from the database - locations are never invented. Map payloads
are assembled by the admin routes from these helpers plus the stored rows.
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
