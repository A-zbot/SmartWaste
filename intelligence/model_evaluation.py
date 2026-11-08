"""Model evaluation reporting (Module B).

Everything here is read from the JSON reports written by
``intelligence.model_training`` during an actual training run - the admin
dashboard never displays metrics that were not measured.
"""

from intelligence import _model_store


def evaluation_available():
    return any(_model_store.is_trained(task) for task in _model_store.TASKS)


def task_report(task):
    return _model_store.load_report(task)


def model_comparison():
    """Rows comparing every candidate model that was actually cross-validated."""
    rows = []
    for task in _model_store.TASKS:
        report = task_report(task)
        if not report:
            continue
        best = (report.get("best_model") or {}).get("name")
        for entry in report.get("models", []):
            metrics = entry.get("test_metrics", {})
            rows.append({
                "task": task,
                "model": entry["name"],
                "cv_f1_macro_mean": entry.get("cv_f1_macro_mean"),
                "cv_f1_macro_std": entry.get("cv_f1_macro_std"),
                "test_accuracy": metrics.get("accuracy"),
                "test_f1_macro": metrics.get("f1_macro"),
                "test_precision_macro": metrics.get("precision_macro"),
                "test_recall_macro": metrics.get("recall_macro"),
                "fit_seconds": entry.get("fit_seconds"),
                "selected": entry["name"] == best,
            })
    return rows


def classification_metrics(task):
    """Per-class precision/recall/F1 for the test partition."""
    report = task_report(task)
    if not report:
        return None
    return {
        "task": task,
        "labels": report.get("labels"),
        "per_class": report.get("test_classification_report"),
        "test_metrics": report.get("test_metrics"),
        "best_model": (report.get("best_model") or {}).get("name"),
        "split": report.get("split"),
        "label_distribution": report.get("label_distribution"),
    }


def confusion_matrix(task, partition="test"):
    report = task_report(task)
    if not report:
        return None
    if partition == "holdout":
        holdout = report.get("holdout") or {}
        matrix = holdout.get("confusion_matrix")
        labels = report.get("labels")
        if matrix is None:
            return None
        return {"labels": labels, "matrix": matrix, "rows": holdout.get("rows"),
                "partition": "holdout"}
    matrix = report.get("test_confusion_matrix")
    if matrix is None:
        return None
    return {
        "labels": report.get("labels"),
        "matrix": matrix,
        "rows": (report.get("split") or {}).get("n_test"),
        "partition": "test",
    }


def holdout_summary(task):
    report = task_report(task)
    if not report:
        return None
    holdout = report.get("holdout")
    if not holdout:
        return None
    return {
        "task": task,
        "rows": holdout.get("rows"),
        "metrics": holdout.get("metrics"),
        "note": holdout.get("note"),
    }


def dataset_summary():
    meta = _model_store.load_meta() or {}
    return {
        "datasets": meta.get("datasets", {}),
        "trained_at": meta.get("trained_at"),
        "library_versions": meta.get("library_versions", {}),
    }


def full_summary():
    return {
        "available": evaluation_available(),
        "status": _model_store.status(),
        "comparison": model_comparison(),
        "metrics": {task: classification_metrics(task) for task in _model_store.TASKS},
        "confusion": {
            task: {
                partition: confusion_matrix(task, partition)
                for partition in ("test", "holdout")
            }
            for task in _model_store.TASKS
        },
        "holdout": {task: holdout_summary(task) for task in _model_store.TASKS},
        "dataset": dataset_summary(),
        "disclaimer": (
            "Metrics are measured on synthetic labelled data (see data/README.md). "
            "They demonstrate the training/evaluation pipeline; performance on "
            "real citizen complaints will differ."
        ),
    }
