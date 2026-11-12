"""Artifact store: loads trained pipelines and their evaluation reports.

Models are trained by ``scripts/train_models.py`` (or automatically on first
start when artifacts are missing) with joblib. This module only ever returns
real artifacts; when nothing has been trained yet it reports that fact so the
UI can say "model not trained" instead of inventing predictions.
"""

import json
import os
import threading

import joblib

from config import MODEL_DIR

_LOCK = threading.Lock()
_CACHE = {}
_REPORT_CACHE = {}  # task -> (mtime, parsed report)

TASKS = ("category", "urgency")


def _pipeline_path(task):
    return os.path.join(MODEL_DIR, f"{task}_pipeline.joblib")


def _report_path(task):
    return os.path.join(MODEL_DIR, f"{task}_report.json")


def meta_path():
    return os.path.join(MODEL_DIR, "training_meta.json")


def is_trained(task):
    return os.path.isfile(_pipeline_path(task)) and os.path.isfile(_report_path(task))


def any_trained():
    return any(is_trained(task) for task in TASKS)


def load_pipeline(task):
    """Return the fitted sklearn Pipeline for *task* (cached) or None."""
    if task not in TASKS:
        raise ValueError(f"unknown task: {task}")
    if not is_trained(task):
        return None
    with _LOCK:
        if task in _CACHE:
            return _CACHE[task]
        try:
            pipeline = joblib.load(_pipeline_path(task))
        except Exception:
            return None
        _CACHE[task] = pipeline
        return pipeline


def load_report(task):
    """Return the parsed evaluation report for *task* (mtime-cached) or None.

    Reports are re-read from disk on every dashboard call otherwise; the
    cache key is the file's mtime, so a retrain is picked up immediately.
    """
    if not is_trained(task):
        return None
    path = _report_path(task)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    with _LOCK:
        hit = _REPORT_CACHE.get(task)
        if hit is not None and hit[0] == mtime:
            return hit[1]
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    with _LOCK:
        _REPORT_CACHE[task] = (mtime, data)
    return data


def load_meta():
    try:
        with open(meta_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def clear_cache():
    with _LOCK:
        _CACHE.clear()
        _REPORT_CACHE.clear()


def status():
    """Structured training status for the admin 'models' page."""
    tasks = {}
    for task in TASKS:
        report = load_report(task)
        tasks[task] = {
            "trained": is_trained(task),
            "trained_at": (report or {}).get("trained_at"),
            "best_model": ((report or {}).get("best_model") or {}).get("name"),
            "n_samples": (report or {}).get("n_samples"),
            "labels": (report or {}).get("labels"),
        }
    return {
        "any_trained": any(t["trained"] for t in tasks.values()),
        "tasks": tasks,
        "meta": load_meta(),
        "model_dir": MODEL_DIR,
    }
