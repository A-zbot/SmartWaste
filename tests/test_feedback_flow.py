"""Master prompt tests: citizen feedback authorisation, admin prediction
feedback logging, dashboard panels, upload validation, XSS regression
guards and cache policy (Phases 6, 7, 8, 9).
"""

import io
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-feedback-"), "test.db"),
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
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


def _signup(client, email=None):
    email = email or f"feedback.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    response = client.post("/signup", data={
        "name": "Feedback Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    assert response.status_code in (200, 302)
    return email


def _submit_report(client, **overrides):
    html = client.get("/report").get_data(as_text=True)
    payload = {
        "name": "Feedback Tester",
        "mobile": "9876543210",
        "location": "3 Feedback Lane, Sector 12",
        "waste_type": "Open Garbage",
        "priority": "High",
        "description": "Garbage has been lying on the road for three days.",
        "csrf_token": _token(html),
    }
    payload.update(overrides)
    response = client.post("/report", data=payload)
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


def _walk_to_resolved(report_id):
    from modules.complaints import services as complaint_services

    for step in ("Under Review", "Assigned", "In Progress", "Resolved"):
        result = complaint_services.update_status(report_id, step)
        assert result["ok"], result


def _feedback_count(report_id):
    row = query_one("SELECT COUNT(*) AS n FROM feedback WHERE report_id=?",
                    (report_id,))
    return row["n"]


def _detail(client, report_id):
    return client.get(f"/complaint/{report_id}").get_data(as_text=True)


def _post_feedback(client, report_id, **fields):
    html = _detail(client, report_id)
    token = _token(html, action=f"/complaint/{report_id}/feedback")
    payload = {"csrf_token": token, "rating": "5", "comment": "Handled quickly."}
    payload.update(fields)
    return client.post(f"/complaint/{report_id}/feedback", data=payload)


def _user_id_by_email(email):
    row = query_one("SELECT id FROM users WHERE email=?", (email,))
    return row["id"] if row else None


# ---------------------------------------------------------------------------
# Citizen feedback authorisation
# ---------------------------------------------------------------------------
def test_feedback_form_hidden_from_non_owner(client):
    _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)
    client.get("/logout")

    email_b = _signup(client)
    _login(client, email_b, "Passw0rd!")
    response = client.get(f"/complaint/{report_id}")
    assert response.status_code == 403  # citizens cannot view others' complaints


def test_feedback_note_shown_when_owner_is_not_viewer(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)
    client.get("/logout")

    _login(client, admin_credentials["ADMIN_USERNAME"],
           admin_credentials["ADMIN_PASSWORD"])
    html = _detail(client, report_id)
    assert "Only the citizen who submitted this complaint can rate it." in html
    assert f'action="/complaint/{report_id}/feedback"' not in html


def test_feedback_anonymous_blocked_for_owned_complaint(client):
    _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)
    client.get("/logout")

    response = _post_feedback(client, report_id)
    assert response.status_code == 302
    assert _feedback_count(report_id) == 0


def test_feedback_other_user_rejected(client):
    _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)
    client.get("/logout")

    email_b = _signup(client)
    _login(client, email_b, "Passw0rd!")
    _post_feedback(client, report_id)
    assert _feedback_count(report_id) == 0


def test_feedback_owner_succeeds_and_persists_once(client):
    email_a = _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)

    response = _post_feedback(client, report_id)
    assert response.status_code == 302
    assert _feedback_count(report_id) == 1

    row = query_one("SELECT user_id, rating, comment FROM feedback WHERE report_id=?",
                    (report_id,))
    assert row["user_id"] == _user_id_by_email(email_a)
    assert row["rating"] == 5

    # Duplicate rating is refused by the unique constraint.
    _post_feedback(client, report_id, rating="4")
    assert _feedback_count(report_id) == 1

    html = _detail(client, report_id)
    assert "You rated this complaint" in html


def test_feedback_guest_requires_matching_mobile(client):
    report_id = _submit_report(client)  # no session - guest complaint
    row = query_one("SELECT user_id, mobile FROM reports WHERE id=?", (report_id,))
    assert row["user_id"] is None
    _walk_to_resolved(report_id)

    html = _detail(client, report_id)
    assert "Verification for anonymous reports" in html

    _post_feedback(client, report_id, mobile="0000000000")
    assert _feedback_count(report_id) == 0

    _post_feedback(client, report_id, mobile="9876543210")
    assert _feedback_count(report_id) == 1
    assert query_one("SELECT user_id FROM feedback WHERE report_id=?",
                     (report_id,))["user_id"] is None


def test_feedback_service_refuses_before_resolution(client):
    from modules.complaints import services as complaint_services

    email = _signup(client)
    report_id = _submit_report(client)
    result = complaint_services.submit_feedback(
        report_id, _user_id_by_email(email), 5)
    assert result["ok"] is False
    assert "resolved" in result["error"].lower()
    assert _feedback_count(report_id) == 0


def test_feedback_rating_bounds_enforced(client):
    from modules.complaints import services as complaint_services

    email = _signup(client)
    report_id = _submit_report(client)
    _walk_to_resolved(report_id)
    uid = _user_id_by_email(email)

    assert complaint_services.submit_feedback(report_id, uid, 0)["ok"] is False
    assert complaint_services.submit_feedback(report_id, uid, 6)["ok"] is False
    assert complaint_services.submit_feedback(report_id, uid, "x")["ok"] is False
    assert _feedback_count(report_id) == 0


