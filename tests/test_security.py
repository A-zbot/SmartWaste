"""Phase 6 security regression tests.

Locks in the platform hardening:

* baseline security headers on HTML and binary (PDF) responses
* CSRF enforcement on form POSTs
* session cookie flags (HttpOnly, SameSite=Lax)
* ``admin_required`` and the citizen-facing status route
* login throttling units and admin credential verification
* audit trail rows for status transitions
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-security-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402
from db import query_one  # noqa: E402
import security  # noqa: E402


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


def _signup(client, email=None):
    email = email or f"sec.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Security Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _login(client, identifier, password):
    html = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={
        "username": identifier, "password": password,
        "csrf_token": _token(html),
    })


def _submit_report(client):
    html = client.get("/report").get_data(as_text=True)
    response = client.post("/report", data={
        "name": "Security Tester", "mobile": "9876543210",
        "location": "7 Security Lane", "waste_type": "Garbage",
        "priority": "Low",
        "description": "Security fixture complaint used by the phase six tests.",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


# ---------------------------------------------------------------------------
# Headers
# ---------------------------------------------------------------------------
def test_security_headers_on_html_responses(client):
    for path in ("/", "/login", "/report"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("Referrer-Policy") == "same-origin"


def test_security_headers_on_binary_responses(client):
    _signup(client)
    report_id = _submit_report(client)
    response = client.get(f"/complaint/{report_id}/pdf")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def test_form_post_without_csrf_token_is_rejected(client):
    _signup(client)
    response = client.post("/report", data={
        "name": "No Token", "mobile": "9876543210",
        "location": "1 Nowhere Road", "waste_type": "Garbage",
        "priority": "Low", "description": "Attempting to post without a CSRF token.",
    })
    # Browsers must be redirected (3xx) so the flashed error is reachable;
    # the submission itself is rejected either way.
    assert response.status_code == 302
    followed = client.get(response.headers["Location"])
    assert followed.status_code == 200
    assert "expired" in followed.get_data(as_text=True).lower() or \
        "untrusted" in followed.get_data(as_text=True).lower()
    from db import query_one
    row = query_one("SELECT COUNT(*) AS n FROM reports WHERE name=?", ("No Token",))
    assert row["n"] == 0


def test_json_post_without_csrf_header_is_rejected(client):
    _signup(client)
    response = client.post("/report/duplicate-check",
                           json={"text": "overflowing garbage bins"})
    assert response.status_code == 400
    assert response.get_json()["error"]


# ---------------------------------------------------------------------------
# Session cookie
# ---------------------------------------------------------------------------
def test_session_cookie_flags(client):
    response = client.get("/")
    cookie = response.headers.get("Set-Cookie", "")
    assert "session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_admin_route_redirects_anonymous_visitors(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_citizen_cannot_post_status_change(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    # signed-in citizen with a valid CSRF token, but no admin session
    page = client.get("/report").get_data(as_text=True)
    token = _token(page)
    assert token, "report form must expose a CSRF token"
    response = client.post(
        f"/admin/complaint/{report_id}/status",
        data={"status": "Resolved", "csrf_token": token},
    )
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    row = query_one("SELECT status FROM reports WHERE id=?", (report_id,))
    assert row["status"] != "Resolved"  # never applied


# ---------------------------------------------------------------------------
# Login throttling / credentials
# ---------------------------------------------------------------------------
def test_login_throttling_blocks_after_repeated_failures():
    identifier = f"throttle.{uuid.uuid4().hex[:8]}@example.com"
    assert security.login_blocked(identifier) is False
    for _ in range(security.LOGIN_MAX_ATTEMPTS):
        security.record_login_failure(identifier)
    assert security.login_blocked(identifier) is True
    security.clear_login_failures(identifier)
    assert security.login_blocked(identifier) is False


def test_admin_credentials_verification(admin_credentials):
    assert security.active_admin_credentials_configured() is True
    username = admin_credentials["ADMIN_USERNAME"]
    assert security.verify_admin_credentials(username, "definitely-wrong") is False
    assert security.verify_admin_credentials("nobody", admin_credentials["ADMIN_PASSWORD"]) is False
    assert security.verify_admin_credentials(
        username, admin_credentials["ADMIN_PASSWORD"]
    ) is True


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------
def test_status_change_writes_audit_entry(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302

    detail = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    token = _token(detail) or _token(client.get("/report").get_data(as_text=True))
    assert token, "no CSRF token available"
    response = client.post(
        f"/admin/complaint/{report_id}/status",
        data={"status": "Under Review", "remark": "audit trail check",
              "csrf_token": token},
    )
    assert response.status_code in (200, 302)

    row = query_one(
        "SELECT * FROM audit_logs WHERE action='complaint.status_changed' "
        "AND entity_id=? ORDER BY id DESC LIMIT 1",
        (str(report_id),),
    )
    assert row is not None, "status change must be audited"
    assert "Under Review" in (row["detail"] or "")


# ---------------------------------------------------------------------------
# Phase 3 hardening: CSP/HSTS, legacy GET confirmation, e-mail escaping
# ---------------------------------------------------------------------------
def test_csp_and_permissions_policy_headers(client):
    response = client.get("/")
    csp = response.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "object-src 'none'" in csp
    policy = response.headers.get("Permissions-Policy", "")
    assert "geolocation=(self)" in policy
    assert "camera=()" in policy


def test_legacy_status_get_requires_csrf_confirmation(client, admin_credentials):
    """The 1.x GET link must never mutate state directly - it renders a
    confirmation whose form POSTs (with CSRF) to the real endpoint."""
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302

    page = client.get(f"/update_status/{report_id}/Under Review")
    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Confirm" in body
    row = query_one("SELECT status FROM reports WHERE id=?", (report_id,))
    assert row["status"] != "Under Review", "GET must not change the status"

    token = _token(body)
    assert token, "confirmation page must expose a CSRF token"
    response = client.post(
        f"/admin/complaint/{report_id}/status",
        data={"status": "Under Review", "csrf_token": token},
    )
    assert response.status_code == 302
    row = query_one("SELECT status FROM reports WHERE id=?", (report_id,))
    assert row["status"] == "Under Review"


def test_legacy_status_get_unknown_status_is_404(client, admin_credentials):
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302
    assert client.get("/update_status/1/NotAStatus").status_code == 404


def test_legacy_status_get_requires_admin(client):
    response = client.get("/update_status/1/Resolved")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_report_email_escapes_hostile_html(monkeypatch):
    from modules.complaints import email_service

    captured = {}
    monkeypatch.setattr(email_service, "_smtp_ready", lambda: True)
    monkeypatch.setattr(email_service, "REPORT_NOTIFY_EMAIL", "admin@example.com")
    monkeypatch.setattr(
        email_service, "_deliver",
        lambda msg: captured.setdefault("msg", msg),
    )

    hostile = '<script>alert("xss")</script>'
    email_service.send_report_email(
        1, hostile, "9876543210", hostile, "Open Garbage", "High",
        hostile, None, created_at="2026-01-01 00:00:00",
    )
    msg = captured.get("msg")
    assert msg is not None, "e-mail was not built"

    html_part = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            html_part = part.get_payload(decode=True).decode("utf-8", "replace")
    assert html_part is not None
    assert "<script>" not in html_part, "raw HTML from the citizen must be escaped"
    assert "&lt;script&gt;" in html_part
