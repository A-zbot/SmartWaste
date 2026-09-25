from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, uuid, hmac, secrets, logging, smtplib, ssl
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app.secret_key = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def db():
    con = sqlite3.connect(os.path.join(BASE_DIR, "waste.db"))
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            mobile TEXT NOT NULL,
            location TEXT NOT NULL,
            waste_type TEXT NOT NULL,
            priority TEXT NOT NULL,
            description TEXT NOT NULL,
            image TEXT,
            status TEXT DEFAULT 'Pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL,
            subject TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.commit()
    con.close()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

REPORT_NOTIFY_EMAIL = os.environ.get("REPORT_NOTIFY_EMAIL", "garvitagarwall.army@gmail.com")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM = os.environ.get("SMTP_FROM") or SMTP_USER

def send_report_email(report_id, name, mobile, location, waste_type,
                      priority, description, filename, created_at=None):
    if not (SMTP_USER and SMTP_PASSWORD):
        logger.info("SMTP_USER/SMTP_PASSWORD not set - skipping report notification email.")
        return False
    if not REPORT_NOTIFY_EMAIL:
        return False

    ref = f"SW-{report_id:05d}"
    stamp = created_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "A new waste report has been submitted on SmartWaste.",
        "",
        f"Report ID   : #{ref}",
        f"Submitted at: {stamp}",
        f"Name        : {name}",
        f"Mobile      : {mobile}",
        f"Location    : {location}",
        f"Waste type  : {waste_type}",
        f"Priority    : {priority}",
        f"Status      : Pending",
        f"Image       : {filename or 'not provided'}",
        "",
        "Description:",
        description,
    ]
    text_body = "\n".join(lines)

    html_body = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937">
  <h2 style="margin:0 0 12px">New Waste Report <span style="color:#16a34a">#{ref}</span></h2>
  <table cellpadding="6" style="border-collapse:collapse">
    <tr><td><b>Submitted at</b></td><td>{stamp}</td></tr>
    <tr><td><b>Name</b></td><td>{name}</td></tr>
    <tr><td><b>Mobile</b></td><td>{mobile}</td></tr>
    <tr><td><b>Location</b></td><td>{location}</td></tr>
    <tr><td><b>Waste type</b></td><td>{waste_type}</td></tr>
    <tr><td><b>Priority</b></td><td>{priority}</td></tr>
    <tr><td><b>Status</b></td><td>Pending</td></tr>
    <tr><td><b>Image</b></td><td>{filename or 'not provided'}</td></tr>
  </table>
  <p style="margin:14px 0 4px"><b>Description</b></p>
  <p style="white-space:pre-wrap;margin:0">{description}</p>
</div>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[SmartWaste] New report #{ref} - {priority} priority"
    msg["From"] = SMTP_FROM
    msg["To"] = REPORT_NOTIFY_EMAIL
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    image_path = os.path.join(app.config["UPLOAD_FOLDER"], filename) if filename else ""
    if image_path and os.path.isfile(image_path):
        with open(image_path, "rb") as fh:
            attachment = MIMEImage(fh.read(), name=filename)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    context = ssl.create_default_context()
    if SMTP_PORT == 465:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15, context=context) as server:
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    else:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls(context=context)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
    logger.info("Report #%s notification emailed to %s", report_id, REPORT_NOTIFY_EMAIL)
    return True

@app.route("/")
def home():
    con = db()
    total = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    resolved = con.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved'").fetchone()[0]
    progress = con.execute("SELECT COUNT(*) FROM reports WHERE status='In Progress'").fetchone()[0]
    pending = con.execute("SELECT COUNT(*) FROM reports WHERE status='Pending'").fetchone()[0]
    con.close()
    return render_template("index.html", total=total, resolved=resolved, progress=progress, pending=pending)

