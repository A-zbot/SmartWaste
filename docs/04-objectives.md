# 04 · Objectives

## 4.1 Primary Objectives

1. **Design and implement a web-based complaint lifecycle system** that lets
   citizens submit, track and receive status updates on waste complaints, and
   lets administrators triage, assign and resolve them with a full audit
   trail.
2. **Integrate supervised machine learning into the submission pipeline** so
   that every complaint receives an AI-predicted category, urgency level,
   confidence score and human-readable explanation at the moment of intake.
3. **Build a duplicate-detection module** that fuses lexical (TF-IDF cosine)
   and geospatial (haversine) signals to flag possible duplicates without
   auto-rejecting any report.
4. **Implement geospatial hotspot detection** using DBSCAN over geocoded
   complaints, with persisted cluster snapshots and a silhouette-based quality
   measure.
5. **Implement demand forecasting** with seasonal, moving-average and
   machine-learning baselines evaluated on a chronological hold-out window.
6. **Provide decision-support recommendations** (backlog age, rising areas,
   urgent work) on the administrator console.
7. **Guarantee evaluability**: every model and rule ships with a labelled
   evaluation set, a reproducible evaluation script and machine-readable
   reports — and states honestly when data is insufficient.

## 4.2 Supporting Objectives

8. Deliver CSV and server-side PDF exports of complaint records.
9. Deliver best-effort e-mail notifications for new reports and citizen
   status changes (never blocking the transaction).
10. Harden the application: CSRF protection, session-cookie flags, login
   throttling, security headers, constant-time admin credential checks.
11. Achieve high automated-test coverage of the critical paths (73 tests)
    and run them continuously through GitHub Actions.
12. Document the system to MCA major-project standard: architecture, DFDs,
   ER model, algorithms, testing, results, deployment and future scope.

## 4.3 Success Criteria

| Criterion | Target | Status |
|---|---|---|
| Complaint submission + tracking end-to-end | working | achieved |
| Category model CV F1-macro | ≥ 0.90 | 0.9486 (RF) |
| Urgency model CV F1-macro | ≥ 0.90 | 0.9556 (LR) |
| Duplicate rule measured on labelled pairs | F1 ≥ 0.90 | 0.9648 (combined) |
| Cluster quality measurable | silhouette reported when computable | implemented |
| Forecast honest split | chronological, baselines included | implemented |
| Automated tests | ≥ 60 passing | 73 passing |
| CI on every push | GitHub Actions | implemented |
