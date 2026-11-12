# 19 · Testing

## 19.1 Strategy

Testing follows the risk of each layer: the complaint lifecycle and security
controls get the densest coverage, ML behaviour is tested through its
measurable outputs, and the UI is tested structurally (links, labels, a11y
markers) rather than pixel-wise. All tests run against a temporary SQLite
database (`DATABASE_PATH` pointed at a temp file before import), so a run
never touches the developer's `waste.db`.

## 19.2 Suite Breakdown (115 tests)

| File | Tests | Covers |
|---|---|---|
| `test_smoke.py` | 13 | app creation, home/login 200, DB init, CSRF on forms, signup/login/logout, report submission, tracking, feedback, chart data endpoint |
| `test_regressions.py` | 10 | historical defects: Chart.js linkage, `chartsAvailable()` guards, duplicate-detection rules, preprocessing fallback, forecasting guards, status vocab |
| `test_evaluation.py` | 17 | evaluation harness: pair CSV integrity, `pair_similarity`/`score_duplicate` behaviour, threshold monotonicity, report JSON schema, silhouette helper, honest insufficient-data paths |
| `test_phase4.py` | 16 | PDF generation (both audiences, masking, safe text), route access control, audit on admin PDF, status-change e-mail hook (background, best-effort), `_smtp_ready` semantics |
| `test_security.py` | 15 | security headers (HTML + PDF, CSP, Permissions-Policy, prod-only HSTS), form & JSON CSRF rejection, browser CSRF redirect, legacy status GET confirmation, session-cookie flags, admin access control, login throttling (unit), constant-time credential check, status-change audit trail |
| `test_frontend.py` | 7 | template `url_for` integrity, `img alt` coverage, dead internal anchors, `lang`/viewport/skip-link/`main` landmarks, CSS guarantees (focus-visible, reduced-motion) |
| `test_ai_review.py` | 6 | admin AI-correction workflow: columns, route, immutability of original AI output, badges, PDF/history surfacing |
| `test_duplicate_link.py` | 6 | debounced auto duplicate-check hook, link/unlink-as-duplicate, badges and citizen notes, audit entries |
| `test_lifecycle.py` | 7 | enforced status state machine: legal walk, illegal jumps rejected, appeal/reopen paths, same-status remarks |
| `test_performance.py` | 10 | duplicate matrix caching, forecast memoization (TTL + invalidation), mtime report cache, pagination of queue/inbox/audit/citizen history with clamping, filter-scoped audit totals |
| `test_profile.py` | 5 | profile editing: persistence, session refresh, audit, duplicate email rejection, validation, login/CSRF gates |
| `test_priority_explanation.py` | 3 | "why this priority" context cards for citizens and admins, system-priority rows |

Run:

```powershell
python -m pytest tests/ -q        # 115 passed
```

## 19.3 Continuous Integration

`.github/workflows/ci.yml` runs on every push/PR:

* matrix: **Python 3.12 and 3.14** on `ubuntu-latest`
* generates a throw-away `.env` (no secrets needed)
* `pip install -r requirements.txt -r requirements-dev.txt`
* `python -m pytest tests/ -q`

A red build blocks the merge; the badge lives in the repository README.

## 19.4 Manual / Exploratory Checks

* Real-server boot smoke: `flask run` → `/`, `/login` 200;
  `/complaint/1/pdf` → 404 on an empty database (correct).
* Browser checks: geolocation button, image upload limit, mobile layouts,
  keyboard-only navigation (skip link → form → submit).
* End-to-end journey: submit → track (`/track` with tracking ID + mobile) →
  admin review / AI correction → legal status flow → resolve → citizen
  feedback → PDF download.
* E-mail path exercised manually with SMTP credentials configured once; with
  credentials absent the suite verifies the skip behaviour.

## 19.5 Quality Gates

1. Full pytest suite green (115/115).
2. `python -m compileall` clean.
3. No metric in docs or UI that is not present in a machine-readable report
   (`models/*_report.json`, `models/duplicate_report.json`,
   `experiments/RESULTS.md`).
