"""Role-scoped data builders for SmartWaste AI.

These are the ONLY functions that read complaint data for the assistant.
They run in Flask before any model call, so the model never chooses what it
may see: citizens get only their own complaints, administrators get
aggregates from the live database. Nothing here fabricates a number - every
value is a real query result (or an explicit "unavailable" marker).
"""

import json

from db import get_connection, query, query_one

OPEN_STATUSES = ("Submitted", "Under Review", "Assigned", "In Progress", "Pending")


# ---------------------------------------------------------------------------
# Shared formatting
# ---------------------------------------------------------------------------
def _dumps(payload):
    return json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Citizen scope
# ---------------------------------------------------------------------------
def citizen_profile(user_id):
    row = query_one(
        "SELECT id, name, email, role FROM users WHERE id=?", (user_id,)
    )
    if row is None:
        return None
    return dict(row)


def citizen_complaints(user_id, limit=10):
    """The signed-in citizen's own complaints - never anyone else's."""
    rows = query(
        "SELECT id, tracking_id, status, waste_type, priority, ai_urgency, "
        "       area, location, created_at, resolved_at "
        "FROM reports WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, int(limit)),
    )
    items = [dict(row) for row in rows]
    counts = query(
        "SELECT status, COUNT(*) AS n FROM reports WHERE user_id=? GROUP BY status",
        (user_id,),
    )
    return {
        "total": len(items),
        "status_counts": {row["status"]: row["n"] for row in counts},
        "items": items,
    }


def citizen_complaint(user_id, reference):
    """Resolve a tracking id / numeric id against the citizen's OWN reports."""
    rows = query(
        "SELECT r.id, r.tracking_id, r.status, r.waste_type, r.priority, "
        "       r.ai_urgency, r.area, r.location, r.description, "
        "       r.created_at, r.updated_at, r.resolved_at, r.admin_remarks "
        "FROM reports r WHERE r.user_id=? AND (r.id=? OR r.tracking_id=?) "
        "ORDER BY r.id DESC LIMIT 1",
        (user_id, int(reference), f"SW-{int(reference):05d}"),
    )
    if not rows:
        return None
    report = dict(rows[0])
    history = query(
        "SELECT new_status, remark, created_at FROM complaint_history "
        "WHERE report_id=? ORDER BY id",
        (report["id"],),
    )
    report["history"] = [dict(row) for row in history]
    return report


def citizen_summary_payload(user_id):
    profile = citizen_profile(user_id)
    complaints = citizen_complaints(user_id, limit=10)
    return {
        "citizen": {"name": profile["name"] if profile else None},
        "complaints": complaints,
    }


# ---------------------------------------------------------------------------
# Administrator scope (aggregates only - same sources as the dashboard)
# ---------------------------------------------------------------------------
def _kpis():
    from modules.admin.services import kpis
    try:
        return kpis({})
    except Exception:
        return None


def _chart_series():
    from modules.admin.services import chart_series
    try:
        return chart_series({}, history_days=90)
    except Exception:
        return None


def admin_overview():
    kpis_data = _kpis()
    if kpis_data is None:
        return {"available": False, "reason": "query_failed"}
    return {
        "available": True,
        "total_complaints": kpis_data["total"],
        "open": kpis_data["open"],
        "pending_submitted": kpis_data["pending"],
        "resolved": kpis_data["resolved"],
        "rejected": kpis_data["rejected"],
        "urgent_open": kpis_data["urgent_open"],
        "needs_ai_review": kpis_data["needs_review"],
        "resolution_pct": kpis_data["resolution_pct"],
        "avg_resolution_hours": kpis_data["avg_resolution_hours"],
        "resolved_with_timestamp": kpis_data["resolved_with_timestamp"],
        "missing_coordinates": kpis_data["missing_geo"],
    }


def admin_breakdowns():
    series = _chart_series()
    if series is None:
        return {"available": False, "reason": "query_failed"}
    return {
        "available": True,
        "by_status": series["status"],
        "by_category": series["category"],
        "by_area": series["area"],
        "by_urgency": series["urgency"],
        "last_30_days_total": sum(
            v for label, v in zip(series["daily"]["labels"], series["daily"]["values"])
            if label >= _days_ago(30)
        ),
        "recent_8": [
            {k: row[k] for k in ("tracking_id", "status", "waste_type",
                                 "area", "created_at")}
            for row in series["recent"]
        ],
    }


def _days_ago(n):
    from datetime import date, timedelta
    return (date.today() - timedelta(days=n)).isoformat()


