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
    if not is_trained(task):
        return None
    try:
        with open(_report_path(task), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def load_meta():
    try:
        with open(meta_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def clear_cache():
    with _LOCK:
        _CACHE.clear()


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