# ---------------------------------------------------------------------------
# Admin prediction feedback logging
# ---------------------------------------------------------------------------
def test_ai_review_writes_prediction_feedback_row(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    _login(client, admin_credentials["ADMIN_USERNAME"],
           admin_credentials["ADMIN_PASSWORD"])
    detail = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(detail, action=f"/admin/complaint/{report_id}/ai-review")
    response = client.post(f"/admin/complaint/{report_id}/ai-review", data={
        "final_category": "Plastic Waste",
        "final_urgency": "Low",
        "csrf_token": token,
    })
    assert response.status_code == 302

    row = query_one("SELECT * FROM prediction_feedback WHERE report_id=?",
                    (report_id,))
    assert row is not None, "ai-review must log administrator feedback"
    assert row["model_name"] in (None, "Random Forest", "Logistic Regression")
    assert row["model_version"], "model version must travel with the review"
    assert row["was_correction"] == 1
    assert row["corrected_category"] == "Plastic Waste"
    assert row["admin_label"] == admin_credentials["ADMIN_USERNAME"]

    original = query_one("SELECT ai_category FROM reports WHERE id=?",
                         (report_id,))
    assert row["original_category"] == original["ai_category"]


def test_dashboard_renders_prediction_feedback_stats(client, admin_credentials):
    _login(client, admin_credentials["ADMIN_USERNAME"],
           admin_credentials["ADMIN_PASSWORD"])
    html = client.get("/admin").get_data(as_text=True)
    assert "Administrator feedback" in html
    assert "Reviews recorded" in html


# ---------------------------------------------------------------------------
# Dashboard panels (Phase 7)
# ---------------------------------------------------------------------------
def test_dashboard_renders_pending_forecast_and_duplicate_panels(
        client, admin_credentials):
    _login(client, admin_credentials["ADMIN_USERNAME"],
           admin_credentials["ADMIN_PASSWORD"])
    html = client.get("/admin").get_data(as_text=True)
    assert 'id="kpiPending"' in html
    assert "Forecast (next" in html
    assert "Duplicate complaints" in html
    assert "linked" in html
    # Honest empty states - never fabricated numbers.
    assert "No complaints are recorded as duplicates yet" in html or "Duplicate of" in html


# ---------------------------------------------------------------------------
# Upload validation (M8)
# ---------------------------------------------------------------------------
def _multipart(client, filename, content):
    html = client.get("/report").get_data(as_text=True)
    data = {
        "name": "Upload Tester",
        "mobile": "9876543210",
        "location": "4 Upload Street, Sector 9",
        "waste_type": "Open Garbage",
        "priority": "High",
        "description": "Garbage has been lying on the road for three days.",
        "image": (io.BytesIO(content), filename),
        "csrf_token": _token(html),
    }
    return client.post("/report", data=data, content_type="multipart/form-data")


def _report_count():
    return query_one("SELECT COUNT(*) AS n FROM reports")["n"]


def test_report_rejects_dangerous_upload_extension(client):
    before = _report_count()
    response = _multipart(client, "shell.php", b"<?php echo 1; ?>")
    assert response.status_code == 302
    assert "/report" in response.headers.get("Location", "")
    assert _report_count() == before


def test_report_rejects_file_with_fake_image_signature(client):
    before = _report_count()
    response = _multipart(client, "fake.png", b"<script>alert(1)</script>")
    assert response.status_code == 302
    assert _report_count() == before


def test_report_accepts_file_with_valid_png_signature(client, monkeypatch):
    import modules.complaints.services as services

    upload_dir = tempfile.mkdtemp(prefix="smartwaste-uploads-")
    monkeypatch.setattr(services, "UPLOAD_FOLDER", upload_dir)

    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    response = _multipart(client, "photo.png", png)
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    report_id = int(re.search(r"(\d+)", location.split("/")[-1]).group(1))
    row = query_one("SELECT image FROM reports WHERE id=?", (report_id,))
    assert row["image"]
    assert os.path.isfile(os.path.join(upload_dir, row["image"]))


def test_legacy_category_alias_is_normalised(client):
    report_id = _submit_report(client, waste_type="Garbage")
    row = query_one("SELECT waste_type FROM reports WHERE id=?", (report_id,))
    assert row["waste_type"] == "Open Garbage"


def test_unknown_category_rejected_by_route(client):
    before = _report_count()
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Route Tester",
        "mobile": "9876543210",
        "location": "5 Route Street",
        "waste_type": "Nuclear Waste",
        "priority": "High",
        "description": "Garbage has been lying on the road for three days.",
        "csrf_token": _token(html),
    })
    assert response.status_code == 302
    assert _report_count() == before


# ---------------------------------------------------------------------------
# XSS regression guard (H1) + cache policy (Phase 8)
# ---------------------------------------------------------------------------
def test_duplicate_panel_escapes_dynamic_fields():
    with open(os.path.join(REPO_ROOT, "static", "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    for field in ("m.tracking_id", "m.category", "m.status", "m.location",
                  "m.created_at"):
        assert f"escapeHtml({field})" in js, f"{field} must be escaped"
    assert "escapeHtml(data.error" in js
    assert "escapeHtml(data.checked" in js
    assert "escapeHtml(data.window_days" in js
    assert "escapeHtml(data.warnings" in js


def test_html_responses_are_no_store(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "no-store" in response.headers.get("Cache-Control", "")
