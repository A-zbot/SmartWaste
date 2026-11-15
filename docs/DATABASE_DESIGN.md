# SmartWaste 2.0 — Database Design

Runtime database: **SQLite**, single file at `DATABASE_PATH`
(default `waste.db`), schema managed entirely by `db.py`.
Current schema version: **5** (`SCHEMA_VERSION`, stored in
`PRAGMA user_version`).

This document is the engineer-facing reference (columns, keys, invariants,
migrations). The report-style ER diagram lives in `docs/12-er-diagram.md`.

## 1. Entity-relationship overview

```mermaid
erDiagram
    users ||--o{ reports : "submits"
    reports ||--|| feedback : "rated once"
    reports ||--o{ complaint_history : "timeline"
    reports ||--o{ predictions : "AI output"
    reports ||--o{ prediction_feedback : "admin reviews"
    reports ||--o{ complaint_images : "photos"
    reports ||--o{ notifications : "alerts"
    reports }o--|| reports : "duplicate_of_report_id"
    reports }o--o{ complaint_clusters : "membership (report_ids JSON)"
    users ||--o{ complaint_images : "uploads"
    users ||--o{ notifications : "receives"
    audit_logs }o--|| reports : "entity_id (polymorphic)"
    messages {
        id pk
        name
        email
        subject
        message
        created_at
    }
```

Polymorphic notes:

- `audit_logs.entity`/`entity_id` reference whichever row the action touched
  (`report`, `user`, `model`, …) — audit is append-only and never joined
  with `ON DELETE` so history survives deletions.
- `complaint_clusters.report_ids` stores a JSON array of member report ids
  (clusters are recomputed on demand; the table caches the last computation).

## 2. Tables

### 2.1 `users`

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name` | TEXT NOT NULL | |
| `email` | TEXT NOT NULL UNIQUE | login identifier |
| `password_hash` | TEXT NOT NULL | salted hash (Werkzeug) |
| `role` | TEXT DEFAULT `'citizen'` | `citizen` / `admin` |
| `is_active` | INTEGER DEFAULT 1 | admin can deactivate |
| `created_at` / `updated_at` | TIMESTAMP | `updated_at` set on profile edits |

### 2.2 `reports` — central entity

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `name`, `mobile`, `location` | TEXT NOT NULL | citizen input (submission form) |
| `waste_type` | TEXT NOT NULL | **citizen's** category, allowlisted against `CATEGORIES` + `CATEGORY_ALIASES` (aliases normalised before insert) |
| `priority` | TEXT NOT NULL | **citizen's** priority, must be in `PRIORITIES` |
| `description` | TEXT NOT NULL | 20–2000 chars (service-enforced) |
| `image` | TEXT | filename under `UPLOAD_FOLDER`, or NULL; extension + magic-byte validated |
| `status` | TEXT DEFAULT `'Submitted'` | lifecycle value (see §4) |
| `user_id` | INTEGER → users | NULL = anonymous/guest complaint |
| `tracking_id` | TEXT UNIQUE | `SW-#####` (unique index `idx_reports_tracking`) |
| `area`, `latitude`, `longitude` | TEXT/REAL | area backfilled from location; coords used by hotspots/duplicates |
| `created_at`, `updated_at`, `resolved_at` | TIMESTAMP | `resolved_at` set on entering Resolved |
| `admin_remarks` | TEXT | last admin remark |
| `ai_category`, `ai_urgency`, `ai_confidence`, `ai_needs_review` | | **model suggestion** (advisory, from submission-time inference) |
| `final_category`, `final_urgency`, `ai_review_note`, `ai_reviewed_at`, `ai_reviewed_by` | | **administrator's confirmation/correction** — fills only after admin AI review; originals stay untouched |
| `duplicate_of_report_id` | INTEGER → reports | NULL or the earlier report this one duplicates (self-FK, app-enforced) |
| `source` | TEXT DEFAULT `'live'` | `'demo'` marks demo-seeded rows so forecasting can disclose demo share |

Indexes: `status`, `created_at`, `user_id`, `area`, `waste_type`,
`(latitude, longitude)`, `ai_urgency`, unique `tracking_id`.

### 2.3 `complaint_history`

Timeline of status changes: `old_status`, `new_status`, `remark`,
`actor_type` (`citizen`/`admin`/`system`), `actor_id`, `actor_label`,
`created_at`. Every `update_status()` writes one row; `init_db()` backfills a
`Submitted` event for legacy rows that have none (`_seed_initial_history`).

### 2.4 `predictions`

