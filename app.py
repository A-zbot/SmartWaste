"""SmartWaste 2.0 - AI-Driven Urban Waste Management and Predictive Decision
Support System.

Application factory. The module-level ``app`` object is what gunicorn imports
(``gunicorn app:app`` - see Procfile / render.yaml).

Layout:
    config.py        tunable application / ML / forecasting parameters
    db.py            SQLite schema + forward-only migrations
    security.py      CSRF, access control, audit logging, login throttling
    modules/         Flask blueprints (public, auth, complaints, admin, analytics)
    intelligence/    ML & geospatial pipeline (trained models live in models/)
"""

import logging
import os
from datetime import datetime, timezone

from flask import Flask, render_template, request, session

import config
from db import init_db
from modules import register_blueprints
from security import install_security

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
def create_app():
    app = Flask(__name__)
    app.secret_key = config.SECRET_KEY
    app.config.update(
        MAX_CONTENT_LENGTH=config.MAX_CONTENT_LENGTH,
        SESSION_COOKIE_HTTPONLY=config.SESSION_COOKIE_HTTPONLY,
        SESSION_COOKIE_SAMESITE=config.SESSION_COOKIE_SAMESITE,
        SESSION_COOKIE_SECURE=config.SESSION_COOKIE_SECURE,
        UPLOAD_FOLDER=config.UPLOAD_FOLDER,
        JSON_SORT_KEYS=False,
    )
    os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)

    init_db()
    install_security(app)
    _install_security_headers(app)
    register_blueprints(app)
    _register_template_helpers(app)
    _register_context_processors(app)
    _register_error_handlers(app)
    _log_startup_warnings(app)
    ensure_models_ready()
    return app


def _install_security_headers(app):
    """Baseline hardening headers on every response (never overrides a
    response that already sets its own value).

    CSP notes: styles and scripts are heavily inline in the server-rendered
    templates (``onclick`` handlers, JSON data islands), so ``'unsafe-inline'``
    is required for both; the policy still pins every external origin to
    ``'self'`` plus the OpenStreetMap tile CDN used by the Leaflet map.
    HSTS is only emitted in production (never over plain-HTTP dev servers).
    """
    csp = "; ".join([
        "default-src 'self'",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: https://*.tile.openstreetmap.org",
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'self'",
    ])

    @app.after_request
    def _apply_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(self), camera=(), microphone=(), payment=()",
        )
        if config.IS_PRODUCTION:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


# ---------------------------------------------------------------------------
# Template helpers
# ---------------------------------------------------------------------------
def _register_template_helpers(app):
    @app.template_filter("mask_name")
    def mask_name(value):
        v = (value or "").strip()
        if len(v) <= 2:
            return "*" * len(v)
        return v[0] + "*" * (len(v) - 2) + v[-1]

    @app.template_filter("mask_mobile")
    def mask_mobile(value):
        digits = "".join(ch for ch in (value or "") if ch.isdigit())
        if len(digits) < 4:
            return "*" * len(digits)
        return digits[:2] + "*" * (len(digits) - 4) + digits[-2:]

    @app.template_filter("dt")
    def format_datetime(value, fmt="%d %b %Y, %H:%M"):
        if not value:
            return "-"
        if isinstance(value, datetime):
            return value.strftime(fmt)
        text = str(value).replace("T", " ")
        for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f",
                        "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(text[:26], pattern).strftime(fmt)
            except ValueError:
                continue
        return str(value)

    @app.template_filter("dateonly")
    def format_date(value):
        return format_datetime(value, "%d %b %Y")

    @app.template_filter("hours_since")
    def hours_since(value):
        if not value:
            return None
        stamp = str(value).replace("T", " ")[:19]
        try:
            moment = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        delta = datetime.now(timezone.utc).replace(tzinfo=None) - moment
        return round(delta.total_seconds() / 3600.0, 1)

    @app.template_filter("status_class")
    def status_class(value):
        return (value or "").lower().replace(" ", "-")

    @app.template_filter("zip")
    def zip_filter(a, b):
        """Pair two sequences (Jinja has no built-in zip filter)."""
        return list(zip(a or [], b or []))


