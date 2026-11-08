"""Complaint lifecycle services (Module A + integration of Modules B/C/F).

Submission pipeline:
    validate -> save image -> run ML models -> insert row -> tracking id ->
    history event -> stored explanation (model + context) -> duplicate report ->
    citizen notification -> audit log -> admin e-mail (best effort)

Status transitions add a history event, notify the owner and write an audit
record, so every change is traceable.
"""

import logging
import os
import threading
import uuid
from datetime import datetime, timezone

from werkzeug.utils import secure_filename

from config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER
from db import dumps, get_connection, tracking_id_for
from intelligence.complaint_classifier import classify
from intelligence.duplicate_detection import find_duplicates
from intelligence.explainability import explain_prediction
from intelligence.geospatial_analysis import area_from_location, parse_legacy_coordinates
from intelligence.hotspot_detection import cluster_membership
from intelligence.priority_predictor import effective_urgency, predict_urgency, recommend_action
from security import audit

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("name", "mobile", "location", "waste_type", "priority", "description")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file_storage):
    """Persist an uploaded image; returns the stored filename or None."""
    if not file_storage or not file_storage.filename:
        return None, None
    if not allowed_file(file_storage.filename):
        raise ValueError("Only PNG, JPG, JPEG or WEBP images are allowed.")
    ext = secure_filename(file_storage.filename).rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_FOLDER, filename))
    return filename, ext


def parse_coordinates(form):
    """Read lat/lon from the form, tolerating the legacy free-text pattern."""
    lat = form.get("latitude", "").strip()
    lon = form.get("longitude", "").strip()
    if lat and lon:
        try:
            lat_f, lon_f = float(lat), float(lon)
        except ValueError:
            lat_f = lon_f = None
        else:
            if -90 <= lat_f <= 90 and -180 <= lon_f <= 180 and not (lat_f == 0 and lon_f == 0):
                return lat_f, lon_f
    legacy = parse_legacy_coordinates(form.get("location", ""))
    return legacy or (None, None)


def validate(form, file_storage=None):
    missing = [f for f in REQUIRED_FIELDS if not form.get(f, "").strip()]
    if missing:
        return f"Please fill all required fields: {', '.join(missing)}."
    mobile = "".join(ch for ch in form.get("mobile", "") if ch.isdigit())
    if len(mobile) < 10:
        return "Please enter a valid mobile number (at least 10 digits)."
    description = form.get("description", "").strip()
    if len(description) < 15:
        return "Please describe the problem in at least 15 characters so the model and the field team can act on it."
    if len(description) > 2000:
        return "Description must be under 2000 characters."
    if file_storage and file_storage.filename and not allowed_file(file_storage.filename):
        return "Only PNG, JPG, JPEG or WEBP images are allowed."
    return None


def add_history(con, report_id, old_status, new_status, remark,
                actor_type="system", actor_id=None, actor_label=None):
    con.execute(
        "INSERT INTO complaint_history "
        "(report_id, old_status, new_status, remark, actor_type, actor_id, actor_label, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (report_id, old_status, new_status, remark, actor_type, actor_id, actor_label, utc_now()),
    )


