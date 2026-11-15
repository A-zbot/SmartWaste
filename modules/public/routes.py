"""Public-facing pages: landing, about, team, contact."""

import re

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import get_connection
from security import audit, rate_limit_hit

bp = Blueprint("public", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _home_stats():
    con = get_connection()
    try:
        row = con.execute(
            "SELECT COUNT(*) AS total, "
            "  SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) AS resolved, "
            "  SUM(CASE WHEN status = 'In Progress' THEN 1 ELSE 0 END) AS progress, "
            "  SUM(CASE WHEN status NOT IN ('Resolved', 'Rejected') THEN 1 ELSE 0 END) AS pending, "
            "  SUM(CASE WHEN ai_needs_review = 1 THEN 1 ELSE 0 END) AS reviewed_by_ai "
            "FROM reports"
        ).fetchone()
        areas = con.execute(
            "SELECT COUNT(DISTINCT area) AS n FROM reports "
            "WHERE area IS NOT NULL AND area != ''"
        ).fetchone()["n"]
    finally:
        con.close()
    return {
        "total": row["total"] or 0,
        "resolved": row["resolved"] or 0,
        "progress": row["progress"] or 0,
        "pending": row["pending"] or 0,
        "areas": areas or 0,
        "needs_review": row["reviewed_by_ai"] or 0,
    }


@bp.route("/")
def home():
    return render_template("index.html", stats=_home_stats())


@bp.route("/about")
def about():
    return render_template("about.html")


@bp.route("/team")
def team():
    return render_template("team.html")


@bp.route("/founder")
def founder_redirect():
    return redirect(url_for("public.team"))


@bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        if rate_limit_hit("contact", request.remote_addr or ""):
            flash("Too many messages from your connection. Please wait a few minutes.", "error")
            return redirect(url_for("public.contact"))
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not all([name, email, subject, message]):
            flash("Please fill all fields.", "error")
            return redirect(url_for("public.contact"))
        if len(name) > 80 or len(email) > 120 or len(subject) > 150 or len(message) > 3000:
            flash("One or more fields are too long.", "error")
            return redirect(url_for("public.contact"))
        if not EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("public.contact"))
        con = get_connection()
        try:
            con.execute(
                "INSERT INTO messages (name, email, subject, message) VALUES (?, ?, ?, ?)",
                (name, email, subject, message),
            )
            con.commit()
        finally:
            con.close()
        audit("contact.message", entity="message", detail=subject[:120],
              actor_type="guest", actor_label=name)
        flash("Your message has been sent successfully.", "success")
        return redirect(url_for("public.contact"))
    return render_template("contact.html")
