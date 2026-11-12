# SmartWaste 2.0 — Development Plan

> Phased implementation strategy for transforming SmartWaste into
> **SmartWaste 2.0 — AI-Driven Urban Waste Management and Predictive Decision Support System**.
> Companion document: `AUDIT_REPORT.md` (repository state at baseline commit `2b0495b`).

**Scope agreed with the project owner:** gap-closure and hardening of the existing
codebase — finish the requirements from the master prompt that are missing or
partial, fix confirmed security defects, enforce the complaint lifecycle, and
remove performance bottlenecks. No feature sprawl. Synthetic data stays synthetic
and disclosed. Out of scope: real-data acquisition, SHAP/waterfall plots, public
map page, dark mode, assignee/team model, changing the documented model-selection
rule, removing model artifacts from git.

**Working rule:** every phase ends with a green `python -m pytest tests/ -q`
(baseline: 73 tests). Backups of `waste.db`, `render.yaml`, `.env.example`,
`Procfile`, `requirements.txt` live in `backups/` (gitignored).

---

## Phase 0 — Backup, baseline, audit, plan ✅
- Copy configuration + database files to `backups/`; add `backups/` to `.gitignore`.
- Run full test suite → baseline **73 passed**.
- Produce `AUDIT_REPORT.md` and this `DEVELOPMENT_PLAN.md`.

## Phase 1 — Admin AI-correction workflow *(closes Part 4 gap)* ✅
**Problem:** the system promises "admin will verify/correct the classification"
but no correction mechanism exists anywhere; `ai_needs_review` is never cleared.

- `db.py`: bump `SCHEMA_VERSION`, extend `UPGRADE_COLUMNS["reports"]` with
  `final_category TEXT`, `final_urgency TEXT`, `ai_review_note TEXT`,
  `ai_reviewed_at TIMESTAMP`, `ai_reviewed_by TEXT`.
  Original `ai_*` prediction stays immutable (evaluation honesty).
- `modules/admin/routes.py`: `POST /admin/complaint/<int:report_id>/ai-review`
  — form fields `final_category` (8-class taxonomy whitelist), `final_urgency`
  (4-level whitelist), optional note (≤ 500 chars). Writes `final_*` +
  `ai_reviewed_*`, sets `ai_needs_review = 0`, appends `complaint_history` event,
  `audit_logs` entry, and a citizen notification.
- `templates/admin/complaint_detail.html`: review form inside the AI panel
  (shown when `ai_needs_review` or already-corrected state), "Verified" badge
  when `final_category` set.
- `templates/admin/complaints.html`: distinguish "awaiting review" vs "verified".
- Citizen surface: `templates/complaint_detail.html` shows **Verified category**
  (from `final_category`) when present, clearly labelled as administrator-confirmed;
  same in `pdf_service.py` (admin + citizen copies).
- `intelligence/recommender.py`: low-confidence recommendation text now links to a
  real action.
- Tests: correction route clears flag, persists fields, writes history + audit +
  notification, preserves original `ai_category`; citizen cannot call the route;
  detail pages render the verified badge.

## Phase 2 — Priority/urgency explanation display *(closes Part 5 gap)* ✅
**Problem:** `explainability.explain_prediction()` returns
`text_features.urgency_task` but no template renders it — citizens see *what*
the urgency is, never *why*.

- `templates/complaint_detail.html` + `templates/admin/complaint_detail.html`:
  new **"Why this priority"** block — signed urgency feature contributions
  (same `.feature-tag` pattern as category), model urgency confidence, and the
  context factors already returned by the backend (declared priority, complaint
  age, nearby duplicates, hotspot membership, citizen-vs-AI agreement).
- Make the effective-urgency rule explicit in copy: system priority = max of
  citizen-declared priority and model prediction (`effective_urgency`).
- Tests: detail pages render urgency contribution tags and confidence.

## Phase 3 — Security hardening *(fixes S1–S5)* ✅
1. **S1 — state-changing GET** (`admin/routes.py:212` legacy `/update_status`):
   replace direct mutation with a CSRF-protected confirmation page that
   auto-POSTs to the real `/admin/complaint/<id>/status` endpoint. Old email /
   bookmark links keep working; `<img src>` CSRF dies.
2. **S2 — CSRF-failure redirect** (`security.py:71`): non-JSON requests get
   `flash` + redirect with **302** so browsers follow it; JSON/API requests keep
   **400**. Update the assertion in `tests/test_security.py`.
3. **S3 — HTML injection in admin report e-mail** (`email_service.py:79-93`):
   run `html_escape` over `name`, `mobile`, `location`, `description` before
   interpolation (mirror `send_status_email`).
4. **S4 — unauthenticated PII lookup** (`complaints/routes.py:200-203`): `/track`
   requires a complaint ID or tracking ID; a mobile number is only accepted as a
   second factor alongside an ID — never alone. Update affected tests.
5. **S5 — headers** (`app.py:58-67`): add `Content-Security-Policy` (self;
   OSM tiles/images for Leaflet; `img-src 'self' data:` for previews) and
   `Strict-Transport-Security` **only when `IS_PRODUCTION`**, plus
   `Permissions-Policy: geolocation=(self)`.
- Tests: legacy GET no longer mutates without CSRF confirm; redirect follows;
   e-mail HTML escapes hostile input; track-by-mobile-alone returns no results.

## Phase 4 — Complaint lifecycle state machine ✅
- `config.py`: `ALLOWED_TRANSITIONS` map —
  `Submitted → [Under Review, Rejected]`,
  `Under Review → [Assigned, Rejected]`,
  `Assigned → [In Progress]`,
  `In Progress → [Resolved, Rejected]`,
  `Rejected → [Under Review]` (appeal/reopen),
  `Resolved → [In Progress]` (reopen for correction).
