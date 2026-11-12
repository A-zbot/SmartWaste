# SmartWaste 2.0 — Repository Audit Report

> Completed as Phase 0 of the SmartWaste 2.0 transformation (MCA major project).
> Date: 2026-11-09 · Baseline: commit `2b0495b` · Test baseline: **73 passed** (pytest, Python 3.14).

This report documents the state of the existing repository *before* the gap-closure
and hardening work described in `DEVELOPMENT_PLAN.md`. Every finding below was
verified by reading the code — no feature was assumed present or absent.

---

## 1. Existing Features

### Citizen / public
| Feature | Evidence |
|---|---|
| Signup / login / logout, password hashing (Werkzeug), min-length 8 | `modules/authentication/routes.py:61-138` |
| Profile page with KPIs, notifications, feedback history, change password | `modules/authentication/routes.py:151-234`, `templates/profile.html` |
| Complaint submission (anonymous or authenticated) with validation | `modules/complaints/services.py:72-86, 112-252` |
| Unique tracking IDs (`SW-00001`) | `services.py:148-165` |
| Image evidence upload (png/jpg/webp, 5 MB, UUID filenames) | `services.py:43-53`, `config.py:55-57` |
| Browser geolocation + manual location entry, lat/lng stored | `static/app.js:32-100`, `db.py:89-90` |
| Complaint category + citizen-declared priority selection | `templates/report.html` |
| Complaint tracking by ID / tracking ID / mobile | `modules/complaints/routes.py:183-211` |
| Complaint history + 5-stage status timeline (Submitted → … → Resolved, plus Rejected) | `templates/_report_card.html` (`timeline()`), `complaint_history` table |
| Resolution evidence photo displayed to citizen | `templates/complaint_detail.html:60` |
| Citizen feedback (1–5 + comment, Resolved-only, once per complaint) | `services.py:360-397` |
| In-app notifications + unread nav badge + status-change e-mails | `notifications` table, `email_service.py:114-166` |
| Pre-submit AJAX duplicate warning + post-submit duplicate list | `/report/duplicate-check`, `static/app.js:104-147`, `templates/success.html:41-62` |
| PDF receipt download | `modules/complaints/pdf_service.py` |
| AI transparency: predicted category, confidence bar, urgency, explainability tags | `templates/success.html`, `templates/complaint_detail.html:134-169` |

### Admin
| Feature | Evidence |
|---|---|
| Env-configured admin login (constant-time compare), session role | `security.py:103-108` |
| Dashboard: 8 KPIs, 6 Chart.js charts, 8 filters, AJAX refresh, recommendations | `templates/admin/dashboard.html`, `/admin/api/overview` |
| Complaint queue with 9 filters, status tabs, CSV export | `templates/admin/complaints.html`, `admin/services.py:248-280` |
| Status workflow updates with remark + resolution image | `admin/routes.py:190-209` |
| Hotspot map (Leaflet + DBSCAN re-cluster with silhouette quality) | `admin/routes.py:229-314`, `intelligence/hotspot_detection.py` |
| Forecast page: RF vs seasonal-naive vs moving-average, MAE/RMSE, backtest, 7–30 d horizon with uncertainty band | `intelligence/forecasting.py`, `templates/admin/forecast.html` |
| Models page: candidate comparison, per-class metrics, confusion matrices, holdout scores, retrain button | `templates/admin/models.html`, `intelligence/model_evaluation.py` |
| Decision-support recommendations (8 rule types from live SQL) | `intelligence/recommender.py` |
| Citizen account enable/disable, audit trail, contact inbox, per-complaint PDF | `admin/routes.py:392-474` |

