"""Citizen authentication, session handling and profile (Module A)."""

import re
import sqlite3

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_connection
from security import (
    active_admin_credentials_configured,
    audit,
    clear_login_failures,
    citizen_required,
    login_blocked,
    record_login_failure,
    verify_admin_credentials,
)

bp = Blueprint("auth", __name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LENGTH = 8


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("admin.dashboard"))
    if session.get("user_id"):
        return redirect(url_for("public.home"))

    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if not identifier or not password:
            flash("Please enter your username and password.", "error")
            return render_template("login.html")

        if login_blocked(identifier):
            flash("Too many failed attempts. Please wait a few minutes and try again.", "error")
            return render_template("login.html"), 429

        # Administrator sign-in (constant-time comparison against env config)
        if verify_admin_credentials(identifier, password):
            session.clear()
            session["admin"] = True
            clear_login_failures(identifier)
            audit("auth.admin_login", detail=f"admin '{identifier}' signed in",
                  actor_type="admin")
            return redirect(url_for("admin.dashboard"))

        con = get_connection()
        try:
            user = con.execute(
                "SELECT * FROM users WHERE email = ?", (identifier.lower(),)
            ).fetchone()
        finally:
            con.close()

        if user and check_password_hash(user["password_hash"], password):
            if not user["is_active"]:
                flash("This account has been disabled. Please contact the administrator.", "error")
                audit("auth.login_blocked", detail=f"disabled account '{identifier}'",
                      actor_type="citizen")
                return render_template("login.html"), 403
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            clear_login_failures(identifier)
            audit("auth.login", actor_type="citizen", actor_id=user["id"],
                  actor_label=user["name"])
            return redirect(url_for("public.home"))

        record_login_failure(identifier)
        audit("auth.login_failed", detail=f"identifier '{identifier[:60]}'",
              actor_type="guest", actor_label=identifier[:60])
        if not active_admin_credentials_configured() and not user:
            flash("Admin sign-in is not configured. Set ADMIN_USERNAME and ADMIN_PASSWORD in your .env file.", "error")
        else:
            flash("Invalid username or password.", "error")

    return render_template("login.html")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("admin"):
        return redirect(url_for("admin.dashboard"))
    if session.get("user_id"):
        return redirect(url_for("public.home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not all([name, email, password, confirm]):
            flash("Please fill all fields.", "error")
            return render_template("signup.html")
        if len(name) < 2 or len(name) > 80:
            flash("Please enter a valid name (2-80 characters).", "error")
            return render_template("signup.html")
        if not EMAIL_RE.match(email):
            flash("Please enter a valid email address.", "error")
            return render_template("signup.html")
        if len(password) < MIN_PASSWORD_LENGTH:
            flash(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
            return render_template("signup.html")
        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("signup.html")

        con = get_connection()
        try:
            cur = con.execute(
                "INSERT INTO users (name, email, password_hash, role, is_active) "
                "VALUES (?, ?, ?, 'citizen', 1)",
                (name, email, generate_password_hash(password)),
            )
            con.commit()
            user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            flash("An account with this email already exists.", "error")
            return render_template("signup.html")
        finally:
            con.close()

        session.clear()
        session["user_id"] = user_id
        session["user_name"] = name
        audit("auth.signup", actor_type="citizen", actor_id=user_id, actor_label=name)
        flash("Your account has been created successfully.", "success")
        return redirect(url_for("public.home"))

    return render_template("signup.html")


@bp.route("/logout")
def logout():
    if session.get("admin"):
        audit("auth.logout", actor_type="admin", detail="administrator signed out")
    elif session.get("user_id"):
        audit("auth.logout", actor_type="citizen", actor_id=session.get("user_id"),
              actor_label=session.get("user_name"))
    session.clear()
    return redirect(url_for("public.home"))


@bp.route("/profile")
@citizen_required
def profile():
    user_id = session["user_id"]
    con = get_connection()
    try:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        stats = con.execute(
            "SELECT COUNT(*) AS total, "
            "  SUM(CASE WHEN status NOT IN ('Resolved','Rejected') THEN 1 ELSE 0 END) AS open, "
            "  SUM(CASE WHEN status = 'Resolved' THEN 1 ELSE 0 END) AS resolved, "
            "  SUM(CASE WHEN ai_needs_review = 1 THEN 1 ELSE 0 END) AS ai_flagged "
            "FROM reports WHERE user_id=?",
            (user_id,),
        ).fetchone()
        notifications = con.execute(
            "SELECT * FROM notifications WHERE user_id=? ORDER BY id DESC LIMIT 6",
            (user_id,),
        ).fetchall()
        unread = con.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
            (user_id,),
        ).fetchone()[0]
        feedback_rows = con.execute(
            "SELECT f.*, r.tracking_id, r.location FROM feedback f "
            "JOIN reports r ON r.id = f.report_id WHERE f.user_id=? ORDER BY f.id DESC",
            (user_id,),
        ).fetchall()
    finally:
        con.close()

    if user is None:
        session.clear()
        flash("Your account no longer exists.", "error")
        return redirect(url_for("auth.login"))

    return render_template(
        "profile.html",
        user=user,
        stats={
            "total": stats["total"] or 0,
            "open": stats["open"] or 0,
            "resolved": stats["resolved"] or 0,
            "ai_flagged": stats["ai_flagged"] or 0,
        },
        notifications=notifications,
        unread=unread,
        feedback_rows=feedback_rows,
    )


@bp.route("/profile/password", methods=["POST"])
@citizen_required
def change_password():
    user_id = session["user_id"]
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")

    if len(new) < MIN_PASSWORD_LENGTH:
        flash(f"New password must be at least {MIN_PASSWORD_LENGTH} characters.", "error")
        return redirect(url_for("auth.profile"))
    if new != confirm:
        flash("New passwords do not match.", "error")
        return redirect(url_for("auth.profile"))

    con = get_connection()
    try:
        user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], current):
            flash("Your current password is incorrect.", "error")
            return redirect(url_for("auth.profile"))
        con.execute(
            "UPDATE users SET password_hash=?, updated_at=datetime('now') WHERE id=?",
            (generate_password_hash(new), user_id),
        )
        con.commit()
    finally:
        con.close()

    audit("auth.password_changed", actor_type="citizen", actor_id=user_id,
          actor_label=session.get("user_name"))
    flash("Your password has been updated.", "success")
    return redirect(url_for("auth.profile"))
