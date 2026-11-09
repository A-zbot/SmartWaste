# 06 · Literature Survey

## 6.1 Waste Classification from Text

Supervised text classification with bag-of-words and TF-IDF features remains
the industrial baseline for short, noisy documents such as citizen reports.
Joachims (1998) established SVM/TF-IDF text categorisation; later work showed
that linear models over TF-IDF remain competitive on short texts where deep
models overfit. SmartWaste therefore uses TF-IDF (1–2 grams, sublinear TF,
NLTK preprocessing) with Logistic Regression and Random Forest, selected by
5-fold cross-validation — a deliberate, explainable and reproducible choice
for an 800-row corpus rather than a large language model.

## 6.2 Duplicate and Near-Duplicate Detection

Near-duplicate detection classically combines lexical similarity (cosine over
TF-IDF, MinHash, shingles) with blocking keys. In geospatial complaint
systems, location is the second natural key: two complaints about "garbage
not collected" in localities 15 km apart are different incidents, while two
phrasings at the same street corner almost certainly are the same one.
SmartWaste's Module C follows this literature by fusing three signals —
cosine similarity, haversine distance with a hard 2 km gate, and a category
agreement bonus — into a single interpretable score with published weights
(0.65 / 0.25 / 0.10) and two thresholds (text gate 0.45, combined 0.55).

## 6.3 Spatial Clustering of Events

Density-based clustering is the standard tool for event hotspots: DBSCAN
(Ester, Kriegel, Sander, Xu, 1996) discovers arbitrarily shaped clusters and
labels sparse points as noise, which matches complaint data where isolated
reports are common. Because DBSCAN's eps is distance-based, a geographic
metric (haversine) with radius in metres is required. Cluster *quality* is
commonly assessed with the silhouette coefficient (Rousseeuw, 1987); SmartWaste
computes it on clustered points with the same haversine metric DBSCAN used,
and reports `null` with a reason when fewer than two clusters exist — an
explicit rejection of fabricated quality scores.

## 6.4 Complaint Volume Forecasting

Operational forecasting for service-request volumes typically compares a
seasonal-naive baseline (same weekday last week) against moving averages and
tree-based regressors over lag features. Hyndman & Athanasopoulos (2018)
recommend always reporting naive baselines so that model skill is measurable.
Module E implements exactly this ladder — seasonal-naive (t−7), 7-day moving
average and a Random Forest over lags 1–28 plus calendar features — with a
chronological split (test window never used for fitting) and an uncertainty
band of ±1.96 × measured test RMSE.

## 6.5 Explainable AI for Public Sector

Public administrators cannot act on unexplained predictions. Module F stores,
per prediction, the model identity, the most influential text features
(per-class contributions) and contextual factors (citizen's own category and
priority), and surfaces them on the admin detail page — consistent with
guidelines for contestable automated decision-making: a human remains in the
loop, with an explicit manual-review flag below the confidence threshold.

## 6.6 Summary of Adopted Techniques

| Problem | Technique | Source tradition |
|---|---|---|
| Text classification | TF-IDF + LogReg / RandomForest, CV selection | Joachims; scikit-learn practice |
| Duplicate detection | Cosine + haversine + category fusion | Near-duplicate literature + GIS blocking |
| Hotspot detection | DBSCAN (haversine) + silhouette | Ester et al.; Rousseeuw |
| Forecasting | Seasonal-naive / MA / RF with lag features | Hyndman & Athanasopoulos |
| Explainability | Feature contributions + context factors | XAI for tabular/text baselines |
