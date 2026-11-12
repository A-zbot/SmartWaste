"""Municipal administrator routes: decision-support dashboard, complaint
management with AI explanations, hotspot map, forecasting, model evaluation,
user management, audit trail and CSV export (Modules B-G).
"""

import re
import threading
from datetime import datetime, timezone

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from config import (
    ALLOWED_TRANSITIONS,
    CATEGORIES,
    COMPLAINT_STATUSES,
    DBSCAN_EPS_METERS,
    DBSCAN_MIN_SAMPLES,
    PRIORITIES,
)
from db import get_connection, loads
from intelligence import _model_store
from intelligence.duplicate_detection import find_duplicates
from intelligence.hotspot_detection import (
    hotspot_stats,
    load_clusters,
    run_clustering,
    stored_run_params,
)
from intelligence.model_evaluation import full_summary
from intelligence.preprocessing import describe as preprocessing_describe
from intelligence.priority_predictor import effective_urgency, recommend_action
from intelligence.recommender import build_recommendations
from security import admin_required, audit
from modules.admin import services as admin_services
from modules.analytics.services import forecasting_payload, overview
from modules.complaints import services as complaint_services
from modules.complaints.pdf_service import build_complaint_pdf

bp = Blueprint("admin", __name__)

# Background retraining state (single process - gunicorn worker).
_retrain = {"running": False, "started_at": None, "finished_at": None, "error": None}


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@bp.route("/admin")
@admin_required
def dashboard():
    payload = overview(request.args)
    messages = admin_services.message_rows(limit=5)["total"]
    return render_template(
        "admin/dashboard.html",
        payload=payload,
        filters=payload["filters"],
        kpis=payload["kpis"],
        charts=payload["charts"],
        recommendations=payload["recommendations"],
        model_status=payload["model_status"],
        areas=payload["areas"],
        messages_total=messages,
        categories=CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        default_eps=DBSCAN_EPS_METERS,
        retrain=_retrain,
    )


# ---------------------------------------------------------------------------
# Complaint management
# ---------------------------------------------------------------------------
QUEUE_PER_PAGE = 20


def _paginate(args, per_page):
    """Return ``(page, per_page)`` with an invalid/absent page defaulting to 1."""
    try:
        page = int(args.get("page", 1))
    except (TypeError, ValueError):
        page = 1
    return max(1, page), per_page


def _complaint_list_context(args):
    filters = admin_services.parse_filters(args)
    page, per_page = _paginate(args, QUEUE_PER_PAGE)
    total = admin_services.count_filtered_reports(filters)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = admin_services.filtered_reports(
        filters, limit=per_page, offset=(page - 1) * per_page
    )
    counts = admin_services.status_breakdown(filters)
    needs_review_count = admin_services.count_filtered_reports(
        {**filters, "needs_review": True}
    )
    return filters, rows, counts, total, page, pages, needs_review_count


@bp.route("/admin/complaints")
@admin_required
def complaints():
    filters, rows, counts, total, page, pages, needs_review_count = (
        _complaint_list_context(request.args)
    )
    return render_template(
        "admin/complaints.html",
        filters=filters,
        reports=rows,
        counts=counts,
        total=total,
        page=page,
        pages=pages,
        areas=admin_services.available_areas(),
        categories=CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        priorities=PRIORITIES,
        needs_review_count=needs_review_count,
    )


