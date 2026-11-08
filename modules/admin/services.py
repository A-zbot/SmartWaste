"""Administrative query/filter services (Module G backend).

All lists and aggregates are built from parameterised SQL over the live
database; nothing here fabricates numbers for the dashboard.
"""

import csv
import io
from datetime import datetime, timezone

from config import (
    CATEGORIES,
    COMPLAINT_STATUSES,
    PRIORITIES,
)
from db import get_connection

OPEN_STATUSES = ("Submitted", "Under Review", "Assigned", "In Progress", "Pending")
CLOSED_STATUSES = ("Resolved", "Rejected")


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------
def parse_filters(args):
    def clean(key, limit=60):
        value = (args.get(key) or "").strip()
        return value[:limit] if value else ""

    filters = {
        "start": clean("start"),
        "end": clean("end"),
        "category": clean("category") if clean("category") in CATEGORIES else "",
        "status": clean("status") if clean("status") in COMPLAINT_STATUSES + ["Pending"] else "",
        "area": clean("area", 80),
        "urgency": clean("urgency") if clean("urgency") in PRIORITIES else "",
        "q": clean("q", 120),
        "needs_review": args.get("needs_review") in ("1", "true", "yes"),
        "sort": clean("sort", 20) or "newest",
    }
    return filters


def _where(filters):
    clauses, params = [], []
    if filters.get("start"):
        clauses.append("date(created_at) >= date(?)")
        params.append(filters["start"])
    if filters.get("end"):
        clauses.append("date(created_at) <= date(?)")
        params.append(filters["end"])
    if filters.get("category"):
        clauses.append("waste_type = ?")
        params.append(filters["category"])
    if filters.get("status"):
        clauses.append("status = ?")
        params.append(filters["status"])
    if filters.get("area"):
        clauses.append("area LIKE ?")
        params.append(f"%{filters['area']}%")
    if filters.get("urgency"):
        clauses.append("(ai_urgency = ? OR (ai_urgency IS NULL AND priority = ?))")
        params.extend([filters["urgency"], filters["urgency"]])
    if filters.get("needs_review"):
        clauses.append("ai_needs_review = 1")
    if filters.get("q"):
        clauses.append("(description LIKE ? OR location LIKE ? OR name LIKE ? "
                       "OR mobile LIKE ? OR tracking_id LIKE ?)")
        like = f"%{filters['q']}%"
        params.extend([like] * 5)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def filtered_reports(filters, limit=None):
    where, params = _where(filters)
    order = {
        "oldest": "created_at ASC",
        "priority": "CASE ai_urgency WHEN 'Emergency' THEN 0 WHEN 'High' THEN 1 "
                    "WHEN 'Medium' THEN 2 ELSE 3 END, created_at DESC",
        "newest": "created_at DESC",
    }.get(filters.get("sort"), "created_at DESC")
    sql = f"SELECT * FROM reports {where} ORDER BY {order}"
    if limit:
        sql += " LIMIT ?"
        params = [*params, int(limit)]
    con = get_connection()
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def available_areas():
    rows = None
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT DISTINCT area FROM reports "
            "WHERE area IS NOT NULL AND area != '' ORDER BY area"
        ).fetchall()
    finally:
        con.close()
    return [row["area"] for row in rows]


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------
def kpis(filters=None):
    where, params = _where(filters or {})
    con = get_connection()
    try:
        base = con.execute(
            f"SELECT COUNT(*) AS total, "
            f"  SUM(CASE WHEN status IN ({','.join('?' for _ in OPEN_STATUSES)}) THEN 1 ELSE 0 END) AS open, "
            f"  SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) AS resolved, "
            f"  SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) AS rejected, "
            f"  SUM(CASE WHEN status IN ({','.join('?' for _ in OPEN_STATUSES)}) "
            f"            AND (priority IN ('High','Emergency') OR ai_urgency IN ('High','Emergency')) "
            f"            THEN 1 ELSE 0 END) AS urgent_open, "
            f"  SUM(CASE WHEN ai_needs_review = 1 THEN 1 ELSE 0 END) AS needs_review, "
            f"  SUM(CASE WHEN latitude IS NULL OR longitude IS NULL THEN 1 ELSE 0 END) AS missing_geo "
            f"FROM reports {where}",
            (*OPEN_STATUSES, *OPEN_STATUSES, *params),
        ).fetchone()
        resolution = con.execute(
            f"SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) AS avg_hours, "
            f"  COUNT(*) AS n "
            f"FROM reports {where} AND status = 'Resolved' AND resolved_at IS NOT NULL"
            if where else
            "SELECT AVG((julianday(resolved_at) - julianday(created_at)) * 24) AS avg_hours, "
            "COUNT(*) AS n FROM reports WHERE status = 'Resolved' AND resolved_at IS NOT NULL",
            params if where else (),
        ).fetchone()
    finally:
        con.close()

    total = base["total"] or 0
    resolved = base["resolved"] or 0
    closed = resolved + (base["rejected"] or 0)
    from intelligence.hotspot_detection import hotspot_stats
    hotspots = hotspot_stats()

    return {
        "total": total,
        "open": base["open"] or 0,
        "pending": base["open"] or 0,
        "resolved": resolved,
        "rejected": base["rejected"] or 0,
        "urgent_open": base["urgent_open"] or 0,
        "needs_review": base["needs_review"] or 0,
        "missing_geo": base["missing_geo"] or 0,
        "resolution_pct": round(100.0 * resolved / total, 1) if total else 0.0,
        "closed_pct": round(100.0 * closed / total, 1) if total else 0.0,
        "avg_resolution_hours": round(float(resolution["avg_hours"]), 1)
        if resolution and resolution["avg_hours"] is not None else None,
        "resolved_with_timestamp": int(resolution["n"]) if resolution else 0,
        "hotspots": hotspots["clusters"],
        "recurring_locations": hotspots["recurring"],
        "complaints_in_clusters": hotspots["complaints_in_clusters"],
        "unresolved_in_clusters": hotspots["unresolved_in_clusters"],
        "hotspot_params": hotspots["parameters"],
    }


