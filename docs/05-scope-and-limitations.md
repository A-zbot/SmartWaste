# 05 · Scope and Limitations

## 5.1 In Scope

* **Citizen web application**: signup/login, complaint submission with
  browser geolocation and image upload, complaint tracking by ID/mobile,
  complaint detail with status timeline, duplicate hints, notifications,
  feedback with rating.
* **Administrator console**: filterable queue, complaint detail with AI
  explanation, status workflow with remarks and resolution images, hotspot
  map with DBSCAN re-clustering, forecasting page, model-evaluation page,
  user management, audit log, messages, CSV and PDF exports.
* **Intelligence layer (Modules B–G)**: classification, duplicate detection,
  geospatial analysis, forecasting, explainability, recommendations — each
  with an offline evaluation path sharing the production code.
* **Quality infrastructure**: 73 pytest tests, GitHub Actions CI, honest
  synthetic-data documentation, reproducible experiment scripts.

## 5.2 Out of Scope

* Native mobile applications (the web UI is responsive, not a native app).
* Real-time GPS tracking of collection vehicles.
* Multi-tenant deployment for several municipalities in one instance.
* Payment, billing or service-level penalties.
* Image-based waste recognition (photographs are stored and displayed, not
  classified by a vision model).
* Production-grade RDBMS administration (the prototype uses SQLite).

## 5.3 Limitations (honest statement)

1. **Synthetic data.** All training and evaluation corpora
   (`data/*.csv`, `data/duplicate_pairs.csv`) are machine-generated or
   constructed from generated text. Reported model scores are therefore an
   *upper bound* and validate the pipeline, not real-world accuracy. The
   annotation workflow for acquiring real data is documented in
   `data/ANNOTATION.md`.
2. **Cold-start forecasting.** The forecasting module refuses to publish
   metrics when the database history is empty or shorter than the configured
   minimum; in that state it reports *insufficient data* instead of numbers.
3. **Geocoding quality.** Hotspot detection depends on coordinates captured
   in the browser; reports without coordinates are excluded from DBSCAN and
   counted explicitly (`Without coordinates` KPI).
4. **Single-process deployment.** Login throttling and retraining flags are
   in-memory per process; a multi-worker deployment would need a shared store.
5. **SMTP dependency.** E-mails are best-effort; if SMTP is unconfigured the
   application logs and continues (by design).
6. **Manual admin review.** Predictions below the confidence threshold are
   flagged for human review — the system assists, it does not auto-close
   complaints.