One row per complaint per inference at submission time:
`model_name`, `model_version` (training timestamp — the model's identity),
`predicted_category`, `predicted_urgency`, `confidence`, `needs_review`,
`explanation` (JSON consumed by the "why this priority" panel),
`created_at`. **Append-only** — administrator corrections never rewrite it.

### 2.5 `prediction_feedback` (schema v5, append-only)

One row per administrator AI review (confirmation *or* correction):

| Column | Notes |
|---|---|
| `report_id` | FK, cascade delete |
| `model_name`, `model_version` | copied from the reviewed prediction — enables per-version correction rates |
| `original_category` / `corrected_category` | pre-review vs admin decision |
| `original_urgency` / `corrected_urgency` | same for urgency |
| `was_correction` | 1 when either value changed |
| `admin_label` | administrator identity (`ADMIN_USERNAME`) |
| `note`, `created_at` | optional review note |

Indexes: `report_id`, `created_at`. Reviews made before this table existed
are counted separately via `reports.final_category IS NOT NULL`
(`legacy_reviews` in `admin.services.ai_feedback_stats()`), so nothing is
double-counted.

### 2.6 `feedback` (citizen satisfaction)

`report_id` **UNIQUE** (one rating per complaint), `user_id` (NULL for
anonymous complaints verified by mobile second factor), `rating` with
`CHECK (rating BETWEEN 1 AND 5)`, optional `comment`, `created_at`.

### 2.7 `complaint_images`

Multi-image history: `report_id` FK, `filename`, `kind`
(`submission`/…), `caption`, `uploaded_by`, `created_at`. The submission's
primary file is mirrored in `reports.image`.

### 2.8 `notifications`

User-facing alerts: `user_id`, `report_id` (both FK, cascade),
`title`, `message`, `link`, `is_read`, `created_at`. Index
`(user_id, is_read)`.

### 2.9 `complaint_clusters`

DBSCAN output cache: `label`, `centroid_lat/lng`, `complaint_count`,
`unresolved_count`, `top_category`, `report_ids` (JSON array), `params`
(eps/min_samples JSON), `computed_at`.

### 2.10 `messages`

Contact-form inbox: `name`, `email`, `subject`, `message`, `created_at`.
Subject/body length capped and CRLF-stripped at the route.

### 2.11 `audit_logs`

Append-only trail: `actor_type`, `actor_id`, `actor_label`, `action`,
`entity`, `entity_id`, `detail`, `ip`, `created_at`. Index on `created_at`.
Written by `security.audit()` for logins, submissions, status changes, AI
reviews, duplicate links, exports and retraining.

## 3. Constraints and invariants

| Invariant | Enforced by |
|---|---|
| `waste_type` ∈ taxonomy (+normalised aliases) | `complaints.services.validate()` |
| `priority` ∈ `PRIORITIES` | `complaints.services.validate()` |
| Legal status transitions only | `ALLOWED_TRANSITIONS` in `config.py`, checked by `update_status()` (unit-tested in `tests/test_lifecycle.py`) |
| One feedback row per report | `UNIQUE(report_id)` + service-level friendly error |
| Rating 1–5 | SQL `CHECK` + service validation |
| Unique tracking ids | `UNIQUE` index (backfilled before creation) |
| Image must be a real image | extension allowlist + 16-byte magic signature check in `save_image()` |
| Original AI prediction immutable | `predictions` append-only; corrections go to `final_*` + `prediction_feedback` |
| Audit never mutated | no UPDATE/DELETE paths exist on `audit_logs` |

## 4. Status lifecycle

```text
Submitted ──► Under Review ──► Assigned ──► In Progress ──► Resolved
    │              │                                             │
    └─► Rejected ◄─┘                    Rejected ◄───────────────┘
         │                                 │
         └── appeal ──► Under Review       └── reopen ──► In Progress
```

`config.py::ALLOWED_TRANSITIONS` is the single source of truth; same-status
updates remain allowed for remark/evidence-only changes.

## 5. Migration strategy

Migrations are **additive and idempotent** — `init_db()` runs on every start:

1. `executescript(DDL)` — `CREATE TABLE/INDEX IF NOT EXISTS` (new tables like
   `prediction_feedback` appear automatically on old databases).
2. `_upgrade_columns()` — `ALTER TABLE … ADD COLUMN` for every entry in
   `UPGRADE_COLUMNS` not yet present (SmartWaste 1.x → 2.0 columns).
3. `_normalise_legacy_data()` — maps 1.x vocabulary onto the 2.0 model:
   `LEGACY_STATUS_MAP` (`Pending/Open → Submitted`, `Closed → Resolved`),
   `LEGACY_CATEGORY_MAP` (`General Garbage → Open Garbage`, …), backfills
   `tracking_id` and `area`.
4. `_seed_initial_history()` — guarantees every report has at least one
   timeline event.
5. `PRAGMA user_version = SCHEMA_VERSION` (currently 5).

There is **no destructive migration**: columns and rows are never dropped, so
rolling back the application code against a migrated database stays safe.

## 6. Data honesty

- The shipped database (demo deployments) contains demo-seeded rows marked
  `source='demo'`; the forecast API discloses their share instead of mixing
  them silently with live submissions.
- Training/evaluation corpora in `data/` are synthetic and documented in
  `data/README.md`; the schema itself never fabricates metrics — measured
  values come only from `models/*_report.json` and `experiments/RESULTS.md`.
