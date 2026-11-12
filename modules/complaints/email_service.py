"""SMTP notifications (best effort).

Credentials come from the environment only - nothing is hard-coded. If SMTP
is not configured the function simply returns False and the application
continues normally, exactly like SmartWaste 1.x.
"""

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape as html_escape

from config import (
    REPORT_NOTIFY_EMAIL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_USER,
    UPLOAD_FOLDER
)

import os

logger = logging.getLogger(__name__)


def _smtp_ready():
    return bool(SMTP_USER and SMTP_PASSWORD)


def _deliver(msg):
    """Send one prepared message; raises on transport failure (callers wrap)."""
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


def send_report_email(report_id, name, mobile, location, waste_type,
                      priority, description, filename, created_at=None):
    if not _smtp_ready():
        logger.info("SMTP_USER/SMTP_PASSWORD not set - skipping report email.")
        return False
    if not REPORT_NOTIFY_EMAIL:
        return False

    ref = f"SW-{report_id:05d}"
    stamp = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    lines = [
        "A new waste complaint has been submitted on SmartWaste 2.0.",
        "",
        f"Report ID   : #{ref}",
        f"Submitted at: {stamp}",
        f"Name        : {name}",
        f"Mobile      : {mobile}",
        f"Location    : {location}",
        f"Waste type  : {waste_type}",
        f"Priority    : {priority}",
        f"Status      : Submitted",
        f"Image       : {filename or 'not provided'}",
        "",
        "Description:",
        description,
    ]
    text_body = "\n".join(lines)

    html_body = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937">
  <h2 style="margin:0 0 12px">New Waste Complaint <span style="color:#0e7a52">#{ref}</span></h2>
  <table cellpadding="6" style="border-collapse:collapse">
    <tr><td><b>Submitted at</b></td><td>{html_escape(str(stamp))}</td></tr>
    <tr><td><b>Name</b></td><td>{html_escape(str(name))}</td></tr>
    <tr><td><b>Mobile</b></td><td>{html_escape(str(mobile))}</td></tr>
    <tr><td><b>Location</b></td><td>{html_escape(str(location))}</td></tr>
    <tr><td><b>Waste type</b></td><td>{html_escape(str(waste_type))}</td></tr>
    <tr><td><b>Priority</b></td><td>{html_escape(str(priority))}</td></tr>
    <tr><td><b>Status</b></td><td>Submitted</td></tr>
    <tr><td><b>Image</b></td><td>{html_escape(str(filename or 'not provided'))}</td></tr>
  </table>
  <p style="margin:14px 0 4px"><b>Description</b></p>
  <p style="white-space:pre-wrap;margin:0">{html_escape(str(description))}</p>
</div>"""

    msg = MIMEMultipart("mixed")
    msg["Subject"] = f"[SmartWaste] New complaint #{ref} - {priority} priority"
    msg["From"] = SMTP_FROM
    msg["To"] = REPORT_NOTIFY_EMAIL
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    image_path = os.path.join(UPLOAD_FOLDER, filename) if filename else ""
    if image_path and os.path.isfile(image_path):
        with open(image_path, "rb") as fh:
            attachment = MIMEImage(fh.read(), name=filename)
        attachment.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(attachment)

    _deliver(msg)
    logger.info("Report #%s notification emailed to %s", report_id, REPORT_NOTIFY_EMAIL)
    return True


def send_status_email(to_email, report_id, tracking_id, name, old_status,
                      new_status, remark=""):
    """Best-effort citizen notification when an administrator changes status.

    Returns False - never raises - when SMTP is unconfigured or there is no
    recipient: the status change itself must never depend on e-mail delivery.
    """
    if not _smtp_ready():
        logger.info("SMTP_USER/SMTP_PASSWORD not set - skipping status email.")
        return False
    to_email = (to_email or "").replace("\r", "").replace("\n", "").strip()
    if not to_email:
        return False

    ref = tracking_id or f"SW-{report_id:05d}"
    display_name = name or "there"
    note = (remark or "").strip()

    text_body = "\n".join([
        "Hello " + display_name + ",",
        "",
        f"Your SmartWaste complaint {ref} has been updated.",
        "",
        f"Previous status: {old_status}",
        f"Current status : {new_status}",
        f"Updated at     : {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
    ] + ([f"Administrator note: {note}"] if note else []) + [
        "",
        "Sign in to SmartWaste to view the full status timeline.",
    ])

    note_html = (f'<p style="margin:10px 0 0"><b>Administrator note:</b> '
                 f'{html_escape(note)}</p>' if note else "")
    html_body = f"""<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1f2937">
  <h2 style="margin:0 0 10px">Complaint <span style="color:#0e7a52">{html_escape(ref)}</span> updated</h2>
  <p style="margin:0 0 12px">Hello {html_escape(display_name)}, the status of your waste complaint changed:</p>
  <table cellpadding="6" style="border-collapse:collapse">
    <tr><td><b>Previous status</b></td><td>{html_escape(str(old_status))}</td></tr>
    <tr><td><b>Current status</b></td><td><b>{html_escape(str(new_status))}</b></td></tr>
  </table>
  {note_html}
  <p style="color:#6b7280;font-size:12px;margin:14px 0 0">Sign in to SmartWaste to view the full status timeline.</p>
</div>"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[SmartWaste] {ref} is now {new_status}"
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    _deliver(msg)
    logger.info("Status change for #%s emailed to %s", report_id, to_email)
    return True
