"""DBSCAN-based complaint hotspot detection (Module D).

Parameters (all configurable through ``config.py`` / environment):

* ``DBSCAN_EPS_METERS`` (default 400 m) - neighbourhood radius. Two complaints
  belong to the same hotspot when they are reachable within this distance.
  sklearn's ``haversine`` metric is used, so eps is converted from metres to
  radians (eps / earth radius) and distances are true great-circle distances.
* ``DBSCAN_MIN_SAMPLES`` (default 3) - a hotspot needs at least this many
  complaints inside its radius; fewer points become noise.
* ``CITY_BOUNDS`` (optional) - bounding box used to discard gross geographic
  outliers (e.g. a mistyped coordinate in another country). Invalid or missing
  coordinates are always excluded and reported, never invented.

The table ``complaint_clusters`` stores the result of the most recent run so
the dashboard can show cluster statistics without recomputing.
"""

import json
import math
from collections import Counter
from datetime import datetime, timezone

import numpy as np
from sklearn.cluster import DBSCAN

from config import (
    CITY_BOUNDS,
    DBSCAN_EPS_METERS,
    DBSCAN_MIN_SAMPLES,
    HOTSPOT_MIN_COMPLAINTS,
)
from db import get_connection, dumps, loads
from intelligence.geospatial_analysis import (
    EARTH_RADIUS_KM,
    haversine_km,
    inside_bounds,
    valid_coords,
)

EARTH_RADIUS_M = EARTH_RADIUS_KM * 1000.0
UNRESOLVED_STATUSES = ("Submitted", "Under Review", "Assigned", "In Progress", "Pending")


def _fetch_points(con):
    rows = con.execute(
        "SELECT id, tracking_id, waste_type, status, latitude, longitude "
        "FROM reports "
        "WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
    ).fetchall()
    valid, invalid = [], []
    outliers = []
    for row in rows:
        if not valid_coords(row["latitude"], row["longitude"]):
            invalid.append(row["id"])
            continue
        if not inside_bounds(row["latitude"], row["longitude"], CITY_BOUNDS):
            outliers.append(row["id"])
            continue
        valid.append(row)
    return valid, invalid, outliers


def run_clustering(eps_meters=None, min_samples=None, persist=True, con=None):
    """Cluster every geocoded complaint. Returns a JSON-safe summary."""
    eps_meters = float(eps_meters or DBSCAN_EPS_METERS)
    min_samples = int(min_samples or DBSCAN_MIN_SAMPLES)
    own_con = con is None
    if own_con:
        con = get_connection()
    try:
        points, invalid, outliers = _fetch_points(con)
        summary = {
            "eps_meters": eps_meters,
            "min_samples": min_samples,
            "metric": "haversine",
            "points_with_coordinates": len(points),
            "excluded_invalid_coordinates": len(invalid),
            "excluded_outliers": len(outliers),
            "n_clusters": 0,
            "clustered_points": 0,
            "noise_points": 0,
            "clusters": [],
            "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "insufficient": False,
            "notes": [],
        }

        if len(points) < max(min_samples, 2):
            summary["insufficient"] = True
            summary["notes"].append(
                f"Only {len(points)} geocoded complaint(s) available; DBSCAN "
                f"requires at least {min_samples} points to form a cluster."
            )
            if persist:
                _persist(con, summary, clusters=[])
            return summary

        coords = np.array(
            [[math.radians(p["latitude"]), math.radians(p["longitude"])] for p in points]
        )
        eps_radians = eps_meters / EARTH_RADIUS_M
        model = DBSCAN(
            eps=eps_radians, min_samples=min_samples,
            metric="haversine", algorithm="ball_tree",
        )
        labels = model.fit_predict(coords)

        noise = int(np.sum(labels == -1))
        summary["noise_points"] = noise
        summary["clustered_points"] = int(len(labels) - noise)

        grouped = {}
        for point, label in zip(points, labels):
            if label == -1:
                continue
            grouped.setdefault(int(label), []).append(point)

        clusters = []
        ordered = sorted(grouped.items(), key=lambda kv: (-len(kv[1]), kv[0]))
        for index, (dbscan_label, members) in enumerate(ordered, start=1):
            lats = [m["latitude"] for m in members]
            lons = [m["longitude"] for m in members]
            centroid_lat = float(np.mean(lats))
            centroid_lng = float(np.mean(lons))
            radius_km = max(
                haversine_km(m["latitude"], m["longitude"], centroid_lat, centroid_lng) or 0
                for m in members
            )
            categories = Counter(m["waste_type"] for m in members)
            unresolved = sum(1 for m in members if m["status"] in UNRESOLVED_STATUSES)
            clusters.append({
                "label": f"H{index}",
                "dbscan_label": dbscan_label,
                "centroid_lat": round(centroid_lat, 6),
                "centroid_lng": round(centroid_lng, 6),
                "complaint_count": len(members),
                "unresolved_count": unresolved,
                "top_category": categories.most_common(1)[0][0],
                "radius_km": round(radius_km, 3),
                "report_ids": [m["id"] for m in members],
                "tracking_ids": [m["tracking_id"] for m in members if m["tracking_id"]],
                "categories": dict(categories),
            })

        summary["n_clusters"] = len(clusters)
        summary["clusters"] = clusters
        if not clusters:
            summary["notes"].append(
                f"No cluster reached the minimum of {min_samples} complaints "
                f"within {eps_meters:.0f} m of each other."
            )
        recurring = [c for c in clusters if c["complaint_count"] >= HOTSPOT_MIN_COMPLAINTS]
        summary["recurring_count"] = len(recurring)

        if persist:
            _persist(con, summary, clusters)
        return summary
    finally:
        if own_con:
            con.close()