# ---------------------------------------------------------------------------
# Chart series (consumed as JSON by Chart.js)
# ---------------------------------------------------------------------------
def _rows(con, sql, params=()):
    return con.execute(sql, params).fetchall()


def chart_series(filters, history_days=90):
    where, params = _where(filters)
    scope = where if where else ""
    con = get_connection()
    try:
        daily = _rows(
            con,
            f"SELECT date(created_at) AS day, COUNT(*) AS n FROM reports {scope} "
            f"{'AND' if where else 'WHERE'} created_at >= datetime('now', ?) "
            "GROUP BY day ORDER BY day",
            (*params, f"-{int(history_days)} days"),
        )
        category = _rows(
            con, f"SELECT waste_type AS label, COUNT(*) AS n FROM reports {scope} "
                 "GROUP BY waste_type ORDER BY n DESC", params)
        status = _rows(
            con, f"SELECT status AS label, COUNT(*) AS n FROM reports {scope} "
                 "GROUP BY status ORDER BY n DESC", params)
        area = _rows(
            con, f"SELECT area AS label, COUNT(*) AS n FROM reports "
                 f"{scope}{' AND' if where else 'WHERE'} area IS NOT NULL AND area != '' "
                 "GROUP BY area ORDER BY n DESC LIMIT 10", params)
        monthly = _rows(
            con, f"SELECT strftime('%Y-%m', created_at) AS label, COUNT(*) AS n "
                 f"FROM reports {scope} GROUP BY label ORDER BY label DESC LIMIT 12", params)
        urgency = _rows(
            con, f"SELECT COALESCE(ai_urgency, priority) AS label, COUNT(*) AS n "
                 f"FROM reports {scope} GROUP BY label ORDER BY n DESC", params)
        recent = _rows(
            con, f"SELECT id, tracking_id, location, waste_type, priority, ai_urgency, "
                 f"status, created_at, area, latitude, longitude, ai_needs_review "
                 f"FROM reports {scope} ORDER BY created_at DESC LIMIT 8", params)
    finally:
        con.close()

    # Fill the daily series with zero-count days so the line chart is honest
    # about days without reports.
    daily_map = {row["day"]: row["n"] for row in daily}
    labels, values = [], []
    from datetime import date, timedelta
    current = date.today() - timedelta(days=history_days - 1)
    while current <= date.today():
        key = current.isoformat()
        labels.append(key)
        values.append(daily_map.get(key, 0))
        current += timedelta(days=1)

    return {
        "daily": {"labels": labels, "values": values},
        "category": [{"label": r["label"], "value": r["n"]} for r in category],
        "status": [{"label": r["label"], "value": r["n"]} for r in status],
        "area": [{"label": r["label"], "value": r["n"]} for r in area],
        "monthly": [{"label": r["label"], "value": r["n"]} for r in reversed(monthly)],
        "urgency": [{"label": r["label"], "value": r["n"]} for r in urgency],
        "recent": [dict(r) for r in recent],
    }


