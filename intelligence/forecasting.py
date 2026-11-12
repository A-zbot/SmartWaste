"""Complaint-volume forecasting (Module E).

Methodology (documented so the dashboard can show exactly what was done):

* The observed daily complaint counts are rebuilt from the database with zero
  filling on days without reports.
* A **seasonal-naive baseline** (value of the same weekday one week earlier)
  and a **7-day moving-average baseline** are computed. Both only use past
  observations, so there is no leakage.
* Where at least ``FORECAST_MIN_DAYS_ML`` days of history exist, a
  **Random Forest regressor** with lag / calendar features is trained with a
  chronological split: the last ~20 % of days are the test set and are never
  used for fitting. MAE and RMSE are reported for the ML model *and* both
  baselines on exactly the same test days.
* Future days are forecast recursively from the fitted model. The uncertainty
  band is +/- 1.96 x test RMSE (a normal-approximation interval derived from
  the measured test error - clearly labelled as an estimate, not a calibrated
  prediction interval).
* If history is too short the module returns an honest ``insufficient`` status
  instead of inventing a forecast.
"""

import copy
import math
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from config import (
    FORECAST_HORIZON_DAYS,
    FORECAST_HISTORY_DAYS,
    FORECAST_LAGS,
    FORECAST_MIN_DAYS_BASELINE,
    FORECAST_MIN_DAYS_ML,
    FORECAST_TEST_RATIO,
)
from db import get_connection

RANDOM_STATE = 42


# ---------------------------------------------------------------------------
# Historical series
# ---------------------------------------------------------------------------
def daily_series(days=None, con=None):
    """Zero-filled daily complaint counts over the last *days* days (UTC)."""
    days = days or FORECAST_HISTORY_DAYS
    own = con is None
    if own:
        con = get_connection()
    try:
        rows = con.execute(
            "SELECT date(created_at) AS day, COUNT(*) AS n "
            "FROM reports WHERE created_at >= datetime('now', ?) "
            "GROUP BY day ORDER BY day",
            (f"-{int(days)} days",),
        ).fetchall()
        demo_rows = con.execute(
            "SELECT source, COUNT(*) AS n FROM reports "
            "WHERE created_at >= datetime('now', ?) GROUP BY source",
            (f"-{int(days)} days",),
        ).fetchall()
    finally:
        if own:
            con.close()

    counts = {row["day"]: int(row["n"]) for row in rows}
    source_totals = {row["source"]: int(row["n"]) for row in demo_rows}
    total = sum(source_totals.values())
    demo = source_totals.get("demo", 0)

    start = date.today() - timedelta(days=int(days) - 1)
    dates, values = [], []
    current = start
    while current <= date.today():
        key = current.isoformat()
        dates.append(key)
        values.append(counts.get(key, 0))
        current += timedelta(days=1)

    return {
        "dates": dates,
        "counts": values,
        "total": total,
        "demo_rows": demo,
        "live_rows": total - demo,
        "demo_share": round(demo / total, 4) if total else 0.0,
        "window_days": int(days),
        "observed_days": len(dates),
        "days_with_reports": sum(1 for v in values if v > 0),
    }


def aggregate(dates, counts, period="week"):
    """Roll daily series into ISO weeks or calendar months."""
    buckets = defaultdict(int)
    labels = {}
    for key, value in zip(dates, counts):
        day = date.fromisoformat(key)
        if period == "week":
            bucket = day - timedelta(days=day.weekday())
            label = bucket.isoformat()
        elif period == "month":
            label = day.strftime("%Y-%m")
        else:
            label = key
        buckets[label] += value
        labels[label] = label
    ordered = sorted(buckets.items())
    return {"labels": [k for k, _ in ordered], "counts": [v for _, v in ordered]}


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def _dow_features(day_iso):
    day = date.fromisoformat(day_iso)
    angle = 2 * math.pi * day.weekday() / 7.0
    return math.sin(angle), math.cos(angle)


def _feature_row(counts, index, dates):
    row = []
    for lag in FORECAST_LAGS:
        row.append(float(counts[index - lag]) if index - lag >= 0 else 0.0)
    window7 = counts[max(0, index - 7):index]
    window14 = counts[max(0, index - 14):index]
    row.append(float(np.mean(window7)) if window7 else 0.0)
    row.append(float(np.mean(window14)) if window14 else 0.0)
    row.append(float(np.max(window7)) if window7 else 0.0)
    sin_dow, cos_dow = _dow_features(dates[index])
    row.append(sin_dow)
    row.append(cos_dow)
    return row


FEATURE_NAMES = (
    [f"lag_{lag}" for lag in FORECAST_LAGS]
    + ["mean_7d", "mean_14d", "max_7d", "dow_sin", "dow_cos"]
)


def _build_supervised(dates, counts, start_index):
    x, y, indices = [], [], []
    for t in range(start_index, len(counts)):
        x.append(_feature_row(counts, t, dates))
        y.append(counts[t])
        indices.append(t)
    return x, y, indices


