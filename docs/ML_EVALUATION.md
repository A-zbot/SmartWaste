# SmartWaste — ML Evaluation Report

> **Every number in this document was measured by a committed script.**
> Reproduce with:
> ```bash
> python scripts/train_models.py       # writes models/*_report.json + training_meta.json
> python experiments/evaluation.py     # writes models/duplicate_report.json + experiments/RESULTS.md
> ```
> Source of truth: `models/category_report.json`, `models/urgency_report.json`,
> `models/duplicate_report.json`, `experiments/RESULTS.md` (auto-generated).
> **All data is synthetic** — see `docs/DATASET_DOCUMENTATION.md`. These scores
> validate the pipeline; they are *not* claims of real-world accuracy.

---

## 1. Evaluation protocol

| Aspect | Protocol |
|---|---|
| Primary metric | **F1-macro** (robust to the 8% Emergency minority class) |
| Supporting metrics | accuracy, precision-macro, recall-macro, per-class P/R/F1, confusion matrix, full classification report |
| Validation | 5-fold stratified CV (`shuffle=True, random_state=42`) on the training partition only |
| Test partition | stratified 20% hold-out (`random_state=42`), scored after selection |
| Independent evaluation | 80-row handwritten synthetic holdout — never used for training, tuning or selection |
| Selection rule | highest mean CV F1-macro on the training partition; tie-break prefers Logistic Regression |
| Reproducibility | fixed seeds everywhere; dataset SHA-256 + library versions recorded in `models/training_meta.json` |
| Model version | `trained_at` ISO timestamp stored in each report, written to `predictions.model_version` in the DB at inference, displayed on PDFs |

## 2. Classification results (measured)

### Category task (8 classes, 800 rows)

| Candidate | CV F1-macro (5-fold) | Test accuracy | Test F1-macro | Holdout accuracy | Holdout F1-macro |
|---|---|---|---|---|---|
| Logistic Regression | 0.9455 ± 0.0216 | **0.9938** | **0.9934** | 0.7875 | **0.8003** |
| **Random Forest (selected)** | **0.9486 ± 0.0149** | 0.9688 | 0.9649 | 0.7875 | 0.7907 |

- **Selected model: Random Forest** by the documented rule (highest CV
  F1-macro; the 0.003 CV gap is within noise).
- **Honest observation:** on the independent holdout the *non-selected*
  Logistic Regression scores higher (F1-macro 0.8003 vs 0.7907) and higher on
  the test split too. This is recorded rather than hidden; changing the
  selection rule after seeing holdout results would itself be a form of
  leakage, so the rule stays as specified in `docs/DATASET_DOCUMENTATION.md` §5.
- Selected-model test classification: macro P 0.9741 / R 0.9593; weakest
  classes on the holdout are Food Waste (F1 0.67), Open Garbage (0.70),
  Plastic Waste (0.71), E-Waste (0.71) — per-class tables and both confusion
  matrices live in `models/category_report.json` and render on `/admin/models`.

### Urgency task (4 levels, 800 rows)

| Candidate | CV F1-macro (5-fold) | Test accuracy | Test F1-macro | Holdout accuracy | Holdout F1-macro |
|---|---|---|---|---|---|
| **Logistic Regression (selected)** | **0.9556 ± 0.0297** | **0.9812** | **0.9852** | **0.8625** | **0.8560** |
| Random Forest | 0.8784 ± 0.0262 | 0.9313 | 0.9374 | 0.5375 | 0.5515 |

\* RF urgency metrics per `urgency_report.json` `models[]`; the RF also
collapses on the independent holdout (F1-macro 0.5515), confirming LR as the
right choice for this task.

- Holdout per-class F1 (LR): Low 0.936, Medium 0.846, High 0.818,
  Emergency 0.824 — Emergency is the hardest class, consistent with its 8%
  training share.

### Why these algorithms

- **TF-IDF + Logistic Regression** — strong, fast, interpretable baseline for
  text classification; its coefficients double as the explainability signal
  used in the UI (`intelligence/explainability.py`).
- **TF-IDF + Random Forest** — non-linear competitor that can capture
  feature interactions; included to make model selection *empirical* rather
  than assumed. It wins category CV, loses urgency badly.
- No third classifier was added: with a fixed synthetic corpus, a third
  candidate would add compute without a meaningful scientific comparison.
  (Documented scope decision.)

## 3. Duplicate detection (500 labelled pairs)

