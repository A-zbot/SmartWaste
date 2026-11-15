# SmartWaste 2.0 — Viva Preparation

Question–answer preparation for the MCA major-project viva. Answers use only
**verified facts and measured numbers** from this repository
(`docs/ML_EVALUATION.md`, `experiments/RESULTS.md`, `docs/TESTING_REPORT.md`).
Do not quote numbers that are not in those files.

## 1. The 60-second pitch

> "SmartWaste 2.0 is an AI-driven waste reporting and management system.
> Citizens file complaints from any device with a photo, category and
> location; a machine-learning pipeline immediately suggests the waste
> category and urgency, flags possible duplicates against existing reports,
> and gives administrators a plain-language explanation of the prediction.
> Administrators work a server-enforced status lifecycle, confirm or correct
> the AI output (the original prediction stays immutable for honest
> evaluation), view DBSCAN hotspot clusters, a demand forecast (7-day default,
> up to 30 days) with honest insufficient-data states, and a full append-only audit trail.
> Everything runs on Flask + SQLite with classical ML — TF-IDF with Logistic
> Regression and Random Forest — selected by 5-fold cross-validation. The
> training data is synthetic and disclosed as such: our metrics validate the
> pipeline, they are not claimed as real-world accuracy."

## 2. Architecture (30 seconds)

- **Presentation:** server-rendered Jinja templates + vanilla JS
  (progressive enhancement; core flows work without JS).
- **Web layer:** Flask factory in `app.py`, five blueprints
  (`public`, `authentication`, `complaints`, `admin`, `analytics`), with
  cross-cutting security in `security.py` (CSRF, role gates, rate limits,
  headers, audit).
- **Service layer:** validation and workflows in `modules/*/services.py`.
- **Intelligence layer:** pure-Python modules with **no Flask imports** —
  preprocessing, classifier, urgency predictor, duplicate detection,
  forecasting, hotspot clustering, explainability, training/evaluation.
- **Data:** SQLite schema v5 (`db.py`), trained artifacts in `models/`,
  synthetic corpora in `data/`.

Detail: `docs/PROJECT_ARCHITECTURE.md`.

## 3. Machine-learning questions

**Q: Which models do you use and why not deep learning?**
TF-IDF features with Logistic Regression and Random Forest for both
multi-class tasks (waste category, urgency). Our labelled corpus is small
and synthetic; classical models are reproducible on CPU, interpretable, and
5-fold CV shows they saturate the task (category CV F1-macro ≈ 0.95).
Deep models would add training cost and overfitting risk without a larger
corpus — and the project's honesty constraints forbid claiming gains we
cannot measure.

**Q: How do you select the final model?**
Documented rule: highest **mean 5-fold CV F1-macro on the training
partition**, tie-break prefers Logistic Regression. The untouched holdout
set is evaluated only afterwards. For category, RF won CV
(0.9486 ± 0.0149 vs LR 0.9455) — note that LR scored slightly higher on the
holdout (F1-macro 0.8003 vs 0.7907); we report that openly rather than
retro-fitting the rule (`docs/ML_EVALUATION.md` §5). For urgency, LR won CV
(0.9556 ± 0.0297) and also dominated the holdout (0.8560 vs RF 0.5515).

**Q: How do you prevent data leakage?**
Partition-aware pipeline: vectoriser is fit inside each CV fold; the
holdout set is generated and stored separately (`data/README.md` documents
the split, seed and duplication controls). Evaluation scripts read the
partitions; training never sees holdout rows.

**Q: What do the reported numbers mean given synthetic data?**
They validate the **pipeline** (features, training, selection, honest
reporting) — not field accuracy. This is stated in `data/README.md`, the
admin models page, README and the reports themselves.

**Q: How does the system explain a prediction?**
`intelligence/explainability.py` composes a plain-language "why this
priority" card from citizen priority, model urgency, confidence and the
dominant features; category predictions surface top TF-IDF keywords and the
full probability distribution on the complaint detail page.

**Q: What happens if the model is unavailable?**
`classify()`/`predict_urgency()` return `available=False` with a reason and
`needs_review=True`; the UI shows "model not trained" states and never
invents a prediction (unit-tested).

**Q: How does forecasting stay honest?**
Chronological split with seasonal-naive and moving-average baselines scored
alongside the Random Forest; with < 14 days of history the API returns
`status=insufficient` with **no forecast at all**, between 14–27 days it
returns baseline-only. Demo-seeded row share is disclosed.

**Q: How is duplicate detection computed?**
TF-IDF cosine similarity on cleaned text (gate 1) combined with haversine
distance, recency window and category agreement (gate 2). Measured on the
synthetic duplicate-pair set: text gate P 0.9957 / R 0.932 / F1 0.9628;
combined gate P 1.0 / R 0.932 / F1 0.9648 (`experiments/RESULTS.md`).
Linking is an explicit administrator action, not automatic.

## 4. Software-engineering questions

