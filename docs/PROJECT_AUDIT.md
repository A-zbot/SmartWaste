# SmartWaste 2.0 — Project Audit Report (Phase 1)

> **Date:** 2026-11-15 · **Baseline commit:** `ea26a09` · **Python:** 3.14.7
> **Test baseline at audit time:** `python -m pytest tests/ -q` → **115 passed**
>
> This is the current-state audit required by the master upgrade prompt. It supersedes
> the historical baseline audit in `../AUDIT_REPORT.md` (written at commit `2b0495b`)
> and records what is *still* open after the completed `DEVELOPMENT_PLAN.md` phases 0–8.
> Every finding below was verified by reading the running code — no feature was assumed.

---

## 1. Existing Architecture

```
app.py (create_app factory, security headers, error handlers, auto-train thread)
 ├── config.py            env-driven config, taxonomy (8 categories, 4 urgencies),
 │                        ALLOWED_TRANSITIONS state machine, thresholds
 ├── db.py                SQLite DDL (10 tables), SCHEMA_VERSION=4, forward-only
 │                        column upgrades, legacy normalisation (WAL, FK on)
 ├── security.py          CSRF (session token, HMAC compare), admin credential
 │                        verify, login throttle, audit(), role decorators
 ├── intelligence/        13 modules — preprocessing, complaint_classifier,
 │                        priority_predictor, duplicate_detection, hotspot_detection,
 │                        geospatial_analysis (haversine), forecasting, explainability,
 │                        recommender, model_training, model_evaluation, _model_store
 ├── modules/             blueprints: public, authentication, complaints, admin,
 │                        analytics (5 blueprints, 18 admin routes all @admin_required)
 ├── templates/           21 citizen + 9 admin Jinja2 templates
 ├── static/              style.css design tokens, app.js (vanilla), vendored
 │                        Chart.js + Leaflet
 ├── scripts/             generate_dataset.py, train_models.py, build_duplicate_pairs.py
 ├── models/              joblib pipelines + JSON evaluation reports (committed)
 ├── data/                synthetic corpora, README.md + ANNOTATION.md (honesty docs)
 ├── experiments/         evaluation.py harness → RESULTS.md
 ├── docs/                24 MCA documents + this audit
 └── tests/               12 pytest files, 115 tests + GitHub Actions (3.12/3.14)
```

**Request flow (complaint submission):** route → `services.validate` →
`parse_coordinates` → `classify()` + `predict_urgency()` (lazy-loaded joblib pipelines)
→ `find_duplicates()` (TF-IDF cosine + haversine + category) → image save → INSERT
`reports` → INSERT `predictions` (model_name/version, explanation JSON) → history +
notification → audit → threaded admin e-mail → `explain_prediction()` context factors.

**Database (10 tables):** `users`, `reports`, `messages`, `complaint_images`,
`complaint_history`, `predictions`, `complaint_clusters`, `notifications`, `feedback`,
`audit_logs`. Key AI columns on `reports`: `ai_category`, `ai_urgency`, `ai_confidence`,
`ai_needs_review`, `final_category`, `final_urgency`, `ai_reviewed_at/by/note`,
`duplicate_of_report_id`.

---

## 2. Feature Inventory (verified present)

### Citizen / public
| Feature | Evidence |
|---|---|
| Signup / login / logout, scrypt password hashing, min length 8 | `modules/authentication/routes.py:61-138` |
| Profile view, name/e-mail edit, change password, KPIs, notifications | `authentication/routes.py:151-279`, `templates/profile.html` |
| Complaint submission (anonymous or authenticated) with validation | `modules/complaints/services.py:72-86, 112-252` |
| Unique tracking IDs (`SW-00001`), status timeline (6 states + Rejected) | `db.py`, `config.py:72-86` |
| Image evidence upload (png/jpg/webp, 5 MB, UUID filenames) | `services.py:39-53`, `config.py:55-57` |
| Browser geolocation + manual entry, lat/lng stored | `static/app.js:32-100`, `db.py:89-90` |
| Tracking by ID / tracking ID / mobile-as-second-factor (PII-safe) | `complaints/routes.py:186-231` |
| Pre-submit debounced AJAX duplicate warning + post-submit list | `/report/duplicate-check`, `static/app.js:104-149` |
| AI transparency: predicted category, confidence, urgency, "why this priority" | `templates/success.html`, `complaint_detail.html:164-209` |
| Citizen feedback (1–5 + comment, Resolved-only) | `services.py:376-404` |
| In-app notifications + status-change e-mails, PDF receipt | `email_service.py`, `pdf_service.py` |