def status_breakdown(filters=None):
    where, params = _where(filters or {})
    con = get_connection()
    try:
        rows = con.execute(
            f"SELECT status, COUNT(*) AS n FROM reports {where} GROUP BY status",
            params,
        ).fetchall()
    finally:
        con.close()
    return {row["status"]: row["n"] for row in rows}


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
EXPORT_COLUMNS = (
    ("tracking_id", "Tracking ID"),
    ("created_at", "Submitted At"),
    ("status", "Status"),
    ("name", "Citizen"),
    ("mobile", "Mobile"),
    ("area", "Area"),
    ("location", "Location"),
    ("waste_type", "Category"),
    ("priority", "Citizen Priority"),
    ("ai_category", "AI Category"),
    ("ai_urgency", "AI Urgency"),
    ("ai_confidence", "AI Confidence"),
    ("ai_needs_review", "Needs Review"),
    ("latitude", "Latitude"),
    ("longitude", "Longitude"),
    ("description", "Description"),
    ("admin_remarks", "Admin Remarks"),
    ("resolved_at", "Resolved At"),
)


def export_csv(filters):
    rows = filtered_reports(filters)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([title for _, title in EXPORT_COLUMNS])
    for row in rows:
        writer.writerow([
            "" if row[key] is None else row[key] for key, _ in EXPORT_COLUMNS
        ])
    filename = f"smartwaste_complaints_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return buffer.getvalue(), filename, len(rows)


# ---------------------------------------------------------------------------
# User management / audit helpers
# ---------------------------------------------------------------------------
def list_users(search=""):
    con = get_connection()
    try:
        if search:
            rows = con.execute(
                "SELECT u.id, u.name, u.email, u.role, u.is_active, u.created_at, "
                "  (SELECT COUNT(*) FROM reports r WHERE r.user_id = u.id) AS reports, "
                "  (SELECT COUNT(*) FROM notifications n WHERE n.user_id = u.id AND n.is_read = 0) AS unread "
                "FROM users u WHERE u.name LIKE ? OR u.email LIKE ? "
                "ORDER BY u.created_at DESC",
                (f"%{search}%", f"%{search}%"),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT u.id, u.name, u.email, u.role, u.is_active, u.created_at, "
                "  (SELECT COUNT(*) FROM reports r WHERE r.user_id = u.id) AS reports, "
                "  (SELECT COUNT(*) FROM notifications n WHERE n.user_id = u.id AND n.is_read = 0) AS unread "
                "FROM users u ORDER BY u.created_at DESC"
            ).fetchall()
        counts = con.execute(
            "SELECT COUNT(*) AS total, SUM(is_active) AS active FROM users"
        ).fetchone()
    finally:
        con.close()
    return {"users": rows, "total": counts["total"] or 0, "active": counts["active"] or 0}


def set_user_active(user_id, active):
    con = get_connection()
    try:
        cur = con.execute(
            "UPDATE users SET is_active=?, updated_at=datetime('now') WHERE id=?",
            (1 if active else 0, user_id),
        )
        con.commit()
        return cur.rowcount > 0
    finally:
        con.close()


def audit_rows(limit=200, action=""):
    con = get_connection()
    try:
        if action:
            rows = con.execute(
                "SELECT * FROM audit_logs WHERE action LIKE ? "
                "ORDER BY id DESC LIMIT ?", (f"%{action}%", int(limit)),
            ).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (int(limit),)
            ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
    finally:
        con.close()
    return {"rows": rows, "total": total}


def message_rows(limit=200):
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (int(limit),)
        ).fetchall()
        total = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    finally:
        con.close()
    return {"rows": rows, "total": total}