def _persist(con, summary, clusters):
    """Replace stored clusters with the latest run (table = latest snapshot)."""
    params = {
        "eps_meters": summary["eps_meters"],
        "min_samples": summary["min_samples"],
        "metric": summary["metric"],
        "points_with_coordinates": summary["points_with_coordinates"],
        "excluded_invalid_coordinates": summary["excluded_invalid_coordinates"],
        "excluded_outliers": summary["excluded_outliers"],
        "noise_points": summary["noise_points"],
        "computed_at": summary["computed_at"],
        "notes": summary["notes"],
    }
    con.execute("DELETE FROM complaint_clusters")
    for cluster in clusters:
        con.execute(
            "INSERT INTO complaint_clusters "
            "(label, centroid_lat, centroid_lng, complaint_count, unresolved_count, "
            " top_category, report_ids, params, computed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                cluster["label"],
                cluster["centroid_lat"],
                cluster["centroid_lng"],
                cluster["complaint_count"],
                cluster["unresolved_count"],
                cluster["top_category"],
                dumps(cluster["report_ids"]),
                dumps(params | {"radius_km": cluster["radius_km"],
                                "categories": cluster["categories"]}),
                summary["computed_at"],
            ),
        )
    con.commit()


def load_clusters():
    """Clusters from the most recent stored run (empty list if never run)."""
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT * FROM complaint_clusters ORDER BY complaint_count DESC"
        ).fetchall()
    finally:
        con.close()
    clusters = []
    for row in rows:
        params = loads(row["params"], {}) or {}
        clusters.append({
            "label": row["label"],
            "centroid_lat": row["centroid_lat"],
            "centroid_lng": row["centroid_lng"],
            "complaint_count": row["complaint_count"],
            "unresolved_count": row["unresolved_count"],
            "top_category": row["top_category"],
            "report_ids": loads(row["report_ids"], []) or [],
            "computed_at": row["computed_at"],
            "radius_km": params.get("radius_km"),
            "categories": params.get("categories"),
            "params": params,
        })
    return clusters


def stored_run_params():
    clusters = load_clusters()
    return clusters[0]["params"] if clusters else None


def cluster_membership(report_id):
    for cluster in load_clusters():
        if report_id in cluster["report_ids"]:
            return cluster
    return None


def hotspot_stats():
    clusters = load_clusters()
    params = stored_run_params()
    return {
        "clusters": len(clusters),
        "complaints_in_clusters": sum(c["complaint_count"] for c in clusters),
        "unresolved_in_clusters": sum(c["unresolved_count"] for c in clusters),
        "recurring": sum(
            1 for c in clusters if c["complaint_count"] >= HOTSPOT_MIN_COMPLAINTS
        ),
        "parameters": params,
        "recurring_threshold": HOTSPOT_MIN_COMPLAINTS,
    }
