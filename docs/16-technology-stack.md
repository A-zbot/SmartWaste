# 16 · Technology Stack

| Layer | Technology | Version / notes |
|---|---|---|
| Language | Python | 3.12 / 3.14 (CI matrix) |
| Web framework | Flask + Werkzeug | 3.x, blueprint modularisation |
| Server (prod) | gunicorn | `Procfile`: `web: gunicorn app:app` |
| Database | SQLite 3 | via stdlib `sqlite3`, schema in `db.py` |
| ML / data | scikit-learn, pandas, numpy | ≥1.6 / ≥2.3 / ≥2.3 |
| NLP | NLTK (stopwords, lemmatizer) | with deterministic offline fallback |
| Serialisation | joblib | model pipelines |
| PDF export | reportlab | ≥4.2,<5 — server-side, no headless browser |
| E-mail | smtplib (STARTTLS) | best-effort, non-blocking |
| Frontend | HTML5, CSS3, vanilla JS | responsive, no SPA build step |
| Charts | Chart.js (CDN) | guarded by `chartsAvailable()` |
| Maps | Leaflet + OpenStreetMap tiles | admin hotspot view |
| Tests | pytest | `requirements-dev.txt`: `pytest>=8,<9` |
| CI | GitHub Actions | `.github/workflows/ci.yml`, matrix 3.12/3.14 |
| Config | python-dotenv + `config.py` | all thresholds centralised |
| Hosting | Render (blueprint) | `render.yaml`, live demo linked in README |
| Version control | Git / GitHub | `A-zbot/SmartWaste` |

**Design rationale:** a deliberately conservative stack — server-rendered
Flask templates and vanilla JS avoid a build pipeline, keep the code readable
for examiners, and make the 73-test suite meaningful. Machine learning uses
scikit-learn pipelines so training and serving share one artefact.
