"""Decision-support recommendations (Module G).

Every recommendation is produced by querying the live database - titles,
counts and evidence come from actual complaint records, cluster statistics and
model flags. There are no hardcoded sample recommendations.

Each item carries:
    code, severity, title, detail, count, evidence, action, link
"""

from datetime import datetime, timezone

from config import (
    BACKLOG_AGE_DAYS,
    OVERDUE_AGE_DAYS,
    RECOMMENDATION_LIMIT,
    RISING_MIN_INCREASE,
    RISING_WINDOW_DAYS,
)
from db import get_connection
from intelligence.hotspot_detection import (
    HOTSPOT_MIN_COMPLAINTS,
    load_clusters,
    stored_run_params,
)

OPEN_STATUSES = ("Submitted", "Under Review", "Assigned", "In Progress", "Pending")
_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "info": 3}


def _count(con, sql, params=()):
    return int(con.execute(sql, params).fetchone()[0])


def _top_areas(con, window_days, limit=5):
    rows = con.execute(
        "SELECT area, COUNT(*) AS n FROM reports "
        "WHERE area IS NOT NULL AND area != '' "
        "  AND created_at >= datetime('now', ?) "
        "GROUP BY area ORDER BY n DESC LIMIT ?",
        (f"-{int(window_days)} days", int(limit)),
    ).fetchall()
    return [{"area": row["area"], "count": row["n"]} for row in rows]


