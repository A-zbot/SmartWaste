# 03 · Problem Statement

## 3.1 Statement

Municipal corporations lack an integrated system that can **automatically
classify, deduplicate, localise and forecast** citizen waste complaints.
Complaints are handled as isolated tickets, so the same physical problem is
processed many times while recurring hotspots and future workload remain
invisible to planners.

## 3.2 Detailed Analysis

Given a stream of citizen complaints containing free text, an optional
location and an optional photograph, the system must:

1. **Classify** each complaint into one of the eight official waste
   categories (`Open Garbage`, `Plastic Waste`, `Food Waste`,
   `Construction Debris`, `E-Waste`, `Medical Waste`, `Drain & Sewer Waste`,
   `Street Sweeping`) and assign one of four urgency levels
   (`Low`, `Medium`, `High`, `Emergency`) — *before* the complaint is stored,
   so that downstream queues are correct from the first second.
2. **Detect possible duplicates** by comparing the incoming text with recent
   complaints using lexical similarity *and* geographic proximity, so that
   residents reporting the same incident are recognised without suppressing
   genuinely new reports.
3. **Identify hotspots** by grouping geocoded complaints spatially, robustly
   (noise points allowed) and with a measurable quality score, so that
   recurring problem localities can be prioritised.
4. **Forecast demand** for the coming days from historical complaint
   volumes, with honest baselines and a chronological evaluation that never
   leaks future data into training.
5. **Explain** model decisions to administrators (which words and context
   factors mattered) and **recommend** concrete actions for the backlog.
6. **Preserve accountability** — every status transition is audited, exports
   (CSV/PDF) are logged, and all security controls (CSRF, session hardening,
   throttling) remain intact.

## 3.3 Why Existing Approaches Fall Short

* **Manual triage** does not scale and is inconsistent between clerks.
* **Keyword-only systems** miss paraphrases ("bins overflowing" vs.
  "garbage not collected since two days") and cannot rank urgency.
* **Duplicate filters on text alone** reject legitimate reports from
  different streets, or accept near-duplicates from far away; only the
  combination of text, distance and category behaves correctly.
* **Reactive dashboards** show yesterday's counts but cannot answer
  "how many complaints next Monday?" or "which locality is deteriorating?".
* **Black-box AI** is unacceptable in municipal workflows; predictions must
  carry explanations and confidence, with a manual-review path below the
  confidence threshold.

## 3.4 Target Users

| User | Need |
|---|---|
| Citizen | Submit, track and receive status updates on waste complaints |
| Municipal administrator | Triage, assign, resolve; see hotspots, forecasts, recommendations |
| System / auditor | Reproducible metrics, audit trail, exportable records |