### AI/ML (`intelligence/`)
- **Category classification** — TF-IDF (1-2 gram, NLTK preprocessing) + Logistic Regression vs Random Forest, 5-fold stratified CV, independent 80-row handwritten holdout, joblib persistence (`model_training.py`).
- **Urgency prediction** — same pipeline, 4 classes, LR selected.
- **Duplicate detection** — cosine similarity (0.65) + haversine distance (0.25) + category match (0.10), text gate 0.45, 2 km hard gate (`duplicate_detection.py`).
- **Hotspots** — DBSCAN with haversine metric, persisted snapshots, honest silhouette reporting.
- **Forecasting** — lag/rolling/day-of-week features, RandomForestRegressor, two baselines, refuses to fabricate when data insufficient.
- **Explainability** — signed feature contributions (LR coefficients / RF impurity × TF-IDF weight) + DB-derived context factors; explicitly *not* Shapley.
- **Evaluation honesty** — all data is synthetic and disclosed in `data/README.md`, `models/*_report.json`, the admin UI, and the docs; test-set scores (0.96+) are always quoted alongside holdout scores (0.79/0.86).

### Infrastructure
- Flask app factory + 5 blueprints (`app.py`, `modules/__init__.py`), gunicorn/Render deployment (`Procfile`, `render.yaml`).
- SQLite (WAL, FK on) with idempotent DDL, forward-only column upgrades, legacy normalization, history backfill (`db.py`).
- CSRF (session token, HMAC compare), security headers, secure cookie flags, login throttling, audit logging (`security.py`).
- 73 tests across 6 files + GitHub Actions CI (Python 3.12/3.14).
- 24-document MCA documentation set with Mermaid diagrams (`docs/`).

---

## 2. Existing Application Architecture

```
app.py (create_app factory)
 ├── config.py          env-driven config, weak-key rejection, taxonomy, statuses
 ├── db.py              schema (10 tables), migrations, connection helpers
 ├── security.py        CSRF, headers, decorators, throttling, audit()
 ├── intelligence/      13 modules: preprocessing, classifier, priority, duplicates,
 │                      hotspots, geospatial, forecasting, explainability,
 │                      recommender, training, evaluation, model store
 ├── modules/           blueprints: public, authentication, complaints, admin, analytics
 ├── templates/         21 public + 9 admin Jinja2 templates
 ├── static/            style.css (design tokens), app.js (no framework), vendored
 │                      Chart.js + Leaflet
 ├── scripts/           generate_dataset.py, train_models.py, build_duplicate_pairs.py
 ├── models/            joblib pipelines + JSON evaluation reports (committed)
 ├── data/              synthetic corpora + honesty README
 ├── docs/              24 MCA documents
 └── tests/             73 pytest tests + CI workflow
```

Request flow (complaint submission): route → `services.validate` → `parse_coordinates`
→ `classify()` + `predict_urgency()` → `find_duplicates()` → save image → INSERT →
history + `predictions.explanation` + notification → audit → threaded admin e-mail.

---

## 3. Current Database Schema (SCHEMA_VERSION = 3)

| Table | Purpose | Key columns |
|---|---|---|
| `users` | citizen accounts | email UNIQUE, password_hash, role, is_active |
| `reports` | complaints | tracking_id UNIQUE, status, priority, lat/lng, area, `ai_category`, `ai_urgency`, `ai_confidence`, `ai_needs_review`, source, resolved_at, admin_remarks |
| `messages` | contact form | name, email, subject, message |
| `complaint_images` | evidence | report_id FK, filename, kind (`submission`/`resolution`), caption |
| `complaint_history` | status timeline | old_status, new_status, remark, actor_type/id/label |
| `predictions` | stored AI output | model_name/version, predicted_category/urgency, confidence, needs_review, explanation JSON |
| `complaint_clusters` | DBSCAN snapshots | centroid, counts, report_ids, params, silhouette |
| `notifications` | citizen inbox | user_id, report_id, title, message, link, is_read |
| `feedback` | ratings | report_id UNIQUE, rating 1–5 CHECK, comment |
| `audit_logs` | security trail | actor, action, entity, detail, ip |

Indexes on FKs, status, created_at, tracking_id.

