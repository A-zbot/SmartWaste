# 07 · Feasibility Study

## 7.1 Technical Feasibility

| Aspect | Assessment |
|---|---|
| Language / framework | Python 3 + Flask 3 — mature, well documented, single-developer maintainable |
| Database | SQLite — zero-operations embedded RDBMS; schema created by `db.py` on first start; forward-only migrations |
| Machine learning | scikit-learn pipelines (TF-IDF + classifier) serialised with joblib; NLTK preprocessing with a deterministic offline fallback if corpora are missing |
| Geospatial | Pure-Python haversine + sklearn DBSCAN (`ball_tree`, haversine metric) — no PostGIS required |
| PDF export | reportlab, rendered in-process (no external service) |
| E-mail | Standard-library SMTP (TLS), best-effort |
| Hosting | Any WSGI host (gunicorn); Render blueprint included |
| Reproducibility | Seeded generators (`seed 42`), SHA-256 of training data recorded in `models/training_meta.json` |

**Conclusion:** all components are proven open-source technologies with no
exotic infrastructure; the system can be built and operated by a small team.

## 7.2 Economic Feasibility

* **Development cost:** student/academic effort; no licensed software.
* **Running cost:** SQLite and a free-tier or ₹-level web instance; NLTK and
  scikit-learn models train in seconds on CPU (800 rows), so no GPU budget is
  required. Model retraining is a manual/triggered action, not a scheduled
  cloud job.
* **Cost of inaction:** manual triage of thousands of complaints/month and
  duplicated field visits cost far more than the hosting bill.

## 7.3 Operational Feasibility

* Citizens already report waste by text; the form mirrors the information a
  clerk would ask for (location, category, priority, description, photo).
* Administrators get a single console that matches their existing workflow
  (Submitted → Under Review → Assigned → In Progress → Resolved/Rejected)
  with remarks, images and an audit trail.
* Failures degrade gracefully: no SMTP ⇒ emails skipped; no coordinates ⇒
  complaint still filed and counted; insufficient history ⇒ forecast states
  so; low model confidence ⇒ manual-review flag instead of a wrong
  auto-decision.

## 7.4 Schedule Feasibility

| Phase | Content | Effort |
|---|---|---|
| 1 | Repository audit & defect analysis | short |
| 2 | Backend/database corrections | short |
| 3 | Evaluation harness (pairs, silhouette, reports) | medium |
| 4 | PDF export & status e-mails | short |
| 5 | Frontend accessibility hardening | short |
| 6 | Security tests + CI | short |
| 7 | MCA documentation | medium |

All phases are sequential and independently verifiable (each phase ends with
a green test suite), which keeps the project on schedule for submission.
