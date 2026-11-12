"""Server-side PDF export for complaints (reportlab).

Builds two documents from the same database rows:

* ``audience="admin"`` - full operational report for the municipal console
  (contact details, coordinates, submission source, model internals, audit
  actors in the timeline);
* ``audience="citizen"`` - receipt-style summary of what the citizen already
  sees on their complaint page (mobile masked, no internal audit actors).

Both are rendered in-process with reportlab platypus flowables and returned
as ``bytes``; routes stream them as ``application/pdf`` downloads. Text is
sanitised to CP1252 (the repertoire of the built-in Helvetica fonts) before
it reaches ``Paragraph``, so arbitrary complaint content can never break the
layout or raise during rendering. Documents are built with
``pageCompression=0`` so their content stays greppable for tests.
"""

import io
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

BRAND = "SmartWaste 2.0"
_ACCENT = colors.HexColor("#0e7a52")
_MUTED = colors.HexColor("#6b7280")
_GRID = colors.HexColor("#e5e7eb")
_LABEL_BG = colors.HexColor("#f3f4f6")


def _safe(value):
    """Make *value* safe for a CP1252 reportlab Paragraph (escaped markup)."""
    if value is None:
        return ""
    text = str(value).encode("cp1252", "replace").decode("cp1252")
    return escape(text)


def _mask_mobile(value):
    """Same masking rule as the ``mask_mobile`` template filter."""
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if len(digits) < 4:
        return "*" * len(digits)
    return digits[:2] + "*" * (len(digits) - 4) + digits[-2:]


def _field(row, key, default=None):
    """Dict/Row-safe field access (sqlite3.Row has no ``.get``)."""
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _when(value):
    """Format a stored timestamp for humans (already UTC strings)."""
    if not value:
        return "-"
    return str(value).replace("T", " ")[:16]


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "title", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=16, textColor=_ACCENT, alignment=0, spaceAfter=1,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, textColor=_MUTED, spaceAfter=6,
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=11, textColor=colors.HexColor("#111827"),
            spaceBefore=10, spaceAfter=3,
        ),
        "body": ParagraphStyle(
            "body", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, textColor=colors.HexColor("#1f2937"),
        ),
        "small": ParagraphStyle(
            "small", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=_MUTED,
        ),
        "cell": ParagraphStyle(
            "cell", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=colors.HexColor("#1f2937"),
        ),
        "cell_bold": ParagraphStyle(
            "cell_bold", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=8.5, leading=11, textColor=colors.HexColor("#111827"),
        ),
    }