def build_recommendations(con=None):
    own = con is None
    if own:
        con = get_connection()
    try:
        total = _count(con, "SELECT COUNT(*) FROM reports")
        generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if total == 0:
            return {
                "items": [],
                "generated_at": generated_at,
                "total_reports": 0,
                "message": "No complaints recorded yet - recommendations appear "
                           "once real reports come in.",
            }

        placeholders = ",".join("?" for _ in OPEN_STATUSES)
        items = []

        # 1. Aging unresolved complaints -----------------------------------
        overdue = _count(
            con,
            f"SELECT COUNT(*) FROM reports WHERE status IN ({placeholders}) "
            "AND created_at < datetime('now', ?)",
            (*OPEN_STATUSES, f"-{int(OVERDUE_AGE_DAYS)} days"),
        )
        if overdue:
            oldest = con.execute(
                f"SELECT id, tracking_id, location, created_at, priority, "
                f"       ai_urgency, status "
                f"FROM reports WHERE status IN ({placeholders}) "
                "AND created_at < datetime('now', ?) "
                "ORDER BY created_at ASC LIMIT 1",
                (*OPEN_STATUSES, f"-{int(OVERDUE_AGE_DAYS)} days"),
            ).fetchone()
            age_days = con.execute(
                f"SELECT CAST(julianday('now') - julianday(created_at) AS INTEGER) AS age "
                f"FROM reports WHERE status IN ({placeholders}) "
                "AND created_at < datetime('now', ?) "
                "ORDER BY created_at ASC LIMIT 1",
                (*OPEN_STATUSES, f"-{int(OVERDUE_AGE_DAYS)} days"),
            ).fetchone()[0]
            items.append({
                "code": "overdue_unresolved",
                "severity": "high",
                "title": f"{overdue} unresolved complaint(s) past the {OVERDUE_AGE_DAYS}-day SLA",
                "detail": (
                    f"Oldest is {oldest['tracking_id']} in '{oldest['location']}', "
                    f"open for {age_days} days (status: {oldest['status']})."
                ),
                "count": overdue,
                "evidence": {
                    "oldest_tracking_id": oldest["tracking_id"],
                    "oldest_age_days": age_days,
                    "threshold_days": OVERDUE_AGE_DAYS,
                },
                "action": "Escalate overdue complaints to the area officer today.",
                "link": "admin.complaints",
            })

        # 2. High-urgency backlog ------------------------------------------
        urgent = _count(
            con,
            f"SELECT COUNT(*) FROM reports WHERE status IN ({placeholders}) "
            "AND (priority IN ('High','Emergency') OR ai_urgency IN ('High','Emergency'))",
            OPEN_STATUSES,
        )
        if urgent:
            items.append({
                "code": "high_urgency_backlog",
                "severity": "high",
                "title": f"Prioritize {urgent} unresolved high-urgency complaint(s)",
                "detail": (
                    "Combines citizen-declared priority with the urgency model's "
                    "prediction; all are still open."
                ),
                "count": urgent,
                "evidence": {"unresolved_high_or_emergency": urgent},
                "action": "Dispatch inspection/cleanup for these reports first.",
                "link": "admin.complaints",
            })

        # 3. AI predictions below the confidence threshold ------------------
        review = _count(
            con,
            f"SELECT COUNT(*) FROM reports WHERE status IN ({placeholders}) "
            "AND ai_needs_review = 1",
            OPEN_STATUSES,
        )
        if review:
            items.append({
                "code": "low_confidence_review",
                "severity": "medium",
                "title": f"{review} AI prediction(s) need manual review",
                "detail": "Model confidence fell below the configured threshold; "
                          "an administrator should confirm or correct the category "
                          "and urgency.",
                "count": review,
                "evidence": {"pending_ai_review": review},
                "action": "Open the AI review queue and confirm classifications.",
                "link": "admin.complaints",
            })

        # 4. Administrative backlog in a status -----------------------------
        stale_status, stale_count = None, 0
        for status in ("Submitted", "Under Review", "Assigned"):
            n = _count(
                con,
                f"SELECT COUNT(*) FROM reports WHERE status = ? "
                "AND created_at < datetime('now', ?)",
                (status, f"-{int(BACKLOG_AGE_DAYS)} days"),
            )
            if n > stale_count:
                stale_status, stale_count = status, n
        if stale_count:
            items.append({
                "code": "status_backlog",
                "severity": "medium",
                "title": f"Administrative backlog: {stale_count} complaint(s) stuck in '{stale_status}'",
                "detail": f"Older than {BACKLOG_AGE_DAYS} days without moving to the "
                          "next workflow state.",
                "count": stale_count,
                "evidence": {"status": stale_status, "age_days": BACKLOG_AGE_DAYS},
                "action": "Review the queue and advance or reassign these reports.",
                "link": "admin.complaints",
            })

        # 5. Recurring hotspots ---------------------------------------------
        clusters = load_clusters()
        hotspot_clusters = [c for c in clusters if c["unresolved_count"] > 0]
        if hotspot_clusters:
            top = hotspot_clusters[0]
            items.append({
                "code": "recurring_hotspots",
                "severity": "high" if top["complaint_count"] >= HOTSPOT_MIN_COMPLAINTS * 2 else "medium",
                "title": f"Investigate {len(hotspot_clusters)} hotspot(s) with open complaints",
                "detail": (
                    f"Largest: {top['label']} with {top['complaint_count']} complaints "
                    f"({top['unresolved_count']} unresolved), dominated by "
                    f"{top['top_category']}."
                ),
                "count": len(hotspot_clusters),
                "evidence": {
                    "clusters": len(clusters),
                    "clusters_with_open_complaints": len(hotspot_clusters),
                    "largest_cluster": top["label"],
                    "largest_cluster_size": top["complaint_count"],
                },
                "action": "Schedule a field inspection of the densest clusters.",
                "link": "admin.map",
            })
        elif stored_run_params() is None:
            items.append({
                "code": "hotspots_not_computed",
                "severity": "info",
                "title": "Hotspot detection has not been run yet",
                "detail": "Run DBSCAN clustering from the map page to enable "
                          "geographic recommendations.",
                "count": 0,
                "evidence": {},
                "action": "Open the hotspot map and run detection.",
                "link": "admin.map",
            })

        # 6. Areas with rising complaint frequency ---------------------------
        recent_rows = con.execute(
            "SELECT area, COUNT(*) AS n FROM reports "
            "WHERE area IS NOT NULL AND area != '' "
            "  AND created_at >= datetime('now', ?) GROUP BY area",
            (f"-{RISING_WINDOW_DAYS} days",),
        ).fetchall()
        previous_rows = con.execute(
            "SELECT area, COUNT(*) AS n FROM reports "
            "WHERE area IS NOT NULL AND area != '' "
            "  AND created_at >= datetime('now', ?) "
            "  AND created_at < datetime('now', ?) GROUP BY area",
            (f"-{RISING_WINDOW_DAYS * 2} days", f"-{RISING_WINDOW_DAYS} days"),
        ).fetchall()
        previous = {row["area"]: row["n"] for row in previous_rows}
        rising = []
        for row in recent_rows:
            before = previous.get(row["area"], 0)
            if row["n"] - before >= RISING_MIN_INCREASE and row["n"] > before:
                rising.append({
                    "area": row["area"],
                    "recent": row["n"],
                    "previous": before,
                    "increase": row["n"] - before,
                })
        rising.sort(key=lambda r: -r["increase"])
        if rising:
            top_rise = rising[0]
            items.append({
                "code": "rising_areas",
                "severity": "medium",
                "title": f"{len(rising)} area(s) show rising complaint frequency",
                "detail": (
                    f"{top_rise['area']}: {top_rise['previous']} → "
                    f"{top_rise['recent']} complaints in the last "
                    f"{RISING_WINDOW_DAYS} days vs the previous "
                    f"{RISING_WINDOW_DAYS} days."
                ),
                "count": len(rising),
                "evidence": {"areas": rising[:5],
                             "window_days": RISING_WINDOW_DAYS},
                "action": "Review waste collection schedules for these areas.",
                "link": "admin.dashboard",
            })

        # 7. Resolution performance ------------------------------------------
        perf = con.execute(
            "SELECT COUNT(*) AS n, "
            "AVG((julianday(resolved_at) - julianday(created_at)) * 24) AS avg_hours "
            "FROM reports WHERE status = 'Resolved' AND resolved_at IS NOT NULL"
        ).fetchone()
        if perf["n"]:
            avg_hours = float(perf["avg_hours"] or 0)
            severity = "medium" if avg_hours > 72 else "low"
            items.append({
                "code": "resolution_time",
                "severity": severity,
                "title": f"Average resolution time is {avg_hours:.1f} hours",
                "detail": f"Measured across {perf['n']} resolved complaint(s) with "
                          "recorded resolution timestamps.",
                "count": int(perf["n"]),
                "evidence": {"resolved_with_timestamp": int(perf["n"]),
                             "avg_hours": round(avg_hours, 1)},
                "action": ("Aim to reduce cycle time below 72 hours."
                           if avg_hours > 72 else "Maintain current response time."),
                "link": "admin.dashboard",
            })

        # 8. Geographic coverage note -----------------------------------------
        missing_geo = _count(
            con,
            "SELECT COUNT(*) FROM reports "
            "WHERE latitude IS NULL OR longitude IS NULL",
        )
        if missing_geo:
            items.append({
                "code": "missing_coordinates",
                "severity": "low",
                "title": f"{missing_geo} complaint(s) have no coordinates",
                "detail": "These reports are excluded from hotspot detection and "
                          "map views until coordinates are added.",
                "count": missing_geo,
                "evidence": {"missing_coordinates": missing_geo},
                "action": "Capture coordinates during field verification.",
                "link": "admin.map",
            })

        items.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 9), -i["count"]))
        return {
            "items": items[:RECOMMENDATION_LIMIT],
            "total_items": len(items),
            "generated_at": generated_at,
            "total_reports": total,
            "top_areas_7d": _top_areas(con, RISING_WINDOW_DAYS),
            "message": None,
        }
    finally:
        if own:
            con.close()
