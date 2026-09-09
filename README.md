# SmartWaste ♻️

A Flask-based smart waste reporting and administration system. Citizens can submit waste reports with location, category, priority, description and an optional image. Administrators can log in and update report status.

## Features

- Waste report submission
- Browser geolocation support
- Image upload (PNG/JPG/JPEG/WEBP)
- SQLite database
- Admin login
- Admin dashboard and report statistics
- Report status updates
- Contact form
- Responsive frontend
- Ready for deployment with Gunicorn + Render

## Project structure

```text
smartwaste/
├── app.py
├── requirements.txt
├── render.yaml
├── Procfile
├── .env.example
├── .gitignore
├── README.md
├── static/
├── templates/
└── uploads/
```

## Run locally

### 1. Create a virtual environment

Windows:

```bash
python -m venv venv
venv\Scripts\activate
```

macOS/Linux:

```bash
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure admin credentials (optional)

Copy `.env.example` to `.env` and set your own values. The app reads environment variables directly; for local development you can also set them in your terminal.

Windows PowerShell:

```powershell
$env:SECRET_KEY="your-secret-key"
$env:ADMIN_USERNAME="admin"
$env:ADMIN_PASSWORD="your-password"
```

### 4. Start the app

```bash
python app.py
```

Open `http://127.0.0.1:5000`.

## Deploy using GitHub + Render

**GitHub stores the source code; Render runs the Flask application.** GitHub Pages cannot run this Flask backend.

### Step 1 — Create a GitHub repository

Create a new repository on GitHub, then upload the contents of this folder. The important files (`app.py`, `requirements.txt`, `render.yaml`, `templates/`, and `static/`) must be in the repository root.

### Step 2 — Push with Git

```bash
git init
git add .
git commit -m "Initial SmartWaste project"
git branch -M main
git remote add origin YOUR_GITHUB_REPOSITORY_URL
git push -u origin main
```

### Step 3 — Deploy on Render

In Render, create a **Web Service** and connect the GitHub repository. Use:

- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`

The included `render.yaml` can also be used for configuration.

### Step 4 — Add environment variables

Set these in Render:

```text
SECRET_KEY = a-long-random-secret
ADMIN_USERNAME = admin
ADMIN_PASSWORD = your-strong-password
```

Do **not** commit real passwords or `.env` files to GitHub.

## Admin

Open `/login` on your deployed site. The username and password are controlled by `ADMIN_USERNAME` and `ADMIN_PASSWORD`.

## Important deployment limitation

This version uses SQLite and local image storage. On hosting with an ephemeral filesystem, data and uploaded images can be lost after certain restarts/redeploys. That is acceptable for a college/demo prototype, but a production system should use PostgreSQL (or another managed database) and persistent object storage such as S3-compatible storage.

## Security notes

Before treating this as a production application, add proper user authentication, CSRF protection, stronger validation, rate limiting, secure POST-only admin actions, persistent storage, and production database/object storage.
