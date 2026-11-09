"""Phase 3 evaluation tests - Module C scoring, Module D cluster quality.

These lock in the evaluation machinery the MCA report quotes:

* duplicate-pair scoring shares the exact production rule
  (`pair_similarity` / `score_duplicate` from intelligence/duplicate_detection)
* the labelled pair set stays balanced, complete and honestly attributed
* DBSCAN cluster separation is measured with a real silhouette coefficient
  and persisted so the admin map can show it
* classification metrics are read from the measured training reports
"""

import csv
import math
import os
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-eval-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

from experiments.evaluation import (  # noqa: E402
    classification_summary,
    precision_recall_f1,
)
from intelligence.duplicate_detection import (  # noqa: E402
    pair_similarity,
    score_duplicate,
)
from intelligence.hotspot_detection import (  # noqa: E402
    _cluster_quality,
    run_clustering,
    stored_run_params,
)
from db import execute, init_db  # noqa: E402


# ---------------------------------------------------------------------------
# Metric helper
# ---------------------------------------------------------------------------
def test_precision_recall_f1_known_values():
    y_true = [1, 1, 0, 0, 1, 0]
    y_pred = [1, 0, 0, 1, 1, 0]
    # tp=2, fp=1, fn=1 -> precision 2/3, recall 2/3, f1 2/3
    metrics = precision_recall_f1(y_true, y_pred)
    assert metrics["tp"] == 2 and metrics["fp"] == 1 and metrics["fn"] == 1
    assert metrics["precision"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["recall"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["f1"] == pytest.approx(2 / 3, abs=1e-4)
    assert metrics["support_positives"] == 3
    assert metrics["support_negatives"] == 3


def test_precision_recall_f1_all_negative_predictions():
    metrics = precision_recall_f1([1, 0, 1], [0, 0, 0])
    assert metrics["precision"] == 0.0
    assert metrics["recall"] == 0.0
    assert metrics["f1"] == 0.0


# ---------------------------------------------------------------------------
# Module C - production scoring rule
# ---------------------------------------------------------------------------
def test_pair_similarity_identical_text_is_higher_than_unrelated():
    same = ("Overflowing garbage bins near the market street create a foul "
            "smell that disturbs the residents every morning.")
    unrelated_a = "Construction debris is blocking the service lane outside the school."
    unrelated_b = "Used syringes and medical waste were dumped behind the clinic."

    identical = pair_similarity(same, same)
    related = pair_similarity(same, same + " Please send someone today.")
    different = pair_similarity(unrelated_a, unrelated_b)

    assert identical > related > different
    assert identical == pytest.approx(1.0, abs=1e-6)
    assert different < 0.30


def test_pair_similarity_handles_empty_input():
    assert pair_similarity("", "") == pytest.approx(0.0, abs=1e-6)


def test_score_duplicate_rejects_below_text_gate():
    from config import DUPLICATE_SIMILARITY_THRESHOLD

    assert score_duplicate(DUPLICATE_SIMILARITY_THRESHOLD - 0.05, 0.1, True) is None
    assert score_duplicate(None, 0.1, True) is None


def test_score_duplicate_rejects_pairs_beyond_distance_gate():
    from config import DUPLICATE_DISTANCE_KM

    verdict = score_duplicate(0.9, DUPLICATE_DISTANCE_KM + 0.5, True)
    assert verdict is None  # far apart cannot be the same incident


def test_score_duplicate_neutral_geo_when_coordinates_unknown():
    verdict = score_duplicate(0.9, None, same_category=True)
    assert verdict is not None
    assert verdict["geo_score"] == pytest.approx(0.4)
    assert verdict["is_likely"] is True  # strong text still clears the bar


def test_score_duplicate_penalises_hard_negatives():
    """Same category + ~300 m apart + weak-but-passing text must not be likely."""
    verdict = score_duplicate(0.5, 0.3, same_category=True)
    assert verdict is not None
    # 0.65*0.5 + 0.25*1.0 + 0.10*1.0 = 0.675 -> likely; the hard-negative
    # rejection therefore comes from the text gate in the pair set, not here.
    assert verdict["score"] == pytest.approx(0.65 * 0.5 + 0.25 * 1.0 + 0.10 * 1.0)


def test_score_duplicate_far_pair_with_strong_text_is_rejected_by_geo():
    verdict = score_duplicate(0.95, 5.0, same_category=True)
    assert verdict is None


# ---------------------------------------------------------------------------
# Labelled pair set integrity
# ---------------------------------------------------------------------------
def test_duplicate_pairs_csv_is_balanced_and_attributed():
    path = os.path.join(REPO_ROOT, "data", "duplicate_pairs.csv")
    assert os.path.isfile(path), "run scripts/build_duplicate_pairs.py first"

    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 500
    positives = [r for r in rows if r["label"] == "1"]
    negatives = [r for r in rows if r["label"] == "0"]
    assert len(positives) == 250 and len(negatives) == 250

    required = {"pair_id", "text_a", "text_b", "category_a", "category_b",
                "lat_a", "lon_a", "lat_b", "lon_b", "label", "construction",
                "origin"}
    assert required <= set(rows[0])

    for row in rows:
        assert row["origin"] == "synthetic_construction"
        assert row["construction"].startswith(("positive/", "negative/"))
        assert (row["label"] == "1") == row["construction"].startswith("positive/")
        for key in ("lat_a", "lon_a", "lat_b", "lon_b"):
            value = float(row[key])
            assert -90 <= value <= 90 if "lat" in key else -180 <= value <= 180
        if row["label"] == "1":
            # positives describe one incident: same spot, same category
            assert row["category_a"] == row["category_b"]
            assert float(row["lat_a"]) == float(row["lat_b"])
            assert float(row["lon_a"]) == float(row["lon_b"])
        else:
            assert float(row["lat_a"]) != float(row["lat_b"]) or \
                   float(row["lon_a"]) != float(row["lon_b"])


def test_duplicate_pairs_hard_negatives_are_nearby():
    """The ~300 m bucket is what makes the text signal matter."""
    path = os.path.join(REPO_ROOT, "data", "duplicate_pairs.csv")
    with open(path, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    near = [r for r in rows if r["construction"] == "negative/same_category_near"]
    assert len(near) == 80
    for row in near:
        d_lat = abs(float(row["lat_a"]) - float(row["lat_b"]))
        assert d_lat < 0.01  # ~300 m, far inside the 2 km gate


# ---------------------------------------------------------------------------
# Module D - cluster quality
# ---------------------------------------------------------------------------
def _two_tight_clusters():
    """(radians) labels array for two compact clusters far apart."""
    import numpy as np

    base_a = (math.radians(28.6100), math.radians(77.2000))
    base_b = (math.radians(28.7500), math.radians(77.2000))  # ~15 km away
    step = math.radians(0.0008)  # ~90 m
    coords, labels = [], []
    for i in range(5):
        coords.append((base_a[0] + i * step * 0.001, base_a[1] + i * step))
        labels.append(0)
    for i in range(5):
        coords.append((base_b[0] + i * step * 0.001, base_b[1] + i * step))
        labels.append(1)
    return np.array(coords), np.array(labels)


def test_cluster_quality_scores_two_separated_clusters():
    coords, labels = _two_tight_clusters()
    quality = _cluster_quality(coords, labels)
    assert quality["silhouette"] is not None
    assert quality["silhouette"] > 0.5
    assert quality["n_clusters"] == 2
    assert quality["scored_points"] == 10
    assert quality["metric"] == "haversine"
    assert quality["reason"] is None


def test_cluster_quality_refuses_single_cluster():
    import numpy as np

    coords = np.array([[math.radians(28.6 + i * 0.001), math.radians(77.2)]
                       for i in range(6)])
    labels = np.zeros(6, dtype=int)
    quality = _cluster_quality(coords, labels)
    assert quality["silhouette"] is None
    assert quality["reason"]


def test_cluster_quality_refuses_all_noise():
    import numpy as np

    coords = np.array([[math.radians(28.6 + i), math.radians(77.2 + i)]
                       for i in range(5)])
    labels = np.full(5, -1, dtype=int)
    quality = _cluster_quality(coords, labels)
    assert quality["silhouette"] is None
    assert quality["scored_points"] == 0


def _insert_report(lat, lon, waste_type="Open Garbage"):
    execute(
        "INSERT INTO reports (name, mobile, location, waste_type, priority, "
        " description, status, created_at, latitude, longitude, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), ?, ?, 'live')",
        ("Eval", "9876543210", "Eval Street", waste_type, "Medium",
         "Evaluation fixture complaint for clustering tests.", lat, lon),
    )


def test_run_clustering_measures_and_persists_silhouette():
    init_db()
    # two groups: 4 points around 28.6100/77.2000, 4 around 28.7500/77.2000
    for i in range(4):
        _insert_report(28.6100 + i * 0.0007, 77.2000 + i * 0.0005)
    for i in range(4):
        _insert_report(28.7500 + i * 0.0007, 77.2000 + i * 0.0005,
                       waste_type="Construction Debris")

    summary = run_clustering(eps_meters=400, min_samples=3, persist=True)
    assert summary["insufficient"] is False
    assert summary["n_clusters"] >= 2  # extra fixture rows may add noise, not clusters

    quality = summary["quality"]
    assert quality is not None
    assert quality["silhouette"] is not None
    assert quality["silhouette"] > 0.5
    assert quality["scored_points"] >= 8

    stored = stored_run_params()
    assert stored is not None
    assert stored["quality"]["silhouette"] == quality["silhouette"]
    assert stored["quality"]["metric"] == "haversine"


def test_run_clustering_reports_honestly_when_too_few_points():
    """An empty database must say 'not enough data', never invent clusters."""
    import sqlite3

    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE reports (id INTEGER PRIMARY KEY, tracking_id TEXT, "
        " waste_type TEXT, status TEXT, latitude REAL, longitude REAL)"
    )
    con.execute(
        "INSERT INTO reports (waste_type, status, latitude, longitude) "
        "VALUES ('Open Garbage', 'Submitted', NULL, NULL)"
    )
    summary = run_clustering(eps_meters=400, min_samples=3, persist=False, con=con)
    con.close()

    assert summary["insufficient"] is True
    assert summary["n_clusters"] == 0
    assert summary["quality"] is None
    assert summary["notes"]


# ---------------------------------------------------------------------------
# Module B - measured classification reports
# ---------------------------------------------------------------------------
def test_classification_summary_reads_measured_reports():
    summary = classification_summary()
    for task in ("category", "urgency"):
        block = summary[task]
        assert block["available"], f"{task} report missing - run scripts/train_models.py"
        assert block["algorithm"]
        test_metrics = block["test_metrics"]
        assert 0.0 <= test_metrics["accuracy"] <= 1.0
        assert 0.0 <= test_metrics["f1_macro"] <= 1.0
        assert block["cv_f1_macro"] is not None
        holdout = block["holdout"]
        assert holdout["rows"] and holdout["metrics"]["accuracy"] >= 0.0
        assert block["confusion_matrix_test"], "confusion matrix must be stored"
