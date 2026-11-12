# SmartWaste - Smart Waste Reporting & Management System

[![CI](https://github.com/A-zbot/SmartWaste/actions/workflows/ci.yml/badge.svg)](https://github.com/A-zbot/SmartWaste/actions/workflows/ci.yml)

SmartWaste is a web-based waste reporting and management platform for
municipal-style operations. Citizens submit waste complaints from any device;
an AI pipeline classifies and prioritises each report; administrators work the
queue through an operations console with a status lifecycle, duplicate
handling, geospatial hotspots, demand forecasting and a full audit trail.

> **Data honesty:** every labelled dataset, model score and seeded demo row in
> this repository is synthetic and disclosed as such (`data/README.md`,
> `data/ANNOTATION.md`, `models/*_report.json`, and the admin models page).
> Reported metrics are pipeline checks, not real-world accuracy claims.

---

## Live Demo

[**View SmartWaste Live**](https://smartwaste-nyvw.onrender.com/)

---

## Features

### Citizen portal

- Account signup / login with complaint history, notifications and feedback on
  resolved complaints
- Submit waste reports with location (browser geolocation), waste category,
  priority, description and an optional photo
- Tracking ID on every report; status lookup at `/track` (tracking ID first,
  mobile number as confirmation)
- Complaint detail page: status timeline, administrator remarks, AI category
  and urgency with a plain-language **"why this priority"** explanation,
  possible-duplicate context and a verified-category badge once an
  administrator confirms the AI output
- PDF export of a complaint, profile editing (name, email, password),
  mobile-friendly UI

### Admin console

- Dashboard with KPIs, charts and data-quality recommendations
- Complaint queue with server-side filters, status tabs and pagination;
  CSV export and per-complaint PDF
- **Status lifecycle** enforced server-side:
  `Submitted -> Under Review -> Assigned -> In Progress -> Resolved`, plus
  `Rejected` and the appeal/reopen paths - illegal jumps are rejected
- **AI correction workflow**: administrators verify or override the predicted
  category/urgency with a note; the original AI output stays immutable and
  verified rows are badged everywhere
- **Duplicate handling**: automatic text + geospatial similarity check
  (debounced while typing, on complaint detail pages), and an explicit
  link/unlink-as-duplicate control with badges for admins and citizens
- Hotspot map (DBSCAN clustering over geocoded complaints) with explicit
  clustering controls
- 30-day demand forecasting with seasonal-naive and moving-average baselines,
  a Random Forest model where history allows, measured test error bands, and
  honest "insufficient data" states instead of fabricated forecasts
- Model evaluation page (cross-validation comparison, confusion matrices,
  holdout scores) with admin-triggered retraining
- User management, contact-message inbox, and a filterable, paginated audit
  trail - all server-side paginated (queue, inbox, audit, citizen history)

### Intelligence modules (Flask-agnostic, testable in isolation)

- Complaint classifier (waste category) and urgency predictor:
  TF-IDF + classical ML with 5-fold CV model selection and plain-language
  explanations of every prediction
- Priority/urgency explanation: citizen priority, AI prediction and effective
  priority with the factors behind the score
- Duplicate detection: TF-IDF cosine similarity + haversine distance + recency
  window + category agreement (cached candidate matrix)
- Forecasting and hotspot clustering as described above

### Security

- CSRF protection on every state-changing form **and** JSON endpoint
- Role gates (`admin_required`, `citizen_required`) with server-side session
  checks; per-account login failure tracking and temporary lockout
- Security headers: CSP, Permissions-Policy, prod-only HSTS; HTML-escaped
  outbound report emails
- Append-only audit log covering logins, submissions, status changes, AI
  corrections, duplicate links, exports and retraining

---

## Quickstart

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit the values
python app.py                 # http://127.0.0.1:5000
```

Trained model artifacts ship with the repository, so the app starts
immediately. On a fresh clone without artifacts the first start trains the
models automatically; set `AUTO_TRAIN_MODELS=0` to skip that.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests/ -q
```

The suite covers the full stack: submission and tracking, the status state
machine, AI review, duplicate linking, security (CSRF, headers, access
control), pagination, forecasting/duplicate/evaluation honesty checks, and
the public pages. **115 tests, all passing.**

## Configuration

Copy `.env.example` to `.env` and fill in the values.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin dashboard login |
| `REPORT_NOTIFY_EMAIL` | Inbox that receives new-report emails |
| `SMTP_HOST` / `SMTP_PORT` | SMTP server, defaults `smtp.gmail.com` / `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP login - for Gmail use an [App Password](https://myaccount.google.com/apppasswords) (regular passwords are rejected) |
| `SMTP_FROM` | Sender address, defaults to `SMTP_USER` |
| `DATABASE_PATH` | SQLite database location (default `waste.db`) |
| `AUTO_TRAIN_MODELS` | Set `0` to never auto-train on startup |

If `SMTP_USER` or `SMTP_PASSWORD` is missing, the app runs normally and
simply skips the email. Email sending is best-effort: a mail failure never
blocks a report submission.

---

## Project Architecture

```text
                    +-----------------------+
                    |      Citizen /        |
                    |   Administrator       |
                    |     Web Browser       |
                    +-----------+-----------+
                                |
                                v
                    +-----------------------+
                    |    Flask Web App      |
                    |       app.py          |
                    +-----------+-----------+
                                |
        +-----------+-----------+-----------+------------+
        |           |           |           |            |
        v           v           v           v            v
  +-----------+ +--------+ +---------+ +-----------+ +-----------+
  | Modules   | | SQLite | |  ML /   | | Templates | |  Static   |
  | auth,     | |   DB   | | NLP /   | |   HTML    | | CSS + JS  |
  | complaints| | waste  | | Geo /   | +-----------+ +-----------+
  | admin,    | |  .db   | | Forecast|
  | analytics | +--------+ +---------+
  +-----------+
```

- `modules/` - blueprints: authentication, complaints, admin, analytics, public
- `intelligence/` - ML/NLP/geo/forecast modules (no Flask dependencies)
- `experiments/` - offline evaluation entry points and recorded results
- `data/` - synthetic corpora with honesty documentation
- `models/` - trained artifacts + evaluation reports
- `templates/`, `static/` - server-rendered UI, CSS, JS
- `docs/` - full project documentation set (abstract to future scope)
- `tests/` - pytest suite (see above)

## Documentation

- `docs/README.md` - index of the full documentation set
- `AUDIT_REPORT.md` - Phase 0 codebase audit findings
- `DEVELOPMENT_PLAN.md` - phased hardening plan (Phases 0-8, all completed)
- `data/README.md` - synthetic data disclosure and schema

## Deployment

Render blueprint (`render.yaml`) and a gunicorn `Procfile` are included; the
live demo link above runs this configuration.

---

*SmartWaste 2.0 - MCA major project.*