---

## 4. Technical Limitations

1. **No status transition state machine** — any listed status reachable from any other (`services.py:278-283`).
2. **Duplicate detection refits TF-IDF per call** — runs on every detail-page render, twice per submission (`duplicate_detection.py:136-143`).
3. **Forecast retrains RandomForestRegressor (300 trees) on every forecast page view** (`forecasting.py:303-307`).
4. **No pagination** — `/admin/complaints`, `/my_reports`, messages, audit load entire tables.
5. **`_model_store.load_report()` re-reads JSON from disk every call** (only pipelines are cached).
6. **Process-local mutable state** — login throttle, retrain status dict are per-worker.
7. **`users.role` never drives authorization**; admin is a single env credential, not DB-backed.
8. **E-mail sent in bare daemon threads** — no queue/retry.
9. **README describes SmartWaste 1.x** — no mention of AI, map, forecast, or console.
10. **10.5 MB `category_pipeline.joblib` committed to git** (noted, intentionally left in scope-0 scope; removal would break offline auto-train).

---

## 5. Security Vulnerabilities

| # | Severity | Finding | Location |
|---|---|---|---|
| S1 | **High** | State-changing GET `/update_status/<id>/<status>` bypasses CSRF entirely — an `<img src>` in any page an admin visits flips complaint status | `admin/routes.py:212-223`, `security.py:46` |
| S2 | Medium | CSRF-failure redirect is issued with status **400**, so browsers do not follow `Location` — user lands on an empty page instead of the flashed message | `security.py:71` |
| S3 | Medium | **HTML injection** in admin report e-mail: `name`, `mobile`, `location`, `description` interpolated raw into HTML (attacker-controlled content, admin recipient) | `email_service.py:79-93` |
| S4 | Medium | **Unauthenticated PII lookup**: `/track` returns complaints matched by raw mobile number to anonymous visitors | `complaints/routes.py:200-203` |
| S5 | Low | No CSP, HSTS, or Permissions-Policy | `app.py:58-67` |
| S6 | Low | `/uploads/<filename>` serves images forever, public, no auth/expiry (mitigated by UUID names + `nosniff`) | `complaints/routes.py:362` |
| S7 | Low | No rate limiting on `/report`, `/signup`, `/contact` (login is throttled) | — |
| S8 | Info | Image upload validates extension only, not magic bytes | `services.py:39-53` |

Present and working (strengths): CSRF on all POSTs, security headers, secure cookie flags,
weak-secret rejection with production hard-fail, constant-time admin compare, login
throttling (8/300 s → 429), parameterized SQL, audit logging, PII masking in PDFs/lists.

---

## 6. Code Quality Issues

1. **Dead code**: `db.now_utc()` never called; `config.STATUS_ORDER` never referenced; `users.role` write-only.
2. **Over-broad exception handling**: bare `except Exception` around feedback insert masks real DB errors as "already rated" (`services.py:388`).
3. **Fragile 6-tuple returns with `None` sentinels** in complaint detail loaders.
4. **Dead keys in evaluation harness**: `experiments/evaluation.py:97` reads `candidates` but training writes `models`.
5. **`unread_notifications()` returns last N rows regardless of read state** — misleading name.
6. **Weak contact e-mail validation**: `"@" in email` (`public/routes.py:68`).
7. **Config smell**: personal Gmail hardcoded as `REPORT_NOTIFY_EMAIL` in `render.yaml` and `.env.example`.
8. **Legacy GET routes** (S1 above) exist "for backward-compatible links" but should be confirm-then-POST.
9. **Selected category model (RF) is not the best on holdout** — LR wins test (0.9934 vs 0.9649) and holdout (0.8003 vs 0.7907) while losing CV by 0.003 (within noise). The selection rule is documented and honest; left unchanged per scope agreement.

---

## 7. Missing Functionality (vs. the master prompt)