def _load_admin_report(report_id):
    con = get_connection()
    try:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if report is None:
            con.close()
            return None, None, None, None, None, None
        images = con.execute(
            "SELECT * FROM complaint_images WHERE report_id=? ORDER BY id", (report_id,)
        ).fetchall()
        history = con.execute(
            "SELECT * FROM complaint_history WHERE report_id=? ORDER BY id", (report_id,)
        ).fetchall()
        prediction = con.execute(
            "SELECT * FROM predictions WHERE report_id=? ORDER BY id DESC LIMIT 1",
            (report_id,),
        ).fetchone()
        feedback = con.execute(
            "SELECT * FROM feedback WHERE report_id=?", (report_id,)
        ).fetchone()
        owner = None
        if report["user_id"]:
            owner = con.execute(
                "SELECT u.id, u.name, u.email, u.created_at, "
                "       (SELECT COUNT(*) FROM reports r WHERE r.user_id = u.id) AS reports "
                "FROM users u WHERE u.id=?",
                (report["user_id"],),
            ).fetchone()
        return report, images, history, prediction, feedback, {"con": con, "owner": owner}
    except Exception:
        con.close()
        raise


@bp.route("/admin/complaint/<int:report_id>")
@admin_required
def complaint_detail(report_id):
    report, images, history, prediction, feedback, extra = _load_admin_report(report_id)
    if report is None:
        abort(404)
    con = extra["con"]
    try:
        explanation = loads(prediction["explanation"], {}) if prediction else {}
        if not explanation:
            from intelligence.complaint_classifier import classify
            from intelligence.priority_predictor import predict_urgency
            from intelligence.explainability import explain_prediction
            explanation = explain_prediction(
                report["description"], classify(report["description"]),
                predict_urgency(report["description"]),
                context={"citizen_category": report["waste_type"],
                         "citizen_priority": report["priority"]},
            )
        duplicates = find_duplicates(
            report["description"], latitude=report["latitude"],
            longitude=report["longitude"], category=report["waste_type"],
            exclude_report_id=report["id"], limit=8,
        )
        dup_target = None
        if report["duplicate_of_report_id"]:
            dup_target = con.execute(
                "SELECT id, tracking_id, status FROM reports WHERE id=?",
                (report["duplicate_of_report_id"],),
            ).fetchone()
        cluster = None
        for item in load_clusters():
            if report["id"] in item["report_ids"]:
                cluster = item
                break
        return render_template(
            "admin/complaint_detail.html",
            report=report,
            images=images,
            history=history,
            prediction=prediction,
            explanation=explanation,
            feedback=feedback,
            owner=extra["owner"],
            duplicates=duplicates,
            dup_target=dup_target,
            cluster=cluster,
            statuses=COMPLAINT_STATUSES,
            next_statuses=[
                s for s in COMPLAINT_STATUSES
                if s == report["status"]
                or s in ALLOWED_TRANSITIONS.get(report["status"], [])
            ],
            categories=CATEGORIES,
            priorities=PRIORITIES,
            recommended_action=recommend_action(
                report["ai_category"] or report["waste_type"],
                report["ai_urgency"] or report["priority"],
            ),
            effective_priority=effective_urgency(
                report["priority"], report["ai_urgency"]
            ),
        )
    finally:
        con.close()