@app.route("/report", methods=["GET", "POST"])
def report():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        location = request.form.get("location", "").strip()
        waste_type = request.form.get("waste_type", "").strip()
        priority = request.form.get("priority", "").strip()
        description = request.form.get("description", "").strip()
        image = request.files.get("image")

        if not all([name, mobile, location, waste_type, priority, description]):
            flash("Please fill all required fields.", "error")
            return redirect(url_for("report"))

        filename = ""
        if image and image.filename:
            if not allowed_file(image.filename):
                flash("Only PNG, JPG, JPEG or WEBP images are allowed.", "error")
                return redirect(url_for("report"))
            ext = secure_filename(image.filename).rsplit(".", 1)[1].lower()
            filename = f"{uuid.uuid4().hex}.{ext}"
            image.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))

        con = db()
        cur = con.execute("""
            INSERT INTO reports
            (name, mobile, location, waste_type, priority, description, image)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (name, mobile, location, waste_type, priority, description, filename))
        report_id = cur.lastrowid
        created_at = con.execute(
            "SELECT created_at FROM reports WHERE id=?", (report_id,)
        ).fetchone()[0]
        con.commit()
        con.close()

        try:
            send_report_email(report_id, name, mobile, location, waste_type,
                              priority, description, filename, created_at)
        except Exception:
            logger.exception("Could not send notification email for report #%s", report_id)

        return render_template("success.html", report_id=report_id, name=name)

    return render_template("report.html")

@app.route("/uploads/<filename>")
def uploaded_file(filename):
    from flask import send_from_directory
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

@app.route("/team")
def team():
    return render_template("team.html")

@app.route("/founder")
def founder_redirect():
    from flask import redirect
    return redirect("/team")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip()
        subject = request.form.get("subject", "").strip()
        message = request.form.get("message", "").strip()
        if not all([name, email, subject, message]):
            flash("Please fill all fields.", "error")
            return redirect(url_for("contact"))
        con = db()
        con.execute(
            "INSERT INTO messages (name,email,subject,message) VALUES (?,?,?,?)",
            (name, email, subject, message)
        )
        con.commit()
        con.close()
        flash("Your message has been sent successfully.", "success")
        return redirect(url_for("contact"))
    return render_template("contact.html")

def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("admin"))
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        identifier = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        admin_username = os.environ.get("ADMIN_USERNAME", "")
        admin_password = os.environ.get("ADMIN_PASSWORD", "")
        if (
            admin_username
            and admin_password
            and hmac.compare_digest(identifier.encode(), admin_username.encode())
            and hmac.compare_digest(password.encode(), admin_password.encode())
        ):
            session.clear()
            session["admin"] = True
            return redirect(url_for("admin"))
        con = db()
        user = con.execute(
            "SELECT * FROM users WHERE email = ?", (identifier.lower(),)
        ).fetchone()
        con.close()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            return redirect(url_for("home"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("admin"):
        return redirect(url_for("admin"))
    if session.get("user_id"):
        return redirect(url_for("home"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")
        if not all([name, email, password, confirm]):
            flash("Please fill all fields.", "error")
            return redirect(url_for("signup"))
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("signup"))
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for("signup"))
        if password != confirm:
            flash("Passwords do not match.", "error")
            return redirect(url_for("signup"))
        con = db()
        try:
            cur = con.execute(
                "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password)),
            )
            con.commit()
            user_id = cur.lastrowid
        except sqlite3.IntegrityError:
            con.close()
            flash("An account with this email already exists.", "error")
            return redirect(url_for("signup"))
        con.close()
        session.clear()
        session["user_id"] = user_id
        session["user_name"] = name
        flash("Your account has been created successfully.", "success")
        return redirect(url_for("home"))
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

@app.route("/admin")
@login_required
def admin():
    con = db()
    reports = con.execute("SELECT * FROM reports ORDER BY id DESC").fetchall()
    total = con.execute("SELECT COUNT(*) FROM reports").fetchone()[0]
    pending = con.execute("SELECT COUNT(*) FROM reports WHERE status='Pending'").fetchone()[0]
    progress = con.execute("SELECT COUNT(*) FROM reports WHERE status='In Progress'").fetchone()[0]
    resolved = con.execute("SELECT COUNT(*) FROM reports WHERE status='Resolved'").fetchone()[0]
    messages = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    con.close()
    return render_template(
        "admin.html",
        reports=reports, total=total, pending=pending,
        progress=progress, resolved=resolved, messages=messages
    )

@app.route("/update_status/<int:report_id>/<status>")
@login_required
def update_status(report_id, status):
    if status not in {"Pending", "In Progress", "Resolved"}:
        return redirect(url_for("admin"))
    con = db()
    con.execute("UPDATE reports SET status=? WHERE id=?", (status, report_id))
    con.commit()
    con.close()
    return redirect(url_for("admin"))

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
