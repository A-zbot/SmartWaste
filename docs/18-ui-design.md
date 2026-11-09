# 18 · UI Design

## 18.1 Information Architecture

```
Public site
├── /                      landing: hero, features, stats, how-it-works, contact
├── /report                complaint form (category, priority, text, photo, geolocation)
├── /track                 track by tracking ID / report ID / mobile
├── /complaint/<id>        citizen detail: timeline, AI explanation, feedback
├── /complaint/<id>/pdf    citizen PDF
├── /about /contact /privacy
└── /login /signup

Admin console (admin_base.html)
├── /admin                 dashboard: KPIs, charts, recommendations, alerts
├── /admin/complaints      filterable queue → detail (/admin/complaint/<id>)
├── /admin/map             DBSCAN hotspot map (Leaflet)
├── /admin/forecast        volume forecast with baselines
├── /admin/models          evaluation reports, confusion matrices, retrain
├── /admin/users           user management
├── /admin/audit           audit log
├── /admin/messages        contact messages
└── CSV / PDF exports from queue and detail views
```

## 18.2 Screen Highlights

* **Complaint form** — grouped fieldsets, live duplicate hint area, optional
  "use my location" (navigator.geolocation), client-side required-field
  hints mirrored by server validation.
* **Success page** — large tracking ID (copyable), AI badge
  (`Category · Urgency · confidence`), manual-review notice when applicable,
  possible-duplicate list with evidence.
* **Admin dashboard** — KPI cards (total, open, resolved, without
  coordinates), status/category charts (Chart.js, guarded), recommendation
  list with evidence, overdue alerts.
* **Hotspot map** — cluster circles sized by complaint count, legend,
  explicit note when data is insufficient to cluster.
* **Forecast page** — line chart with the uncertainty band, baseline
  comparison table, and an honest banner when history is too short.

## 18.3 Visual & Accessibility Standards

| Aspect | Implementation |
|---|---|
| Colour | neutral base + status badges; contrast checked against WCAG AA for body text |
| Typography | system font stack; readable line length |
| Layout | mobile-first CSS grid/flex; breakpoints at 640/960/1200 |
| Keyboard | visible `:focus-visible` rings everywhere; skip-link as first focusable element on both bases |
| Landmarks | `role="banner"`, `<main id="main">`, `role="contentinfo"` |
| Live regions | flash messages use `role="status" aria-live="polite"` |
| Forms | every input has a `<label for>`; errors rendered next to fields with `aria-invalid` |
| Images | all `<img>` carry descriptive `alt` (enforced by `tests/test_frontend.py`) |
| Motion | `@media (prefers-reduced-motion: reduce)` disables transitions |
| Icons | decorative icons `aria-hidden="true"` |

## 18.4 State Design

Every list and dashboard defines four states explicitly: **loading**,
**populated**, **empty-with-guidance** ("no complaints match these filters")
and **error**. Intelligence surfaces add a fifth: **insufficient data**
(DBSCAN without coordinates, forecast without history) — rendered as plain
text explanations rather than blank charts, so the administrator is never
shown a misleading picture.
