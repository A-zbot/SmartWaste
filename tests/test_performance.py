"""Phase 6 tests: performance & correctness hardening.

* duplicate detection must reuse a fitted TF-IDF candidate matrix instead of
  refitting on every request, while invalidating the moment candidates change
* forecast payloads must be memoized for a short TTL, handed out as private
  copies, expired after the TTL and invalidated by new data
* model evaluation reports must load through the mtime cache
* server-side pagination on the admin queue, messages inbox, audit log and
  the citizen's complaint history - with invalid/out-of-range pages clamped
* the audit action filter must scope the reported total to the filter
"""

import os
import re
import sys
import tempfile
import uuid

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-perf-"), "test.db"),
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


@pytest.fixture()
def admin_credentials():
    path = os.path.join(REPO_ROOT, ".env")
    creds = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    creds[key.strip()] = value.strip()
    return creds


def _token(html, action=None):
    if action:
        match = re.search(r'<form[^>]*action="[^"]*%s[^"]*"[^>]*>.*?</form>' % re.escape(action),
                          html, re.S)
    else:
        match = re.search(r"<form[^>]*>.*?</form>", html, re.S)
    if not match:
        return None
    found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', match.group(0))
    return found.group(1) if found else None


def _login(client, identifier, password):
    html = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={
        "username": identifier, "password": password,
        "csrf_token": _token(html),
    })


def _admin_login(client, admin_credentials):
    return _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"])


def _signup(client, email=None):
    email = email or f"perf.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Pagination Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


# ---------------------------------------------------------------------------
# Duplicate detection: fitted vectorizer cache
# ---------------------------------------------------------------------------
@pytest.fixture()
def dup_rows():
    marker = uuid.uuid4().hex[:8]
    text = (f"Overflowing dumpster behind the {marker} storage yard is "
            "drawing rats and a terrible stench.")
    ids = []
    for k in range(2):
        ids.append(execute(
            "INSERT INTO reports (name, mobile, location, waste_type, priority, "
            " description, status, created_at, latitude, longitude, source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), ?, ?, 'live')",
            ("Perf Tester", "9876543210", f"{k} Perf Lane {marker}", "Garbage",
             "High", text, round(28.61 + k * 0.001, 4), round(77.20 + k * 0.001, 4)),
        ))
    yield {"marker": marker, "text": text, "ids": ids}
    for rid in ids:
        execute("DELETE FROM reports WHERE id=?", (rid,))


def test_find_duplicates_caches_fitted_matrix_and_keeps_scores(dup_rows):
    from intelligence import duplicate_detection as dd

    dd.clear_vectorizer_cache()
    first = dd.find_duplicates(dup_rows["text"], category="Garbage", limit=10)
    sig_after_first = dd._VEC_CACHE["sig"]
    assert sig_after_first, "the candidate matrix must be cached"

    second = dd.find_duplicates(dup_rows["text"], category="Garbage", limit=10)
    assert dd._VEC_CACHE["sig"] == sig_after_first, "second call must hit the cache"

    assert second["checked"] == first["checked"]
    assert second["matches"] == first["matches"]
    mine = [m for m in second["matches"] if m["report_id"] in dup_rows["ids"]]
    assert mine, "identical descriptions must still be found on the cached path"
    assert all(m["similarity"] >= 0.999 for m in mine)


def test_vectorizer_cache_invalidates_when_candidates_change(dup_rows):
    from intelligence import duplicate_detection as dd

    dd.clear_vectorizer_cache()
    before = dd.find_duplicates(dup_rows["text"], category="Garbage")
    sig_before = dd._VEC_CACHE["sig"]

    extra = execute(
        "INSERT INTO reports (name, mobile, location, waste_type, priority, "
        " description, status, created_at, latitude, longitude, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), ?, ?, 'live')",
        ("Perf Tester", "9876543210", f"3 Perf Lane {dup_rows['marker']}", "Garbage",
         "High", dup_rows["text"], 28.6130, 77.2030),
    )
    try:
        after = dd.find_duplicates(dup_rows["text"], category="Garbage")
        assert after["checked"] == before["checked"] + 1
        assert dd._VEC_CACHE["sig"] != sig_before, "new candidates must refit the matrix"
    finally:
        execute("DELETE FROM reports WHERE id=?", (extra,))


# ---------------------------------------------------------------------------
# Forecast memoization
# ---------------------------------------------------------------------------
@pytest.fixture()
def forecast_env(monkeypatch):
    from intelligence import forecasting

    forecasting.clear_forecast_cache()
    calls = {"n": 0}
    original = forecasting._forecast_from_series

    def counting(horizon, series):
        calls["n"] += 1
        return original(horizon, series)

    monkeypatch.setattr(forecasting, "_forecast_from_series", counting)
    yield forecasting, calls
    forecasting.clear_forecast_cache()


