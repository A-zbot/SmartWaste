"""Analytics payload builders shared by the dashboard and its JSON API."""

import logging

from intelligence import _model_store
from intelligence.forecasting import forecast
from intelligence.hotspot_detection import hotspot_stats
from intelligence.recommender import build_recommendations
from modules.admin.services import (
    ai_feedback_stats,
    available_areas,
    chart_series,
    kpis,
    parse_filters,
    recent_duplicate_links,
)

logger = logging.getLogger(__name__)


def overview(args, history_days=90):
    filters = parse_filters(args)
    charts = chart_series(filters, history_days=history_days)
    forecast_block = forecast_summary()
    return {
        "filters": filters,
        "kpis": kpis(filters),
        "charts": charts,
        "recommendations": build_recommendations(),
        "model_status": _model_store.status(),
        "areas": available_areas(),
        "feedback_stats": ai_feedback_stats(),
        "duplicate_links": recent_duplicate_links(filters),
        "forecast_summary": forecast_block,
    }


def forecast_summary(horizon=7):
    """Compact 7-day forecast block for the dashboard (never raises).

    Uses the same memoized ``forecast()`` as the forecast page, so the
    dashboard does not trigger an extra model fit within the TTL window.
    """
    try:
        payload = forecast(horizon=horizon)
    except Exception:  # pragma: no cover - defensive: dashboard must not crash
        logger.exception("Forecast summary failed")
        return {"available": False, "status": "error",
                "message": "Forecasting is temporarily unavailable."}

    block = {
        "available": False,
        "status": payload.get("status"),
        "message": payload.get("message"),
        "generated_at": payload.get("generated_at"),
        "data_note": payload.get("data_note"),
        "metrics": payload.get("metrics"),
        "horizon": horizon,
    }
    fc = payload.get("forecast")
    if fc and fc.get("values"):
        values = [float(v) for v in fc["values"]]
        dates = fc.get("dates") or []
        peak_i = max(range(len(values)), key=lambda i: values[i])
        first, last = values[0], values[-1]
        if first <= 0:
            trend = "rising" if last > first else "flat"
        else:
            delta = (last - first) / first
            trend = "rising" if delta > 0.1 else ("falling" if delta < -0.1 else "flat")
        block.update({
            "available": True,
            "dates": dates,
            "values": values,
            "lower": fc.get("lower"),
            "upper": fc.get("upper"),
            "total": round(sum(values), 1),
            "peak_date": dates[peak_i] if dates else None,
            "peak_value": values[peak_i],
            "first_value": first,
            "last_value": last,
            "trend": trend,
        })
    return block


def forecasting_payload(args=None):
    args = args or {}
    try:
        horizon = max(1, min(int(args.get("horizon", 7)), 30))
    except (TypeError, ValueError):
        horizon = 7
    payload = forecast(horizon=horizon)
    payload["hotspots"] = hotspot_stats()
    return payload