| Decision rule | Precision | Recall | F1 | TP | FP | FN |
|---|---|---|---|---|---|---|
| Text gate only (cosine ≥ 0.45) | 0.9957 | 0.9320 | 0.9628 | 233 | 1 | 17 |
| Combined rule (text 0.65 + haversine 0.25 + category 0.10) | **1.0000** | 0.9320 | **0.9648** | 233 | 0 | 17 |

- Distance is **haversine** (never raw Euclidean on lat/lng); 2 km hard gate;
  neutral geo score 0.4 when coordinates are unknown.
- Threshold sweep (0.30–0.60) in `experiments/RESULTS.md` §C — 0.45 chosen
  for precision; the sweep exists so the choice is auditable.
- Caveats: constructed corpus; offline pair scoring fits TF-IDF on the pair
  alone while the live path fits on the candidate corpus (same decision rule,
  slightly different IDF statistics).
- Duplicates are **advisory only** — nothing is auto-deleted or auto-rejected
  on similarity alone; administrators link duplicates explicitly.

## 4. Geographic hotspots (DBSCAN)

- Metric: sklearn `haversine` on radian coordinates with `ball_tree`;
  eps = 400 m (configurable), min_samples = 3, minimum 3 complaints per
  published cluster.
- Quality: silhouette computed **with the same haversine metric**; reported
  honestly as `None` + reason when fewer than 2 clusters exist.
- **Current database state:** not enough geocoded complaints to form
  clusters — no quality score is reported rather than a fabricated one
  (`experiments/RESULTS.md` §D).

## 5. Forecasting (complaint volume)

Protocol (see `intelligence/forecasting.py`):
- Daily counts over a 180-day window, zero-filled for missing days.
- **Chronological split** — last ~20% of days (min 3) held out; never a random
  split; lag/rolling features use past values only.
- Baselines: seasonal naive (t-7) and 7-day moving average; ML model:
  RandomForestRegressor (300 trees) on lag/rolling/day-of-week features.
- Metrics: **MAE and RMSE** for every model on the same test days; forecast
  band = ±1.96 × measured test RMSE (normal approximation, labelled as such).
- Honest statuses: `insufficient` (< 14 days → no forecast at all),
  `baseline_only` (< 28 days), `ok`.

**Current database state:** 0 complaints in the last 180 days — the series is
all zeros, so every model scores MAE 0.0 / RMSE 0.0 over 36 test days. That
measures the harness, **not** forecast skill; it is flagged as such in
`experiments/RESULTS.md` §E and in the UI. Re-run after real reports exist.

Limitations to state in any presentation: the system forecasts *complaint
counts*, never waste tonnage (no tonnage measurements exist); low-volume
series make any model indistinguishable from the baselines.

## 6. Evaluation-vs-artifact caveat

After model selection, the winning estimator is **refit on all 800 rows** to
maximize training data for deployment (`model_training.py`), while the reported
test/holdout metrics come from the candidate fitted on the 640-row training
split. The served joblib therefore has no metric of its own — the reported
numbers characterise the *selection procedure*, not the exact deployed
weights. This is a deliberate, documented trade-off (more training data for
the model that actually serves traffic).

## 7. Model artifacts and versioning

| Artifact | Contents |
|---|---|
| `models/category_pipeline.joblib` | fitted TF-IDF + classifier (single sklearn `Pipeline`) |
| `models/urgency_pipeline.joblib` | same for urgency |
| `models/{task}_report.json` | labels, distributions, split config, CV results, per-candidate parameters, test + holdout metrics/reports/matrices, selection rule, `trained_at`, library versions |
| `models/training_meta.json` | `trained_at`, dataset paths/rows/SHA-256, artifact list, library versions |
| `models/duplicate_report.json` | pair-corpus metrics, threshold sweep, provenance |
| DB `predictions.model_version` | `trained_at` captured at inference time, stored per complaint, shown on PDFs |

Inference always loads the persisted pipeline (never re-fits), caches it
thread-safely, and degrades gracefully to `available=False` +
`ai_needs_review=1` if artifacts are missing — complaint submission never
depends on model availability.

## 8. Model monitoring (administrator feedback)

Every administrator confirmation or correction is appended to the
`prediction_feedback` table with: original vs corrected category/urgency,
model name/version in force, administrator identity, timestamp and note.
Original `ai_*` predictions are never overwritten. Correction statistics are
shown on the dashboard (reviews, corrections, correction rate) — they are the
ground-truth signal for deciding when a retrain is justified. **Retraining is
never triggered automatically from feedback**; it stays a manual, validated
action (`POST /admin/models/retrain`).
