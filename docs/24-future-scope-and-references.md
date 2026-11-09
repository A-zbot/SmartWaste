# 24 · Future Scope and References

## 24.1 Future Scope

1. **Real-data acquisition** — execute the annotation workflow in
   `data/ANNOTATION.md` with a municipal partner: collect 12–24 months of
   historical complaints, double-annotate category/urgency and duplicate
   pairs, and re-run `experiments/evaluation.py` to replace synthetic
   scores with field scores.
2. **PostgreSQL migration** — move `db.py` to PostgreSQL + SQLAlchemy for
   multi-worker production, with connection pooling and row-level backups.
3. **Image-based classification** — a lightweight CNN (e.g. MobileNet
   transfer learning) over uploaded photos to corroborate the text-based
   category and flag misreports.
4. **Persistent rate limiting** — Redis-backed counters for login and
   submission throttling so limits hold across gunicorn workers.
5. **Automated retraining pipeline** — scheduled jobs that retrain when the
   data-drift monitor ( PSI on feature distributions ) exceeds a threshold,
   with model versioning and rollback.
6. **GIS integration** — ward/boundary shapefiles, service-level agreement
   (SLA) clocks per category, and route optimisation for collection vehicles
   using the hotspot map.
7. **Multilingual intake** — Indic-language complaint text (Hindi/regional)
   via transliteration or multilingual embeddings, since real complaints are
   rarely English-only.
8. **Push channels** — SMS and WhatsApp status notifications alongside
   e-mail, using the same best-effort delivery abstraction.
9. **Pilot evaluation** — A/B study in one ward measuring resolution time,
   duplicate rate and citizen satisfaction before/after deployment.
10. **Accessibility audit** — formal WCAG 2.2 AA audit and screen-reader
    testing (NVDA/VoiceOver) beyond the current automated checks.

## 24.2 References

1. Joachims, T. (1998). *Text Categorization with Support Vector Machines:
   Learning with Relevant Features.* ECML-98.
2. Ester, M., Kriegel, H.-P., Sander, J. and Xu, X. (1996). *A Density-Based
   Algorithm for Discovering Clusters in Large Spatial Databases with Noise.*
   KDD-96.
3. Rousseeuw, P. J. (1987). *Silhouettes: A Graphical Aid to the
   Interpretation and Validation of Cluster Analysis.* J. Comput. Appl. Math.
4. Hyndman, R. J. and Athanasopoulos, G. (2018). *Forecasting: Principles and
   Practice*, 2nd ed. OTexts — seasonal-naive baselines and accuracy
   measurement.
5. Breiman, L. (2001). *Random Forests.* Machine Learning, 45(1).
6. Pedregosa, F. et al. (2011). *Scikit-learn: Machine Learning in Python.*
   JMLR, 12.
7. Flask Documentation (2024). https://flask.palletsprojects.com/
8. OWASP (2021). *OWASP Top Ten* and *Cross-Site Request Forgery Prevention
   Cheat Sheet.*
9. W3C (2018). *Web Content Accessibility Guidelines (WCAG) 2.1.*
10. scikit-learn documentation — `TfidfVectorizer`, `DBSCAN` (haversine
    metric with `ball_tree`), `silhouette_score`.
11. reportlab documentation — *User Guide*, Platypus API.
12. Render Inc. documentation — Python web services, persistent disks.
13. GitHub Actions documentation — *Configuring a workflow*.

## 24.3 Artefact Index

| Artefact | Location |
|---|---|
| Evaluation harness | `experiments/evaluation.py` |
| Measured results | `experiments/RESULTS.md` |
| Model reports | `models/category_report.json`, `urgency_report.json`, `duplicate_report.json` |
| Training provenance | `models/training_meta.json` (SHA-256 of training data) |
| Duplicate corpus | `data/duplicate_pairs.csv` |
| Data honesty docs | `data/README.md`, `data/ANNOTATION.md` |
| Tests | `tests/` (73) |
| CI | `.github/workflows/ci.yml` |
| Deployment | `Procfile`, `render.yaml` |
| Live demo | https://smartwaste-nyvw.onrender.com/ |