def notify_user(con, user_id, report_id, title, message, link=None):
    if not user_id:
        return
    con.execute(
        "INSERT INTO notifications (user_id, report_id, title, message, link, is_read, created_at) "
        "VALUES (?, ?, ?, ?, ?, 0, ?)",
        (user_id, report_id, title, message, link, utc_now()),
    )


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------
def create_complaint(form, file_storage, user_id=None, ip=None):
    """Create a complaint with ML predictions, duplicate analysis and audit."""
    error = validate(form, file_storage)
    if error:
        return {"ok": False, "error": error}

    name = form.get("name", "").strip()
    mobile = "".join(ch for ch in form.get("mobile", "") if ch.isdigit())
    location = form.get("location", "").strip()
    waste_type = form.get("waste_type", "").strip()
    priority = form.get("priority", "").strip()
    description = form.get("description", "").strip()
    latitude, longitude = parse_coordinates(form)
    area = area_from_location(location)

    # --- Module B: genuine model predictions (run before insert) -----------
    category_prediction = classify(description)
    urgency_prediction = predict_urgency(description)
    predicted_category = category_prediction.get("category")
    predicted_urgency = urgency_prediction.get("urgency")
    needs_review = bool(
        category_prediction.get("needs_review") or urgency_prediction.get("needs_review")
    )

    # --- Module C: possible duplicates before the row exists ---------------
    duplicates = find_duplicates(
        description, latitude=latitude, longitude=longitude, category=waste_type
    )

    try:
        image_filename, _ = save_image(file_storage)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    con = get_connection()
    try:
        cur = con.execute(
            "INSERT INTO reports "
            "(name, mobile, location, waste_type, priority, description, image, "
            " user_id, status, created_at, updated_at, area, latitude, longitude, "
            " ai_category, ai_urgency, ai_confidence, ai_needs_review, source) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Submitted', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'live')",
            (
                name, mobile, location, waste_type, priority, description,
                image_filename, user_id, utc_now(), utc_now(), area,
                latitude, longitude,
                predicted_category, predicted_urgency,
                category_prediction.get("confidence"),
                1 if needs_review else 0,
            ),
        )
        report_id = cur.lastrowid
        tracking_id = tracking_id_for(report_id)
        con.execute("UPDATE reports SET tracking_id=? WHERE id=?", (tracking_id, report_id))

        if image_filename:
            con.execute(
                "INSERT INTO complaint_images (report_id, filename, kind, uploaded_by, created_at) "
                "VALUES (?, ?, 'submission', ?, ?)",
                (report_id, image_filename, user_id, utc_now()),
            )

        add_history(
            con, report_id, None, "Submitted",
            "Complaint registered on SmartWaste",
            actor_type="citizen" if user_id else "guest",
            actor_id=user_id, actor_label=name,
        )

        # --- Module F: stored explanation (model features + context) -------
        cluster = cluster_membership(report_id)
        explanation = explain_prediction(
            description, category_prediction, urgency_prediction,
            context={
                "citizen_category": waste_type,
                "citizen_priority": priority,
                "hours_since_submission": 0.0,
                "similar_nearby_count": len(duplicates.get("matches", [])),
                "hotspot_label": cluster["label"] if cluster else None,
                "hotspot_size": cluster["complaint_count"] if cluster else None,
            },
        )
        con.execute(
            "INSERT INTO predictions "
            "(report_id, model_name, model_version, predicted_category, "
            " predicted_urgency, confidence, needs_review, explanation, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report_id,
                category_prediction.get("model_name") or "unavailable",
                category_prediction.get("model_version"),
                predicted_category, predicted_urgency,
                category_prediction.get("confidence"),
                1 if needs_review else 0,
                dumps(explanation),
                utc_now(),
            ),
        )

        notify_user(
            con, user_id, report_id,
            f"Complaint {tracking_id} submitted",
            f"We received your report ({waste_type}). Status: Submitted. "
            "You will be notified when it changes.",
            link=f"/complaint/{report_id}",
        )
        con.commit()
    finally:
        con.close()

    audit(
        "complaint.submitted", entity="report", entity_id=report_id,
        detail=f"{tracking_id} | {waste_type} | AI={predicted_category or 'n/a'} "
               f"({category_prediction.get('confidence')})",
        actor_type="citizen" if user_id else "guest", actor_id=user_id,
        actor_label=name, ip=ip,
    )

    # --- best-effort admin e-mail -----------------------------------------
    threading.Thread(
        target=_send_new_report_email,
        args=(report_id, name, mobile, location, waste_type, priority,
              description, image_filename),
        daemon=True,
    ).start()

    effective = effective_urgency(priority, predicted_urgency)
    return {
        "ok": True,
        "report_id": report_id,
        "tracking_id": tracking_id,
        "name": name,
        "ai": {
            "category": category_prediction,
            "urgency": urgency_prediction,
            "effective_urgency": effective,
            "recommended_action": recommend_action(predicted_category or waste_type, effective),
        },
        "duplicates": duplicates,
        "needs_review": needs_review,
    }


def _send_new_report_email(report_id, name, mobile, location, waste_type,
                           priority, description, image_filename):
    try:
        from modules.complaints.email_service import send_report_email
        send_report_email(report_id, name, mobile, location, waste_type,
                          priority, description, image_filename)
    except Exception:
        logger.exception("Report #%s notification email failed", report_id)