### Admin
| Feature | Evidence |
|---|---|
| Env-credential admin login (constant-time), session role, all 18 routes guarded | `security.py:80-111`, AST-verified |
| Dashboard: 8 KPIs, 6 Chart.js charts, 8 filters, live recommendations | `templates/admin/dashboard.html`, `admin/services.py:122-` |
| Complaint queue: 9 filters, status tabs, pagination, CSV export | `templates/admin/complaints.html`, `admin/services.py:248-280` |
| Status workflow with enforced `ALLOWED_TRANSITIONS`, remark, resolution image | `services.py:278-318` |
| AI correction workflow (`final_*`, review form, badges, PDF rows) | `admin/routes.py:234-315` |
| Duplicate link/unlink with cycle guard + optional auto-reject | `admin/routes.py:317-423` |
| Hotspot map (Leaflet + DBSCAN haversine, silhouette quality) | `admin/routes.py:449-560`, `intelligence/hotspot_detection.py` |
| Forecast page: RF vs seasonal-naive vs 7-day MA, MAE/RMSE, backtest, horizon | `intelligence/forecasting.py`, `templates/admin/forecast.html` |
| Models page: candidate comparison, per-class metrics, confusion matrices, retrain | `model_evaluation.py`, `templates/admin/models.html` |
| Decision-support recommendations (8 SQL-driven rule types) | `intelligence/recommender.py` |
| Users enable/disable, contact inbox, audit log viewer, per-complaint PDF | `admin/routes.py` |

### AI/ML
- **Category classification** — TF-IDF (1-2 gram, NLTK preprocessing) inside a single
  sklearn `Pipeline` with Logistic Regression vs Random Forest; 5-fold stratified CV;
  independent 80-row handwritten holdout; joblib persistence (`model_training.py`).
- **Urgency prediction** — same pipeline, 4 classes, LR selected.
- **Duplicate detection** — cosine (0.65) + haversine (0.25) + category match (0.10),
  text gate 0.45, 2 km hard gate; vectorizer cached (`duplicate_detection.py`).
- **Hotspots** — DBSCAN with sklearn `haversine` metric on radians, persisted snapshots,
  honest silhouette reporting, `None` + reason when not computable.
- **Forecasting** — lag/rolling/day-of-week features, chronological holdout,
  RandomForestRegressor vs two baselines, MAE/RMSE, refuses to fabricate.
- **Explainability** — signed LR coefficients / RF importance × TF-IDF weight plus
  DB-derived context factors (explicitly not Shapley).
- **Fallback** — missing/corrupt model files degrade to `available=False`,
  `ai_needs_review=1`, complaint submission still succeeds (`services.py:128-160`).
- **Evaluation honesty** — all data disclosed synthetic in `data/README.md`,
  `data/ANNOTATION.md`, `models/*_report.json`, admin UI and docs; test-set scores
  (0.96+) always quoted alongside holdout scores (0.79 / 0.86).

---

## 3. Problems Discovered (severity-ranked)

### Critical
*None found.* No admin auth bypass, no SQL injection, no remote code execution path,
`.env` and `waste.db` are not and never were committed.

### High

| # | Finding | Location | Impact |
|---|---|---|---|
| **H1** | **Stored DOM XSS in the duplicate-check panel.** `output.innerHTML` interpolates `m.tracking_id`, `m.category`, `m.status`, `m.location` unescaped. `category` originates from citizen-submitted `waste_type` free text, so a submitted complaint containing `<img src=x onerror=…>` executes in any browser that runs a duplicate check matching it (citizen report form, admin detail page duplicate panel). The same file escapes correctly elsewhere (`app.js:365`, `:482`), proving the omission is accidental. | `static/app.js:121-144` (sinks at 127, 128, 133) | Session/CSRF-token theft, actions as the victim |
| **H2** | **No taxonomy allowlist on submission inputs.** `waste_type` and `priority` are accepted as free text (`validate()` checks only presence/length), stored raw, then interpolated into the admin e-mail **Subject** (`msg["Subject"] = f"… - {priority} priority"`) — an embedded CRLF survives `.strip()` → SMTP header injection. Free text also feeds H1. Admin-side forms do allowlist (`admin/routes.py:250-253`); the citizen path does not. | `complaints/services.py:72-86, 121-122`; `email_service.py:96` | Header injection, XSS amplifier, taxonomy pollution |

### Medium