def test_forecast_payload_is_memoized_and_isolated(forecast_env):
    forecasting, calls = forecast_env
    payload = forecasting.forecast(horizon=7)
    assert calls["n"] == 1

    counts = list(payload["history"]["counts"])
    payload["history"]["counts"] = []          # attempt to corrupt the cache
    payload["status"] = "corrupted"

    again = forecasting.forecast(horizon=7)
    assert calls["n"] == 1, "second call must be served from the TTL cache"
    assert again["status"] != "corrupted"
    assert again["history"]["counts"] == counts


def test_forecast_cache_expires_after_ttl(forecast_env):
    forecasting, calls = forecast_env
    forecasting.forecast(horizon=7)
    assert calls["n"] == 1

    signature = next(iter(forecasting._FORECAST_CACHE))
    stored_at, stored_payload = forecasting._FORECAST_CACHE[signature]
    forecasting._FORECAST_CACHE[signature] = (
        stored_at - forecasting.FORECAST_CACHE_TTL - 1.0, stored_payload,
    )
    forecasting.forecast(horizon=7)
    assert calls["n"] == 2, "an expired entry must be rebuilt"


def test_new_complaint_invalidates_forecast_cache(forecast_env):
    forecasting, calls = forecast_env
    payload = forecasting.forecast(horizon=7)
    total_before = payload["history"]["total"]

    marker = uuid.uuid4().hex[:8]
    rid = execute(
        "INSERT INTO reports (name, mobile, location, waste_type, priority, "
        " description, status, created_at, source) "
        "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now'), 'live')",
        ("Perf Forecast", "9876543210", f"Forecast Lane {marker}", "Garbage",
         "Medium", f"Forecast invalidation fixture row {marker}."),
    )
    try:
        fresh = forecasting.forecast(horizon=7)
        assert calls["n"] == 2, "a new complaint must invalidate the cached payload"
        assert fresh["history"]["total"] == total_before + 1
    finally:
        execute("DELETE FROM reports WHERE id=?", (rid,))


# ---------------------------------------------------------------------------
# Model report mtime cache
# ---------------------------------------------------------------------------
def test_model_report_load_is_cached():
    from intelligence import _model_store

    if not _model_store.is_trained("category"):
        pytest.skip("model artifacts not trained in this environment")

    _model_store.clear_cache()
    first = _model_store.load_report("category")
    assert first and "best_model" in first

    second = _model_store.load_report("category")
    assert second is first, "the second load must be served from the cache"

    _model_store.clear_cache()
    third = _model_store.load_report("category")
    assert third is not first, "clearing the cache must force a re-read"
    assert third == first


# ---------------------------------------------------------------------------
# Admin complaint queue pagination
# ---------------------------------------------------------------------------
def _insert_queue_rows(area, n=25):
    ids = []
    for i in range(n):
        ids.append(execute(
            "INSERT INTO reports (name, mobile, location, waste_type, priority, "
            " description, status, created_at, area, tracking_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now', ?), ?, ?, 'live')",
            ("Perf Queue", "9876543210", f"Pagination Block {i} ({area})", "Garbage",
             "Medium", f"Pagination fixture row {i} for {area} - queue paging test.",
             f"-{i} minutes", area, f"SW-9{i:04d}"),
        ))
    return ids


@pytest.fixture()
def queue_area():
    area = f"PaginationZone-{uuid.uuid4().hex[:8]}"
    ids = _insert_queue_rows(area)
    yield area, ids
    execute("DELETE FROM reports WHERE area=?", (area,))


def test_admin_queue_is_paginated_and_clamped(client, admin_credentials, queue_area):
    area, _ = queue_area
    assert _admin_login(client, admin_credentials).status_code == 302

    page1 = client.get("/admin/complaints",
                       query_string={"area": area}).get_data(as_text=True)
    assert "Page 1 of 2" in page1
    assert page1.count("<tr data-status=") == 20
    assert "25 complaints" in page1
    assert "Pagination Block 0" in page1          # newest row (created_at now)
    assert "Pagination Block 24" not in page1

    next_link = re.search(r'href="([^"]*page=2[^"]*)"', page1)
    assert next_link, "a Next page link must be rendered"
    assert area in next_link.group(1), "the Next link must preserve filters"

    page2 = client.get("/admin/complaints",
                       query_string={"area": area, "page": 2}).get_data(as_text=True)
    assert "Page 2 of 2" in page2
    assert page2.count("<tr data-status=") == 5
    assert "Pagination Block 24" in page2
    assert "Pagination Block 0" not in page2

    invalid = client.get("/admin/complaints",
                         query_string={"area": area, "page": "abc"})
    assert invalid.status_code == 200
    assert "Page 1 of 2" in invalid.get_data(as_text=True)

    far = client.get("/admin/complaints",
                     query_string={"area": area, "page": 999})
    assert far.status_code == 200
    assert "Page 2 of 2" in far.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Citizen history pagination