def _meta_table(rows, styles):
    """Two-column label/value table; empty values are skipped by the caller."""
    data = [
        [Paragraph(_safe(label), styles["cell_bold"]),
         Paragraph(_safe(value), styles["cell"])]
        for label, value in rows if value not in (None, "")
    ]
    table = Table(data, colWidths=[38 * mm, 136 * mm], hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), _LABEL_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _timeline_table(history, styles, include_actor):
    headers = ["When", "From", "To", "Note"]
    if include_actor:
        headers.append("By")
    data = [[Paragraph(f"<b>{h}</b>", styles["cell"]) for h in headers]]
    for entry in history or ():
        cells = [
            _when(_field(entry, "created_at")),
            _field(entry, "old_status") or "-",
            _field(entry, "new_status") or "-",
            _field(entry, "remark") or "-",
        ]
        if include_actor:
            actor = _field(entry, "actor_label") or _field(entry, "actor_type") or "-"
            cells.append(str(actor))
        data.append([Paragraph(_safe(c), styles["cell"]) for c in cells])
    if len(data) == 1:
        data.append([Paragraph("No status changes recorded yet.", styles["cell"])]
                    + [Paragraph("", styles["cell"])] * (len(headers) - 1))
    widths = [30 * mm, 24 * mm, 24 * mm, 66 * mm]
    if include_actor:
        widths.append(30 * mm)
    table = Table(data, colWidths=widths, hAlign="LEFT", repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), _LABEL_BG),
        ("GRID", (0, 0), (-1, -1), 0.4, _GRID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def build_complaint_pdf(report, *, history=(), prediction=None,
                        recommended_action="", audience="admin",
                        generated_at=None):
    """Render one complaint to PDF bytes.

    *audience* selects the document variant; everything shown is a subset of
    what the corresponding web page already displays - the PDF never exposes
    new information.
    """
    if audience not in ("admin", "citizen"):
        raise ValueError(f"unknown audience: {audience!r}")
    is_admin = audience == "admin"
    styles = _styles()
    stamp = generated_at or datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )
    tracking = _field(report, "tracking_id") or f"SW-{int(_field(report, 'id', 0) or 0):05d}"

    story = [
        Paragraph(f"{BRAND} — "
                  f"{'Complaint Report' if is_admin else 'Complaint Receipt'}",
                  styles["title"]),
        Paragraph(f"<b>{_safe(tracking)}</b> · generated {stamp} · "
                  f"{'administrator copy' if is_admin else 'citizen copy'}",
                  styles["subtitle"]),
        HRFlowable(width="100%", thickness=0.8, color=_ACCENT,
                   spaceBefore=0, spaceAfter=6),
    ]

    # --- core complaint --------------------------------------------------
    story.append(Paragraph("Complaint", styles["h2"]))
    meta = [
        ("Tracking ID", tracking),
        ("Status", _field(report, "status")),
        ("Priority", _field(report, "priority")),
        ("Reported category", _field(report, "waste_type")),
        ("AI category", _field(report, "ai_category")),
        ("AI urgency", _field(report, "ai_urgency")),
        ("Verified category (admin)", _field(report, "final_category")),
        ("Verified priority (admin)", _field(report, "final_urgency")),
    ]
    confidence = _field(report, "ai_confidence")
    meta.append(("AI confidence",
                 f"{round(float(confidence) * 100)}%" if confidence is not None else None))
    if is_admin:
        meta.append(("Needs manual AI review",
                     "yes" if _field(report, "ai_needs_review") else "no"))
    meta += [
        ("Submitted", _when(_field(report, "created_at"))),
        ("Last updated", _when(_field(report, "updated_at"))),
        ("Resolved", _when(_field(report, "resolved_at"))),
        ("Location", _field(report, "location")),
        ("Area", _field(report, "area")),
    ]
    if is_admin:
        meta += [
            ("Coordinates",
             f"{_field(report, 'latitude')}, {_field(report, 'longitude')}"
             if _field(report, "latitude") is not None else "not geocoded"),
            ("Submission source", _field(report, "source") or "web"),
            ("Citizen", _field(report, "name")),
            ("Mobile", _field(report, "mobile")),
            ("Submitted image", _field(report, "image") or "none"),
        ]
    else:
        meta += [
            ("Reported by", _field(report, "name")),
            ("Mobile", _mask_mobile(_field(report, "mobile"))),
        ]
    story.append(_meta_table(meta, styles))

    story.append(Paragraph("Description", styles["h2"]))
    story.append(Paragraph(_safe(_field(report, "description") or "-"),
                           styles["body"]))

    if recommended_action:
        story.append(Paragraph("Recommended action", styles["h2"]))
        story.append(Paragraph(_safe(recommended_action), styles["body"]))

    if _field(report, "admin_remarks"):
        story.append(Paragraph(
            "Rejection reason" if _field(report, "status") == "Rejected"
            else "Latest administrator note",
            styles["h2"],
        ))
        story.append(Paragraph(_safe(_field(report, "admin_remarks")),
                               styles["body"]))

    # --- model output ----------------------------------------------------
    story.append(Paragraph("AI assessment", styles["h2"]))
    if _field(report, "ai_needs_review"):
        story.append(Paragraph(
            "Confidence is below the review threshold - an administrator "
            "will verify this classification manually.",
            styles["small"],
        ))
        story.append(Spacer(1, 3))
    ai_rows = [
        ("Model", _field(prediction, "model_name")),
        ("Model version", _field(prediction, "model_version")),
        ("Predicted category", _field(report, "ai_category")),
        ("Predicted urgency", _field(report, "ai_urgency")),
        ("Verified category (admin)", _field(report, "final_category")),
        ("Verified priority (admin)", _field(report, "final_urgency")),
        ("Reviewed by", _field(report, "ai_reviewed_by")),
        ("Reviewed at", _when(_field(report, "ai_reviewed_at"))
         if _field(report, "ai_reviewed_at") else None),
        ("Recorded at", _when(_field(prediction, "created_at"))),
    ]
    if not is_admin:
        ai_rows = [row for row in ai_rows if row[0] != "Model version"]
    story.append(_meta_table(ai_rows, styles))

    # --- history ---------------------------------------------------------
    story.append(Paragraph("Status timeline", styles["h2"]))
    story.append(_timeline_table(history, styles, include_actor=is_admin))

    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Generated by {BRAND} from the live complaint record. "
        "This document mirrors the information available in the application "
        "at generation time.",
        styles["small"],
    ))

    def _footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(_GRID)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 15 * mm, A4[0] - 18 * mm, 15 * mm)
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(_MUTED)
        canvas.drawString(18 * mm, 11 * mm,
                          f"{BRAND} · {tracking} · {audience} copy")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm,
                               f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=20 * mm,
        pageCompression=0,
    )
    document.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return buffer.getvalue()