| # | Finding | Location |
|---|---|---|
| **M1** | **Feedback route has no auth guard.** `POST /complaint/<id>/feedback` lacks `@citizen_required`; the ownership check `if user_id and row["user_id"] and …` is falsy for anonymous sessions, so a visitor can insert feedback on *anyone's* Resolved complaint (occupying the `report_id UNIQUE` slot). | `complaints/routes.py:376-388`, `services.py:389-396` |
| **M2** | **No rate limiting on public write endpoints** (`/report`, `/signup`, `/contact`, `/report/duplicate-check` — the last runs TF-IDF). Only login is throttled. Open finding **S7** from the baseline audit, still unresolved. | `security.py:117-146` (login only) |
| **M3** | **AI-review citizen notification always says "confirmed it as"** even when the admin *corrected* the category; admin flash has the same defect. The internal remark text is correct. Misinforms citizens about what happened. | `admin/routes.py:299, 311` |
| **M4** | **Hardcoded actor identity** `"administrator"` written to `ai_reviewed_by`, history `actor_label` and audit rows instead of the actual configured admin identifier. | `admin/routes.py:286, 293` |
| **M5** | **Admin correction feedback is not captured as a model-monitoring record.** Corrections live as columns on `reports` (`final_*`, `ai_review_*`) plus history/audit rows, but the **model version in force at correction time is not stored**, and there is no queryable feedback table for computing correction rates / per-model drift statistics (master prompt Phase 6). | `admin/routes.py:277-309`, `db.py:75-105` |
| **M6** | **Dashboard gaps vs Phase 7:** no forecast panel, no potential-duplicates queue, no administrator feedback statistics, no explicit *Pending* KPI (open/pending collapse to the same number, `admin/services.py:159-160`). All shown numbers are correctly DB-derived — the gap is missing panels, not hardcoding. | `templates/admin/dashboard.html` |
| **M7** | **Personal Gmail address committed** as `REPORT_NOTIFY_EMAIL` in `render.yaml:15` and `.env.example:6`. | config templates |
| **M8** | **Upload validation is extension-only** — no magic-byte/content-type check (docs claim content-type checking; see L3). | `services.py:39-53` |

### Low

| # | Finding | Location |
|---|---|---|
| **L1** | `GET /logout` mutates session without CSRF (nuisance logout). | `authentication/routes.py:141-148` |
| **L2** | Login throttle is per-process (defeated by multi-worker/restarts), keyed on raw identifier (unbounded memory), no per-IP component. | `security.py:117-146` |
| **L3** | **Documentation inaccuracies:** `docs/21-security.md:11` claims "role checks in the service layer" (none exist); `:17` claims content-type allowlist (not checked); `docs/19-testing.md:19,24` claims feedback + preprocessing-fallback tests (0 hits in `tests/`); `AUDIT_REPORT.md:59` still says "73 tests across 6 files"; `data/ANNOTATION.md:30` lists a non-existent `"Recyclable"` category. *(All corrected in the upgrade — see §7.)* | see listing |
| **L4** | **Evaluation-vs-artifact drift:** reported metrics come from the candidate fitted on the 640-row train split, but the *deployed* joblib is refit on all 800 rows — the served model has no metrics of its own (documented in code, but worth stating in ML_EVALUATION.md). | `model_training.py:277-281` |
| **L5** | Holdout text-length shift (median 14 vs training 26 words) is measured but undocumented. | `data/complaints_holdout_handwritten.csv` |
| **L6** | No `Cache-Control: no-store` on authenticated/PII pages. | `app.py:58-96` |
| **L7** | `users.role` is write-only dead weight; `STATUS_ORDER` and several `model_info()`/`is_trained()` helpers are dead code. | `db.py:69`, `config.py:89-95` |
| **L8** | Double image storage (`reports.image` *and* `complaint_images` rows) can diverge. | `services.py:156, 168-172` |
| **L9** | Offline duplicate scoring fits TF-IDF on the pair only, while the live path fits on the candidate corpus — same decision rule, different IDF statistics, so `duplicate_report.json` numbers are not byte-identical to live scores. | `duplicate_detection.py:49-60` vs `:123-186` |
| **L10** | Admin password placeholder `change-this-password` is accepted in dev; no admin password strength policy. | `config.py:44`, `.env` |

### Strengths (verified)
Parameterised SQL everywhere; CSRF on all POSTs with form/header support; six security
headers incl. CSP/HSTS/Permissions-Policy; weak-secret production hard-fail; constant-time
admin compare; login throttling; audit logging at 22 call sites; UUID upload names;
`.env`/`waste.db` never committed; state-machine-enforced status transitions; honest
empty/refusal states in clustering and forecasting; synthetic-data disclaimers in five
separate surfaces.

---

## 4. Missing Functionality (vs. master prompt)

*Status column updated at the end of the upgrade (Phase 10 close-out); the
"Notes" column preserves what the audit originally found.*

