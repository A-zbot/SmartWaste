# 20 · Results and Evaluation

> All numbers below were produced by `python experiments/evaluation.py` and
> `python scripts/train_models.py` and are stored in machine-readable form
> (`models/*_report.json`, `models/duplicate_report.json`,
> `experiments/RESULTS.md`). Nothing is hand-entered. Training corpora are
> **synthetic** — these results validate the pipeline, not real-world
> accuracy.

## 20.1 Module B — Classification

### Category task (8 classes)

| Metric | Value |
|---|---|
| Selected algorithm | Random Forest (best 5-fold CV macro-F1) |
| 5-fold CV F1-macro | **0.9486** (± 0.0149) |
| Held-out test split | accuracy 0.9688, F1-macro **0.9649**, P-macro 0.9741, R-macro 0.9593 |
| Independent handwritten holdout (80 rows) | accuracy 0.7875, F1-macro **0.7907** |

### Urgency task (4 levels)

| Metric | Value |
|---|---|
| Selected algorithm | Logistic Regression |
| 5-fold CV F1-macro | **0.9556** (± 0.0297) |
| Held-out test split | accuracy 0.9812, F1-macro **0.9852**, P-macro 0.9885, R-macro 0.9825 |
| Independent handwritten holdout (80 rows) | accuracy 0.8625, F1-macro **0.856** |

Confusion matrices for both tasks are stored in the report JSON and rendered
on `/admin/models`. The handwritten holdout — written independently of the
generator — is the most honest figure and is deliberately reported
alongside the optimistic in-distribution numbers.

## 20.2 Module C — Duplicate Detection

Evaluated on **500 labelled pairs** (250 duplicate / 250 not; constructed
coordinates, `construction` column in `data/duplicate_pairs.csv`).

| Decision rule | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| Text gate (cosine ≥ 0.45) | 0.9957 | 0.9320 | 0.9628 | 233 | 1 | 17 |
| Full combined rule (text + geo + category) | 1.0000 | 0.9320 | **0.9648** | 233 | 0 | 17 |

Text-threshold sweep (0.30–0.60) shows F1 peaking at 0.30 (0.9841) and
declining smoothly; 0.45 was retained as the production gate because it
prioritises precision (0.9957) — false positives would wrongly merge
distinct complaints, which the product rule treats as worse than missing a
near-duplicate.

## 20.3 Module D — Hotspot Detection

Database state at evaluation time: **no geocoded complaints** →
"Not enough geocoded complaints to form clusters — no quality score is
reported rather than a fabricated one." The harness, helper
(`_cluster_quality`) and the `/admin/map` honest-empty state are tested;
silhouette becomes available automatically once ≥ 2 clusters exist.

## 20.4 Module E — Forecasting

* History window: 180 days; chronological split (last 36 days = test);
  uncertainty band ±1.96 × measured test RMSE.
* Database state: 0 complaints → all series are zeros, so the run reports
  MAE/RMSE 0.0 for seasonal-naive, 7-day moving average and Random Forest
  with the explicit note that *the backtest measures the harness, not
  forecast skill, until real reports exist*.

## 20.5 System-Level Results

| Item | Result |
|---|---|
| Automated tests | **73 passed** (6 files) |
| CI | GitHub Actions, Python 3.12 + 3.14 matrix |
| Routes | 38 (admin 16, complaints 11, public 5, auth 5, analytics 1) |
| Security headers | present on HTML and PDF responses |
| CSRF | enforced on form **and** JSON endpoints |
| Live deployment | https://smartwaste-nyvw.onrender.com/ (Render + gunicorn) |

## 20.6 Interpretation

1. The ML pipeline works end-to-end and its scores are reproducible from
   committed scripts.
2. Precision-first duplicate detection fits the municipal use case
   (surfacing evidence, never auto-rejecting).
3. The two modules blocked by empty data (D, E) demonstrate the project's
   central honesty rule: **insufficient data is reported as such**, and the
   same code will produce real metrics as soon as complaints flow in.
