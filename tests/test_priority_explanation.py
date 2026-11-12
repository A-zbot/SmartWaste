"""Phase 2 tests: priority/urgency explanation display (Part 5 gap).

The backend computed ``explanation.text_features.urgency_task`` but no
template rendered it. These tests lock in the "Why this priority" card,
the urgency confidence readout and the explicit system-priority rule.
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-prioexpl-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

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


def _token(html):
    found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return found.group(1) if found else None


def _login(client, identifier, password):
    html = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={
        "username": identifier,
        "password": password,
        "csrf_token": _token(html),
    })


def _signup(client, email=None):
    email = email or f"prio.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Priority Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _submit_report(client):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Priority Tester",
        "mobile": "9876543210",
        "location": "4 Priority Road, Sector 21",
        "waste_type": "Open Garbage",
        "priority": "High",
        "description": "Overflowing garbage bins near the school gate blocking the footpath.",
        "latitude": "28.6300",
        "longitude": "77.2200",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


def test_citizen_detail_renders_priority_explanation(client):
    _signup(client)
    report_id = _submit_report(client)

    body = client.get(f"/complaint/{report_id}").get_data(as_text=True)
    assert "Why this priority" in body
    assert "Model urgency confidence" in body
    assert "System priority" in body
    assert "more urgent of your declared priority" in body.lower()


def test_admin_detail_renders_priority_explanation(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    html = client.get("/login").get_data(as_text=True)
    client.post("/login", data={
        "username": admin_credentials["ADMIN_USERNAME"],
        "password": admin_credentials["ADMIN_PASSWORD"],
        "csrf_token": _token(html),
    })
    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    assert "Why this priority" in body
    assert "System priority" in body
    assert "Context factors" in body


def test_context_factors_render_in_own_card(client):
    """Context factors used to be nested inside the category card and
    disappeared when the category block was unavailable - they now have
    their own card."""
    _signup(client)
    report_id = _submit_report(client)
    body = client.get(f"/complaint/{report_id}").get_data(as_text=True)
    assert "Context factors" in body
    # Declared-priority factor is part of the stored explanation payload.
    assert "Declared priority" in body
