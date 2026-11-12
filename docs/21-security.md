# 21 · Security

## 21.1 Threat Model (summary)

| Threat | Mitigation |
|---|---|
| Cross-site request forgery | CSRF token on every state-changing form **and** JSON endpoint (`security._verify_csrf`; browser failures flash a message and redirect 302 so it is actually seen, JSON requests get a 400) |
| Session hijacking | `HttpOnly`, `SameSite=Lax` session cookie; `Secure` when served over HTTPS |
| Credential stuffing | Per-username login throttling (in-memory window counter) + generic error messages |
| Admin credential leak | Constant-time comparison for the env-provided admin bootstrap; no default password in code |
| Privilege escalation | `@admin_required` / `@citizen_required` decorators on every admin route; role checks in the service layer |
| Status-lifecycle abuse | Transitions enforced server-side against `config.ALLOWED_TRANSITIONS` (`complaints/services.py::update_status`); the legacy `GET /update_status/<id>/<status>` renders a CSRF-protected confirmation page instead of acting |
| Clickjacking | `X-Frame-Options: SAMEORIGIN` on all responses |
| MIME sniffing | `X-Content-Type-Options: nosniff` |
| Referrer leakage | `Referrer-Policy: same-origin` |
| Stored XSS | Jinja auto-escaping everywhere; user HTML never rendered; e-mail bodies HTML-escaped before sending |
| Unrestricted upload | 5 MB limit, extension + content-type allowlist, randomised filenames outside the code tree (`uploads/`) |
| SQL injection | parameterised queries throughout (`?` placeholders) |
| Path traversal | upload/download paths resolved and checked against the configured upload root |
| Password storage | Werkzeug `generate_password_hash` (scrypt/PBKDF2 default) |
| Audit gaps | append-only `audit_logs` for status changes, AI corrections, duplicate links, exports, logins, user management, profile updates |

## 21.2 Security Headers (installed in `app.py`)

```
X-Content-Type-Options: nosniff
X-Frame-Options: SAMEORIGIN
Referrer-Policy: same-origin
Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline';
  style-src 'self' 'unsafe-inline'; img-src 'self' data: https://*.tile.openstreetmap.org;
  font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self';
  form-action 'self'; frame-ancestors 'self'
Permissions-Policy: geolocation=(self), camera=(), microphone=(), payment=()
Strict-Transport-Security: max-age=31536000; includeSubDomains   (production only)
```

`'unsafe-inline'` for scripts/styles is required by the heavily inline,
server-rendered templates; every external origin is otherwise pinned to
`'self'` (plus the OpenStreetMap tile CDN used by the map). HSTS is never
sent to plain-HTTP dev servers.

Verified by `tests/test_security.py` on both HTML pages and PDF downloads.

## 21.3 CSRF Details

* Token stored in the session, rendered into every form as
  `<input type="hidden" name="csrf_token">`.
* `X-CSRFToken` header accepted for JSON/XHR calls (admin retrain, status
  changes via fetch, duplicate auto-check).
* Verification failure ⇒ 400 with a clear message for JSON requests; for
  ordinary browser form posts the failure is flashed and the browser is
  redirected (302) so the message is actually seen.
* Admin status changes on GET-era URLs are downgraded to a confirmation page
  that POSTs the real endpoint with a token.

## 21.4 Audit Trail

`audit_logs(actor_type, actor_id, actor_label, action, entity, entity_id,
detail, ip, created_at)` records at least: status transitions (with old/new
status and remark), AI corrections (admin verify/override with note),
duplicate link/unlink, admin PDF/CSV exports, logins/logouts, admin user
create/activate/deactivate/password-change, citizen profile updates,
clustering re-runs. The admin console renders the log filterably and
server-side paginated (`/admin/audit`, action filter scopes the reported
total); tests assert that a status change produces an audit row.

## 21.5 Secret Handling

`SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `REPORT_NOTIFY_EMAIL` and
SMTP credentials live only in `.env` (git-ignored). CI generates its own
throw-away `.env`. No secret is committed, and the admin password is never
logged or echoed in templates.

## 21.6 Verification

All of the above is enforced by `tests/test_security.py` (15 tests) plus the
lifecycle, profile and performance test files, inside the 115-test suite that
runs on every push (`.github/workflows/ci.yml`, Python 3.12 and 3.14).