| Requirement | Status | Notes |
|---|---|---|
| `docs/PROJECT_AUDIT.md` | **Delivered** | created in Phase 1 |
| `docs/DATASET_DOCUMENTATION.md` | **Delivered** | consolidated from `data/README.md` + `data/ANNOTATION.md` (was scattered) |
| `docs/ML_EVALUATION.md` | **Delivered** | sourced from `models/*_report.json`, `experiments/RESULTS.md`, `docs/20-*.md` (was scattered) |
| `docs/TESTING_REPORT.md` | **Delivered** | requirement→test map for the 150-test suite; `docs/19-testing.md` inaccuracies (L3) also fixed |
| `docs/VIVA_PREPARATION.md` | **Delivered** | Q&A, demo script, honest limits |
| `docs/PROJECT_ARCHITECTURE.md`, `docs/DATABASE_DESIGN.md` | **Delivered** | engineering references alongside the numbered set |
| Real-world evaluation dataset | **Pending by design** | annotation workflow documented; no real data exists — must stay labelled pending |
| Admin prediction-feedback table with model version (Phase 6) | **Delivered** | `prediction_feedback` (schema v5) written by AI-review route; stats on dashboard; test asserts model version |
| Dashboard: forecast, duplicates queue, feedback stats, pending KPI (Phase 7) | **Delivered** | all four panels + `test_dashboard_renders_*` |
| Rate limiting on public endpoints (Phase 8) | **Delivered** | `security.rate_limit_hit()` on `/report`, `/report/duplicate-check`, `/signup`, `/contact`; unit-tested |
| Upload content validation (Phase 8) | **Delivered** | extension allowlist + magic-byte signatures; accept/reject tests |
| Unit tests: preprocessing, `classify()`, `predict_urgency()`, feedback route, upload rejection, forecast insufficiency (Phase 9) | **Delivered** | `tests/test_ml_units.py` (17) + `tests/test_feedback_flow.py` (18) |
| Anonymous-feedback authz test, XSS regression test | **Delivered** | 7 feedback-authz tests; `test_duplicate_panel_escapes_dynamic_fields` source guard |

---

## 5. Recommended Improvements (implementation order)

1. **H1/H2 — input & output hygiene:** HTML-escape all interpolations in the
   duplicate panel (add a shared `escapeHtml` helper); allowlist `waste_type` ∈
   `CATEGORIES` and `priority` ∈ `PRIORITIES` in `validate()`; sanitise the e-mail
   Subject line (strip CR/LF).
2. **M1 — feedback authz:** require an authenticated owner (or admin) for feedback;
   reject anonymous inserts on others' complaints; add tests.
3. **M3/M4 — correction copy & identity:** conditional "corrected to" vs "confirmed"
   in notification + flash; write the configured admin username as actor.
4. **M5 — Phase 6 feedback store:** new `prediction_feedback` table
   (report_id, model_name, model_version, original/corrected category, original/
   corrected urgency, admin id/label, timestamp, note) written by the AI-review
   route; original `ai_*` columns stay immutable; dashboard feedback statistics.
5. **M6 — Phase 7 dashboard:** add forecast summary card, potential-duplicates
   panel, administrator feedback statistics, explicit Pending KPI.
6. **M2/M8/L1 — security sweep:** lightweight throttle on public POSTs; magic-byte
   check for png/jpeg/webp; optional `Cache-Control: no-store` on authenticated pages.
7. **M7 — config hygiene:** replace personal Gmail in `render.yaml`/`.env.example`
   with a placeholder.
8. **Phase 2 docs:** consolidate `DATASET_DOCUMENTATION.md` and `ML_EVALUATION.md`
   from the existing honest sources (no new metrics — only measured ones); fix
   `ANNOTATION.md` "Recyclable"; document the holdout length shift (L5).
9. **Phase 9 tests:** preprocessing units, prediction units (incl. fallback),
   feedback route, upload rejection, allowlist rejection, forecast insufficient-data,
   XSS-escape regression, dashboard feedback stats.
10. **Phase 10 docs:** `TESTING_REPORT.md`, `PROJECT_ARCHITECTURE.md`,
    `DATABASE_DESIGN.md`, `VIVA_PREPARATION.md`, README verification.

---

## 6. Files That Need Modification

