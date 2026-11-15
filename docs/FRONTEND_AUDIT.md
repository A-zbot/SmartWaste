# SmartWaste — Frontend Audit (Phase 1 of redesign)

Read-only audit of the complete frontend before any redesign work.
Method: every template, `static/style.css`, `static/app.js`, both layout
shells, Flask route↔template map, and the test suite that pins markup.

## 1. Architecture

| Layer | Reality |
|---|---|
| Framework | **None** — server-rendered Jinja2 + vanilla JS (explicit "no frameworks, progressive enhancement" in `app.js:1`) |
| Shells | `templates/base.html` (public/citizen, blocks `title/head/content/scripts`), `templates/admin_base.html` (admin, blocks `title/head/crumb/heading/content/scripts`) |
| Styles | single `static/style.css` (35.5 KB, one `:root` token block, ~28 sections, 566 lines) |
| Behaviour | single `static/app.js` (22.9 KB, ~530 lines): nav toggles, geolocation, image preview, duplicate-check AJAX, table filtering, Chart.js rendering (dashboard/forecast), Leaflet map init, flash auto-dismiss |
| Libraries | **Self-hosted only**: `static/vendor/chart.umd.min.js` (Chart.js UMD), `static/vendor/leaflet.js` + css + marker images. No CDN, no build step, no npm |
| Fonts | none loaded — `--font: "Inter","Segoe UI",system-ui…` only renders as Inter if installed locally |
| Data hooks | JSON injected via `<script type="application/json" id="dashboardData">` / `#forecastData`; `window.MAP_DATA`/`window.SW_ACTUALS` built inline in forecast/map templates |
| Pages | 28 templates (17 public/citizen incl. 2 partials, 11 admin) |

**Route ↔ template map:** public blueprint → `index, about, team, founder?, contact`;
auth → `login, signup, profile`; complaints → `report, success, track,
my_reports, complaint_detail, notifications`; admin → `dashboard, complaints,
complaint_detail, forecast, map, models, users, audit, messages,
confirm_status`. Every route renders a template (no SPA); the only JSON
endpoints are `/admin/api/overview` (dashboard AJAX filters) and
`/report/duplicate-check`.

## 2. What works (keep)

- Tokenised palette already forest/emerald based (`:root` vars) — a good seed
  for the new identity.
- Progressive enhancement: every flow (submit, track, status change, feedback,
  filters) works **without JS**; JS only enriches (AJAX filters fall back to a
  normal GET).
- Vendored Chart.js/Leaflet → offline-safe, CSP-safe (`font-src 'self'`,
  `connect-src 'self'`).
- Reusable partials: `_report_card.html` (macros `status_badge`,
  `priority_badge`, `report_card`, `timeline`), `_pagination.html`
  (`paginate()`), shared flash block in both shells.
- Accessibility floor already present and **pinned by tests**: skip link,
  `#main`, `role="status"` flash live region, `prefers-reduced-motion`,
  `:focus-visible`, `alt` on all images, no `href="#"`.

## 3. Findings

