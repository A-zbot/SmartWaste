"""Central configuration for SmartWaste 2.0.

All tunable application, ML, geospatial and forecasting parameters live here so
that behaviour is auditable and reproducible. Secrets are read from the
environment (.env in development) and are never hard-coded.
"""

import os
import secrets

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
# Never sign session cookies with a placeholder or other weak key.
WEAK_SECRET_KEYS = {
    "", "secret", "changeme", "change-me", "change_this_password",
    "dev", "development", "replace-with-a-long-random-secret",
}

IS_PRODUCTION = bool(os.environ.get("RENDER")) or os.environ.get("FLASK_ENV") == "production"


def _resolve_secret_key():
    key = os.environ.get("SECRET_KEY", "").strip()
    if key.lower() in WEAK_SECRET_KEYS or len(key) < 16:
        if IS_PRODUCTION:
            raise RuntimeError(
                "SECRET_KEY is missing or weak. Set a long random SECRET_KEY "
                "(Render generates one automatically in render.yaml)."
            )
        return secrets.token_hex(32), True
    return key, False


SECRET_KEY, SECRET_KEY_IS_EPHEMERAL = _resolve_secret_key()

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "").strip()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_SECURE = IS_PRODUCTION

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------
DATABASE_PATH = os.environ.get("DATABASE_PATH") or os.path.join(BASE_DIR, "waste.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
MAX_CONTENT_MB = 5
MAX_CONTENT_LENGTH = MAX_CONTENT_MB * 1024 * 1024

# ---------------------------------------------------------------------------
# Email notifications (best effort, never blocks a submission)
# ---------------------------------------------------------------------------
REPORT_NOTIFY_EMAIL = os.environ.get("REPORT_NOTIFY_EMAIL", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER

# ---------------------------------------------------------------------------
# Complaint domain model
# ---------------------------------------------------------------------------
COMPLAINT_STATUSES = [
    "Submitted", "Under Review", "Assigned", "In Progress", "Resolved", "Rejected",
]

# Legal lifecycle transitions, enforced by complaints.services.update_status.
# Rejected -> Under Review is an appeal; Resolved -> In Progress is a reopen.
# Same-status updates stay allowed (remark-only / evidence-only changes).
ALLOWED_TRANSITIONS = {
    "Submitted": ["Under Review", "Rejected"],
    "Under Review": ["Assigned", "Rejected"],
    "Assigned": ["In Progress"],
    "In Progress": ["Resolved", "Rejected"],
    "Rejected": ["Under Review"],
    "Resolved": ["In Progress"],
}

# Ordered lifecycle used to render the citizen status timeline.
STATUS_ORDER = {
    "Submitted": 0,
    "Under Review": 1,
    "Assigned": 2,
    "In Progress": 3,
    "Resolved": 4,
}

CATEGORIES = [
    "Open Garbage",
    "Plastic Waste",
    "Food Waste",
    "Construction Debris",
    "E-Waste",
    "Medical Waste",
    "Drain & Sewer Waste",
    "Street Sweeping",
]

PRIORITIES = ["Low", "Medium", "High", "Emergency"]

# Values that existed in SmartWaste 1.x - normalised during migration.
LEGACY_STATUS_MAP = {"Pending": "Submitted", "Open": "Submitted", "Closed": "Resolved"}
LEGACY_CATEGORY_MAP = {
    "General Garbage": "Open Garbage",
    "Construction Waste": "Construction Debris",
}

# ---------------------------------------------------------------------------
# AI / ML
# ---------------------------------------------------------------------------
MODEL_DIR = os.environ.get("MODEL_DIR") or os.path.join(BASE_DIR, "models")
TRAINING_DATA = os.path.join(BASE_DIR, "data", "complaints_training_dataset.csv")
HOLDOUT_DATA = os.path.join(BASE_DIR, "data", "complaints_holdout_handwritten.csv")

# Predictions below this probability are flagged for manual admin review.
ML_CONFIDENCE_THRESHOLD = float(os.environ.get("ML_CONFIDENCE_THRESHOLD", "0.55"))
# Below this absolute probability the prediction is reported as very weak.
ML_LOW_CONFIDENCE = float(os.environ.get("ML_LOW_CONFIDENCE", "0.35"))

# Keyword hints shown alongside (never replacing) model explanations.
MAX_KEYWORDS = 6

# ---------------------------------------------------------------------------
# Duplicate complaint detection (Module C)
# ---------------------------------------------------------------------------
DUPLICATE_SIMILARITY_THRESHOLD = float(os.environ.get("DUPLICATE_SIMILARITY_THRESHOLD", "0.45"))
DUPLICATE_DISTANCE_KM = float(os.environ.get("DUPLICATE_DISTANCE_KM", "2.0"))
DUPLICATE_WINDOW_DAYS = int(os.environ.get("DUPLICATE_WINDOW_DAYS", "45"))
DUPLICATE_MAX_CANDIDATES = 250
DUPLICATE_COMBINED_THRESHOLD = float(os.environ.get("DUPLICATE_COMBINED_THRESHOLD", "0.55"))

# ---------------------------------------------------------------------------
# Geospatial hotspot detection (Module D)
# ---------------------------------------------------------------------------
# DBSCAN is configured in metres; converted to degrees internally.
DBSCAN_EPS_METERS = float(os.environ.get("DBSCAN_EPS_METERS", "400"))
DBSCAN_MIN_SAMPLES = int(os.environ.get("DBSCAN_MIN_SAMPLES", "3"))
HOTSPOT_MIN_COMPLAINTS = int(os.environ.get("HOTSPOT_MIN_COMPLAINTS", "3"))
# Optional city bounding box (min_lat, min_lon, max_lat, max_lon). Points
# outside it are treated as geographic outliers and excluded from clustering.
# Leave unset to accept every coordinate that is valid on Earth.
CITY_BOUNDS = None
if os.environ.get("CITY_MIN_LAT"):
    CITY_BOUNDS = (
        float(os.environ["CITY_MIN_LAT"]),
        float(os.environ["CITY_MIN_LON"]),
        float(os.environ["CITY_MAX_LAT"]),
        float(os.environ["CITY_MAX_LON"]),
    )

# ---------------------------------------------------------------------------
# Predictive analytics (Module E)
# ---------------------------------------------------------------------------
FORECAST_MIN_DAYS_BASELINE = int(os.environ.get("FORECAST_MIN_DAYS_BASELINE", "14"))
FORECAST_MIN_DAYS_ML = int(os.environ.get("FORECAST_MIN_DAYS_ML", "28"))
FORECAST_HISTORY_DAYS = int(os.environ.get("FORECAST_HISTORY_DAYS", "180"))
FORECAST_HORIZON_DAYS = int(os.environ.get("FORECAST_HORIZON_DAYS", "7"))
FORECAST_TEST_RATIO = 0.2
FORECAST_LAGS = (1, 2, 3, 4, 5, 6, 7, 14, 21, 28)

# ---------------------------------------------------------------------------
# Decision support thresholds (Module G)
# ---------------------------------------------------------------------------
BACKLOG_AGE_DAYS = int(os.environ.get("BACKLOG_AGE_DAYS", "3"))
OVERDUE_AGE_DAYS = int(os.environ.get("OVERDUE_AGE_DAYS", "7"))
RISING_WINDOW_DAYS = 7
RISING_MIN_INCREASE = 3
RECOMMENDATION_LIMIT = 8

# ---------------------------------------------------------------------------
# Session / abuse protection
# ---------------------------------------------------------------------------
LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "8"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "300"))