# ---------------------------------------------------------------------------
# Forecasting
# ---------------------------------------------------------------------------
def _baseline_predictions(counts, indices):
    seasonal, moving = {}, {}
    for t in indices:
        if t >= 7:
            seasonal[t] = counts[t - 7]          # same weekday, previous week
        if t >= 7:
            moving[t] = float(np.mean(counts[t - 7:t]))
    return seasonal, moving


def _scores(y_true, y_pred):
    if not y_true:
        return None
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(math.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "n_test_days": len(y_true),
    }


def _seasonal_baseline_forecast(dates, counts, horizon):
    """Seasonal-naive (t-7) projection of the last observed week."""
    n = len(counts)
    base_date = date.fromisoformat(dates[-1])
    future_dates, future_values = [], []
    for step in range(1, horizon + 1):
        day = base_date + timedelta(days=step)
        future_dates.append(day.isoformat())
        future_values.append(counts[n - 7 + ((step - 1) % 7)] if n >= 7 else 0)
    return {
        "dates": future_dates,
        "values": future_values,
        "lower": [],
        "upper": [],
        "interval_note": "seasonal-naive baseline only - no uncertainty band "
                         "without a measured test error for this model",
    }


# The Random Forest refit on every page load is the dominant cost of this
# module. Payloads are memoized for a short TTL, keyed by everything that can
# change the answer (horizon, window, row count, day count, last day).
FORECAST_CACHE_TTL = 120.0  # seconds

_FORECAST_CACHE = {}
_FORECAST_CACHE_LOCK = threading.Lock()


def forecast(horizon=None, days=None):
    """Full forecasting payload for the analytics page (JSON-safe).

    Memoized for ``FORECAST_CACHE_TTL`` seconds; callers always receive a
    private copy so mutations cannot leak into the cache.
    """
    horizon = int(horizon or FORECAST_HORIZON_DAYS)
    series = daily_series(days=days)
    signature = (
        horizon,
        days,
        series["total"],
        len(series["counts"]),
        series["dates"][-1] if series["dates"] else "",
    )
    now = time.monotonic()
    with _FORECAST_CACHE_LOCK:
        hit = _FORECAST_CACHE.get(signature)
    if hit is not None and now - hit[0] <= FORECAST_CACHE_TTL:
        return copy.deepcopy(hit[1])

    payload = _forecast_from_series(horizon, series)
    with _FORECAST_CACHE_LOCK:
        if len(_FORECAST_CACHE) >= 8:
            _FORECAST_CACHE.clear()
        _FORECAST_CACHE[signature] = (now, payload)
    return copy.deepcopy(payload)


def clear_forecast_cache():
    with _FORECAST_CACHE_LOCK:
        _FORECAST_CACHE.clear()


