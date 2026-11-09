"""Citizen-facing complaint routes: submission, tracking, detail, feedback,
duplicate checks and notifications (Module A, with Modules B/C integration).
"""

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from config import (
    CATEGORIES,
    COMPLAINT_STATUSES,
    PRIORITIES,
    UPLOAD_FOLDER,
)
from db import get_connection, loads
from intelligence.duplicate_detection import find_duplicates
from intelligence.explainability import explain_prediction
from intelligence.hotspot_detection import cluster_membership
from intelligence.priority_predictor import recommend_action
from security import citizen_required
from modules.complaints import services

bp = Blueprint("complaints", __name__)


def _unread():
    if not session.get("user_id"):
        return 0
    return services.unread_notifications(session["user_id"], limit=1)["unread"]


def _can_view(report, user_id=None, is_admin=False):
    if is_admin:
        return True
    if report["user_id"] is None:
        return True  # anonymous complaint - accessible via its link/ID
    return user_id is not None and report["user_id"] == user_id


def _load_report(report_id):
    con = get_connection()
    try:
        report = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if report is None:
            con.close()
            return None, None, None, None, None, None
        images = con.execute(
            "SELECT * FROM complaint_images WHERE report_id=? ORDER BY id",
            (report_id,),
        ).fetchall()
        history = con.execute(
            "SELECT * FROM complaint_history WHERE report_id=? ORDER BY id",
            (report_id,),
        ).fetchall()
        prediction = con.execute(
            "SELECT * FROM predictions WHERE report_id=? ORDER BY id DESC LIMIT 1",
            (report_id,),
        ).fetchone()
        feedback = con.execute(
            "SELECT * FROM feedback WHERE report_id=?", (report_id,)
        ).fetchone()
        return report, images, history, prediction, feedback, con
    except Exception:
        con.close()
        raise


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
@bp.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        user_id = session.get("user_id")
        file_storage = request.files.get("image")
        result = services.create_complaint(
            request.form, file_storage, user_id=user_id, ip=request.remote_addr
        )
        if not result.get("ok"):
            flash(result["error"], "error")
            return redirect(url_for("complaints.report"))
        return redirect(url_for("complaints.submitted", report_id=result["report_id"]))

    prefill = {"name": "", "mobile": ""}
    if session.get("user_id"):
        con = get_connection()
        try:
            user = con.execute(
                "SELECT name FROM users WHERE id=?", (session["user_id"],)
            ).fetchone()
            if user:
                prefill["name"] = user["name"]
        finally:
            con.close()
    return render_template(
        "report.html",
        categories=CATEGORIES,
        priorities=PRIORITIES,
        prefill=prefill,
        unread=_unread(),
    )


@bp.route("/report/success/<int:report_id>")
def submitted(report_id):
    con = get_connection()
    try:
        report_row = con.execute(
            "SELECT * FROM reports WHERE id=?", (report_id,)
        ).fetchone()
        prediction = con.execute(
            "SELECT * FROM predictions WHERE report_id=? ORDER BY id DESC LIMIT 1",
            (report_id,),
        ).fetchone()
    finally:
        con.close()

    if report_row is None:
        abort(404)
    if not _can_view(report_row, session.get("user_id"), session.get("admin") is True):
        abort(403)

    duplicates = find_duplicates(
        report_row["description"],
        latitude=report_row["latitude"],
        longitude=report_row["longitude"],
        category=report_row["waste_type"],
        exclude_report_id=report_row["id"],
    )
    explanation = loads(prediction["explanation"], {}) if prediction else {}
    ai = {
        "category": report_row["ai_category"],
        "urgency": report_row["ai_urgency"],
        "confidence": report_row["ai_confidence"],
        "needs_review": bool(report_row["ai_needs_review"]),
        "recommended_action": recommend_action(
            report_row["ai_category"] or report_row["waste_type"],
            report_row["ai_urgency"] or report_row["priority"],
        ),
    }
    return render_template(
        "success.html",
        report=report_row,
        ai=ai,
        duplicates=duplicates,
        explanation=explanation,
        unread=_unread(),
    )


@bp.route("/report/duplicate-check", methods=["POST"])
def duplicate_check():
    """AJAX endpoint used by the complaint form before submission."""
    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if len(text) < 15:
        return jsonify({"ok": False, "error": "Describe the problem (15+ characters) to check for duplicates."})
    try:
        latitude = float(payload.get("latitude")) if payload.get("latitude") not in (None, "") else None
        longitude = float(payload.get("longitude")) if payload.get("longitude") not in (None, "") else None
    except (TypeError, ValueError):
        latitude = longitude = None
    category = payload.get("category") if payload.get("category") in CATEGORIES else None

    result = find_duplicates(text, latitude=latitude, longitude=longitude,
                             category=category, limit=5)
    return jsonify({"ok": True, **result})


