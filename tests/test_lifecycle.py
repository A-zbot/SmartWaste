"""Phase 4 tests: complaint lifecycle state machine.

Locks in ``config.ALLOWED_TRANSITIONS`` enforcement in
``complaints.services.update_status`` plus the admin UI restriction to
legal next statuses.
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-lifecycle-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402
from db import query_one  # noqa: E402
from modules.complaints import services as complaint_services  # noqa: E402


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
        "username": identifier, "password": password,
        "csrf_token": _token(html),
    })


def _signup(client, email=None):
    email = email or f"life.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Lifecycle Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _submit_report(client):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Lifecycle Tester",
        "mobile": "9876543210",
        "location": "2 Lifecycle Avenue",
        "waste_type": "Open Garbage",
        "priority": "Medium",
        "description": "Lifecycle fixture complaint used by the state machine tests.",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


def _status_of(report_id):
    return query_one("SELECT status FROM reports WHERE id=?", (report_id,))["status"]


# ---------------------------------------------------------------------------
# Service-level enforcement
# ---------------------------------------------------------------------------
def test_legal_lifecycle_walk_succeeds(client):
    _signup(client)
    report_id = _submit_report(client)
    for step in ("Under Review", "Assigned", "In Progress", "Resolved"):
        result = complaint_services.update_status(report_id, step)
        assert result["ok"], f"{step}: {result.get('error')}"
        assert _status_of(report_id) == step


def test_illegal_jump_from_submitted_is_rejected(client):
    _signup(client)
    report_id = _submit_report(client)
    result = complaint_services.update_status(report_id, "Resolved")
    assert result["ok"] is False
    assert "Illegal status change" in result["error"]
    assert _status_of(report_id) == "Submitted"


def test_rejected_cannot_jump_to_resolved(client):
    _signup(client)
    report_id = _submit_report(client)
    assert complaint_services.update_status(report_id, "Rejected")["ok"] is True
    result = complaint_services.update_status(report_id, "Resolved")
    assert result["ok"] is False
    assert _status_of(report_id) == "Rejected"


def test_appeal_and_reopen_paths_are_legal(client):
    _signup(client)
    rejected_id = _submit_report(client)
    assert complaint_services.update_status(rejected_id, "Rejected")["ok"] is True
    assert complaint_services.update_status(rejected_id, "Under Review")["ok"] is True
    assert _status_of(rejected_id) == "Under Review"

    resolved_id = _submit_report(client)
    for step in ("Under Review", "Assigned", "In Progress", "Resolved"):
        assert complaint_services.update_status(resolved_id, step)["ok"] is True
    assert complaint_services.update_status(resolved_id, "In Progress")["ok"] is True
    assert _status_of(resolved_id) == "In Progress"


def test_same_status_remark_update_still_allowed(client):
    _signup(client)
    report_id = _submit_report(client)
    result = complaint_services.update_status(
        report_id, "Submitted", remark="note only",
    )
    assert result["ok"] is True
    assert _status_of(report_id) == "Submitted"


# ---------------------------------------------------------------------------
# UI enforcement
# ---------------------------------------------------------------------------
def test_admin_dropdown_offers_only_legal_next_statuses(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302

    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    match = re.search(r'<select name="status" required>(.*?)</select>', body, re.S)
    assert match, "status select missing"
    options = re.findall(r'<option value="([^"]+)"', match.group(1))
    assert options == ["Submitted", "Under Review", "Rejected"]

    # After moving to Under Review the legal set changes.
    token = _token(body)
    client.post(f"/admin/complaint/{report_id}/status",
                data={"status": "Under Review", "csrf_token": token})
    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    match = re.search(r'<select name="status" required>(.*?)</select>', body, re.S)
    options = re.findall(r'<option value="([^"]+)"', match.group(1))
    assert options == ["Under Review", "Assigned", "Rejected"]


def test_illegal_post_is_refused_with_error(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302

    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(body)
    # Craft an illegal transition the UI no longer offers.
    response = client.post(
        f"/admin/complaint/{report_id}/status",
        data={"status": "Resolved", "csrf_token": token},
        follow_redirects=True,
    )
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "Illegal status change" in page
    assert _status_of(report_id) == "Submitted"
