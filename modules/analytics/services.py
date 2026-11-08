"""Analytics payload builders shared by the dashboard and its JSON API."""

from intelligence import _model_store
from intelligence.forecasting import forecast
from intelligence.hotspot_detection import hotspot_stats
from intelligence.recommender import build_recommendations
from modules.admin.services import available_areas, chart_series, kpis, parse_filters


def overview(args, history_days=90):
    filters = parse_filters(args)
    charts = chart_series(filters, history_days=history_days)
    return {
        "filters": filters,
        "kpis": kpis(filters),
        "charts": charts,
        "recommendations": build_recommendations(),
        "model_status": _model_store.status(),
        "areas": available_areas(),
    }


def forecasting_payload(args=None):
    args = args or {}
    try:
        horizon = max(1, min(int(args.get("horizon", 7)), 30))
    except (TypeError, ValueError):
        horizon = 7
    payload = forecast(horizon=horizon)
    payload["hotspots"] = hotspot_stats()
    return payload
