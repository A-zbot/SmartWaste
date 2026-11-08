"""End-to-end smoke tests for SmartWaste 2.0.

Run with:  python -m pytest tests/ -q

The suite points the app at a throw-away SQLite database (``DATABASE_PATH``)
so it never touches the development ``waste.db``.
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

# Must be set before config/app are imported.
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(prefix="smartwaste-test-"), "test.db")
os.environ["AUTO_TRAIN_MODELS"] = "0"

import app as app_module  # noqa: E402


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
    """Extract the CSRF token of the first form (optionally matching action)."""
    if action:
        match = re.search(r'<form[^>]*action="[^"]*%s[^"]*"[^>]*>.*?</form>' % re.escape(action),
                          html, re.S)
    else:
        match = re.search(r"<form[^>]*>.*?</form>", html, re.S)
    if not match:
        return None
    found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', match.group(0))
    return found.group(1) if found else None


def _meta_csrf(html):
    found = re.search(r'name="csrf-token" content="([^"]+)"', html)
    return found.group(1) if found else ""


def _signup(client, email=None):
    email = email or f"smoke.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    response = client.post("/signup", data={
        "name": "Smoke Citizen",
        "email": email,
        "mobile": "9876543210",
        "password": "Passw0rd!",
        "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    assert response.status_code == 302, response.get_data(as_text=True)[:200]
    return email


def _login(client, identifier, password):
    html = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={
        "username": identifier,
        "password": password,
        "csrf_token": _token(html),
    })


def _submit_report(client):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Smoke Citizen",
        "mobile": "9876543210",
        "location": "12 Market Street, Sector 14",
        "waste_type": "Garbage",
        "priority": "High",
        "description": "Overflowing bins near the market street causing foul smell and health hazard.",
        "latitude": "28.6139",
        "longitude": "77.2090",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


# ---------------------------------------------------------------------------
# Public pages
# ---------------------------------------------------------------------------
def test_public_pages_render(client):
    for path in ("/", "/about", "/contact", "/team", "/login", "/signup",
                 "/report", "/track", "/founder"):
        response = client.get(path)
        assert response.status_code in (200, 302), f"{path} -> {response.status_code}"


def test_founder_redirects_to_team(client):
    response = client.get("/founder")
    assert response.status_code == 302
    assert "team" in response.headers.get("Location", "")


def test_unknown_url_uses_404_page(client):
    response = client.get("/no/such/page")
    assert response.status_code == 404
    assert "could not be found" in response.get_data(as_text=True).lower()


# ---------------------------------------------------------------------------
# Citizen flow
# ---------------------------------------------------------------------------
def test_signup_login_profile(client):
    email = _signup(client)
    assert client.get("/profile").status_code == 200

    client.get("/logout")
    assert _login(client, email, "Passw0rd!").status_code == 302
    assert client.get("/profile").status_code == 200
    assert client.get("/my_reports").status_code == 200


def test_password_change_requires_current_password(client):
    email = _signup(client)
    html = client.get("/profile").get_data(as_text=True)
    token = _token(html, action="/profile/password")
    assert token, "profile password form not found"

    response = client.post("/profile/password", data={
        "current_password": "wrong-pass",
        "new_password": "NewPass123!",
        "confirm_password": "NewPass123!",
        "csrf_token": token,
    }, follow_redirects=True)
    assert "incorrect" in response.get_data(as_text=True).lower()


def test_report_submission_flow(client):
    _signup(client)
    report_id = _submit_report(client)

    success = client.get(f"/report/success/{report_id}")
    assert success.status_code == 200

    detail = client.get(f"/complaint/{report_id}")
    assert detail.status_code == 200

    listing = client.get("/my_reports")
    assert listing.status_code == 200 and "Market Street" in listing.get_data(as_text=True)

    by_id = client.get(f"/track?q={report_id}")
    assert by_id.status_code == 200 and "SW-" in by_id.get_data(as_text=True)

    by_mobile = client.get("/track?q=9876543210")
    assert by_mobile.status_code == 200 and "Market Street" in by_mobile.get_data(as_text=True)


def test_duplicate_check_requires_csrf_header(client):
    _signup(client)
    page = client.get("/report").get_data(as_text=True)
    payload = {"text": "Overflowing garbage bins near the market street causing foul smell"}

    assert client.post("/report/duplicate-check", json=payload).status_code == 400

    response = client.post("/report/duplicate-check", json=payload,
                           headers={"X-CSRFToken": _meta_csrf(page)})
    assert response.status_code == 200
    assert response.get_json()["ok"] is True


def test_cannot_view_another_citizens_complaint(client):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    other = f"other.{uuid.uuid4().hex[:8]}@example.com"
    _signup(client, other)
    response = client.get(f"/complaint/{report_id}")
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Admin flow
# ---------------------------------------------------------------------------
def _admin_login(client, admin_credentials):
    return _login(client, admin_credentials["ADMIN_USERNAME"], admin_credentials["ADMIN_PASSWORD"])


def test_admin_pages_render(client, admin_credentials):
    assert _admin_login(client, admin_credentials).status_code == 302
    for path in ("/admin", "/admin/complaints", "/admin/users", "/admin/messages",
                 "/admin/audit", "/admin/map", "/admin/analytics", "/admin/models",
                 "/admin/api/overview", "/admin/export/complaints.csv"):
        response = client.get(path)
        assert response.status_code == 200, f"{path} -> {response.status_code}"


def test_admin_dashboard_renders_recommendations(client, admin_credentials):
    """Regression: recommendations is a dict whose ``items`` key must be
    indexed, not resolved as the builtin ``dict.items`` method."""
    _signup(client)
    _submit_report(client)
    client.get("/logout")

    assert _admin_login(client, admin_credentials).status_code == 302
    body = client.get("/admin").get_data(as_text=True)
    assert "Decision-support recommendations" in body
    assert "builtin_function_or_method" not in body


def test_forecast_page_renders_weekly_table(client, admin_credentials):
    """Regression: the weekly table zips two lists - Jinja has no built-in
    ``zip`` filter, so app.py must register one."""
    assert _admin_login(client, admin_credentials).status_code == 302
    response = client.get("/admin/analytics")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "No filter named" not in body
    assert "Weekly totals" in body


def test_status_update_is_visible_to_citizen(client, admin_credentials):
    email = _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    assert _admin_login(client, admin_credentials).status_code == 302
    detail = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(detail, action=f"/admin/complaint/{report_id}/status") or _token(detail)
    response = client.post(f"/admin/complaint/{report_id}/status",
                           data={"status": "In Progress", "remark": "Assigned to crew",
                                 "csrf_token": token})
    assert response.status_code in (200, 302)

    page = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    assert "In Progress" in page

    client.get("/logout")
    assert _login(client, email, "Passw0rd!").status_code == 302
    citizen_view = client.get(f"/complaint/{report_id}").get_data(as_text=True)
    assert "In Progress" in citizen_view


def test_citizen_blocked_from_admin(client, admin_credentials):
    _signup(client)
    response = client.get("/admin")
    assert response.status_code in (302, 403)