# ---------------------------------------------------------------------------
# Tracking & history
# ---------------------------------------------------------------------------
@bp.route("/track")
def track():
    q = request.args.get("q", "").strip()
    results = []
    if q:
        token = q.lstrip("#").strip()
        by_ref = token[:3].upper() == "SW-"
        if by_ref:
            token = token[3:].strip()
        digits = "".join(ch for ch in token if ch.isdigit())
        con = get_connection()
        try:
            if digits and (by_ref or (token.isdigit() and len(digits) <= 6)):
                results = con.execute(
                    "SELECT * FROM reports WHERE id=? OR tracking_id=?",
                    (int(digits), f"SW-{int(digits):05d}"),
                ).fetchall()
            elif digits:
                results = con.execute(
                    "SELECT * FROM reports WHERE mobile=? ORDER BY id DESC", (digits,)
                ).fetchall()
            elif len(token) >= 3:
                results = con.execute(
                    "SELECT * FROM reports WHERE tracking_id LIKE ? ORDER BY id DESC LIMIT 20",
                    (f"{token.upper()}%",),
                ).fetchall()
        finally:
            con.close()
    return render_template("track.html", q=q, results=results, unread=_unread())


@bp.route("/my_reports")
@citizen_required
def my_reports():
    user_id = session["user_id"]
    con = get_connection()
    try:
        reports = con.execute(
            "SELECT * FROM reports WHERE user_id=? ORDER BY id DESC", (user_id,)
        ).fetchall()
    finally:
        con.close()
    counts = {status: 0 for status in COMPLAINT_STATUSES}
    for row in reports:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return render_template(
        "my_reports.html",
        reports=reports,
        total=len(reports),
        open_count=sum(counts[s] for s in COMPLAINT_STATUSES if s not in ("Resolved", "Rejected")),
        resolved=counts.get("Resolved", 0),
        unread=_unread(),
    )


@bp.route("/complaint/<int:report_id>")
def detail(report_id):
    report_row, images, history, prediction, feedback, con = _load_report(report_id)
    if report_row is None:
        abort(404)
    try:
        if not _can_view(report_row, session.get("user_id"), session.get("admin") is True):
            flash("This complaint belongs to another citizen. Sign in with the owning account to view it.", "error")
            abort(403)

        duplicates = find_duplicates(
            report_row["description"],
            latitude=report_row["latitude"],
            longitude=report_row["longitude"],
            category=report_row["waste_type"],
            exclude_report_id=report_row["id"],
            limit=5,
        )
        explanation = loads(prediction["explanation"], {}) if prediction else {}
        if not explanation and report_row["ai_category"]:
            from intelligence.complaint_classifier import classify
            from intelligence.priority_predictor import predict_urgency
            explanation = explain_prediction(
                report_row["description"],
                classify(report_row["description"]),
                predict_urgency(report_row["description"]),
                context={"citizen_category": report_row["waste_type"],
                         "citizen_priority": report_row["priority"]},
            )
        cluster = cluster_membership(report_row["id"])
        return render_template(
            "complaint_detail.html",
            report=report_row,
            images=images,
            history=history,
            prediction=prediction,
            explanation=explanation,
            feedback=feedback,
            duplicates=duplicates,
            cluster=cluster,
            statuses=COMPLAINT_STATUSES,
            recommended_action=recommend_action(
                report_row["ai_category"] or report_row["waste_type"],
                report_row["ai_urgency"] or report_row["priority"],
            ),
            can_manage=session.get("admin") is True,
            unread=_unread(),
        )
    finally:
        con.close()


@bp.route("/complaint/<int:report_id>/pdf")
def report_pdf(report_id):
    """Citizen PDF receipt - same access rules as the detail page."""
    report_row, images, history, prediction, feedback, con = _load_report(report_id)
    if report_row is None:
        abort(404)
    try:
        if not _can_view(report_row, session.get("user_id"), session.get("admin") is True):
            abort(403)
        from modules.complaints.pdf_service import build_complaint_pdf

        pdf = build_complaint_pdf(
            report_row,
            history=history,
            prediction=prediction,
            recommended_action=recommend_action(
                report_row["ai_category"] or report_row["waste_type"],
                report_row["ai_urgency"] or report_row["priority"],
            ),
            audience="citizen",
        )
        tracking = report_row["tracking_id"] or f"complaint-{report_id}"
        response = Response(pdf, mimetype="application/pdf")
        response.headers["Content-Disposition"] = (
            f'attachment; filename="{tracking}-receipt.pdf"'
        )
        return response
    finally:
        con.close()


@bp.route("/complaint/<int:report_id>/feedback", methods=["POST"])
def submit_feedback(report_id):
    user_id = session.get("user_id")
    result = services.submit_feedback(
        report_id, user_id,
        request.form.get("rating"), request.form.get("comment", ""),
        ip=request.remote_addr,
    )
    if not result.get("ok"):
        flash(result["error"], "error")
    else:
        flash("Thank you for your feedback.", "success")
    return redirect(url_for("complaints.detail", report_id=report_id))


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@bp.route("/notifications")
@citizen_required
def notifications():
    payload = services.unread_notifications(session["user_id"], limit=50)
    return render_template(
        "notifications.html",
        rows=payload["rows"],
        unread=payload["unread"],
    )


@bp.route("/notifications/read", methods=["POST"])
@citizen_required
def mark_notifications_read():
    notification_id = request.form.get("id")
    services.mark_notifications_read(
        session["user_id"],
        int(notification_id) if notification_id and notification_id.isdigit() else None,
    )
    flash("Notifications marked as read.", "success")
    return redirect(request.referrer or url_for("complaints.notifications"))


@bp.route("/uploads/<filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)
