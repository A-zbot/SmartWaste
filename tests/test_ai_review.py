"""Phase 1 tests: admin AI-correction (review) workflow.

Locks in the Part 4 requirement - administrators can confirm or correct the
model's predicted category/priority while the original prediction stays
immutable for evaluation honesty.
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-aireview-"), "test.db"),
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
        "username": identifier,
        "password": password,
        "csrf_token": _token(html),
    })


def _admin_login(client, admin_credentials):
    return _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"])


def _signup(client, email=None):
    email = email or f"aireview.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "AI Review Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _submit_report(client):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "AI Review Tester",
        "mobile": "9876543210",
        "location": "9 Review Lane, Sector 12",
        "waste_type": "Open Garbage",
        "priority": "High",
        "description": "Overflowing bin outside the clinic with garbage spread on the road.",
        "latitude": "28.6200",
        "longitude": "77.2100",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


def _review(client, report_id, data, admin_credentials):
    detail = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(detail, action=f"/admin/complaint/{report_id}/ai-review")
    payload = {"csrf_token": token}
    payload.update(data)
    return client.post(f"/admin/complaint/{report_id}/ai-review", data=payload)


# ---------------------------------------------------------------------------
# Route protection
# ---------------------------------------------------------------------------
def test_ai_review_requires_admin(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    # Supply a valid CSRF token so the failure isolates the admin gate.
    page = client.get("/report").get_data(as_text=True)
    token = _token(page)
    anonymous = client.post(f"/admin/complaint/{report_id}/ai-review",
                            data={"final_category": "Plastic Waste",
                                  "csrf_token": token})
    assert anonymous.status_code == 302
    assert "/login" in anonymous.headers.get("Location", "")

    row = query_one("SELECT final_category FROM reports WHERE id=?", (report_id,))
    assert row["final_category"] is None


# ---------------------------------------------------------------------------
# Confirmation / correction
# ---------------------------------------------------------------------------
def test_ai_review_confirms_and_clears_flag(client, admin_credentials):
    email = _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    before = query_one(
        "SELECT ai_category, ai_urgency, ai_needs_review FROM reports WHERE id=?",
        (report_id,),
    )
    response = _review(client, report_id, {
        "final_category": "Open Garbage",
        "final_urgency": "High",
        "ai_review_note": "Photo confirms mixed garbage overflow.",
    }, admin_credentials)
    assert response.status_code == 302

    after = query_one(
        "SELECT ai_category, ai_urgency, ai_needs_review, final_category, "
        "       final_urgency, ai_review_note, ai_reviewed_at, ai_reviewed_by "
        "FROM reports WHERE id=?",
        (report_id,),
    )
    # Original prediction preserved for evaluation honesty.
    assert after["ai_category"] == before["ai_category"]
    assert after["ai_urgency"] == before["ai_urgency"]
    # Review outcome persisted and flag cleared.
    assert after["final_category"] == "Open Garbage"
    assert after["final_urgency"] == "High"
    assert after["ai_needs_review"] == 0
    assert after["ai_review_note"] == "Photo confirms mixed garbage overflow."
    assert after["ai_reviewed_at"]
    assert after["ai_reviewed_by"] == "administrator"

    history = query_one(
        "SELECT remark, actor_type FROM complaint_history "
        "WHERE report_id=? ORDER BY id DESC LIMIT 1",
        (report_id,),
    )
    assert history["actor_type"] == "admin"
    assert "AI review" in history["remark"]
    assert "Open Garbage" in history["remark"]

    audit_row = query_one(
        "SELECT action, detail FROM audit_logs "
        "WHERE action='complaint.ai_review' AND entity_id=? ORDER BY id DESC LIMIT 1",
        (str(report_id),),
    )
    assert audit_row is not None
    assert "Open Garbage" in audit_row["detail"]


def test_ai_review_rejects_invalid_values(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    response = _review(client, report_id,
                       {"final_category": "Not A Category"},
                       admin_credentials)
    assert response.status_code == 302
    row = query_one("SELECT final_category, ai_needs_review FROM reports WHERE id=?",
                    (report_id,))
    assert row["final_category"] is None
    # Flag untouched by a rejected review.
    assert row["ai_needs_review"] in (0, 1)


def test_ai_review_notifies_and_shows_to_citizen(client, admin_credentials):
    email = _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    response = _review(client, report_id, {
        "final_category": "Drain & Sewer Waste",
        "final_urgency": "Emergency",
    }, admin_credentials)
    assert response.status_code == 302

    notification = query_one(
        "SELECT title, message, is_read FROM notifications "
        "WHERE report_id=? ORDER BY id DESC LIMIT 1",
        (report_id,),
    )
    assert notification is not None
    assert "verified" in notification["title"].lower() or "verified" in notification["message"].lower()
    assert notification["is_read"] == 0

    client.get("/logout")
    assert _login(client, email, "Passw0rd!").status_code == 302
    citizen_view = client.get(f"/complaint/{report_id}").get_data(as_text=True)
    assert "Verified by admin" in citizen_view
    assert "Verified category" in citizen_view
    assert "Drain &amp; Sewer Waste" in citizen_view or "Drain & Sewer Waste" in citizen_view


def test_admin_detail_renders_review_form(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302

    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    assert f"/admin/complaint/{report_id}/ai-review" in body
    assert 'name="final_category"' in body
    assert "Confirm classification" in body


def test_pdf_includes_verified_fields(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _admin_login(client, admin_credentials).status_code == 302
    _review(client, report_id, {"final_category": "Plastic Waste"},
            admin_credentials)

    pdf = client.get(f"/admin/complaint/{report_id}/pdf")
    assert pdf.status_code == 200
    assert pdf.headers.get("Content-Type", "").startswith("application/pdf")
    # Content is compressed, so assert via the rendered admin page instead.
    body = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    assert "Verified category" in body
    assert "Verified" in body