- Enforce in `complaints/services.py::update_status` with a clear error naming
  the illegal move; keep legacy status normalization.
- Tests: legal path succeeds; `Rejected → Resolved` and `Resolved → Assigned`
  rejected; reopen paths succeed; history records the attempt outcome.

## Phase 5 — Duplicate workflow completion ✅
- **Auto-check:** debounce (≈600 ms) the existing `/report/duplicate-check` AJAX
  when the description reaches ≥ 40 characters in `static/app.js` / `report.html`
  — today it only runs on button click.
- **Admin link-as-duplicate:** `db.py` adds `duplicate_of_report_id INTEGER`
  (via `UPGRADE_COLUMNS`); `POST /admin/complaint/<id>/duplicate` accepts a
  target tracking ID (validated, self-reference and cycles rejected), writes a
  history event + audit, optionally sets status `Rejected` with remark
  "Duplicate of SW-xxxxx". Badge/link rendered in queue, admin detail, citizen
  detail.
- Duplicate *scoring* untouched — `tests/test_evaluation.py` pins it.

## Phase 6 — Performance & correctness ✅
- **Duplicate TF-IDF:** cache the fitted vectorizer keyed by the candidate-corpus
  signature (max id + updated_at) in `intelligence/duplicate_detection.py` —
  removes a per-render refit without changing scores.
- **Forecast:** memoize `forecast()` for a short TTL keyed by
  (horizon, series hash, params) — stops retraining 300 trees per page view.
- **`_model_store.load_report()`:** cache JSON with mtime invalidation.
- **Pagination** (server-side `LIMIT/OFFSET`, preserving filters in query string):
  `/admin/complaints`, `/my_reports`, `/admin/messages`, `/admin/audit`.
- Fix dead key `candidates` → `models` in `experiments/evaluation.py`.
- Tests: repeated detail renders hit the vectorizer cache; paginated routes
  return page 1 + correct count; evaluation harness reads candidates again.

## Phase 7 — Profile editing *(completes Part 3)* ✅
- `POST /profile/edit` in `modules/authentication/routes.py`: edit `name` +
  `email` (unique check with friendly error, session refreshed, audit entry).
  (`users` has no mobile column — mobile lives per complaint; out of scope.)
- `templates/profile.html`: inline edit form.
- Tests: edit persists, duplicate email rejected, other citizen's session
  unaffected, audit written.

## Phase 8 — Verification & documentation ✅
- Full `pytest` locally; confirm CI parity (3.12/3.14).
- Manual smoke: submit → track → admin review/correct → status flow → resolve →
  feedback → PDF.
- Rewrite `README.md` (currently describes SmartWaste 1.x) to cover the AI
  modules, console, evaluation honesty, and setup.
- Targeted updates to `docs/17-implementation.md`, `docs/19-testing.md`,
  `docs/21-security.md` where behavior changed. Synthetic-data disclaimers in
  `data/README.md`, `models/*_report.json`, and the models page stay untouched.

---

## Execution order & risk notes

Order: **0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8** (security early to de-risk).

| Risk | Mitigation |
|---|---|
| Schema upgrades on live DBs | existing forward-only `UPGRADE_COLUMNS` mechanism; new columns nullable/defaulted |
| Test assertions encode old insecure behavior (`test_security.py:131`) | update assertions deliberately alongside the fix, never weaken coverage |
| `/track` behavior change breaks citizen UX | ID-first lookup keeps the page usable; mobile becomes a confirmation field |
| Caching introduces stale AI output | cache keys include data signatures; `clear_cache()` already called after retrain |
| Pagination breaks admin filters | query-string round-trip of all filter params is part of the phase-6 tests |

---

## Completion status (all phases done ✅)

| Phase | Result |
|---|---|
| 0 | backups in `backups/`; baseline **73 passed**; `AUDIT_REPORT.md` + this plan written |
| 1 | AI-correction workflow (`final_*` + `ai_review_*` columns, `/ai-review` route, badges, PDF rows) — 6 new tests |
| 2 | "Why this priority" context cards for citizens and admins — 3 new tests |
| 3 | S1–S5 fixed: legacy GET → CSRF confirmation page, browser CSRF redirect 302, e-mail HTML escaping, `/track` ID+mobile hardening, CSP/Permissions-Policy/HSTS headers — 5 added/updated security tests |
| 4 | `ALLOWED_TRANSITIONS` enforced in `update_status`, templates offer only `next_statuses` — 7 new tests |
| 5 | duplicate link/unlink workflow + debounced auto-check + badges/notes — 6 new tests |
| 6 | duplicate matrix cache (content-hash key), forecast TTL memoization, mtime report cache, pagination (queue/inbox/audit/citizen history), `evaluation.py` `candidates`→`models` fix — 10 new tests |
| 7 | `POST /profile/update` (name/email, validation, uniqueness, session refresh, audit) — 5 new tests *(plan named the route `/profile/edit`; implemented as `/profile/update`)* |
| 8 | suite **115 passed** on Python 3.14.7 (CI matrix covers 3.12/3.14); scripted end-to-end journey (submit → track → AI review → legal status flow → resolve → feedback → both PDFs) all green; `compileall` clean; `README.md` rewritten; `docs/17`, `docs/19`, `docs/21` updated |

Final verification commands:

```powershell
python -m pytest tests/ -q        # 115 passed
python -m compileall app.py config.py db.py security.py modules intelligence experiments scripts tests
```