# ---------------------------------------------------------------------------
@pytest.fixture()
def citizen_history(client):
    email = _signup(client)  # also logs the client in
    user_id = query_one("SELECT id FROM users WHERE email=?", (email,))["id"]
    ids = []
    for i in range(12):
        ids.append(execute(
            "INSERT INTO reports (name, mobile, location, waste_type, priority, "
            " description, status, created_at, user_id, tracking_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Submitted', datetime('now', ?), ?, ?, 'live')",
            ("Pagination Citizen", "9876543210", f"Pagination Row {i}", "Garbage",
             "Medium", f"Paging history fixture row {i}.", f"-{i} minutes", user_id,
             f"SW-8{i:04d}"),
        ))
    yield ids
    for rid in ids:
        execute("DELETE FROM reports WHERE id=?", (rid,))


def test_my_reports_is_paginated(client, citizen_history):
    page1 = client.get("/my_reports").get_data(as_text=True)
    assert "Page 1 of 2" in page1
    assert '<div class="kpi-value">12</div>' in page1, "KPIs must cover all 12 rows"
    assert "Pagination Row 11" in page1          # newest (highest id)
    assert "Pagination Row 0" not in page1

    page2 = client.get("/my_reports", query_string={"page": 2}).get_data(as_text=True)
    assert "Page 2 of 2" in page2
    assert "Pagination Row 0" in page2
    assert "Pagination Row 11" not in page2
    assert '<div class="kpi-value">12</div>' in page2

    invalid = client.get("/my_reports", query_string={"page": "abc"})
    assert invalid.status_code == 200
    assert "Page 1 of 2" in invalid.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Admin messages inbox pagination
# ---------------------------------------------------------------------------
@pytest.fixture()
def pagination_messages():
    marker = uuid.uuid4().hex[:8]
    for i in range(25):
        execute(
            "INSERT INTO messages (name, email, subject, message) VALUES (?, ?, ?, ?)",
            ("Pagination Fan", f"pag.{marker}@example.com",
             f"PaginationMsg {marker} #{i}",
             f"Inbox paging fixture message {i} ({marker})."),
        )
    yield marker
    execute("DELETE FROM messages WHERE subject LIKE ?",
            (f"PaginationMsg {marker}%",))


def test_messages_inbox_is_paginated(client, admin_credentials, pagination_messages):
    marker = pagination_messages
    assert _admin_login(client, admin_credentials).status_code == 302

    page1 = client.get("/admin/messages").get_data(as_text=True)
    match = re.search(r"Page (\d+) of (\d+)", page1)
    assert match, "pagination controls must render"
    pages = int(match.group(2))
    assert pages >= 2
    assert f"PaginationMsg {marker} #24" in page1   # newest (highest id)
    assert f"PaginationMsg {marker} #0" not in page1

    page2 = client.get("/admin/messages", query_string={"page": 2}).get_data(as_text=True)
    assert f"PaginationMsg {marker} #0" in page2    # rank 25 -> page 2 at 20/page
    assert f"PaginationMsg {marker} #24" not in page2

    far = client.get("/admin/messages", query_string={"page": 999})
    assert far.status_code == 200
    assert f"Page {pages} of {pages}" in far.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Admin audit pagination + filter-scoped total
# ---------------------------------------------------------------------------
@pytest.fixture()
def audit_marker():
    marker = uuid.uuid4().hex[:8]
    for i in range(25):
        execute(
            "INSERT INTO audit_logs (actor_type, action, entity, detail, ip) "
            "VALUES ('admin', ?, 'report', ?, '127.0.0.1')",
            (f"perftest.{marker}.row", f"Paging audit fixture row {i} ({marker})"),
        )
    # One row outside the action filter so the scoping assertion is meaningful.
    execute(
        "INSERT INTO audit_logs (actor_type, action, detail) "
        "VALUES ('system', ?, 'outside the filtered action set')",
        (f"perfother.{marker}",),
    )
    yield marker
    execute("DELETE FROM audit_logs WHERE action LIKE ?", (f"perftest.{marker}%",))
    execute("DELETE FROM audit_logs WHERE action LIKE ?", (f"perfother.{marker}%",))


def test_audit_log_is_paginated_and_filter_total_is_scoped(
        client, admin_credentials, audit_marker):
    marker = audit_marker
    assert _admin_login(client, admin_credentials).status_code == 302

    filtered = f"perftest.{marker}"
    page1 = client.get("/admin/audit",
                       query_string={"action": filtered}).get_data(as_text=True)
    assert "Total events: <b>25</b>" in page1, "total must be scoped to the filter"
    assert "Page 1 of 2" in page1
    assert f"Paging audit fixture row 24 ({marker})" in page1
    assert f"Paging audit fixture row 0 ({marker})" not in page1

    page2 = client.get("/admin/audit",
                       query_string={"action": filtered, "page": 2}).get_data(as_text=True)
    assert "Page 2 of 2" in page2
    assert f"Paging audit fixture row 0 ({marker})" in page2

    unfiltered = client.get("/admin/audit").get_data(as_text=True)
    total_all = int(re.search(r"Total events: <b>(\d+)</b>", unfiltered).group(1))
    assert total_all >= 26, "unfiltered total must include the companion row"

    invalid = client.get("/admin/audit", query_string={"action": filtered, "page": "abc"})
    assert invalid.status_code == 200
    assert "Page 1 of 2" in invalid.get_data(as_text=True)
