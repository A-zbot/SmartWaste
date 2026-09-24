# ♻️ SmartWaste – Smart Waste Reporting & Management System

SmartWaste is a web-based waste management platform designed to make waste reporting faster, easier, and more transparent.

The system allows citizens to report waste-related issues by providing their location, waste category, priority, description, and an optional image. Administrators can then view reported complaints and update their status through an admin dashboard.

---

## 🚀 Live Demo

👉 [**View SmartWaste Live**](https://smartwaste-nyvw.onrender.com/)

## 🚀 Features

### 👤 Citizen Features

- 📝 Submit waste complaints online
- 📍 Automatically detect current location using browser geolocation
- 🗑️ Select waste category
- 🚨 Set complaint priority
- 📸 Upload an image of the waste
- 📱 Mobile-friendly interface
- ✅ Receive confirmation after submitting a report

### 🛠️ Admin Features

- 🔐 Secure admin login
- 📊 View all submitted waste reports
- 🔎 Review complaint details
- 📍 View reported locations
- 🖼️ View uploaded waste images
- 🔄 Update complaint status
- 📋 Manage reported waste issues

### 📩 Contact System

- Users can send messages through the contact page
- Messages are stored in the database for administrative review

### 📧 Email Notifications

- Every submitted waste report is emailed to the configured inbox (`REPORT_NOTIFY_EMAIL`, defaults to `garvitagarwall.army@gmail.com`)
- The email contains the report ID, reporter details, location, priority, description and the uploaded image as an attachment
- Sending is best-effort: a mail failure never blocks or breaks a report submission

---

## ⚙️ Configuration

Copy `.env.example` to `.env` and fill in the values.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | Admin dashboard login |
| `REPORT_NOTIFY_EMAIL` | Inbox that receives new-report emails (default `garvitagarwall.army@gmail.com`) |
| `SMTP_HOST` / `SMTP_PORT` | SMTP server, defaults `smtp.gmail.com` / `587` |
| `SMTP_USER` / `SMTP_PASSWORD` | SMTP login — for Gmail use an [App Password](https://myaccount.google.com/apppasswords) (regular passwords are rejected) |
| `SMTP_FROM` | Sender address, defaults to `SMTP_USER` |

If `SMTP_USER` or `SMTP_PASSWORD` is missing, the app runs normally and simply skips the email.

---

## 🏗️ Project Architecture

```text
                    ┌─────────────────────┐
                    │       User          │
                    │   Web Browser       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Flask Web App    │
                    │      app.py         │
                    └──────────┬──────────┘
                               │
             ┌─────────────────┼─────────────────┐
             │                 │                 │
             ▼                 ▼                 ▼
       ┌───────────┐     ┌────────────┐    ┌─────────────┐
       │ Templates │     │   SQLite   │    │   Uploads   │
       │   HTML    │     │  Database  │    │    Images   │
       └───────────┘     └────────────┘    └─────────────┘
             │
             ▼
       ┌──────────────┐
       │ Static Files │
       │ CSS + JS      │
       └──────────────┘