| Requirement | Status | Evidence |
|---|---|---|
| **Admin manual correction of AI-predicted category** (Part 4) | **MISSING** — no route, form, or field; `ai_needs_review` never cleared; UI promises it (`recommender.py:145-146`, `success.html:22`) | grep for `SET ai_category` finds only taxonomy migration |
| **Priority/urgency factor contributions displayed** (Part 5) | **MISSING in UI** — `explanation.text_features.urgency_task` computed (`explainability.py:195-198`) but zero templates render it | `grep urgency_task templates/` → 0 hits |
| Complaint lifecycle with Rejected (Part 3) | Present (statuses + timeline) but **unenforced** | `config.py:72-83` |
| Duplicate warnings (Part 3/6) | Present; **manual button only**, no admin link-as-duplicate | `report.html:73-78` |
| Profile management (Part 3) | **Partial** — view + change password only; no name/e-mail editing | `authentication/routes.py:151-234` |
| Notifications, feedback, resolution evidence, geolocation, tracking timeline | **Present** | see §1 |
| Model comparison, confidence display, synthetic-data labeling | **Present** | `model_training.py:81-108`, `success.html:21-22`, `data/README.md` |
| Geospatial hotspots, forecasting, decision support, analytics dashboard | **Present** | see §1 |

> All **MISSING**/**Partial** rows above were closed by `DEVELOPMENT_PLAN.md`
> phases 1–7 (see §9).

---

## 8. Proposed Implementation Strategy

Full phased plan in **`DEVELOPMENT_PLAN.md`**. Summary:

- **Phase 0** — backups, baseline (73 green), this report + plan. ✅
- **Phase 1** — close the Part 4 gap: admin AI-correction workflow (`final_category`/`final_urgency` columns, review route + form, clears `ai_needs_review`, audit/history/notification, citizen + PDF display). ✅
- **Phase 2** — close the Part 5 gap: render urgency/priority explanations on citizen and admin detail pages. ✅
- **Phase 3** — fix S1–S5 (GET status change, CSRF redirect, e-mail HTML injection, track PII lookup, CSP/HSTS). ✅
- **Phase 4** — enforce a legal status-transition map with a reopen path. ✅
- **Phase 5** — debounced auto duplicate check + admin link-as-duplicate. ✅
- **Phase 6** — cache TF-IDF vectorizer and forecast results, mtime-cache reports, paginate long lists, fix dead eval keys. ✅
- **Phase 7** — profile name/e-mail editing. ✅
- **Phase 8** — full test run, README rewrite, targeted doc updates. ✅

Each phase ends with a green `pytest` run. Synthetic-data honesty posture is preserved
throughout; no metric will be claimed that is not measured by a committed script.

---

## 9. Resolution (post-implementation)

All phases completed; final state verified on Python 3.14.7:

| Finding | Status |
|---|---|
| Technical limitations §4 1–5 (no state machine, per-call TF-IDF refit, per-view forecast retrain, no pagination, uncached report loads) | **Fixed** — phases 4 & 6; 17 new tests lock them in |
| Security vulnerabilities S1–S5 | **Fixed** — phase 3; `tests/test_security.py` grew 10 → 15 |
| Dead `candidates` key in evaluation harness (§6.4) | **Fixed** — phase 6 (`experiments/evaluation.py` reads `models`) |
| Other in-scope code-quality items (§6) | addressed per `DEVELOPMENT_PLAN.md` completion table; out-of-scope items noted as accepted |
| §7 missing functionality (AI correction, priority explanations, duplicate link, profile edit, enforced lifecycle) | **Closed** — phases 1, 2, 4, 5, 7 |
| Issue 9 (README describes SmartWaste 1.x) | **Fixed** — phase 8 rewrote `README.md` |
| Final suite | **115 passed** (`python -m pytest tests/ -q`), `compileall` clean, scripted end-to-end journey (submit → track → AI review → status flow → resolve → feedback → PDFs) green |
