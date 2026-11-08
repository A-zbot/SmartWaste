"""SMTP notifications (best effort).

Credentials come from the environment only - nothing is hard-coded. If SMTP
is not configured the function simply returns False and the application
continues normally, exactly like SmartWaste 1.x.
"""

import logging
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

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


def send_report_email(report_id, name, mobile, location, waste_type,
                      priority, description, filename, created_at=None):
    from datetime import datetime

    if not (SMTP_USER and SMTP_PASSWORD):
        logger.info("SMTP_USER/SMTP_PASSWORD not set - skipping report email.")
        return False
    if not REPORT_NOTIFY_EMAIL:
        return False

    ref = f"SW-{report_id:05d}"
    stamp = created_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

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
    <tr><td><b>Submitted at</b></td><td>{stamp}</td></tr>
    <tr><td><b>Name</b></td><td>{name}</td></tr>
    <tr><td><b>Mobile</b></td><td>{mobile}</td></tr>
    <tr><td><b>Location</b></td><td>{location}</td></tr>
    <tr><td><b>Waste type</b></td><td>{waste_type}</td></tr>
    <tr><td><b>Priority</b></td><td>{priority}</td></tr>
    <tr><td><b>Status</b></td><td>Submitted</td></tr>
    <tr><td><b>Image</b></td><td>{filename or 'not provided'}</td></tr>
  </table>
  <p style="margin:14px 0 4px"><b>Description</b></p>
  <p style="white-space:pre-wrap;margin:0">{description}</p>
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
