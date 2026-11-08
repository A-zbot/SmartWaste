"""NLP + geospatial duplicate complaint detection (Module C).

A new complaint is compared against recent complaints on four signals:

* text similarity   - TF-IDF vectors + cosine similarity over complaint text
* geographic closeness - haversine distance between stored coordinates
* recency           - only complaints inside a configurable time window
* category agreement - small bonus when both describe the same waste type

Nothing is auto-rejected: results are surfaced to the citizen and to
administrators as *possible* duplicates with their evidence attached.
"""

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from config import (
    DUPLICATE_COMBINED_THRESHOLD,
    DUPLICATE_DISTANCE_KM,
    DUPLICATE_MAX_CANDIDATES,
    DUPLICATE_SIMILARITY_THRESHOLD,
    DUPLICATE_WINDOW_DAYS,
)
from db import get_connection
from intelligence.geospatial_analysis import haversine_km, valid_coords
from intelligence.preprocessing import preprocess

# Weights of the combined duplicate score.
_W_TEXT, _W_GEO, _W_CATEGORY = 0.65, 0.25, 0.10


def _fetch_candidates(con, exclude_report_id=None, window_days=None):
    window_days = window_days or DUPLICATE_WINDOW_DAYS
    sql = (
        "SELECT id, tracking_id, location, area, waste_type, status, "
        "       description, created_at, latitude, longitude "
        "FROM reports "
        "WHERE created_at >= datetime('now', ?) "
    )
    params = [f"-{int(window_days)} days"]
    if exclude_report_id:
        sql += "AND id != ? "
        params.append(int(exclude_report_id))
    sql += "ORDER BY id DESC LIMIT ?"
    params.append(DUPLICATE_MAX_CANDIDATES)
    return con.execute(sql, params).fetchall()


def find_duplicates(text, latitude=None, longitude=None, category=None,
                    exclude_report_id=None, window_days=None, limit=5):
    """Return possible duplicates of *text* as a JSON-safe dict."""
    text = (text or "").strip()
    result = {
        "checked": 0,
        "matches": [],
        "match_count": 0,
        "likely_count": 0,
        "self_location_known": valid_coords(latitude, longitude),
        "window_days": window_days or DUPLICATE_WINDOW_DAYS,
        "thresholds": {
            "text_similarity": DUPLICATE_SIMILARITY_THRESHOLD,
            "distance_km": DUPLICATE_DISTANCE_KM,
            "combined_score": DUPLICATE_COMBINED_THRESHOLD,
        },
        "warnings": [],
    }
    if not text:
        result["warnings"].append("empty_text")
        return result

    con = get_connection()
    try:
        candidates = _fetch_candidates(con, exclude_report_id, window_days)
    finally:
        con.close()

    result["checked"] = len(candidates)
    if not candidates:
        return result

    corpus = [text] + [row["description"] or "" for row in candidates]
    try:
        vectorizer = TfidfVectorizer(
            preprocessor=preprocess,
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        result["warnings"].append("vectorisation_failed")
        return result

    similarities = linear_kernel(matrix[0:1], matrix[1:]).ravel()

    matches = []
    skipped_no_text = 0
    for row, similarity in zip(candidates, similarities):
        similarity = float(similarity)
        if similarity < DUPLICATE_SIMILARITY_THRESHOLD:
            continue

        candidate_lat, candidate_lon = row["latitude"], row["longitude"]
        self_known = result["self_location_known"]
        other_known = valid_coords(candidate_lat, candidate_lon)
        distance = None
        if self_known and other_known:
            distance = haversine_km(latitude, longitude, candidate_lat, candidate_lon)

        if distance is not None and distance > DUPLICATE_DISTANCE_KM:
            continue  # geographically too far to be the same incident

        if distance is None:
            skipped_no_text += 1
            geo_score = 0.4  # neutral: proximity unknown
        elif distance <= 1.0:
            geo_score = 1.0
        else:
            geo_score = float(np.exp(-(distance - 1.0) / DUPLICATE_DISTANCE_KM))

        category_bonus = 1.0 if (category and row["waste_type"] == category) else 0.0
        score = _W_TEXT * similarity + _W_GEO * geo_score + _W_CATEGORY * category_bonus

        matches.append({
            "report_id": row["id"],
            "tracking_id": row["tracking_id"] or f"SW-{row['id']:05d}",
            "location": row["location"],
            "area": row["area"],
            "category": row["waste_type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "similarity": round(similarity, 4),
            "distance_km": round(distance, 3) if distance is not None else None,
            "score": round(float(score), 4),
            "location_known": other_known,
            "is_likely": float(score) >= DUPLICATE_COMBINED_THRESHOLD,
        })

    matches.sort(key=lambda m: (-m["score"], m["report_id"]))
    result["matches"] = matches[:limit]
    result["match_count"] = len(matches)
    result["likely_count"] = sum(1 for m in matches if m["is_likely"])

    if not result["self_location_known"]:
        result["warnings"].append(
            "Report has no coordinates - geographic proximity could not be verified."
        )
    if skipped_no_text:
        result["warnings"].append(
            f"{skipped_no_text} text-similar complaint(s) skipped because "
            "coordinates were missing on one side."
        )
    return result


def nearby_similar_count(text, latitude, longitude, exclude_report_id=None):
    """Number of text-similar complaints within the duplicate radius.

    Used by decision support / explainability as a real database-derived
    context factor (not a model input).
    """
    check = find_duplicates(
        text, latitude=latitude, longitude=longitude,
        exclude_report_id=exclude_report_id, limit=DUPLICATE_MAX_CANDIDATES,
    )
    return sum(1 for m in check["matches"] if m["distance_km"] is not None)