def admin_pending(limit=10):
    rows = query(
        "SELECT tracking_id, status, waste_type, priority, ai_urgency, area, "
        "       location, created_at "
        "FROM reports WHERE status IN ({}) "
        "ORDER BY created_at ASC LIMIT ?".format(
            ",".join("?" for _ in OPEN_STATUSES)
        ),
        (*OPEN_STATUSES, int(limit)),
    )
    return {"available": True, "items": [dict(row) for row in rows]}


def admin_high_priority(limit=10):
    rows = query(
        "SELECT tracking_id, status, waste_type, priority, ai_urgency, area, "
        "       location, created_at "
        "FROM reports "
        "WHERE status IN ({statuses}) "
        "  AND (priority IN ('High','Emergency') OR ai_urgency IN ('High','Emergency')) "
        "ORDER BY CASE COALESCE(ai_urgency, priority) "
        "           WHEN 'Emergency' THEN 0 WHEN 'High' THEN 1 ELSE 2 END, "
        "         created_at ASC LIMIT ?".format(
            statuses=",".join("?" for _ in OPEN_STATUSES)
        ),
        (*OPEN_STATUSES, int(limit)),
    )
    return {"available": True, "items": [dict(row) for row in rows]}


def admin_hotspots():
    payload = {"available": True}
    try:
        from intelligence.hotspot_detection import hotspot_stats, load_clusters
        stats = hotspot_stats()
        payload["stats"] = {
            "clusters": stats["clusters"],
            "complaints_in_clusters": stats["complaints_in_clusters"],
            "unresolved_in_clusters": stats["unresolved_in_clusters"],
            "recurring_hotspots": stats["recurring"],
            "parameters": stats["parameters"],
        }
        payload["clusters"] = [
            {
                "label": c["label"],
                "complaint_count": c["complaint_count"],
                "unresolved_count": c["unresolved_count"],
                "top_category": c["top_category"],
                "centroid_lat": c["centroid_lat"],
                "centroid_lng": c["centroid_lng"],
            }
            for c in load_clusters()[:8]
        ]
    except Exception:
        payload["available"] = False
        payload["reason"] = "clustering_unavailable"
    series = _chart_series()
    if series:
        payload["top_areas"] = series["area"][:8]
    return payload


def admin_common_category():
    series = _chart_series()
    if not series:
        return {"available": False, "reason": "query_failed"}
    return {"available": True, "by_category": series["category"],
            "by_area": series["area"]}


def admin_recommendations():
    try:
        from intelligence.recommender import build_recommendations
        payload = build_recommendations()
    except Exception:
        return {"available": False, "reason": "unavailable"}
    return {
        "available": True,
        "total_reports": payload.get("total_reports"),
        "items": [
            {
                "severity": item["severity"],
                "title": item["title"],
                "detail": item["detail"],
                "action": item["action"],
                "count": item.get("count"),
            }
            for item in payload.get("items", [])
        ],
        "message": payload.get("message"),
    }


def admin_forecast():
    try:
        from modules.analytics.services import forecast_summary
        block = forecast_summary(horizon=7)
    except Exception:
        return {"available": False, "reason": "forecast_unavailable"}
    if not block.get("available"):
        return {
            "available": False,
            "reason": block.get("status") or "insufficient_data",
            "message": block.get("message"),
        }
    return {
        "available": True,
        "horizon_days": 7,
        "total_forecast": block.get("total"),
        "trend": block.get("trend"),
        "peak_date": block.get("peak_date"),
        "peak_value": block.get("peak_value"),
        "data_note": block.get("data_note"),
        "metrics": block.get("metrics"),
    }


def admin_needs_review(limit=10):
    rows = query(
        "SELECT tracking_id, status, waste_type, ai_category, ai_urgency, "
        "       ai_confidence, area, created_at "
        "FROM reports WHERE ai_needs_review=1 ORDER BY created_at DESC LIMIT ?",
        (int(limit),),
    )
    return {"available": True, "items": [dict(row) for row in rows]}


# ---------------------------------------------------------------------------
# Intent -> data mapping (admin assistant)
# ---------------------------------------------------------------------------
_ADMIN_INTENT_DATA = {
    "admin_stats": lambda: {
        "overview": admin_overview(),
        "breakdowns": admin_breakdowns(),
        "common_category": admin_common_category(),
    },
    "admin_pending": admin_pending,
    "admin_high_priority": admin_high_priority,
    "admin_hotspots": admin_hotspots,
    "admin_recommendations": admin_recommendations,
    "admin_forecast": admin_forecast,
}


def data_for_admin_intent(intent):
    builder = _ADMIN_INTENT_DATA.get(intent)
    if builder is None:
        return {"available": False, "reason": "no_data_source"}
    try:
        return builder()
    except Exception:
        return {"available": False, "reason": "query_failed"}


def data_as_json(payload):
    return _dumps(payload)