| File | Changes |
|---|---|
| `static/app.js` | escape helper + escape duplicate-panel interpolations (H1) |
| `modules/complaints/services.py` | taxonomy allowlist in `validate()`; feedback authz fix (H2, M1) |
| `modules/complaints/routes.py` | guard `submit_feedback` (M1) |
| `modules/complaints/email_service.py` | Subject CRLF sanitisation (H2) |
| `modules/admin/routes.py` | correction copy (M3), actor identity (M4), write `prediction_feedback` (M5), dashboard payload additions (M6) |
| `modules/admin/services.py` | pending KPI, feedback stats, duplicates panel data (M6) |
| `db.py` | `SCHEMA_VERSION` bump + `prediction_feedback` DDL (M5) |
| `security.py` | reusable public-endpoint throttle (M2) |
| `modules/complaints/services.py` (`save_image`) | magic-byte validation (M8) |
| `app.py` | `Cache-Control: no-store` on authenticated responses (L6) |
| `render.yaml`, `.env.example` | placeholder e-mail (M7) |
| `data/ANNOTATION.md`, `data/README.md` | fix "Recyclable" (L3); holdout length-shift note (L5) |
| `templates/admin/dashboard.html` | new panels (M6) |
| `tests/*` | new coverage per §4 |
| `docs/*` | deliverables listed in §4 |

**Preserved unchanged:** duplicate scoring thresholds and tests (`test_evaluation.py`
pins them), model-selection rule, synthetic-data honesty posture, all working citizen
workflows, `AUDIT_REPORT.md`/`DEVELOPMENT_PLAN.md` history.

---

## 7. Remediation Status (post-upgrade)

| Finding | Status | Evidence |
|---|---|---|
| H1 duplicate-panel XSS | **Fixed** | `static/app.js` escapes every interpolated field; guard test `test_feedback_flow.py::test_duplicate_panel_escapes_dynamic_fields` |
| H2 taxonomy allowlist + e-mail CRLF | **Fixed** | `validate()` allowlist + `CATEGORY_ALIASES`; `_header_safe()` in `email_service.py`; tests in `test_ml_units.py` |
| M1 feedback authorisation | **Fixed** | owner/mobile second-factor checks in `services.submit_feedback`; 7 tests in `test_feedback_flow.py` |
| M2 public rate limiting | **Fixed** | `security.rate_limit_hit()` on `/report`, `/report/duplicate-check`, `/signup`, `/contact`; unit test + `PUBLIC_RATE_MAX/WINDOW` config |
| M3 correction copy | **Fixed** | notification/flash distinguish corrected vs confirmed; `test_ai_review.py` asserts both branches |
| M4 administrator identity | **Fixed** | `_admin_label()` reads `ADMIN_USERNAME` everywhere (no hardcoded actor) |
| M5 prediction-feedback store | **Fixed** | `prediction_feedback` table (schema v5, append-only), written by AI-review route with model version; stats on dashboard; `test_ai_review_writes_prediction_feedback_row` |
| M6 Phase 7 dashboard | **Fixed** | Pending KPI + forecast / duplicate / administrator-feedback panels; `test_dashboard_renders_*` |
| M7 personal e-mail in configs | **Fixed** | `render.yaml` has no committed address (`sync: false`); `.env.example` uses `admin@example.com` |
| M8 upload content validation | **Fixed** | magic-byte signatures for png/jpeg/webp in `save_image()`; accept/reject tests |
| L1 GET `/logout` CSRF | **Accepted (documented)** | nuisance-only impact; converting to POST would break navigation links and documented flows used across the suite — noted here as a deliberate risk acceptance |
| L2 login-throttle memory/process scope | **Partially fixed** | identifiers truncated to 64 chars and counters pruned (bounded memory); per-process scope remains acceptable for the single-process demo deployment |
| L3 documentation inaccuracies | **Fixed** | `docs/21-security.md`, `docs/19-testing.md`, `AUDIT_REPORT.md`, `data/ANNOTATION.md` corrected to match the code |
| L4 evaluation-vs-artifact drift | **Documented** | `docs/ML_EVALUATION.md` §6 (deployed joblib refit on all 800 rows) |
| L5 holdout length shift | **Documented** | `data/README.md` (median 14 vs 26 words) |
| L6 `Cache-Control: no-store` | **Fixed** | `app.py` after-request hook for non-static HTML/PDF; regression test |
| L7 dead code (`users.role`, helpers) | **Accepted** | cleanup deferred — removing schema columns/helpers risks working features for no behaviour gain |
| L8 double image storage | **Accepted** | both paths exercised by tests; divergence would be visible in admin detail view |
| L9 offline-vs-live IDF drift | **Documented** | duplicate metrics are pipeline checks; same decision rule, different IDF statistics (this table) |
| L10 dev admin password placeholder | **Accepted** | production hard-fails on weak secrets already; strength policy out of scope for the demo |
