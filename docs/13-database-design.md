# 13 · Database Design

## 13.1 Physical Design

Single SQLite database (`waste.db`, override with `DATABASE_PATH`), created by
`db.py:init_db()` with `CREATE TABLE IF NOT EXISTS` and forward-only
migrations for existing installs. All timestamps are UTC.

### Tables

| Table | Purpose | Key columns |
|---|---|---|
| `users` | citizen/admin accounts | `email` UNIQUE, `password_hash` (Werkzeug), `role`, `is_active` |
| `reports` | the complaint itself | `tracking_id` UNIQUE, `status`, `ai_*` enrichment fields, `latitude`/`longitude`, `user_id` FK |
| `complaint_images` | submission + resolution photos | `report_id` FK CASCADE, `kind` |
| `complaint_history` | status timeline events | `old_status`, `new_status`, `remark`, `actor_*` |
| `predictions` | one row per AI prediction | `model_name`, `confidence`, `needs_review`, `explanation` (JSON) |
| `complaint_clusters` | latest DBSCAN snapshot | `label`, centroids, `report_ids` (JSON), `params` (JSON incl. quality) |
| `notifications` | in-app citizen inbox | `user_id` FK, `report_id` FK, `is_read` |
| `feedback` | rating per complaint | `report_id` UNIQUE FK, `rating` CHECK 1–5 |
| `messages` | contact-form submissions | `email`, `subject` |
| `audit_logs` | security/operations trail | `action`, `entity`, `entity_id`, `ip` |

### DDL excerpt (`reports`)

```sql
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
    source       TEXT NOT NULL DEFAULT 'live'
);
```

## 13.2 Indexes

```sql
CREATE INDEX IF NOT EXISTS idx_reports_status   ON reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_created  ON reports(created_at);
CREATE INDEX IF NOT EXISTS idx_reports_user     ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_area     ON reports(area);
CREATE INDEX IF NOT EXISTS idx_reports_category ON reports(waste_type);
CREATE INDEX IF NOT EXISTS idx_reports_coords   ON reports(latitude, longitude);
```

These cover the hot paths: queue filters (status/date/area/category),
duplicate scanning (created_at window), owner lookups (`user_id`) and map
renders (coordinates).

## 13.3 Integrity Rules

* **Transactions:** status changes update `reports`, `complaint_history` and
  the audit row together; a failed image save rolls the transaction back.
* **Cascade:** deleting a report removes its images, history, predictions and
  feedback (`ON DELETE CASCADE`); deleting a user nulls ownership of their
  reports (`SET NULL`).
* **Checks:** `feedback.rating BETWEEN 1 AND 5`.
* **Status vocabulary** is enforced in application code against
  `config.COMPLAINT_STATUSES`
  (`Submitted, Under Review, Assigned, In Progress, Resolved, Rejected`),
  with `config.LEGACY_STATUS_MAP` normalising 1.x values on migration.
* **Category/urgency vocabularies** are fixed by `config.CATEGORIES` and
  `config.PRIORITIES` and shared by the UI, the models and the exports.

## 13.4 Data Volumes & Retention

The prototype stores unlimited complaints in SQLite; the duplicate scan reads
at most 250 recent candidates per check and forecasting reads a 180-day
window — both bounded regardless of table size. Uploaded images live in
`uploads/` (git-ignored) with a 5 MB per-file limit. Audit logs are append-only.
