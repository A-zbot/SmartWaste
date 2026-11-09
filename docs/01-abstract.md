# 01 · Abstract

**SmartWaste 2.0 — AI-Driven Urban Waste Management and Predictive Decision
Support System**

Municipal solid-waste management is a chronic urban challenge: complaints
arrive as unstructured free text, the same incident is often reported many
times, hotspots repeat in the same localities, and authorities plan collections
without any quantitative view of future load. SmartWaste 2.0 addresses these
problems with an integrated web platform that converts ordinary citizen
complaints into classified, deduplicated, geolocated and forecasted
intelligence for municipal decision-makers.

The system accepts complaints through a public web interface and enriches
each submission with machine-learning output **before** it is stored: an
8-class waste-category classifier and a 4-level urgency predictor (TF-IDF
features with Logistic Regression and Random Forest, selected by 5-fold
cross-validation), a duplicate detector that combines TF-IDF cosine similarity
with haversine proximity and category agreement, and an explainability layer
that records which words and context factors drove each prediction.
Complaints are clustered with DBSCAN (haversine metric, 400 m default radius)
to reveal recurring hotspots, and complaint volumes are forecast with
seasonal-naive, moving-average and Random Forest regressor baselines under a
strict chronological train/test split. A decision-support layer ranks backlog,
rising areas and urgent work for the administrator console.

Every metric reported by the platform is produced by a reproducible
evaluation harness (`experiments/evaluation.py`) and written to
`models/*_report.json` and `experiments/RESULTS.md`; the system states
plainly when data is insufficient rather than inventing a number. All
training and evaluation corpora shipped with the project are synthetic and
are labelled as such — the reported scores validate the pipeline, not
real-world accuracy.

The platform is implemented in Python with the Flask framework, SQLite,
server-side PDF/CSV export and best-effort SMTP notifications, and is
delivered with 73 automated tests plus a GitHub Actions continuous-integration
workflow. The result is a complete, auditable prototype of an
AI-assisted waste-management decision-support system suitable for a municipal
corporation pilot.

**Keywords:** waste management, complaint classification, TF-IDF, duplicate
detection, DBSCAN, time-series forecasting, explainable AI, Flask, decision
support.