# ---------------------------------------------------------------------------
# Context processors
# ---------------------------------------------------------------------------
def _register_context_processors(app):
    @app.context_processor
    def inject_globals():
        context = {
            "app_name": "SmartWaste",
            "nav_unread": 0,
            "admin_messages": 0,
            "current_year": datetime.now(timezone.utc).year,
            "categories": config.CATEGORIES,
            "statuses": config.COMPLAINT_STATUSES,
            "priorities": config.PRIORITIES,
        }
        try:
            if session.get("user_id"):
                from db import query_one
                row = query_one(
                    "SELECT COUNT(*) AS n FROM notifications "
                    "WHERE user_id=? AND is_read=0",
                    (session["user_id"],),
                )
                context["nav_unread"] = row["n"] if row else 0
            if session.get("admin") is True:
                from db import query_one
                row = query_one("SELECT COUNT(*) AS n FROM messages")
                context["admin_messages"] = row["n"] if row else 0
        except Exception:  # pragma: no cover - never break page rendering
            logger.exception("context processor failed")
        return context


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------
def _register_error_handlers(app):
    errors = {
        403: "You do not have permission to view this page.",
        404: "The page or record you requested could not be found.",
        413: "The uploaded file is too large (max 5 MB).",
        500: "Something went wrong on our side. Please try again.",
    }

    def handler(code):
        def view(error):
            message = errors.get(code, str(error))
            return render_template("error.html", code=code, message=message), code
        return view

    for code in errors:
        app.register_error_handler(code, handler(code))


# ---------------------------------------------------------------------------
# Model availability
# ---------------------------------------------------------------------------
def ensure_models_ready():
    """Train the complaint models in the background if artifacts are missing.

    Artifacts normally ship with the repository (models/). If they are absent
    (fresh clone) and AUTO_TRAIN_MODELS is not disabled, we train from the
    committed labelled dataset so the application never has to fake a
    prediction. Until training finishes the UI reports "model not trained".
    """
    if os.environ.get("AUTO_TRAIN_MODELS", "1") == "0":
        return
    from intelligence import _model_store
    if _model_store.any_trained():
        return
    if not os.path.isfile(config.TRAINING_DATA):
        logger.warning("No trained models and no dataset at %s - AI features "
                       "will report 'model not trained'.", config.TRAINING_DATA)
        return

    def _train():
        logger.info("Models missing - training from %s ...", config.TRAINING_DATA)
        try:
            from intelligence.model_training import train_all
            summary = train_all(progress=lambda msg: logger.info(msg))
            logger.info("Model training finished: %s",
                        {k: v["name"] for k, v in summary["tasks"].items()})
        except Exception:
            logger.exception("Automatic model training failed")

    import threading
    threading.Thread(target=_train, daemon=True, name="model-training").start()


def _log_startup_warnings(app):
    if config.SECRET_KEY_IS_EPHEMERAL:
        logger.warning(
            "SECRET_KEY missing or weak - using an ephemeral development key. "
            "Set a long random SECRET_KEY in .env for stable sessions."
        )
    if not (config.ADMIN_USERNAME and config.ADMIN_PASSWORD):
        logger.warning(
            "ADMIN_USERNAME/ADMIN_PASSWORD are not set - admin login will be rejected."
        )
    if not (config.SMTP_USER and config.SMTP_PASSWORD):
        logger.info("SMTP not configured - notification e-mails are skipped.")
    from intelligence import _model_store
    if not _model_store.any_trained():
        logger.warning(
            "ML artifacts not found in %s - run `python scripts/train_models.py`.",
            config.MODEL_DIR,
        )


app = create_app()

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )
