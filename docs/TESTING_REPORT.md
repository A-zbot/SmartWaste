# SmartWaste 2.0 — Testing Report

Master-project testing report for the upgrade described in
`docs/PROJECT_AUDIT.md`. All results below are measured on this repository by
the committed pytest suite; nothing is estimated.

## 1. Environment and command

| Item | Value |
|---|---|
| OS | Windows 10/11 (win32) |
| Python | 3.14.7 |
| pytest | 9.1.1 |
| Runner | `python -m pytest tests/ -q` |
| Test database | per-session temp SQLite file (set in `tests/conftest.py` + per-module `DATABASE_PATH` defaults) |
| Models | committed artifacts in `models/`, `AUTO_TRAIN_MODELS=0` in tests |

## 2. Result

```text
======================= 150 passed in 93.66s (0:01:33) ========================
```

- **150 tests, 0 failures, 0 errors, 0 skipped.**
- Baseline before this upgrade: 115 tests (also passing). This report adds
  35 tests covering the new work: 17 ML/intelligence unit tests and 18
  feedback/upload/dashboard/security tests.
- Tests are behavioural: they exercise the real Flask app through
  `test_client`, the real SQLite schema and the real trained model
  artifacts. No mocks of business logic except where a test explicitly
  simulates a failure path (e.g. model file missing).

## 3. Test inventory

| File | Tests | Covers |
|---|---:|---|
| `test_smoke.py` | 13 | App boots, public pages render, report submission end-to-end, tracking |
| `test_security.py` | 15 | CSRF on forms/JSON, security headers, session cookie flags, role gates, login throttling, audit entries, host-header/email escaping |
| `test_phase4.py` | 16 | Admin queue filters/pagination/CSV, user management, contact inbox, models page, status transitions |
| `test_evaluation.py` | 17 | Model selection rule, honest metrics, holdout behaviour, hotspots, duplicate detector units, forecasting backtest honesty |
| `test_feedback_flow.py` | 18 | **New.** Citizen feedback authorisation (owner/anonymous-mobile), `prediction_feedback` logging, dashboard panels, upload magic-byte/extension validation, legacy alias normalisation, XSS source regression, `Cache-Control: no-store` |
| `test_ml_units.py` | 17 | **New.** Text preprocessing (determinism, markup/URL stripping, NLTK-free fallback), `classify()`/`predict_urgency()` incl. model-missing fallback, forecast insufficient/baseline-only paths, `rate_limit_hit()` unit, e-mail header CRLF sanitisation, image signature bytes, taxonomy allowlist validation |
| `test_ai_review.py` | 6 | Admin confirm/correct workflow, immutable original prediction, notification copy distinguishes correction vs confirmation |
| `test_duplicate_link.py` | 6 | Duplicate link/unlink, badges, target integrity |
| `test_lifecycle.py` | 7 | Status state machine: legal/illegal transitions, reopen paths |
| `test_frontend.py` | 7 | Template rendering, static assets, navigation |
| `test_regressions.py` | 10 | Previously fixed bugs (XSS, CSV injection, pagination bounds, etc.) |
| `test_performance.py` | 10 | Pagination caps, caching, response-time sanity, forecast memoisation |
| `test_profile.py` | 5 | Profile edit, password change |
| `test_priority_explanation.py` | 3 | Plain-language urgency explanation |
| **Total** | **150** | |

## 4. Coverage of the upgrade requirements

