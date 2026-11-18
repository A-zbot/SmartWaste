# Administrator Operations Guide

Reference for municipal administrators using the SmartWaste operations
console: queues, priorities, hotspots, forecasting and recommendations.

## Reading the dashboard

The admin dashboard shows total, open, pending, resolved and urgent-open
complaint counts, resolution percentage, average resolution time in hours,
needs-review count and duplicate links. Charts break complaints down by
day, category, status, area and urgency.

Filters (date range, category, status, area, urgency) apply to the KPIs and
charts together, so a question like "how many plastic complaints this
month" is answered by filtering, then reading the total.

Keywords: dashboard kaise padhe, admin KPI, total complaints, resolution
time, average resolution hours.

## Complaint queue and status transitions

The complaint queue is the working list. Legal transitions are enforced
server-side: Submitted -> Under Review -> Assigned -> In Progress ->
Resolved, with Rejected available from the review stages, Rejected ->
Under Review for appeals and Resolved -> In Progress for reopens.

Illegal jumps are rejected by the platform, so the assistant can never
force a status change either - actions happen in the console with a
confirmation step and an audit entry.

Keywords: status change rules, queue management, complaint assign kaise
kare, lifecycle.

## AI classification review

Each complaint carries an AI category and urgency with a confidence score
and a plain-language explanation. When the model flags a complaint for
review, the administrator confirms or corrects the category and priority.
The original prediction stays immutable and the correction is logged for
model monitoring.

Keywords: AI review, ai category correct kaise kare, model confidence,
needs review.

## Hotspot map and clustering

The hotspot map runs DBSCAN clustering over geocoded complaints. Clusters
show where complaints concentrate, how many are unresolved and the top
category in each cluster. Recurring complaints at one location usually
mean a missed collection route or a persistent dumping spot, not a one-off.

Recluster after a batch of new geocoded complaints to refresh the groups.

Keywords: hotspot map, cluster kya hai, DBSCAN, area wise complaints,
repeated complaints ek jagah.

## Demand forecasting

The forecast page projects complaint volume for the next 7 days by default
(up to 30). It uses a seasonal baseline, moving average and - where
history allows - a Random Forest model with measured error bands. When
there is too little history it reports insufficient data instead of
inventing numbers.

Keywords: forecast kya hai, complaint prediction, next week complaints,
demand forecast.

## Recommendations engine

The recommendation block lists data-driven suggestions: unresolved
high-urgency complaints to prioritise, areas with rising complaint
volumes, locations needing extra collection capacity and data-quality
gaps such as missing coordinates. Each recommendation cites the counts
behind it.

The chatbot assistant surfaces the same recommendations in conversation
but never applies them - closing, reassigning or deleting stays a
human action with explicit confirmation.

Keywords: admin recommendations, what should we do next, prioritise
unresolved, rising areas.

## Exports and audit

Complaints export as CSV with filters applied; each complaint has an
operational PDF. The audit trail records login, status changes, AI
reviews, duplicate links, exports and user management actions with actor,
timestamp and IP.

Keywords: CSV export, audit trail kya hai, report download, logs.