def _forecast_from_series(horizon, series):
    """Build the full payload from an already-fetched daily series."""
    dates, counts = series["dates"], series["counts"]
    n = len(counts)

    payload = {
        "history": {
            "dates": dates,
            "counts": counts,
            "total": series["total"],
            "days_with_reports": series["days_with_reports"],
            "window_days": series["window_days"],
            "demo_rows": series["demo_rows"],
            "live_rows": series["live_rows"],
            "demo_share": series["demo_share"],
        },
        "weekly": aggregate(dates, counts, "week"),
        "monthly": aggregate(dates, counts, "month"),
        "status": "insufficient",
        "message": "",
        "required_days": FORECAST_MIN_DAYS_BASELINE,
        "available_days": n,
        "metrics": None,
        "forecast": None,
        "models": [],
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "methodology": {
            "baseline": "seasonal naive (same weekday, t-7) and 7-day moving average",
            "ml_model": "RandomForestRegressor on lag/rolling/calendar features",
            "split": "chronological - last ~20% of days held out for testing",
            "uncertainty": "+/- 1.96 x test RMSE (normal approximation of the "
                           "measured test error)",
        },
    }

    if n < FORECAST_MIN_DAYS_BASELINE:
        payload["message"] = (
            f"Not enough history to forecast: {n} day(s) of complaint data "
            f"available, at least {FORECAST_MIN_DAYS_BASELINE} required. "
            "Collect more complaints and try again - no forecast is generated "
            "rather than showing a fabricated one."
        )
        return payload

    # ---- chronological test split -------------------------------------
    test_size = max(3, int(math.ceil(n * FORECAST_TEST_RATIO)))
    split_index = n - test_size
    min_index = max(7, FORECAST_LAGS[0])
    if split_index <= min_index:
        split_index = min_index + 1
        test_size = n - split_index
    test_indices = list(range(split_index, n))
    seasonal_all, moving_all = _baseline_predictions(counts, test_indices)
    # Keep only days both baselines can score (t >= 7) - never substitute an
    # actual observation as if it were a prediction.
    test_indices = [t for t in test_indices if t in seasonal_all and t in moving_all]
    y_true = [counts[t] for t in test_indices]
    seasonal_pred = [seasonal_all[t] for t in test_indices]
    moving_pred = [moving_all[t] for t in test_indices]

    models = [
        {
            "name": "Seasonal naive baseline (t-7)",
            "kind": "baseline",
            "metrics": _scores(y_true, seasonal_pred),
            "test_days": [dates[t] for t in test_indices],
            "predictions": seasonal_pred,
        },
        {
            "name": "7-day moving average baseline",
            "kind": "baseline",
            "metrics": _scores(y_true, moving_pred),
            "test_days": [dates[t] for t in test_indices],
            "predictions": moving_pred,
        },
    ]

    ml_block = None
    if n >= FORECAST_MIN_DAYS_ML:
        start_index = max(FORECAST_LAGS[-1], 7)
        if split_index <= start_index:
            split_index = start_index
            test_indices = list(range(split_index, n))
            y_true = [counts[t] for t in test_indices]
            seasonal_all, moving_all = _baseline_predictions(counts, test_indices)
            for model in models:
                preds = (
                    [seasonal_all.get(t, counts[t]) for t in test_indices]
                    if model["kind"] == "baseline" and "Seasonal" in model["name"]
                    else [moving_all.get(t, counts[t]) for t in test_indices]
                )
                model["test_days"] = [dates[t] for t in test_indices]
                model["predictions"] = preds
                model["metrics"] = _scores(y_true, preds)

        x_all, y_all, indices = _build_supervised(dates, counts, start_index)
        train_rows = [i for i, t in enumerate(indices) if t < split_index]
        test_rows = [i for i, t in enumerate(indices) if t >= split_index]
        min_train_rows = 10
        if len(train_rows) >= min_train_rows and test_rows:
            x_train = [x_all[i] for i in train_rows]
            y_train = [y_all[i] for i in train_rows]
            x_test = [x_all[i] for i in test_rows]
            y_test = [y_all[i] for i in test_rows]

            model = RandomForestRegressor(
                n_estimators=300, min_samples_leaf=2,
                random_state=RANDOM_STATE, n_jobs=-1,
            )
            model.fit(x_train, y_train)
            preds = [max(0.0, float(v)) for v in model.predict(x_test)]
            rmse = math.sqrt(mean_squared_error(y_test, preds))
            ml_block = {
                "name": "Random Forest regressor (lags + calendar)",
                "kind": "ml",
                "metrics": _scores(y_test, preds),
                "test_days": [dates[indices[i]] for i in test_rows],
                "predictions": [round(p, 2) for p in preds],
                "test_rmse": round(rmse, 4),
                "n_train_days": len(train_rows),
                "feature_importance": [
                    {"feature": name, "importance": round(float(imp), 4)}
                    for name, imp in sorted(
                        zip(FEATURE_NAMES, model.feature_importances_),
                        key=lambda kv: -kv[1],
                    )[:10]
                ],
            }
            models.append(ml_block)

            # recursive multi-step forecast from the fitted model
            working = list(counts)
            working_dates = list(dates)
            forecast_dates, forecast_values, lower, upper = [], [], [], []
            base_date = date.fromisoformat(dates[-1])
            for step in range(1, horizon + 1):
                day = base_date + timedelta(days=step)
                day_iso = day.isoformat()
                working_dates.append(day_iso)
                row = _feature_row(working, len(working), working_dates)
                value = max(0.0, float(model.predict([row])[0]))
                forecast_dates.append(day_iso)
                forecast_values.append(round(value, 2))
                band = 1.96 * rmse
                lower.append(round(max(0.0, value - band), 2))
                upper.append(round(value + band, 2))
                working.append(value)

            payload["forecast"] = {
                "dates": forecast_dates,
                "values": forecast_values,
                "lower": lower,
                "upper": upper,
                "interval_note": "+/- 1.96 x test RMSE "
                                 f"({rmse}) - normal approximation",
            }
            payload["status"] = "ok"
            payload["message"] = (
                f"Baseline and ML forecast computed on {n} days of history "
                f"({len(y_test)} held-out test days, chronological split)."
            )
        else:
            payload["status"] = "baseline_only"
            payload["message"] = (
                f"{n} days of history available: enough for baseline "
                "forecasts but not for a chronological Random Forest "
                f"train/test split (needs {FORECAST_MIN_DAYS_ML}+ days of "
                "feature-eligible history plus held-out test days)."
            )
            payload["forecast"] = _seasonal_baseline_forecast(dates, counts, horizon)
    else:
        payload["status"] = "baseline_only"
        payload["message"] = (
            f"{n} days of history available: enough for baseline forecasts "
            f"but below the {FORECAST_MIN_DAYS_ML}-day minimum required for "
            "the Random Forest model."
        )
        payload["forecast"] = _seasonal_baseline_forecast(dates, counts, horizon)

    payload["metrics"] = {
        model["name"]: model["metrics"] for model in models if model.get("metrics")
    }
    payload["models"] = models
    if series["demo_rows"]:
        payload["data_note"] = (
            f"{series['demo_rows']} of {series['total']} records in this window "
            "are demo-seed rows (source='demo'); forecasts describe the "
            "database contents, not verified field observations."
        )
    return payload
