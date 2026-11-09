"""Phase 4 tests: server-side PDF export (reportlab) and citizen status e-mail.

Covers:
* citizen receipt PDF and admin report PDF stream as ``application/pdf``
* PDF routes honour exactly the same access rules as the detail pages
* the PDF builder survives hostile / non-Latin-1 complaint text
* status-change e-mails are best-effort: skipped without SMTP, never raising,
  fired once per real transition for owner accounts only
* both UI buttons are wired to the routes
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-phase4-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402
from db import get_connection  # noqa: E402
from modules.complaints import email_service  # noqa: E402
from modules.complaints import services as complaint_services  # noqa: E402
from modules.complaints.pdf_service import build_complaint_pdf  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers (mirrors tests/test_smoke.py)
# ---------------------------------------------------------------------------
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


@pytest.fixture(autouse=True)
def no_real_smtp(monkeypatch):
    """Never open a socket to a real SMTP server while testing."""
    monkeypatch.setattr(email_service, "SMTP_USER", "")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "")


def _token(html):
    found = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    return found.group(1) if found else None


def _signup(client, email=None):
    email = email or f"phase4.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    response = client.post("/signup", data={
        "name": "Phase Four", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    assert response.status_code == 302, response.get_data(as_text=True)[:200]
    return email


def _login(client, identifier, password):
    html = client.get("/login").get_data(as_text=True)
    return client.post("/login", data={
        "username": identifier, "password": password,
        "csrf_token": _token(html),
    })


def _submit_report(client, description=None):
    html = client.get("/report").get_data(as_text=True)
    description = description or (
        "Overflowing bins near the market street causing foul smell "
        "and a serious health hazard for residents."
    )
    response = client.post("/report", data={
        "name": "Phase Four", "mobile": "9876543210",
        "location": "12 Market Street, Sector 14",
        "waste_type": "Garbage", "priority": "High",
        "description": description,
        "latitude": "28.6139", "longitude": "77.2090",
        "csrf_token": _token(html),
    })
    location = response.headers.get("Location", "")
    assert response.status_code == 302 and "success" in location, location
    return int(re.search(r"(\d+)", location.split("/")[-1]).group(1))


def _tracking_id(report_id):
    con = get_connection()
    try:
        row = con.execute(
            "SELECT tracking_id FROM reports WHERE id=?", (report_id,)
        ).fetchone()
    finally:
        con.close()
    return row["tracking_id"] if row else None


# ---------------------------------------------------------------------------
# PDF routes
# ---------------------------------------------------------------------------
def test_citizen_pdf_receipt_download(client):
    _signup(client)
    report_id = _submit_report(client)
    tracking = _tracking_id(report_id)

    response = client.get(f"/complaint/{report_id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    body = response.data
    assert body[:5] == b"%PDF-"
    assert len(body) > 1500
    disposition = response.headers["Content-Disposition"]
    assert f"{tracking}-receipt.pdf" in disposition
    # uncompressed stream keeps key fields greppable
    assert b"Overflowing" in body
    assert tracking.encode() in body
    assert b"SmartWaste 2.0" in body


def test_citizen_pdf_enforces_ownership(client):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    # anonymous viewer
    assert client.get(f"/complaint/{report_id}/pdf").status_code == 403

    # a different signed-in citizen
    _signup(client, f"other.{uuid.uuid4().hex[:8]}@example.com")
    assert client.get(f"/complaint/{report_id}/pdf").status_code == 403


def test_anonymous_complaint_pdf_follows_link_share_rule(client):
    client.get("/logout")
    report_id = _submit_report(client)  # no signed-in owner
    response = client.get(f"/complaint/{report_id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"


def test_admin_pdf_report_download(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")

    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302
    response = client.get(f"/admin/complaint/{report_id}/pdf")
    assert response.status_code == 200
    assert response.mimetype == "application/pdf"
    body = response.data
    assert body[:5] == b"%PDF-"
    assert f"{_tracking_id(report_id)}-report.pdf" in response.headers["Content-Disposition"]
    assert b"Overflowing" in body          # description rendered
    assert b"SmartWaste 2.0" in body       # brand footer
    assert b"admin copy" in body           # audience marker

    # unknown report -> 404
    assert client.get("/admin/complaint/999999/pdf").status_code == 404


def test_citizen_cannot_use_admin_pdf_route(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)
    client.get("/logout")
    # anonymous visitor -> redirected to login, never the PDF
    response = client.get(f"/admin/complaint/{report_id}/pdf")
    assert response.status_code in (302, 403)
    assert response.mimetype != "application/pdf"


def test_pdf_buttons_present_on_pages(client, admin_credentials):
    _signup(client)
    report_id = _submit_report(client)

    citizen_page = client.get(f"/complaint/{report_id}").get_data(as_text=True)
    assert "PDF receipt" in citizen_page

    client.get("/logout")
    assert _login(client, admin_credentials["ADMIN_USERNAME"],
                  admin_credentials["ADMIN_PASSWORD"]).status_code == 302
    admin_page = client.get(f"/admin/complaint/{report_id}").get_data(as_text=True)
    assert "PDF report" in admin_page


# ---------------------------------------------------------------------------
# PDF builder robustness
# ---------------------------------------------------------------------------
def test_pdf_builder_survives_hostile_content():
    report = {
        "id": 3, "tracking_id": "SW-00003", "status": "Submitted",
        "priority": "High", "waste_type": "Open Garbage",
        "ai_category": "Open Garbage", "ai_urgency": "High",
        "ai_confidence": 0.71, "ai_needs_review": 0,
        "created_at": "2026-01-01 10:00:00", "updated_at": None,
        "resolved_at": None, "location": "Zone 5 & <old quarter>",
        "area": "Sector 14", "latitude": 28.6, "longitude": 77.2,
        "source": "web", "name": "Test <user>", "mobile": "9876543210",
        "image": None, "admin_remarks": "Checked <b>twice</b>",
        "description": "Garbage 🗑️ pile <script>alert(1)</script> by the gate "
                       "— mixed Hindi/English text (Hinglish) 汉字 removed?",
    }
    pdf = build_complaint_pdf(
        report,
        history=[{"created_at": "2026-01-01 10:00:00", "old_status": None,
                  "new_status": "Submitted", "remark": "Created <ok>",
                  "actor_type": "system", "actor_label": "system"}],
        recommended_action="Dispatch a sanitation crew.",
        audience="admin",
        generated_at="2026-01-02 09:00 UTC",
    )
    assert pdf[:5] == b"%PDF-"
    # markup is escaped before Paragraph parsing - the hostile string is
    # preserved as plain text content instead of being parsed as markup
    assert b"alert" in pdf
    assert b"&lt;script&gt;" not in pdf   # never emitted as raw markup source
    assert b"Dispatch a sanitation crew." in pdf


def test_pdf_builder_citizen_variant_masks_contact():
    report = {
        "id": 4, "tracking_id": "SW-00004", "status": "Assigned",
        "priority": "Medium", "waste_type": "Plastic Waste",
        "ai_category": "Plastic Waste", "ai_urgency": "Medium",
        "ai_confidence": 0.9, "ai_needs_review": 0,
        "created_at": "2026-01-01 10:00:00", "updated_at": None,
        "resolved_at": None, "location": "Lake Road", "area": None,
        "latitude": None, "longitude": None, "source": "web",
        "name": "Ada", "mobile": "9876543210", "image": None,
        "admin_remarks": None,
        "description": "Plastic bottles dumped by the lake entrance.",
    }
    pdf = build_complaint_pdf(report, audience="citizen")
    assert pdf[:5] == b"%PDF-"
    assert b"98******10" in pdf           # masked like the web page
    assert b"9876543210" not in pdf       # raw number never rendered


def test_pdf_builder_rejects_unknown_audience():
    with pytest.raises(ValueError):
        build_complaint_pdf({"id": 1}, audience="auditor")


# ---------------------------------------------------------------------------
# Status-change e-mail (best effort)
# ---------------------------------------------------------------------------
def test_status_email_skips_without_smtp():
    # autouse fixture already cleared SMTP credentials
    assert email_service.send_status_email(
        "citizen@example.com", 7, "SW-00007", "Ada",
        "Submitted", "Assigned",
    ) is False


def test_status_email_skips_without_recipient(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "secret")
    assert email_service.send_status_email(
        "", 7, "SW-00007", "Ada", "Submitted", "Assigned",
    ) is False
    assert email_service.send_status_email(
        None, 7, "SW-00007", "Ada", "Submitted", "Assigned",
    ) is False


def test_status_email_builds_and_delivers_when_smtp_configured(monkeypatch):
    monkeypatch.setattr(email_service, "SMTP_USER", "user@example.com")
    monkeypatch.setattr(email_service, "SMTP_PASSWORD", "secret")
    delivered = {}
    monkeypatch.setattr(
        email_service, "_deliver",
        lambda msg: delivered.setdefault("msg", msg),
    )

    ok = email_service.send_status_email(
        "citizen@example.com", 7, "SW-00007", "Ada <guest>",
        "Submitted", "In Progress", remark="Crew assigned to Zone 3",
    )
    assert ok is True
    message = delivered["msg"]
    assert message["To"] == "citizen@example.com"
    assert "SW-00007" in message["Subject"]
    assert "In Progress" in message["Subject"]
    plain = "\n".join(
        part.get_payload(decode=True).decode("utf-8")
        for part in message.get_payload()
    )
    assert "Submitted" in plain
    assert "In Progress" in plain
    assert "Crew assigned to Zone 3" in plain
    assert "Ada <guest>" in plain        # name is escaped in HTML, kept in text
    html_parts = [
        part.get_payload(decode=True).decode("utf-8")
        for part in message.get_payload()
    ]
    assert any("&lt;guest&gt;" in part for part in html_parts)


class _ImmediateThread:
    """Drop-in for threading.Thread that runs the target synchronously."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args or ()
        self._kwargs = kwargs or {}

    def start(self):
        if self._target:
            self._target(*self._args, **self._kwargs)