# ---------------------------------------------------------------------------
# Status transitions (administrators)
# ---------------------------------------------------------------------------
def update_status(report_id, new_status, remark="", actor_label="administrator",
                  resolution_image=None, ip=None):
    from config import COMPLAINT_STATUSES

    if new_status not in COMPLAINT_STATUSES:
        return {"ok": False, "error": "Unknown status."}

    con = get_connection()
    try:
        row = con.execute("SELECT * FROM reports WHERE id=?", (report_id,)).fetchone()
        if row is None:
            return {"ok": False, "error": "Complaint not found."}
        old_status = row["status"]
        now = utc_now()
        fields = ["status=?", "updated_at=?"]
        params = [new_status, now]
        if remark:
            fields.append("admin_remarks=?")
            params.append(remark.strip())
        if new_status == "Resolved":
            fields.append("resolved_at=COALESCE(resolved_at, ?)")
            params.append(now)
        params.append(report_id)
        con.execute(f"UPDATE reports SET {', '.join(fields)} WHERE id=?", params)

        if resolution_image and resolution_image.filename:
            try:
                filename, _ = save_image(resolution_image)
            except ValueError as exc:
                con.rollback()
                return {"ok": False, "error": str(exc)}
            if filename:
                con.execute(
                    "INSERT INTO complaint_images (report_id, filename, kind, caption, created_at) "
                    "VALUES (?, ?, 'resolution', ?, ?)",
                    (report_id, filename, remark.strip() or None, now),
                )

        add_history(
            con, report_id, old_status, new_status,
            remark.strip() or None,
            actor_type="admin", actor_label=actor_label,
        )
        notify_user(
            con, row["user_id"], report_id,
            f"{row['tracking_id'] or 'Complaint'} is now {new_status}",
            f"Status changed from {old_status} to {new_status}."
            + (f" Administrator note: {remark.strip()}" if remark else ""),
            link=f"/complaint/{report_id}",
        )
        con.commit()
    finally:
        con.close()

    audit(
        "complaint.status_changed", entity="report", entity_id=report_id,
        detail=f"{old_status} -> {new_status}"
               + (f" | {remark.strip()}" if remark else ""),
        actor_type="admin", actor_label=actor_label, ip=ip,
    )
    return {"ok": True, "old_status": old_status, "new_status": new_status}


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------
def submit_feedback(report_id, user_id, rating, comment="", ip=None):
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Please choose a rating."}
    if not 1 <= rating <= 5:
        return {"ok": False, "error": "Rating must be between 1 and 5."}
    if len(comment or "") > 1000:
        return {"ok": False, "error": "Comment must be under 1000 characters."}

    con = get_connection()
    try:
        row = con.execute(
            "SELECT status, user_id, tracking_id FROM reports WHERE id=?",
            (report_id,),
        ).fetchone()
        if row is None:
            return {"ok": False, "error": "Complaint not found."}
        if row["status"] != "Resolved":
            return {"ok": False, "error": "Feedback can be given after the complaint is resolved."}
        if user_id and row["user_id"] and row["user_id"] != user_id:
            return {"ok": False, "error": "You can only rate your own complaints."}
        try:
            con.execute(
                "INSERT INTO feedback (report_id, user_id, rating, comment, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (report_id, user_id, rating, (comment or "").strip() or None, utc_now()),
            )
        except Exception:
            con.rollback()
            return {"ok": False, "error": "You have already rated this complaint."}
        con.commit()
    finally:
        con.close()

    audit("complaint.feedback", entity="report", entity_id=report_id,
          detail=f"rating={rating}", actor_type="citizen", actor_id=user_id, ip=ip)
    return {"ok": True}


def unread_notifications(user_id, limit=20):
    con = get_connection()
    try:
        rows = con.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        unread = con.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
            (user_id,),
        ).fetchone()[0]
    finally:
        con.close()
    return {"rows": rows, "unread": unread}


def mark_notifications_read(user_id, notification_id=None):
    con = get_connection()
    try:
        if notification_id:
            con.execute(
                "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
                (notification_id, user_id),
            )
        else:
            con.execute(
                "UPDATE notifications SET is_read=1 WHERE user_id=? AND is_read=0",
                (user_id,),
            )
        con.commit()
    finally:
        con.close()