| Requirement | Where verified |
|---|---|
| DOM XSS in duplicate panel escaped | `test_feedback_flow.py::test_duplicate_panel_escapes_dynamic_fields` (source-level guard on `static/app.js`) + escaping functions unit-covered via existing regression tests |
| Waste category/priority allowlist | `test_ml_units.py::test_validate_*`, `test_feedback_flow.py::test_unknown_category_rejected_by_route`, `test_legacy_category_alias_is_normalised` |
| E-mail header injection | `test_ml_units.py::test_email_header_safe_strips_crlf` |
| Upload content validation (magic bytes) | `test_ml_units.py::test_image_magic_byte_signatures`, `test_feedback_flow.py::test_report_rejects_*`, `test_report_accepts_file_with_valid_png_signature` |
| Complaint feedback authorisation | `test_feedback_flow.py` — 7 tests: hidden from non-owner (403), admin sees "only the owner" note, anonymous blocked for owned complaints, other user rejected, owner succeeds exactly once, guest requires matching mobile, service refuses before Resolved, rating bounds |
| Administrator feedback logging | `test_feedback_flow.py::test_ai_review_writes_prediction_feedback_row` (row with model version, original vs corrected, admin label) |
| Dashboard KPIs/panels | `test_feedback_flow.py::test_dashboard_renders_pending_forecast_and_duplicate_panels`, `..._renders_prediction_feedback_stats` |
| Text preprocessing | `test_ml_units.py` — determinism, markup/URL/emoji stripping, regex tokenizer fallback |
| Category & urgency prediction + fallback | `test_ml_units.py::test_classify_*`, `test_predict_urgency_*` |
| Forecast honest paths | `test_ml_units.py::test_forecast_refuses_to_fabricate_on_short_history`, `test_forecast_baseline_only_between_thresholds`, methodology disclosure |
| Rate limiting | `test_ml_units.py::test_rate_limit_hit_blocks_over_limit_and_is_bounded` (mechanism unit); routes run with a raised `PUBLIC_RATE_MAX` in tests so the shared client IP does not lock the suite out |
| No-store caching on HTML | `test_feedback_flow.py::test_html_responses_are_no_store` |
| Existing behaviour preserved | the original 115 tests, unchanged except `test_ai_review.py`'s corrected notification-copy assertions |

## 5. Testing strategy notes

- **Isolation.** `tests/conftest.py` sets `PUBLIC_RATE_MAX=100000` and
  `AUTO_TRAIN_MODELS=0` *before* any test module imports `app`/`config`, so
  configuration is correct at import time and no test triggers retraining.
- **Rate limiter.** Because every test client shares 127.0.0.1, the public
  throttle is disabled via configuration for the suite and tested directly
  (`rate_limit_hit(max_attempts=2, window=60)`) instead — the mechanism is
  verified without fighting the shared-IP side effect.
- **Fixtures.** Each module creates its own temp database path default and
  builds the real app with `TESTING=True`; CSRF tokens are extracted from the
  real forms, so tests fail if the token plumbing breaks.
- **Model tests use the shipped artifacts**, so a regression in
  `models/category_model.joblib` packaging would be caught.

## 6. Known gaps (honest scope)

| Gap | Why | Mitigation |
|---|---|---|
| No browser/E2E tests (JS interactivity, geolocation) | Requires a browser driver not in the dependency set | Source-level regression guards for the critical XSS fix; manual check list in `docs/VIVA_PREPARATION.md` |
| No load/performance testing | Single-developer scope, SQLite target | Response-time sanity and pagination caps in `test_performance.py` |
| No real-world data validation | All corpora are synthetic (disclosed) | `docs/DATASET_DOCUMENTATION.md` defines the pending real-data workflow; metrics never claimed as field accuracy |
| Rate limit values not load-tested | Unit-tested mechanism only | Values are configuration (`PUBLIC_RATE_MAX`/`PUBLIC_RATE_WINDOW`) |
| SMTP delivery untested end-to-end | Best-effort feature; tests assert escaping and skip logic | Email failure never blocks submission (documented in README) |

## 7. How to reproduce

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q          # full suite: 150 passed
python -m pytest tests/test_ml_units.py tests/test_feedback_flow.py -q   # new tests only
```

See also: `docs/ML_EVALUATION.md` (model metrics), `docs/PROJECT_AUDIT.md`
(finding-to-fix traceability), `experiments/RESULTS.md` (measured evaluation
numbers).
