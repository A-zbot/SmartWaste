"""Phase 5 tests: duplicate-complaint workflow.

* debounced auto duplicate-check hook in static/app.js
* admin "link as duplicate" (with optional reject) and unlink
* badges/notes surfaced to admins and citizens
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-duplink-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402
from db import query_one  # noqa: E402


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
    email = email or f"dup.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Duplicate Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _submit_report(client, location="5 Duplicate Street"):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Duplicate Tester",
        "mobile": "9876543210",
        "location": location,
        "waste_type": "Open Garbage",
        "priority": "Low",
        "description": "Overflowing bins at the duplicate fixture location for testing.",
        "csrf_token": _token(html),
    })
    location_hdr = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location_hdr, location_hdr
    return int(re.search(r"(\d+)", location_hdr.split("/")[-1]).group(1))


def _link(client, report_id, data, admin_credentials):
    detail = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(detail, action=f"/admin/complaint/{report_id}/duplicate")
    payload = {"csrf_token": token}
    payload.update(data)
    return client.post(f"/admin/complaint/{report_id}/duplicate", data=payload)


# ---------------------------------------------------------------------------
# Static guard: debounced auto-check exists
# ---------------------------------------------------------------------------
def test_app_js_auto_runs_duplicate_check():
    with open(os.path.join(REPO_ROOT, "static", "app.js"), encoding="utf-8") as fh:
        source = fh.read()
    assert "descField.addEventListener('input'" in source
    assert "dupTimer = setTimeout(checkDuplicates, 600)" in source


# ---------------------------------------------------------------------------
# Link / unlink workflow
# ---------------------------------------------------------------------------
def test_link_duplicate_records_history_audit_and_badges(client, admin_credentials):
    email = _signup(client)
    original_id = _submit_report(client, location="1 Original Road")
    duplicate_id = _submit_report(client, location="2 Original Road")
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    original_ref = query_one(
        "SELECT tracking_id FROM reports WHERE id=?", (original_id,))["tracking_id"]
    response = _link(client, duplicate_id, {"duplicate_of": original_ref},
                     admin_credentials)
    assert response.status_code == 302

    row = query_one(
        "SELECT duplicate_of_report_id FROM reports WHERE id=?", (duplicate_id,))
    assert row["duplicate_of_report_id"] == original_id

    history = query_one(
        "SELECT remark FROM complaint_history WHERE report_id=? ORDER BY id DESC LIMIT 1",
        (duplicate_id,))
    assert original_ref in history["remark"]

    audit_row = query_one(
        "SELECT detail FROM audit_logs WHERE action='complaint.linked_duplicate' "
        "AND entity_id=? ORDER BY id DESC LIMIT 1", (str(duplicate_id),))
    assert audit_row is not None
    assert original_ref in audit_row["detail"]

    # Badge on the admin queue, note + unlink form on the admin detail page.
    queue = client.get("/admin/complaints").get_data(as_text=True)
    assert '<span class="badge badge-warn">duplicate</span>' in queue
    admin_detail = client.get(f"/admin/complaint/{duplicate_id}").get_data(as_text=True)
    assert original_ref in admin_detail
    assert "Remove duplicate link" in admin_detail

    # Citizen sees the linkage note on their own complaint.
    client.get("/logout")
    assert _login(client, email, "Passw0rd!").status_code == 302
    citizen_view = client.get(f"/complaint/{duplicate_id}").get_data(as_text=True)
    assert "linked this complaint to the earlier report" in citizen_view
    assert original_ref in citizen_view


def test_link_duplicate_rejects_self_and_missing(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    ref = query_one("SELECT tracking_id FROM reports WHERE id=?",
                    (report_id,))["tracking_id"]

    response = _link(client, report_id, {"duplicate_of": ref}, admin_credentials)
    follow = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "cannot be a duplicate of itself" in follow
    assert query_one("SELECT duplicate_of_report_id FROM reports WHERE id=?",
                     (report_id,))["duplicate_of_report_id"] is None

    response = _link(client, report_id, {"duplicate_of": "SW-99999"},
                     admin_credentials)
    follow = client.get(response.headers["Location"]).get_data(as_text=True)
    assert "does not exist" in follow


def test_link_duplicate_with_reject_sets_status(client, admin_credentials):
    _signup(client)
    original_id = _submit_report(client, location="8 Origin Lane")
    duplicate_id = _submit_report(client, location="8B Origin Lane")
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    original_ref = query_one("SELECT tracking_id FROM reports WHERE id=?",
                             (original_id,))["tracking_id"]
    response = _link(client, duplicate_id,
                     {"duplicate_of": original_ref, "reject_duplicate": "on"},
                     admin_credentials)
    assert response.status_code == 302
    row = query_one("SELECT status, duplicate_of_report_id FROM reports WHERE id=?",
                    (duplicate_id,))
    assert row["duplicate_of_report_id"] == original_id
    assert row["status"] == "Rejected"


def test_clear_duplicate_unlinks(client, admin_credentials):
    _signup(client)
    original_id = _submit_report(client, location="3 Origin Way")
    duplicate_id = _submit_report(client, location="4 Origin Way")
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    original_ref = query_one("SELECT tracking_id FROM reports WHERE id=?",
                             (original_id,))["tracking_id"]
    _link(client, duplicate_id, {"duplicate_of": original_ref}, admin_credentials)

    detail = client.get(f"/admin/complaint/{duplicate_id}").get_data(as_text=True)
    token = _token(detail, action=f"/admin/complaint/{duplicate_id}/duplicate/clear")
    response = client.post(f"/admin/complaint/{duplicate_id}/duplicate/clear",
                           data={"csrf_token": token})
    assert response.status_code == 302
    assert query_one("SELECT duplicate_of_report_id FROM reports WHERE id=?",
                     (duplicate_id,))["duplicate_of_report_id"] is None


def test_link_duplicate_requires_admin(client):
    _signup(client)
    report_id = _submit_report(client)
    page = client.get("/report").get_data(as_text=True)
    response = client.post(f"/admin/complaint/{report_id}/duplicate",
                           data={"duplicate_of": "SW-00001",
                                 "csrf_token": _token(page)})
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    assert query_one("SELECT duplicate_of_report_id FROM reports WHERE id=?",
                     (report_id,))["duplicate_of_report_id"] is None
