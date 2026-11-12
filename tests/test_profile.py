"""Phase 7 tests: citizen profile editing (name/email).

* the profile page exposes an edit form wired to POST /profile/update
* valid submissions persist to the DB, refresh the session display name,
  record an audit entry and flash success
* duplicate emails are rejected without changing the account
* input validation matches signup rules (name length, email format)
* the endpoint is citizen-only and CSRF-protected
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
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-profile-"), "test.db"),
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


def _signup(client, email=None):
    email = email or f"prof.{uuid.uuid4().hex[:8]}@example.com"
    html = client.get("/signup").get_data(as_text=True)
    client.post("/signup", data={
        "name": "Profile Tester", "email": email, "mobile": "9876543210",
        "password": "Passw0rd!", "confirm": "Passw0rd!",
        "csrf_token": _token(html),
    })
    return email


def _update(client, data):
    html = client.get("/profile").get_data(as_text=True)
    payload = {"csrf_token": _token(html, action="/profile/update")}
    payload.update(data)
    response = client.post("/profile/update", data=payload, follow_redirects=True)
    return response.get_data(as_text=True)


def _user_row(email=None):
    if email:
        return query_one("SELECT * FROM users WHERE email=?", (email,))
    return query_one("SELECT * FROM users ORDER BY id DESC LIMIT 1")


# ---------------------------------------------------------------------------
# Form presence and successful update
# ---------------------------------------------------------------------------
def test_profile_page_offers_edit_form(client):
    _signup(client)
    page = client.get("/profile").get_data(as_text=True)
    assert 'action="/profile/update"' in page
    assert 'name="name"' in page
    assert 'name="email"' in page


def test_profile_update_persists_and_refreshes_session(client):
    _signup(client)
    original = _user_row()
    new_email = f"renamed.{uuid.uuid4().hex[:8]}@example.com"

    body = _update(client, {"name": "Renamed Citizen", "email": new_email})
    assert "Your profile has been updated." in body
    assert "Renamed Citizen" in body

    row = query_one("SELECT * FROM users WHERE id=?", (original["id"],))
    assert row["name"] == "Renamed Citizen"
    assert row["email"] == new_email

    with client.session_transaction() as sess:
        assert sess.get("user_name") == "Renamed Citizen"

    entry = query_one(
        "SELECT * FROM audit_logs WHERE action='auth.profile_updated' "
        "ORDER BY id DESC")
    assert entry is not None, "the update must be audited"
    assert new_email in (entry["detail"] or "")


# ---------------------------------------------------------------------------
# Duplicate email rejection
# ---------------------------------------------------------------------------
def test_profile_update_rejects_duplicate_email(client):
    taken = _signup(client)
    client.get("/logout")
    _signup(client)  # second, currently signed-in account

    before = _user_row()
    body = _update(client, {"name": "Copycat", "email": taken})
    assert "An account with this email already exists." in body

    after = _user_row()
    assert after["id"] == before["id"]
    assert after["email"] == before["email"], "duplicate must not change the account"
    assert after["name"] != "Copycat"


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------
def test_profile_update_validates_name_and_email(client):
    _signup(client)
    original = _user_row()

    body = _update(client, {"name": "x", "email": f"ok.{uuid.uuid4().hex[:8]}@example.com"})
    assert "valid name (2-80 characters)" in body
    assert _user_row()["name"] == original["name"]

    body = _update(client, {"name": "Fine Name", "email": "not-an-email"})
    assert "valid email address" in body
    row = _user_row()
    assert row["email"] == original["email"]
    assert row["name"] == original["name"]


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def test_profile_update_requires_login_and_csrf(client):
    # anonymous POST never reaches the view
    users_before = query_one("SELECT COUNT(*) AS n FROM users")["n"]
    response = client.post("/profile/update",
                           data={"name": "Anyone", "email": "a@b.co",
                                 "csrf_token": "forged"})
    assert response.status_code == 302
    assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == users_before

    # signed-in POST without a CSRF token is rejected by the security layer
    _signup(client)
    before = _user_row()
    body = client.post("/profile/update",
                       data={"name": "Tokenless", "email": "sneaky@example.com"},
                       follow_redirects=True).get_data(as_text=True)
    assert "form expired or was submitted from an untrusted page" in body
    row = _user_row()
    assert row["name"] == before["name"]
    assert row["email"] == before["email"]
