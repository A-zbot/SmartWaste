from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, uuid
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

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
    con.commit()
    con.close()

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

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
        con.commit()
        con.close()

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

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        admin_username = os.environ.get("ADMIN_USERNAME", "admin")
        admin_password = os.environ.get("ADMIN_PASSWORD", "admin123")
        if username == admin_username and password == admin_password:
            session["admin"] = True
            return redirect(url_for("admin"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect(url_for("home"))

@app.route("/admin")
def admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

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
def update_status(report_id, status):
    if not session.get("admin"):
        return redirect(url_for("login"))
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
