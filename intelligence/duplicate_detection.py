"""NLP + geospatial duplicate complaint detection (Module C).

A new complaint is compared against recent complaints on four signals:

* text similarity   - TF-IDF vectors + cosine similarity over complaint text
* geographic closeness - haversine distance between stored coordinates
* recency           - only complaints inside a configurable time window
* category agreement - small bonus when both describe the same waste type

Nothing is auto-rejected: results are surfaced to the citizen and to
administrators as *possible* duplicates with their evidence attached.
"""

import hashlib
import threading

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

# Fitted TF-IDF state for the candidate corpus. Refitting on every request is
# wasteful, so the matrix is reused until the candidate descriptions change.
_VEC_CACHE = {"sig": None, "vectorizer": None, "matrix": None}
_VEC_LOCK = threading.Lock()


def pair_similarity(text_a, text_b):
    """TF-IDF cosine similarity between exactly two texts.

    Uses the same vectoriser configuration as :func:`find_duplicates`
    (1-2 grams, NLTK preprocessing, sublinear TF). Exposed separately so the
    offline evaluation in ``experiments/evaluation.py`` scores pairs with the
    identical method the live path uses.
    """
    try:
        vectorizer = TfidfVectorizer(
            preprocessor=preprocess,
            ngram_range=(1, 2),
            min_df=1,
            sublinear_tf=True,
            strip_accents="unicode",
        )
        matrix = vectorizer.fit_transform([text_a or "", text_b or ""])
    except ValueError:
        return 0.0
    return float(linear_kernel(matrix[0:1], matrix[1:]).ravel()[0])


def score_duplicate(similarity, distance_km=None, same_category=False):
    """Apply the production decision rule to precomputed pair signals.

    Returns ``None`` when the pair must be rejected (below the text gate, or
    geographically too far), otherwise a dict with the combined ``score`` and
    the ``is_likely`` verdict. Shared by the live query path and the offline
    evaluation so both always agree on the rule.
    """
    if similarity is None or similarity < DUPLICATE_SIMILARITY_THRESHOLD:
        return None
    if distance_km is not None and distance_km > DUPLICATE_DISTANCE_KM:
        return None  # geographically too far to be the same incident

    if distance_km is None:
        geo_score = 0.4  # neutral: proximity unknown
    elif distance_km <= 1.0:
        geo_score = 1.0
    else:
        geo_score = float(np.exp(-(distance_km - 1.0) / DUPLICATE_DISTANCE_KM))

    category_bonus = 1.0 if same_category else 0.0
    score = _W_TEXT * similarity + _W_GEO * geo_score + _W_CATEGORY * category_bonus
    return {
        "score": float(score),
        "geo_score": geo_score,
        "category_bonus": category_bonus,
        "is_likely": float(score) >= DUPLICATE_COMBINED_THRESHOLD,
    }


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


def _candidate_matrix(candidates):
    """TF-IDF matrix for the candidate descriptions, cached by content hash.

    Returns ``(vectorizer, matrix)`` or ``(None, None)`` when the corpus has
    no usable terms. The cache key hashes the exact texts that were fitted,
    so it can never serve a vectoriser built from different data.
    """
    corpus = [row["description"] or "" for row in candidates]
    sig = hashlib.md5("\x1f".join(corpus).encode("utf-8")).hexdigest()
    with _VEC_LOCK:
        if _VEC_CACHE["sig"] == sig:
            return _VEC_CACHE["vectorizer"], _VEC_CACHE["matrix"]

    vectorizer = TfidfVectorizer(
        preprocessor=preprocess,
        ngram_range=(1, 2),
        min_df=1,
        sublinear_tf=True,
        strip_accents="unicode",
    )
    try:
        matrix = vectorizer.fit_transform(corpus)
    except ValueError:
        return None, None
    with _VEC_LOCK:
        _VEC_CACHE["sig"] = sig
        _VEC_CACHE["vectorizer"] = vectorizer
        _VEC_CACHE["matrix"] = matrix
    return vectorizer, matrix


def clear_vectorizer_cache():
    with _VEC_LOCK:
        _VEC_CACHE["sig"] = None
        _VEC_CACHE["vectorizer"] = None
        _VEC_CACHE["matrix"] = None


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

    vectorizer, matrix = _candidate_matrix(candidates)
    if vectorizer is None:
        result["warnings"].append("vectorisation_failed")
        return result

    query_vector = vectorizer.transform([text])
    similarities = linear_kernel(query_vector, matrix).ravel()

    matches = []
    missing_coords = 0
    for row, similarity in zip(candidates, similarities):
        similarity = float(similarity)

        candidate_lat, candidate_lon = row["latitude"], row["longitude"]
        self_known = result["self_location_known"]
        other_known = valid_coords(candidate_lat, candidate_lon)
        distance = None
        if self_known and other_known:
            distance = haversine_km(latitude, longitude, candidate_lat, candidate_lon)

        same_category = bool(category and row["waste_type"] == category)
        verdict = score_duplicate(similarity, distance, same_category)
        if verdict is None:
            continue

        if distance is None:
            missing_coords += 1

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
            "score": round(verdict["score"], 4),
            "location_known": other_known,
            "is_likely": verdict["is_likely"],
        })

    matches.sort(key=lambda m: (-m["score"], m["report_id"]))
    result["matches"] = matches[:limit]
    result["match_count"] = len(matches)
    result["likely_count"] = sum(1 for m in matches if m["is_likely"])

    if not result["self_location_known"]:
        result["warnings"].append(
            "Report has no coordinates - geographic proximity could not be verified."
        )
    if missing_coords:
        result["warnings"].append(
            f"{missing_coords} text-similar complaint(s) matched without a distance "
            "because coordinates were missing on one side; they are shown with a "
            "neutral proximity score."
        )
    return result