### 3.1 Visual / design-system gaps
1. **One look everywhere**: landing, citizen pages and admin console share the
   same card/section language — no distinct visual purpose per area (the
   prompt's key requirement).
2. Typography is flat: no display scale, no editorial headings, no numeric
   hierarchy for KPIs (`.kpi-value` overridden inline on 3 admin pages).
3. Palette lacks the requested **warm ivory / muted sage / fresh lime** roles
   and has **no dark mode** at all.
4. Landing is a template-looking 3-column hero: same `♻` icon for all 8
   category cards, duplicated caption text (`index.html:60-64`), dead class
   `.hero-copy` (no CSS rule), hard-coded "SW-00001 format" row.
5. ~**100 inline `style=` attributes** across templates (≈45 across the two
   complaint-detail pages) — duplicated theme colours (`rgba` warn/ok tones
   that exist as `.mini-note` classes), ad-hoc `max-width`, `padding-top`.
6. Charts/tables/KPIs are functional but visually generic; canvases have no
   loading/empty/aria states; chart palette hard-codes 5 colours in `app.js:176`.

### 3.2 Defects (real bugs)
| Severity | Defect | Location |
|---|---|---|
| High | `confirm('…{{ u.name }}…')` — user name interpolated into single-quoted JS string → handler breaks/injection | `admin/users.html:53` |
| High | Invalid HTML: `<div class="kv">` wrapping `<dt>/<dd>` ×8 (success:18, profile:85, complaint_detail:259, admin detail:287+307, dashboard:117+156+215) | several |
| Med | `<form>` nested inside `<span>` (phrasing-content violation) | `notifications.html:29-38` |
| Med | `.notif` rows missing icon child → 3-column grid misaligns (content lands in the 34px icon column) | `profile.html:26-33` |
| Med | Unguarded Jinja `explanation.model.*` / `hours_since` → potential 500 when model absent | `complaint_detail.html:160,200`; `admin/complaint_detail.html:298` |
| Med | Client-side table filter fights server pagination — searching hides rows of *current page only*; "All" tab sets `statusFilter.value="all"` which matches no `<option>` | `admin/complaints.html:11,59-61` |
| Med | Tab count badges use `<small>` but CSS styles `.tab b` → counts unstyled | `admin/complaints.html` vs `style.css` |
| Low | Success page duplicate timestamps missing `\|dt`; `#reportForm` dead hook; macro param `show_ai` unused | success:56, report:18, `_report_card:22` |
| Low | Map page: 5 KPI cards in a 4-column grid (orphan); legend colours hard-coded inline (won't theme) | `admin/map.html` |
| Low | Admin credential hint rendered to every visitor on login | `login.html:22-25` |

### 3.3 Structure / UX gaps
- **No breadcrumbs/search/date filters/profile menu/theme control** in the
  admin topbar; top actions are 4 buttons + no notification area.
- Landing lacks the required sections: impact stats, AI showcase, hotspot
  showcase, workflows, CTA, premium footer (footer exists but plain).
- Citizen dashboard (`my_reports`) is a bare list: **no search/filter, no
  status tabs, KPIs shown even when empty**.
- Complaint form is single-page with all 4 concerns at once (no steps, no
  progress, no review step, GPS buttons wrongly inside `<label>`).
- **No toast system** (only fixed flash banners), no modal, no tooltip, no
  loading skeleton, no empty-state component class (each page improvises).
- Empty states missing on: citizen/admin complaint history, profile
  notifications (bare `<p>`), dashboard charts.
- No `<caption>`/`scope="col"` on **any** table; no `role="img"`/`aria-label`
  on any canvas or the map (a11y gap for an exam).
- Track results + user list unpaginated; pagination is prev/next only.

### 3.4 Responsive problems
- `table.data{min-width:940px}` relies on invisible horizontal scroll.
- `.notif` row grid has no mobile rule; chart boxes fixed 270/340px; map
  5-KPI orphan; detail grids collapse only at 760px (tablet gap at ~900px).
- Hero/section paddings in `%` produce inconsistent gutters on ultrawide.

### 3.5 Test constraints the redesign MUST keep (regression fence)
From `tests/test_frontend.py`, `test_regressions.py`, `test_lifecycle.py`,
`test_feedback_flow.py`, `test_duplicate_link.py`, `test_ai_review.py`,
`test_smoke.py`, `test_ml_units.py`:
1. `url_for` endpoints all valid; `<img>` all have `alt`; **no `href="#"`**.
2. Both shells keep `lang`, viewport, `<title>`, `.skip-link href="#main"`,
   `id="main"`, flash `role="status" aria-live="polite"`.
3. CSS keeps `prefers-reduced-motion`, `a:focus-visible`,
   `.table-scroll{overflow:auto}`, `@media(max-width:1100px|900px|760px)`.
4. `admin_base.html` loads `vendor/chart.umd.min.js` **before** `app.js`.
5. Report card renders **exactly one** `class="badge status-*"` span.
6. Admin queue keeps `<label for="…">Search</label>` + matching input id.
7. Homepage keeps "Awaiting manual AI review" (and never "under AI analysis").
8. Admin detail keeps `<select name="status" required>` with options in exact
   legal order; queue keeps literal `<span class="badge badge-warn">duplicate</span>`
   (or the test updated only if presentation genuinely changes — prefer keep).
9. Strings pinned: "Confirm classification", "Verified category", "Verified by
   admin", "Remove duplicate link", "linked this complaint to the earlier
   report", "Only the citizen who submitted this complaint can rate it.",
   "You rated this complaint", "Verification for anonymous reports",
   "id=\"kpiPending\"", "Forecast (next", "Duplicate complaints",
   "Administrator feedback", "Reviews recorded", "Page X of Y",
   "could not be found" (404), "incorrect" (login), JS
   `escapeHtml(m.tracking_id|category|status|location|created_at)` etc.
10. `app.js` must keep `function chartsAvailable()` and the duplicate-panel
    escaping (source-level tests in `test_ml_units.py`).

## 4. Verdict / plan

The backend contract and progressive-enhancement base are solid — **the work
is a full presentation-layer replacement**: design tokens + typography + four
distinct page identities (landing / citizen / workflow / admin console),
component library (cards, KPI, chart shell, table, timeline, badges, buttons,
forms, toast, modal, empty/skeleton states), dark mode, animation layer —
while preserving every pinned string, id, hook and endpoint above.

Phases: 2 design system + shells → 3 landing → 4 citizen dashboard & report
flow → 5 admin dashboard → 6 detail/analytics pages → 7 interactions/theme/
animation → 8 responsive → 9 full test pass.