@pytest.fixture()
def record_status_email(monkeypatch):
    calls = []
    monkeypatch.setattr(
        email_service, "send_status_email",
        lambda *args, **kwargs: calls.append(args) or True,
    )
    monkeypatch.setattr(
        complaint_services, "threading",
        type("t", (), {"Thread": _ImmediateThread}),
    )
    return calls


def test_update_status_notifies_owner(client, record_status_email):
    email = _signup(client)
    report_id = _submit_report(client)
    tracking = _tracking_id(report_id)

    result = complaint_services.update_status(
        report_id, "Assigned", remark="Crew dispatched",
    )
    assert result["ok"] is True

    assert len(record_status_email) == 1
    (to_email, sent_id, sent_tracking, name, old, new, remark) = \
        record_status_email[0]
    assert to_email == email
    assert sent_id == report_id
    assert sent_tracking == tracking
    assert old == "Submitted" and new == "Assigned"
    assert remark == "Crew dispatched"


def test_update_status_skips_email_when_status_unchanged(client,
                                                          record_status_email):
    _signup(client)
    report_id = _submit_report(client)

    result = complaint_services.update_status(report_id, "Submitted")
    assert result["ok"] is True
    assert record_status_email == []      # no transition -> no e-mail


def test_update_status_skips_email_for_anonymous_complaint(client,
                                                            record_status_email):
    client.get("/logout")
    report_id = _submit_report(client)    # no owner account

    result = complaint_services.update_status(report_id, "Under Review")
    assert result["ok"] is True
    assert record_status_email == []


def test_status_email_failure_never_breaks_status_change(client, monkeypatch):
    _signup(client)
    report_id = _submit_report(client)

    def _boom(*args, **kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr(email_service, "send_status_email", _boom)
    monkeypatch.setattr(
        complaint_services, "threading",
        type("t", (), {"Thread": _ImmediateThread}),
    )

    result = complaint_services.update_status(report_id, "In Progress")
    assert result["ok"] is True            # status change still succeeded