**Q: Why Flask and SQLite?**
Small dependency footprint, server-rendered pages fit a government-style
operations console, SQLite gives zero-ops persistence for a demo scale.
The service layer is DB-agnostic enough to move to PostgreSQL if multi-
instance deployment becomes necessary (documented trade-off).

**Q: How is the status lifecycle protected?**
`ALLOWED_TRANSITIONS` in `config.py` is enforced in
`complaints.services.update_status()`; illegal jumps return an error and are
covered by `tests/test_lifecycle.py`. Appeals (Rejected → Under Review) and
reopens (Resolved → In Progress) are explicit edges.

**Q: What stops an administrator from breaking model evaluation?**
Corrections never overwrite the model's output: `predictions` is
append-only, the citizen's own category is preserved, and every review lands
in `prediction_feedback` with model name/version, original vs corrected
values, and the admin's identity — so correction rates can later be computed
per model version.

**Q: Which security measures are implemented?**
CSRF on every state-changing form *and* JSON endpoint; role gates with
server-side session checks; per-account login throttling; public rate
limits on report/signup/contact/duplicate-check (configurable
`PUBLIC_RATE_MAX`/`PUBLIC_RATE_WINDOW`); CSP + Permissions-Policy +
prod-only HSTS; `Cache-Control: no-store` on HTML/PDF; magic-byte image
validation; taxonomy allowlist validation; CRLF-safe e-mail headers;
HTML-escaped output (duplicate panel); append-only audit log; session
cookies HttpOnly/SameSite. Verified by 15 security tests.

**Q: How do you test?**
150 pytest tests: full-stack route tests with real CSRF tokens, service
unit tests, ML unit tests (preprocessing, prediction fallbacks, forecast
honest paths), security regression tests. `docs/TESTING_REPORT.md` maps
requirements to tests; the suite runs in ~90 seconds.

**Q: What is NOT implemented / honest limits?**
No real-world data validation (all synthetic), no browser-E2E suite, no
load testing, no camera/facial-recognition/SMS features (explicitly out of
scope), SMTP is best-effort. Real-data workflow is defined but pending in
`docs/DATASET_DOCUMENTATION.md`.

## 5. Suggested live demo script

1. **Citizen:** `/signup` → `/report` (type description, allow geolocation,
   category "Open Garbage", submit) → note tracking ID.
2. **Detail page:** show AI category/urgency card + "why this priority"
   explanation; submit a very similar second report and show the
   duplicate-check panel (it escapes all server data — mention the XSS fix).
3. **Track:** `/track` with tracking ID (and `/track` with wrong ID →
   honest failure message).
4. **Admin:** `/admin` → Pending KPI, forecast panel (honest baseline-only
   state on a fresh DB), duplicate panel, administrator-feedback panel.
5. **Queue:** `/admin/complaints` → filter by status/category, CSV export.
6. **AI review:** open a complaint → confirm or correct the prediction →
   show verified badge; re-open to show the original prediction unchanged.
7. **Status lifecycle:** walk Submitted → … → Resolved; attempt an illegal
   jump to show server-side rejection.
8. **Feedback:** as the citizen, rate the resolved complaint; as a
   different user, show that the form is not available.
9. **Models page:** `/admin/models` → CV comparison, confusion matrices,
   holdout scores, correction statistics; mention retrain is admin-triggered.
10. **Security tour:** submit a form without CSRF (rejected), inspect
    response headers (CSP present), show the audit trail entries created by
    every action above.

## 6. Tricky questions to handle carefully

| Question | Safe answer |
|---|---|
| "What is your accuracy on real data?" | "We have not evaluated on real data — our corpora are synthetic and disclosed. `docs/DATASET_DOCUMENTATION.md` defines the procedure we would run on real data." |
| "Why is LR's holdout better if RF is deployed?" | "Selection is by CV on the training partition, decided before seeing the holdout. We report both numbers; changing the rule after seeing holdout results would be test-set tuning." |
| "Is the forecast production-ready?" | "It is honest about its limits: chronological backtest with baselines, demo-share disclosure, insufficient-data refusal. The demo dataset has few real days, so baseline-only states are expected." |
| "Can you scale this?" | "Architecture-wise yes (service layer + indexed SQLite → PostgreSQL path documented); we have not load-tested, and we don't claim otherwise." |
| "How do you handle privacy?" | "No real personal data in the repo; synthetic corpora only; passwords hashed; mobile number used as second factor for anonymous feedback; audit log stores actor + IP for accountability." |

## 7. Files to have ready during the viva

- `docs/PROJECT_AUDIT.md` — what was wrong and what was fixed
- `docs/ML_EVALUATION.md` — every metric with its source
- `docs/TESTING_REPORT.md` — 150 tests and coverage map
- `docs/DATASET_DOCUMENTATION.md` — synthetic-data honesty + real-data plan
- `experiments/RESULTS.md` — measured evaluation output
- `README.md` — quickstart + feature list
