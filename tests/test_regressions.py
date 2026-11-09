"""Regression tests for defects found during the Phase 1 repository audit.

Each test locks in one fix so the defect cannot silently return:

* Chart.js must be linked by the admin layout (all 8 admin charts were blank).
* requirements.txt must declare the ML dependencies (clean deploys crashed).
* the status badge must render once per report card.
* the duplicate-detection warning must not claim matches were "skipped" when
  they are actually included with a neutral proximity score.
* legacy dead files stay deleted.
* label/for association on the admin queue search box.
* honest public wording for the low-confidence review counter.
"""

import os
import re
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-regression-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402
from db import execute, query_one  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = app_module.app
    application.config["TESTING"] = True
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


# ---------------------------------------------------------------------------
# Deployment integrity
# ---------------------------------------------------------------------------
def test_admin_layout_loads_chart_js():
    """All admin charts call new Chart(); the library must be linked first."""
    with open(os.path.join(REPO_ROOT, "templates", "admin_base.html"), encoding="utf-8") as fh:
        layout = fh.read()
    assert "vendor/chart.umd.min.js" in layout
    assert layout.index("vendor/chart.umd.min.js") < layout.index("app.js")


def test_app_js_guards_missing_chart_library():
    with open(os.path.join(REPO_ROOT, "static", "app.js"), encoding="utf-8") as fh:
        source = fh.read()
    assert "function chartsAvailable()" in source
    # silent swallows replaced with visible diagnostics
    assert "/* noop */" not in source


def test_requirements_declare_ml_dependencies():
    with open(os.path.join(REPO_ROOT, "requirements.txt"), encoding="utf-8") as fh:
        requirements = fh.read().lower()
    for package in ("nltk", "scikit-learn", "pandas", "numpy", "joblib"):
        assert package in requirements, f"{package} missing from requirements.txt"
    # and they must actually import in this environment
    import joblib  # noqa: F401
    import nltk  # noqa: F401
    import numpy  # noqa: F401
    import pandas  # noqa: F401
    import sklearn  # noqa: F401


def test_legacy_dead_files_removed():
    assert not os.path.exists(os.path.join(REPO_ROOT, "templates", "admin.html"))
    assert not os.path.exists(os.path.join(REPO_ROOT, "static", "script.js"))


# ---------------------------------------------------------------------------
# Template correctness
# ---------------------------------------------------------------------------
def test_report_card_shows_status_badge_once(client):
    """_report_card.html rendered the status badge twice per card."""
    token_html = client.get("/signup").get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', token_html).group(1)
    email = f"badge.{os.urandom(4).hex()}@example.com"
    client.post("/signup", data={
        "name": "Badge Tester", "email": email, "password": "Passw0rd!",
        "confirm": "Passw0rd!", "csrf_token": token,
    })

    html = client.get("/report").get_data(as_text=True)
    token = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html).group(1)
    client.post("/report", data={
        "name": "Badge Tester", "mobile": "9876543210",
        "location": "14 Badge Street, Sector 2",
        "waste_type": "Garbage", "priority": "Low",
        "description": "A badge regression complaint with enough characters to pass validation.",
        "csrf_token": token,
    })

    listing = client.get("/my_reports").get_data(as_text=True)
    # one report card in the list -> exactly one status badge span
    badges = re.findall(r'class="badge status-[a-z-]+"', listing)
    assert len(badges) == 1, f"expected 1 status badge, found {len(badges)}"


def test_admin_queue_search_label_points_at_input(client):
    with open(os.path.join(REPO_ROOT, "templates", "admin", "complaints.html"),
              encoding="utf-8") as fh:
        markup = fh.read()
    match = re.search(r'<label for="([^"]+)">Search</label>', markup)
    assert match, "search label not found"
    assert f'id="{match.group(1)}"' in markup


def test_homepage_uses_honest_review_wording(client):
    body = client.get("/").get_data(as_text=True)
    assert "Awaiting manual AI review" in body
    assert "under AI analysis" not in body


# ---------------------------------------------------------------------------
# Duplicate detection honesty
# ---------------------------------------------------------------------------
def test_duplicate_warning_does_not_claim_matches_were_skipped():
    """Matches without coordinates are *included* with a neutral geo score,
    so the warning must say that - not that they were skipped."""
    from intelligence.duplicate_detection import find_duplicates

    text = ("Overflowing garbage bins near the market street are creating a "
            "terrible foul smell for everyone in the neighbourhood.")
    execute(
        "INSERT INTO reports (name, mobile, location, waste_type, priority, "
        " description, status, created_at, latitude, longitude, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), ?, ?, 'live')",
        ("A", "9876543210", "12 Market Street", "Garbage", "High", text,
         28.6139, 77.2090),
    )
    execute(
        "INSERT INTO reports (name, mobile, location, waste_type, priority, "
        " description, status, created_at, latitude, longitude, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), NULL, NULL, 'live')",
        ("B", "9876543211", "Unknown spot", "Garbage", "High", text),
    )

    result = find_duplicates(text, latitude=28.6139, longitude=77.2090,
                             category="Garbage")
    assert result["match_count"] >= 1, "expected the coordinate-less twin to match"

    joined = " ".join(result["warnings"])
    assert "skipped" not in joined.lower(), joined
    assert "neutral proximity score" in joined.lower(), joined

    row = query_one("SELECT COUNT(*) AS n FROM reports WHERE latitude IS NULL")
    assert row["n"] >= 1  # sanity: the fixture row exists


# ---------------------------------------------------------------------------
# Forecasting must never substitute an observation as a prediction
# ---------------------------------------------------------------------------
def test_baseline_predictions_cover_every_test_index():
    from intelligence.forecasting import _baseline_predictions

    counts = list(range(40))
    indices = list(range(30, 40))
    seasonal, moving = _baseline_predictions(counts, indices)
    assert all(t in seasonal and t in moving for t in indices)
    # and the value used is a genuine lag-7 / rolling computation
    assert seasonal[35] == counts[28]
    assert moving[35] == pytest.approx(sum(counts[28:35]) / 7)


def test_run_clustering_honours_explicit_zero_is_not_default():
    """`eps_meters or DEFAULT` silently replaced an explicit 0 with the default."""
    import inspect

    from intelligence import hotspot_detection

    source = inspect.getsource(hotspot_detection.run_clustering)
    assert "eps_meters or DBSCAN_EPS_METERS" not in source
    assert "is None" in source
