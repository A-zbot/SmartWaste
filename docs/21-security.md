# 21 · Security

## 21.1 Threat Model (summary)

| Threat | Mitigation |
|---|---|
| Cross-site request forgery | CSRF token on every state-changing form **and** JSON endpoint (`security._verify_csrf`; JSON requests without a token now get a JSON 400) |
| Session hijacking | `HttpOnly`, `SameSite=Lax` session cookie; `Secure` when served over HTTPS |
| Credential stuffing | Per-username login throttling (in-memory window counter) + generic error messages |
| Admin credential leak | Constant-time comparison for the env-provided admin bootstrap; no default password in code |
| Privilege escalation | `@admin_required` / `@citizen_required` decorators on every admin route; role checks in the service layer |
| Clickjacking | `X-Frame-Options: SAMEORIGIN` on all responses |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| Referrer leakage | `Referrer-Policy: same-origin` |
| Stored XSS | Jinja auto-escaping everywhere; user HTML never rendered; e-mail bodies HTML-escaped before sending |
| Unrestricted upload | 5 MB limit, extension + content-type allowlist, randomised filenames outside the code tree (`uploads/`) |
| SQL injection | parameterised queries throughout (`?` placeholders) |
| Path traversal | upload/download paths resolved and checked against the configured upload root |
| Password storage | Werkzeug `generate_password_hash` (scrypt/PBKDF2 default) |
| Audit gaps | append-only `audit_logs` for status changes, exports, logins, user management |

## 21.2 Security Headers (installed in `app.py`)

```
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: same-origin
```

Verified by `tests/test_security.py` on both HTML pages and PDF downloads.

## 21.3 CSRF Details

* Token stored in the session, rendered into every form as
  `<input type="hidden" name="csrf_token">`.
* `X-CSRFToken` header accepted for JSON/XHR calls (admin retrain, status
  changes via fetch).
* Verification failure ⇒ 400 with a clear message (JSON error body for
  `application/json` requests).

## 21.4 Audit Trail

`audit_logs(actor_type, actor_id, actor_label, action, entity, entity_id,
detail, ip, created_at)` records at least: status transitions (with old/new
status and remark), admin PDF/CSV exports, logins/logouts, admin user
create/activate/deactivate/password-change, clustering re-runs. The admin
console renders the log filterably (`/admin/audit`); tests assert that a
status change produces an audit row.

## 21.5 Secret Handling

`SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `REPORT_NOTIFY_EMAIL` and
SMTP credentials live only in `.env` (git-ignored). CI generates its own
throw-away `.env`. No secret is committed, and the admin password is never
logged or echoed in templates.

## 21.6 Verification

All of the above is enforced by `tests/test_security.py` (10 tests) inside
the 73-test suite that runs on every push.
