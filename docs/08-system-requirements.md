# 08 · System Requirements

## 8.1 Functional Requirements

| ID | Requirement | Module |
|---|---|---|
| FR-01 | Register / login / logout citizens; profile with password change | A |
| FR-02 | Submit a complaint with text, category, priority, optional image and browser geolocation | A |
| FR-03 | Assign tracking ID and show a success page after submission | A |
| FR-04 | Track a complaint by tracking ID, report ID or mobile number | A |
| FR-05 | Show complaint detail with status timeline and history events | A |
| FR-06 | Predict category and urgency with confidence at intake; store explanation | B |
| FR-07 | Flag predictions below the confidence threshold for manual review | B |
| FR-08 | Detect possible duplicates (text + distance + category) and surface evidence | C |
| FR-09 | Cluster geocoded complaints (DBSCAN) and expose hotspots on an admin map | D |
| FR-10 | Persist the latest clustering run and its parameters/quality | D |
| FR-11 | Forecast complaint volume for the next N days with baselines | E |
| FR-12 | Store per-prediction explanation (features + context) | F |
| FR-13 | Rank backlog, rising areas and urgent work as recommendations | G |
| FR-14 | Admin queue with filters, status workflow, remarks, resolution images | G |
| FR-15 | Export filtered complaints as CSV and a complaint as PDF | G |
| FR-16 | Notify administrators of new reports and citizens of status changes (best-effort e-mail) | A |
| FR-17 | In-app notifications for the owning citizen | A |
| FR-18 | Contact messages stored for administrative review | public |
| FR-19 | Audit log for status changes, exports, logins and user actions | security |
| FR-20 | Model evaluation page + machine-readable evaluation reports | B |

## 8.2 Non-Functional Requirements

| ID | Requirement | How addressed |
|---|---|---|
| NFR-01 | Security | CSRF on every state-changing request, HttpOnly/SameSite cookies, login throttling, constant-time admin credential check, security headers |
| NFR-02 | Reliability | E-mails best-effort; ML/NLTK failures fall back deterministically; DB transactions around status changes |
| NFR-03 | Performance | Indexed SQLite columns (`status`, `created_at`, `user_id`, `area`, …); model inference < 50 ms on CPU; duplicate search limited to 250 recent candidates |
| NFR-04 | Usability | Responsive layouts, skip links, labelled forms, honest empty states |
| NFR-05 | Maintainability | Blueprint modules, `config.py` centralising all tunables, 73 tests, CI |
| NFR-06 | Reproducibility | Seeded data generators, recorded training-data hashes, evaluation script |
| NFR-07 | Honesty | Insufficient-data states; synthetic-data caveats in README/data docs/results |

## 8.3 Hardware Requirements (development & demo)

* CPU: dual-core 64-bit (model training runs in seconds)
* RAM: 4 GB (scikit-learn + Flask; category pipeline ≈ 10 MB on disk)
* Disk: ~500 MB for Python environment, models and uploads
* Network: browser geolocation requires HTTPS in production

## 8.4 Software Requirements

* Python 3.12+ (CI verified on 3.12 and 3.14)
* Flask 3.x, Werkzeug, python-dotenv, gunicorn
* scikit-learn ≥ 1.6, pandas, numpy, nltk, joblib, reportlab
* SQLite 3 (bundled with Python)
* Browser with JavaScript and (optionally) geolocation API
