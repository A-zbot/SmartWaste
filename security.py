"""Security helpers: CSRF protection, access decorators, audit logging and
lightweight login throttling.

Nothing here fabricates data or bypasses the real authentication checks that
already existed in SmartWaste 1.x (env-configured admin credentials and
Werkzeug password hashing for citizens).
"""

import hmac
import secrets
import threading
import time
from functools import wraps

from flask import flash, g, redirect, request, session, url_for

from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS,
)

CSRF_SESSION_KEY = "csrf_token"


# ---------------------------------------------------------------------------
# CSRF
# ---------------------------------------------------------------------------
def csrf_token():
    """Return the per-session CSRF token, creating it on first use."""
    token = session.get(CSRF_SESSION_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        session[CSRF_SESSION_KEY] = token
    return token


def _client_supplied_token():
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        return request.form.get("csrf_token") or request.headers.get("X-CSRFToken")
    return None


def _verify_csrf():
    if request.method not in ("POST", "PUT", "PATCH", "DELETE"):
        return None
    if request.endpoint in ("static", None):
        return None
    supplied = _client_supplied_token()
    expected = session.get(CSRF_SESSION_KEY, "")
    if not expected or not supplied or not hmac.compare_digest(supplied, expected):
        return ("The form expired or was submitted from an untrusted page. "
                "Please go back, refresh and try again.", 400)
    return None


def install_security(app):
    app.before_request(_verify_csrf_return)
    app.context_processor(lambda: {"csrf_token": csrf_token})


def _verify_csrf_return():
    result = _verify_csrf()
    if result is None:
        return None
    message, status = result
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return {"error": message}, status
    flash(message, "error")
    # 302 (not the 400 from _verify_csrf): browsers only follow redirects on
    # 3xx, so this is what makes the flashed error actually reach the user.
    # JSON/API callers still receive the 400 above.
    return redirect(request.referrer or url_for("public.home"))


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------
def admin_required(f):
    """Deny access to every admin-only route unless the session holds an
    authenticated admin (set solely by a successful admin login)."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if session.get("admin") is not True:
            flash("Please sign in with an administrator account.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapped


def citizen_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            flash("Please log in to view this page.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return wrapped


def active_admin_credentials_configured():
    return bool(ADMIN_USERNAME and ADMIN_PASSWORD)


def verify_admin_credentials(identifier, password):
    """Constant-time comparison against the configured admin credentials."""
    if not active_admin_credentials_configured():
        return False
    return hmac.compare_digest(identifier.encode(), ADMIN_USERNAME.encode()) and \
        hmac.compare_digest(password.encode(), ADMIN_PASSWORD.encode())


# ---------------------------------------------------------------------------
# Login throttling (in-memory, per-process)
# ---------------------------------------------------------------------------
_lock = threading.Lock()
_failures = {}


def _prune(bucket, now):
    cutoff = now - LOGIN_WINDOW_SECONDS
    bucket[:] = [ts for ts in bucket if ts > cutoff]


def login_blocked(identifier):
    now = time.time()
    with _lock:
        bucket = _failures.get(identifier)
        if not bucket:
            return False
        _prune(bucket, now)
        return len(bucket) >= LOGIN_MAX_ATTEMPTS


def record_login_failure(identifier):
    now = time.time()
    with _lock:
        bucket = _failures.setdefault(identifier, [])
        _prune(bucket, now)
        bucket.append(now)


def clear_login_failures(identifier):
    with _lock:
        _failures.pop(identifier, None)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------
def audit(action, entity=None, entity_id=None, detail=None,
          actor_type="system", actor_id=None, actor_label=None, ip=None):
    """Append an entry to audit_logs. Never raises into the request path."""
    from db import execute
    try:
        if actor_label is None and actor_type == "admin":
            actor_label = "administrator"
        if actor_label is None and actor_type == "citizen":
            actor_label = session.get("user_name") or None
        if ip is None:
            ip = request.remote_addr if request else None
        execute(
            "INSERT INTO audit_logs "
            "(actor_type, actor_id, actor_label, action, entity, entity_id, detail, ip) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (actor_type, actor_id, actor_label, action, entity,
             str(entity_id) if entity_id is not None else None, detail, ip),
        )
    except Exception:  # pragma: no cover - auditing must never break a request
        pass


def client_ip():
    return request.remote_addr if request else None