@bp.route("/admin/complaint/<int:report_id>/ai-review", methods=["POST"])
@admin_required
def ai_review(report_id):
    """Confirm or correct the model's classification (Part 4 review workflow).

    The original ``ai_*`` prediction is never overwritten - the verified values
    live in ``final_*`` so evaluation numbers stay honest.
    """
    final_category = request.form.get("final_category", "").strip()
    final_urgency = request.form.get("final_urgency", "").strip()
    note = request.form.get("ai_review_note", "").strip()

    def _reject(message):
        flash(message, "error")
        return redirect(url_for("admin.complaint_detail", report_id=report_id))

    if final_category not in CATEGORIES:
        return _reject("Choose a valid waste category to confirm.")
    if final_urgency and final_urgency not in PRIORITIES:
        return _reject("Choose a valid priority level.")
    if len(note) > 500:
        return _reject("Review note must be 500 characters or fewer.")

    con = get_connection()
    try:
        report = con.execute(
            "SELECT id, status, user_id, tracking_id, ai_category, ai_urgency "
            "FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
        if report is None:
            abort(404)

        changed = final_category != report["ai_category"]
        parts = [f"category {'corrected to' if changed else 'confirmed as'} "
                 f"'{final_category}' (model: {report['ai_category'] or 'unavailable'})"]
        if final_urgency:
            parts.append(f"priority {'corrected to' if final_urgency != report['ai_urgency'] else 'confirmed as'} "
                         f"'{final_urgency}' (model: {report['ai_urgency'] or 'unavailable'})")
        if note:
            parts.append(note)
        remark = "AI review: " + "; ".join(parts) + "."

        con.execute(
            "UPDATE reports SET final_category=?, final_urgency=?, ai_review_note=?, "
            " ai_reviewed_at=?, ai_reviewed_by=?, ai_needs_review=0, updated_at=? "
            "WHERE id=?",
            (
                final_category,
                final_urgency or None,
                note or None,
                complaint_services.utc_now(),
                "administrator",
                complaint_services.utc_now(),
                report_id,
            ),
        )
        complaint_services.add_history(
            con, report_id, report["status"], report["status"], remark,
            actor_type="admin", actor_label="administrator",
        )
        complaint_services.notify_user(
            con, report["user_id"], report_id,
            "Complaint classification verified",
            f"Our team reviewed the AI classification for {report['tracking_id']} "
            f"and confirmed it as '{final_category}'.",
            link=url_for("complaints.detail", report_id=report_id),
        )
        con.commit()
    finally:
        con.close()

    audit(
        "complaint.ai_review", entity="report", entity_id=report_id,
        detail=remark, actor_type="admin", ip=request.remote_addr,
    )
    flash(
        f"AI review saved: {report['tracking_id']} verified as '{final_category}'.",
        "success",
    )
    return redirect(url_for("admin.complaint_detail", report_id=report_id))


@bp.route("/admin/complaint/<int:report_id>/duplicate", methods=["POST"])
@admin_required
def link_duplicate(report_id):
    """Link this complaint as a duplicate of an earlier one (advisory -> recorded)."""
    target_ref = request.form.get("duplicate_of", "").strip()
    also_reject = request.form.get("reject_duplicate") == "on"

    def _reject(message):
        flash(message, "error")
        return redirect(url_for("admin.complaint_detail", report_id=report_id))

    match = re.fullmatch(r"(?:SW-)?0*(\d{1,6})", target_ref, re.I)
    if not match:
        return _reject("Enter the tracking ID (e.g. SW-00012) or number of the original complaint.")
    target_id = int(match.group(1))
    if target_id == report_id:
        return _reject("A complaint cannot be a duplicate of itself.")

    con = get_connection()
    try:
        report = con.execute(
            "SELECT id, status, user_id, tracking_id FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
        if report is None:
            abort(404)
        target = con.execute(
            "SELECT id, tracking_id, status, duplicate_of_report_id FROM reports WHERE id=?",
            (target_id,),
        ).fetchone()
        if target is None:
            return _reject("The original complaint you entered does not exist.")
        if target["duplicate_of_report_id"] == report_id:
            return _reject("That would create a circular duplicate link.")

        now = complaint_services.utc_now()
        con.execute(
            "UPDATE reports SET duplicate_of_report_id=?, updated_at=? WHERE id=?",
            (target_id, now, report_id),
        )
        complaint_services.add_history(
            con, report_id, report["status"], report["status"],
            f"Linked as duplicate of {target['tracking_id']}",
            actor_type="admin", actor_label="administrator",
        )
        complaint_services.notify_user(
            con, report["user_id"], report_id,
            "Complaint linked as duplicate",
            f"{report['tracking_id']} was linked to the earlier report "
            f"{target['tracking_id']}; both are tracked together.",
            link=url_for("complaints.detail", report_id=report_id),
        )
        con.commit()
    finally:
        con.close()

    audit(
        "complaint.linked_duplicate", entity="report", entity_id=report_id,
        detail=f"{report['tracking_id']} -> duplicate of {target['tracking_id']} (#{target_id})",
        actor_type="admin", ip=request.remote_addr,
    )
    message = f"{report['tracking_id']} linked as duplicate of {target['tracking_id']}."
    flash(message, "success")

    if also_reject:
        result = complaint_services.update_status(
            report_id, "Rejected",
            remark=f"Duplicate of {target['tracking_id']}",
            ip=request.remote_addr,
        )
        if not result.get("ok"):
            flash(f"Link saved, but status could not change: {result.get('error')}", "error")
    return redirect(url_for("admin.complaint_detail", report_id=report_id))


@bp.route("/admin/complaint/<int:report_id>/duplicate/clear", methods=["POST"])
@admin_required
def clear_duplicate(report_id):
    con = get_connection()
    try:
        report = con.execute(
            "SELECT id, status, tracking_id, duplicate_of_report_id FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
        if report is None:
            abort(404)
        if not report["duplicate_of_report_id"]:
            flash("This complaint is not linked as a duplicate.", "error")
            return redirect(url_for("admin.complaint_detail", report_id=report_id))
        con.execute(
            "UPDATE reports SET duplicate_of_report_id=NULL, updated_at=? WHERE id=?",
            (complaint_services.utc_now(), report_id),
        )
        complaint_services.add_history(
            con, report_id, report["status"], report["status"],
            "Duplicate link removed",
            actor_type="admin", actor_label="administrator",
        )
        con.commit()
    finally:
        con.close()
    audit(
        "complaint.cleared_duplicate", entity="report", entity_id=report_id,
        detail=f"{report['tracking_id']} unlinked",
        actor_type="admin", ip=request.remote_addr,
    )
    flash(f"Duplicate link removed from {report['tracking_id']}.", "success")
    return redirect(url_for("admin.complaint_detail", report_id=report_id))


@bp.route("/admin/complaint/<int:report_id>/status", methods=["POST"])
@admin_required
def update_status(report_id):
    new_status = request.form.get("status", "").strip()
    remark = request.form.get("remark", "").strip()
    resolution_image = request.files.get("resolution_image")
    result = complaint_services.update_status(
        report_id, new_status, remark=remark,
        actor_label="administrator", resolution_image=resolution_image,
        ip=request.remote_addr,
    )
    if not result.get("ok"):
        flash(result.get("error", "Could not update the complaint."), "error")
    else:
        flash(
            f"{result['new_status']}: status updated "
            f"(was {result['old_status']}).",
            "success",
        )
    return redirect(url_for("admin.complaint_detail", report_id=report_id))


@bp.route("/update_status/<int:report_id>/<status>")
@admin_required
def legacy_update_status(report_id, status):
    """Backward-compatible link from SmartWaste 1.x emails/bookmarks.

    A GET must never mutate state (CSRF via ``<img src>`` etc.), so this
    renders a CSRF-protected confirmation that POSTs to the real endpoint.
    """
    if status not in COMPLAINT_STATUSES:
        abort(404)
    con = get_connection()
    try:
        report = con.execute(
            "SELECT id, tracking_id, status FROM reports WHERE id=?", (report_id,)
        ).fetchone()
    finally:
        con.close()
    if report is None:
        abort(404)
    return render_template(
        "admin/confirm_status.html",
        report=report,
        new_status=status,
    )


# ---------------------------------------------------------------------------
# Hotspot map
# ---------------------------------------------------------------------------
@bp.route("/admin/map")
@admin_required
def map_view():
    filters = admin_services.parse_filters(request.args)
    rows = admin_services.filtered_reports(filters)
    markers = []
    for row in rows:
        if row["latitude"] is None or row["longitude"] is None:
            continue
        markers.append({
            "id": row["id"],
            "tracking_id": row["tracking_id"],
            "lat": float(row["latitude"]),
            "lng": float(row["longitude"]),
            "location": row["location"],
            "area": row["area"],
            "category": row["waste_type"],
            "status": row["status"],
            "priority": row["priority"],
            "urgency": row["ai_urgency"],
            "confidence": row["ai_confidence"],
            "created_at": row["created_at"],
            "needs_review": bool(row["ai_needs_review"]),
        })
    unresolved = [m for m in markers if m["status"] not in ("Resolved", "Rejected")]
    urgent = [m for m in markers
              if m["urgency"] in ("High", "Emergency") or m["priority"] in ("High", "Emergency")]
    return render_template(
        "admin/map.html",
        markers=markers,
        clusters=load_clusters(),
        stats=hotspot_stats(),
        run_params=stored_run_params(),
        filters=filters,
        areas=admin_services.available_areas(),
        categories=CATEGORIES,
        statuses=COMPLAINT_STATUSES,
        map_summary={
            "total": len(markers),
            "unresolved": len(unresolved),
            "urgent": len(urgent),
            "without_coords": sum(
                1 for r in rows if r["latitude"] is None or r["longitude"] is None
            ),
            "filtered": len(rows),
        },
        default_eps=DBSCAN_EPS_METERS,
        default_min=DBSCAN_MIN_SAMPLES,
    )


@bp.route("/admin/map/recluster", methods=["POST"])
@admin_required
def recluster():
    try:
        eps = float(request.form.get("eps_meters", DBSCAN_EPS_METERS))
        min_samples = int(request.form.get("min_samples", DBSCAN_MIN_SAMPLES))
    except (TypeError, ValueError):
        eps, min_samples = DBSCAN_EPS_METERS, DBSCAN_MIN_SAMPLES
    eps = max(50.0, min(eps, 10000.0))
    min_samples = max(2, min(min_samples, 100))

    summary = run_clustering(eps_meters=eps, min_samples=min_samples)
    audit(
        "hotspots.reclustered",
        entity="complaint_clusters",
        detail=(f"eps={eps:.0f}m min_samples={min_samples} "
                f"clusters={summary['n_clusters']} points={summary['points_with_coordinates']} "
                f"noise={summary['noise_points']}"),
        actor_type="admin", ip=request.remote_addr,
    )
    flash(
        f"Clustering complete: {summary['n_clusters']} hotspot(s) from "
        f"{summary['points_with_coordinates']} geocoded complaints "
        f"({summary['noise_points']} outside clusters).",
        "success" if summary["n_clusters"] else "info",
    )
    return redirect(url_for("admin.map_view", **{
        k: v for k, v in {
            "start": request.form.get("start", ""),
            "end": request.form.get("end", ""),
            "category": request.form.get("category", ""),
            "status": request.form.get("status", ""),
            "area": request.form.get("area", ""),
        }.items() if v
    }))


# ---------------------------------------------------------------------------
# Predictive analytics
# ---------------------------------------------------------------------------
@bp.route("/admin/analytics")
@admin_required
def analytics():
    payload = forecasting_payload(request.args)
    filters = admin_services.parse_filters(request.args)
    distributions = admin_services.chart_series(filters, history_days=90)
    return render_template(
        "admin/forecast.html",
        forecast=payload,
        distributions=distributions,
        categories=CATEGORIES,
        statuses=COMPLAINT_STATUSES,
    )


# ---------------------------------------------------------------------------
# Model evaluation & retraining
# ---------------------------------------------------------------------------
@bp.route("/admin/models")
@admin_required
def models():
    evaluation = full_summary()
    return render_template(
        "admin/models.html",
        evaluation=evaluation,
        preprocessing=preprocessing_describe(),
        retrain=_retrain,
        categories=CATEGORIES,
    )


@bp.route("/admin/models/retrain", methods=["POST"])
@admin_required
def retrain():
    global _retrain
    if _retrain.get("running"):
        flash("Training is already running - refresh in a moment.", "info")
        return redirect(url_for("admin.models"))

    def _run():
        global _retrain
        try:
            from intelligence.model_training import train_all
            train_all(progress=lambda *_: None)
            _retrain.update(
                running=False,
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                error=None,
            )
        except Exception as exc:  # pragma: no cover - surfaced in the UI
            _retrain.update(
                running=False,
                finished_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                error=str(exc),
            )

    _retrain = {
        "running": True,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "finished_at": None,
        "error": None,
    }
    threading.Thread(target=_run, daemon=True).start()
    audit("models.retrain", entity="model", detail="manual retraining requested",
          actor_type="admin", ip=request.remote_addr)
    flash("Model training started in the background. Refresh this page shortly to see the new metrics.", "success")
    return redirect(url_for("admin.models"))


# ---------------------------------------------------------------------------
# Users / messages / audit
# ---------------------------------------------------------------------------
@bp.route("/admin/users")
@admin_required
def users():
    search = (request.args.get("q") or "").strip()[:80]
    payload = admin_services.list_users(search)
    return render_template("admin/users.html", users=payload, q=search)


@bp.route("/admin/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def toggle_user(user_id):
    active = request.form.get("active") == "1"
    ok = admin_services.set_user_active(user_id, active)
    if not ok:
        flash("User not found.", "error")
    else:
        state = "enabled" if active else "disabled"
        audit("users.toggled", entity="user", entity_id=user_id,
              detail=f"account {state}", actor_type="admin", ip=request.remote_addr)
        flash(f"Account {state}.", "success")
    return redirect(url_for("admin.users", q=request.form.get("q", "")))


@bp.route("/admin/messages")
@admin_required
def messages():
    page, per_page = _paginate(request.args, 20)
    payload = admin_services.message_rows(limit=per_page)
    pages = max(1, -(-payload["total"] // per_page))
    page = min(page, pages)
    if page > 1:
        payload = admin_services.message_rows(
            limit=per_page, offset=(page - 1) * per_page
        )
    return render_template(
        "admin/messages.html", payload=payload, page=page, pages=pages
    )


@bp.route("/admin/audit")
@admin_required
def audit_log():
    action = (request.args.get("action") or "").strip()[:60]
    page, per_page = _paginate(request.args, 20)
    payload = admin_services.audit_rows(limit=per_page, action=action)
    pages = max(1, -(-payload["total"] // per_page))
    page = min(page, pages)
    if page > 1:
        payload = admin_services.audit_rows(
            limit=per_page, action=action, offset=(page - 1) * per_page
        )
    return render_template(
        "admin/audit.html", payload=payload, action=action, page=page, pages=pages
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------
@bp.route("/admin/export/complaints.csv")
@admin_required
def export_complaints():
    filters = admin_services.parse_filters(request.args)
    csv_text, filename, count = admin_services.export_csv(filters)
    audit("reports.exported", entity="report", detail=f"{count} row(s)",
          actor_type="admin", ip=request.remote_addr)
    response = Response(csv_text, mimetype="text/csv; charset=utf-8")
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


@bp.route("/admin/complaint/<int:report_id>/pdf")
@admin_required
def export_report_pdf(report_id):
    """Full operational complaint report as PDF (server-side, reportlab)."""
    report, images, history, prediction, feedback, extra = _load_admin_report(report_id)
    if report is None:
        abort(404)
    con = extra["con"]
    try:
        pdf = build_complaint_pdf(
            report,
            history=history,
            prediction=prediction,
            recommended_action=recommend_action(
                report["ai_category"] or report["waste_type"],
                report["ai_urgency"] or report["priority"],
            ),
            audience="admin",
        )
        audit("reports.exported_pdf", entity="report", entity_id=report_id,
              detail=report["tracking_id"] or "", actor_type="admin",
              ip=request.remote_addr)
        tracking = report["tracking_id"] or f"complaint-{report_id}"
        response = Response(pdf, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{tracking}-report.pdf"'
        )
        return response
    finally:
        con.close()
