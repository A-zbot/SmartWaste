# 14 · Algorithms

## 14.1 Text Preprocessing (`intelligence/preprocessing.py`)

```
input text
  → lowercase
  → regex: keep [a-z0-9\s], collapse whitespace
  → word tokens
  → drop NLTK English stopwords (if the corpus is available)
  → lemmatise with NLTK WordNetLemmatizer (if available)
  → deterministic fallback (stopword list + simple stemmer) when NLTK data
    cannot be downloaded (offline builds)
  → cleaned text
```

The fallback guarantees the same function can run in CI without network
access; both paths are unit-tested.

## 14.2 Category / Urgency Classification (Module B)

* **Features:** `TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True,
  min_df=2, max_features=20000)` over the preprocessed text.
* **Candidates:** Logistic Regression (class-balanced) and Random Forest
  (500 trees, balanced).
* **Selection:** 5-fold stratified CV, metric = macro F1; the winner is
  serialised to `models/category_model.joblib` /
  `models/urgency_model.joblib` with its report.
* **Inference:** `pipeline.predict_proba` → label + confidence;
  `confidence < ML_CONFIDENCE_THRESHOLD (0.55)` ⇒ `needs_review = 1`.

## 14.3 Duplicate Detection (Module C)

For candidate pair (query, candidate):

```
text_sim   = cosine(TF-IDF(query), TF-IDF(candidate))          # shared vectorisers
geo_gate   = distance_km ≤ 2 km ? 1.0 : (both unknown ? 0.4 : 0.0)
cat_bonus  = categories equal ? 1.0 : 0.0
score      = 0.65*text_sim + 0.25*geo_gate + 0.10*cat_bonus

duplicate  = (text_sim ≥ 0.45) AND (score ≥ 0.55)
```

Distance uses the haversine formula (R = 6371 km). Live path scans at most
`DUPLICATE_CANDIDATES_LIMIT = 250` recent complaints; the offline harness
scores the same way through `pair_similarity()` / `score_duplicate()`.

**Measured (500 labelled pairs):** text gate P 0.9957 / R 0.932 / F1 0.9628;
combined rule P 1.0 / R 0.932 / F1 0.9648. Threshold sweep at
0.30–0.60 is reported in `experiments/RESULTS.md`.

## 14.4 DBSCAN Hotspots (Module D)

```
points = complaints with valid coordinates
clusters = DBSCAN(eps = HOTSPOT_EPS_METRES (400 m),
                  min_samples = HOTSPOT_MIN_SAMPLES (3),
                  metric = haversine, algorithm = ball_tree)
noise points → labelled "noise", excluded from KPI clusters
snapshot: label, centroid, counts, report_ids, params{eps, min_samples}
quality: silhouette(points, labels, metric=haversine) if ≥ 2 clusters
         else null with reason "not enough clusters"
```

## 14.5 Forecasting (Module E)

```
series_t = count of complaints per day over 180-day window
split    = last FORECAST_HORIZON_DAYS (36) days = test (never fitted on)

baselines:
  seasonal naive : ŷ_t = series_{t-7}
  moving average : ŷ_t = mean(series_{t-1..t-7})

model features (Random Forest, 300 trees):
  lags 1..28, rolling means (7, 14), day-of-week, day-of-month, is_weekend

metrics: MAE, RMSE on the test window
band   : ±1.96 × test RMSE
states : insufficient (< MIN_HISTORY_DAYS), baseline_only, ok
```

## 14.6 Recommendation Ranking (Module G)

* **Backlog:** complaints with `status ∉ {Resolved, Rejected}` ordered by age
  (`created_at` ASC) — the oldest unresolved work first.
* **Rising areas:** compare complaint counts per `area` between the last 14
  days and the previous 14 days; rank by increase.
* **Urgent:** `priority = Emergency` or `ai_urgency = Emergency` and not yet
  resolved, ranked by age.

Each recommendation carries its computed evidence (age in days, delta) so the
administrator can verify the reasoning without trusting the model.
