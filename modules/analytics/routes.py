"""JSON analytics endpoints used by the admin dashboard (filters -> charts)."""

from flask import Blueprint, jsonify, request

from security import admin_required

from modules.analytics.services import overview

bp = Blueprint("analytics", __name__)


@bp.route("/admin/api/overview")
@admin_required
def api_overview():
    payload = overview(request.args)
    return jsonify({
        "ok": True,
        "kpis": payload["kpis"],
        "charts": payload["charts"],
        "recommendations": payload["recommendations"]["items"],
        "filters": payload["filters"],
    })
