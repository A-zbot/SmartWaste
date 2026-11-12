"""SQLite schema, connection helpers and forward-only migrations.

SmartWaste 1.x stored everything in three tables (reports, users, messages).
SmartWaste 2.0 keeps those tables (so no existing record is lost or renamed)
and layers the new intelligence/audit entities on top of them.

Migrations are idempotent: every step checks for the object/column before
creating it, so running init_db() on an old database is always safe.
"""

import json
import os
import sqlite3

from config import DATABASE_PATH, LEGACY_CATEGORY_MAP, LEGACY_STATUS_MAP

SCHEMA_VERSION = 4


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------
def get_connection():
    con = sqlite3.connect(DATABASE_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


def query(sql, params=()):
    con = get_connection()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def query_one(sql, params=()):
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql, params=()):
    con = get_connection()
    try:
        cur = con.execute(sql, params)
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def now_utc():
    return sqlite3.connect(":memory:").execute(
        "SELECT datetime('now')"
    ).fetchone()[0]


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------
DDL = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    email         TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'citizen',
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    mobile       TEXT NOT NULL,
    location     TEXT NOT NULL,
    waste_type   TEXT NOT NULL,
    priority     TEXT NOT NULL,
    description  TEXT NOT NULL,
    image        TEXT,
    status       TEXT DEFAULT 'Submitted',
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    tracking_id  TEXT UNIQUE,
    area         TEXT,
    latitude     REAL,
    longitude    REAL,
    updated_at   TIMESTAMP,
    resolved_at  TIMESTAMP,
    admin_remarks TEXT,
    ai_category  TEXT,
    ai_urgency   TEXT,
    ai_confidence REAL,
    ai_needs_review INTEGER NOT NULL DEFAULT 0,
    final_category TEXT,
    final_urgency  TEXT,
    ai_review_note TEXT,
    ai_reviewed_at TIMESTAMP,
    ai_reviewed_by TEXT,
    duplicate_of_report_id INTEGER,
    source       TEXT NOT NULL DEFAULT 'live'
);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    email      TEXT NOT NULL,
    subject    TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS complaint_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    filename    TEXT NOT NULL,
    kind        TEXT NOT NULL DEFAULT 'submission',
    caption     TEXT,
    uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS complaint_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id   INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    old_status  TEXT,
    new_status  TEXT NOT NULL,
    remark      TEXT,
    actor_type  TEXT NOT NULL DEFAULT 'system',
    actor_id    INTEGER,
    actor_label TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS predictions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id          INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    model_name         TEXT NOT NULL,
    model_version      TEXT,
    predicted_category TEXT,
    predicted_urgency  TEXT,
    confidence         REAL,
    needs_review       INTEGER NOT NULL DEFAULT 0,
    explanation        TEXT,
    created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS complaint_clusters (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    label           TEXT NOT NULL,
    centroid_lat    REAL,
    centroid_lng    REAL,
    complaint_count INTEGER NOT NULL DEFAULT 0,
    unresolved_count INTEGER NOT NULL DEFAULT 0,
    top_category    TEXT,
    report_ids      TEXT,
    params          TEXT,
    computed_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notifications (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,
    report_id  INTEGER REFERENCES reports(id) ON DELETE CASCADE,
    title      TEXT NOT NULL,
    message    TEXT NOT NULL,
    link       TEXT,
    is_read    INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id  INTEGER NOT NULL UNIQUE REFERENCES reports(id) ON DELETE CASCADE,
    user_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
    rating     INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment    TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_type  TEXT NOT NULL DEFAULT 'system',
    actor_id    INTEGER,
    actor_label TEXT,
    action      TEXT NOT NULL,
    entity      TEXT,
    entity_id   TEXT,
    detail      TEXT,
    ip          TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reports_status      ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_created     ON reports(created_at);
CREATE INDEX IF NOT EXISTS idx_reports_user        ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_area        ON reports(area);
CREATE INDEX IF NOT EXISTS idx_reports_category    ON reports(waste_type);
CREATE INDEX IF NOT EXISTS idx_reports_coords      ON reports(latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_reports_urgency     ON reports(ai_urgency);
CREATE INDEX IF NOT EXISTS idx_history_report      ON complaint_history(report_id);
CREATE INDEX IF NOT EXISTS idx_predictions_report  ON predictions(report_id);
CREATE INDEX IF NOT EXISTS idx_notifications_user  ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_audit_created       ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_images_report       ON complaint_images(report_id);
"""

# Columns SmartWaste 1.x tables did not have -> added without touching data.
UPGRADE_COLUMNS = {
    "users": {
        "role": "TEXT NOT NULL DEFAULT 'citizen'",
        "is_active": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "TIMESTAMP",
    },
    "reports": {
        "tracking_id": "TEXT",
        "area": "TEXT",
        "latitude": "REAL",
        "longitude": "REAL",
        "updated_at": "TIMESTAMP",
        "resolved_at": "TIMESTAMP",
        "admin_remarks": "TEXT",
        "ai_category": "TEXT",
        "ai_urgency": "TEXT",
        "ai_confidence": "REAL",
        "ai_needs_review": "INTEGER NOT NULL DEFAULT 0",
        "final_category": "TEXT",
        "final_urgency": "TEXT",
        "ai_review_note": "TEXT",
        "ai_reviewed_at": "TIMESTAMP",
        "ai_reviewed_by": "TEXT",
        "duplicate_of_report_id": "INTEGER",
        "source": "TEXT NOT NULL DEFAULT 'live'",
    },
}


def _existing_columns(con, table):
    return {row[1] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _table_exists(con, table):
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _upgrade_columns(con):
    for table, columns in UPGRADE_COLUMNS.items():
        if not _table_exists(con, table):
            continue
        existing = _existing_columns(con, table)
        for name, declaration in columns.items():
            if name not in existing:
                con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _normalise_legacy_data(con):
    """Map SmartWaste 1.x vocabulary onto the 2.0 taxonomy/status model."""
    for old, new in LEGACY_STATUS_MAP.items():
        con.execute("UPDATE reports SET status=? WHERE status=?", (new, old))
    for old, new in LEGACY_CATEGORY_MAP.items():
        con.execute("UPDATE reports SET waste_type=? WHERE waste_type=?", (new, old))
    # Tracking ids for rows that predate the feature.
    con.execute(
        "UPDATE reports SET tracking_id = 'SW-' || printf('%05d', id) "
        "WHERE tracking_id IS NULL OR tracking_id = ''"
    )
    # Area label = first segment of the free-text location, used for grouping.
    con.execute(
        "UPDATE reports SET area = TRIM(SUBSTR(location, 1, "
        "CASE WHEN INSTR(location, ',') > 0 THEN INSTR(location, ',') - 1 "
        "ELSE LENGTH(location) END)) "
        "WHERE (area IS NULL OR area = '') AND location IS NOT NULL"
    )
    con.execute("UPDATE reports SET source = 'live' WHERE source IS NULL")


def _seed_initial_history(con):
    """Give pre-existing reports a Submitted event so timelines are complete."""
    rows = con.execute(
        "SELECT r.id, r.created_at FROM reports r "
        "WHERE NOT EXISTS (SELECT 1 FROM complaint_history h WHERE h.report_id = r.id)"
    ).fetchall()
    for row in rows:
        con.execute(
            "INSERT INTO complaint_history "
            "(report_id, old_status, new_status, remark, actor_type, actor_label, created_at) "
            "VALUES (?, NULL, 'Submitted', 'Complaint registered on SmartWaste', "
            "'citizen', NULL, ?)",
            (row["id"], row["created_at"]),
        )


def init_db():
    con = get_connection()
    try:
        con.executescript(DDL)
        _upgrade_columns(con)
        _normalise_legacy_data(con)
        _seed_initial_history(con)
        # Unique tracking ids (after the backfill above).
        con.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_reports_tracking "
            "ON reports(tracking_id)"
        )
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Small helpers used across modules
# ---------------------------------------------------------------------------
def row_to_dict(row):
    return dict(row) if row is not None else None


def dumps(value):
    return json.dumps(value, ensure_ascii=False)


def loads(value, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def tracking_id_for(report_id):
    return f"SW-{report_id:05d}"


if __name__ == "__main__":  # pragma: no cover
    init_db()
    print(f"Database ready at {DATABASE_PATH} (schema v{SCHEMA_VERSION})")
    print(os.path.exists(DATABASE_PATH))
