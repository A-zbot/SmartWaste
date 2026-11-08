"""Reproducible training pipeline for the SmartWaste complaint models.

Two supervised tasks are trained from the labelled dataset in ``data/``:

* ``category`` - which waste category a complaint describes (8 classes)
* ``urgency``  - how urgent the complaint is (Low/Medium/High/Emergency)

For every task we:

1. validate the labels against the configured taxonomy,
2. make a stratified, seeded train/test split (no leakage between them),
3. cross-validate each candidate model (TF-IDF + estimator) on the training
   partition only,
4. report accuracy / precision / recall / F1-macro plus the confusion matrix
   on the untouched test partition,
5. additionally evaluate the winner on the independent hand-written holdout
   file when it exists,
6. refit the winning pipeline on the full labelled dataset for deployment and
   persist it with joblib together with a JSON report containing only the
   metrics actually measured.

Run with:  python scripts/train_models.py
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import time
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

from config import CATEGORIES, HOLDOUT_DATA, MODEL_DIR, PRIORITIES, TRAINING_DATA
from intelligence.preprocessing import preprocess

RANDOM_STATE = 42
TEST_SIZE = 0.2
CV_FOLDS = 5

TASKS = {
    "category": {"column": "category", "labels": CATEGORIES},
    "urgency": {"column": "urgency", "labels": PRIORITIES},
}


# ---------------------------------------------------------------------------
# Pipeline / candidate definitions
# ---------------------------------------------------------------------------
def build_tfidf():
    return TfidfVectorizer(
        preprocessor=preprocess,
        ngram_range=(1, 2),
        min_df=2,
        max_df=0.95,
        sublinear_tf=True,
        strip_accents="unicode",
        max_features=20000,
    )


def candidate_models():
    """The two families compared for each task (both are justified below).

    Logistic Regression over TF-IDF is the strong linear baseline for text;
    Random Forest captures non-linear feature interactions. The winner is
    chosen empirically by cross-validated F1-macro, not by preference.
    """
    return {
        "Logistic Regression": (
            LogisticRegression(
                max_iter=2000,
                C=3.0,
                class_weight="balanced",
                random_state=RANDOM_STATE,
            ),
            0,  # tie-break preference: lower inference cost
        ),
        "Random Forest": (
            RandomForestClassifier(
                n_estimators=400,
                min_samples_leaf=2,
                class_weight="balanced_subsample",
                random_state=RANDOM_STATE,
                n_jobs=-1,
            ),
            1,
        ),
    }


def build_pipeline(estimator):
    return Pipeline([("tfidf", build_tfidf()), ("clf", estimator)])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_dataset(path, column, labels, name):
    if not os.path.isfile(path):
        return None
    df = pd.read_csv(path)
    required = {"text", column}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"{name} is missing columns: {sorted(missing)}")
    df = df.dropna(subset=["text", column])
    df["text"] = df["text"].astype(str).str.strip()
    df[column] = df[column].astype(str).str.strip()
    df = df[df["text"] != ""]
    unknown = sorted(set(df[column].unique()) - set(labels))
    if unknown:
        raise ValueError(
            f"{name} contains labels outside the configured taxonomy: {unknown}"
        )
    return df.reset_index(drop=True)


def _metrics(y_true, y_pred, labels):
    return {
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "f1_macro": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "precision_macro": round(float(precision_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "recall_macro": round(float(recall_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "per_class_f1": {
            label: round(float(v), 4)
            for label, v in zip(
                labels,
                f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0),
            )
        },
    }


def _report_dict(y_true, y_pred, labels):
    report = classification_report(
        y_true, y_pred, labels=labels, target_names=labels,
        output_dict=True, zero_division=0,
    )
    return {
        label: {
            key: round(float(report[label][key]), 4)
            for key in ("precision", "recall", "f1-score", "support")
        }
        for label in labels
    } | {
        "macro_avg": {
            key: round(float(report["macro avg"][key]), 4)
            for key in ("precision", "recall", "f1-score", "support")
        },
        "weighted_avg": {
            key: round(float(report["weighted avg"][key]), 4)
            for key in ("precision", "recall", "f1-score", "support")
        },
    }


def _matrix(y_true, y_pred, labels):
    return confusion_matrix(y_true, y_pred, labels=labels).tolist()


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train_task(task, df, labels, holdout_df=None, progress=print):
    column = TASKS[task]["column"]
    texts = df["text"].values
    targets = df[column].values

    x_train, x_test, y_train, y_test = train_test_split(
        texts, targets, test_size=TEST_SIZE, random_state=RANDOM_STATE,
        stratify=targets,
    )

    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    candidates = candidate_models()
    results = []
    fitted = {}

    for name, (estimator, tie_break) in candidates.items():
        pipeline = build_pipeline(estimator)
        started = time.time()
        cv_scores = cross_val_score(
            pipeline, x_train, y_train, cv=cv, scoring="f1_macro", n_jobs=1
        )
        pipeline.fit(x_train, y_train)
        y_pred = pipeline.predict(x_test)
        fitted[name] = pipeline
        result = {
            "name": name,
            "tie_break": tie_break,
            "cv_f1_macro_mean": round(float(cv_scores.mean()), 4),
            "cv_f1_macro_std": round(float(cv_scores.std()), 4),
            "test_metrics": _metrics(y_test, y_pred, labels),
            "fit_seconds": round(time.time() - started, 2),
            "parameters": {
                "tfidf": {
                    "ngram_range": [1, 2],
                    "min_df": 2,
                    "max_df": 0.95,
                    "sublinear_tf": True,
                    "max_features": 20000,
                },
                "estimator": {k: v for k, v in estimator.get_params().items()
                              if isinstance(v, (int, float, str, bool, type(None)))}
                              | {"class": estimator.__class__.__name__},
            },
        }
        results.append(result)
        progress(
            f"  {task}/{name}: CV F1-macro={result['cv_f1_macro_mean']:.4f} "
            f"(+/-{result['cv_f1_macro_std']:.4f}) "
            f"test F1-macro={result['test_metrics']['f1_macro']:.4f}"
        )

    # Selection rule: highest CV F1-macro on the training partition; ties go to
    # the cheaper-to-run model. The holdout set is never used for selection -
    # it is scored afterwards purely as an independent diagnostic.
    best = min(results, key=lambda r: (-r["cv_f1_macro_mean"], r["tie_break"]))
    best_name = best["name"]

    holdout_block = None
    if holdout_df is not None and column in holdout_df.columns:
        holdout_df = holdout_df.dropna(subset=["text", column])
        if len(holdout_df) >= 10:
            hx = holdout_df["text"].astype(str).values
            hy = holdout_df[column].astype(str).values
            for result in results:
                preds = fitted[result["name"]].predict(hx)
                result["holdout_metrics"] = _metrics(hy, preds, labels)
            winner_preds = fitted[best_name].predict(hx)
            holdout_block = {
                "rows": int(len(holdout_df)),
                "metrics": _metrics(hy, winner_preds, labels),
                "classification_report": _report_dict(hy, winner_preds, labels),
                "confusion_matrix": _matrix(hy, winner_preds, labels),
                "per_model_f1_macro": {
                    result["name"]: result["holdout_metrics"]["f1_macro"]
                    for result in results
                },
                "note": "Independent hand-written evaluation set (synthetic, "
                        "not produced by the training generator). Not used for "
                        "model selection.",
            }
            progress(
                f"  {task}/holdout({len(holdout_df)}): "
                f"F1-macro={holdout_block['metrics']['f1_macro']:.4f}"
            )

    # Deploy the winner trained on the complete labelled dataset.
    final = clone(fitted[best_name])
    final.fit(texts, targets)

    y_pred = fitted[best_name].predict(x_test)
    report = {
        "task": task,
        "label_column": column,
        "labels": labels,
        "n_samples": int(len(df)),
        "n_labels": int(df[column].nunique()),
        "label_distribution": {
            str(k): int(v) for k, v in df[column].value_counts().items()
        },
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": {
            "test_size": TEST_SIZE,
            "random_state": RANDOM_STATE,
            "stratified": True,
            "n_train": int(len(x_train)),
            "n_test": int(len(x_test)),
        },
        "cross_validation": {"folds": CV_FOLDS, "scoring": "f1_macro"},
        "models": results,
        "best_model": {
            "name": best_name,
            "cv_f1_macro_mean": best["cv_f1_macro_mean"],
            "cv_f1_macro_std": best["cv_f1_macro_std"],
            "test_metrics": best["test_metrics"],
            "selection_rule": "highest mean 5-fold CV F1-macro on the training partition",
        },
        "test_metrics": best["test_metrics"],
        "test_classification_report": _report_dict(y_test, y_pred, labels),
        "test_confusion_matrix": _matrix(y_test, y_pred, labels),
        "holdout": holdout_block,
        "artifact": os.path.basename(_pipeline_path(task)),
        "library_versions": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }
    return final, report


def _pipeline_path(task):
    return os.path.join(MODEL_DIR, f"{task}_pipeline.joblib")


def _report_path(task):
    return os.path.join(MODEL_DIR, f"{task}_report.json")


def train_all(progress=print, dataset_path=None, holdout_path=None):
    dataset_path = dataset_path or TRAINING_DATA
    holdout_path = holdout_path or HOLDOUT_DATA
    os.makedirs(MODEL_DIR, exist_ok=True)

    artifacts = {}
    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "datasets": {},
        "artifacts": [],
        "library_versions": {
            "python": platform.python_version(),
            "scikit-learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
        },
    }

    holdout_base = None
    for task, spec in TASKS.items():
        labels = spec["labels"]
        column = spec["column"]
        df = _load_dataset(dataset_path, column, labels, dataset_path)
        if df is None or len(df) < 50:
            raise RuntimeError(
                f"Training data for '{task}' is missing or too small "
                f"({0 if df is None else len(df)} rows). Expected {dataset_path}."
            )
        holdout = None
        if os.path.isfile(holdout_path):
            if holdout_base is None:
                holdout_base = pd.read_csv(holdout_path)
            holdout = holdout_base
        progress(f"Training {task} model on {len(df)} labelled complaints ...")
        pipeline, report = train_task(task, df, labels, holdout, progress=progress)

        joblib.dump(pipeline, _pipeline_path(task))
        with open(_report_path(task), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        artifacts[task] = report["best_model"]
        meta["datasets"][task] = {
            "path": os.path.relpath(dataset_path),
            "rows": int(len(df)),
            "sha256": _sha256(dataset_path),
        }
        meta["artifacts"].extend([
            os.path.basename(_pipeline_path(task)),
            os.path.basename(_report_path(task)),
        ])
        progress(
            f"  -> best model: {report['best_model']['name']} "
            f"(test F1-macro {report['test_metrics']['f1_macro']})"
        )

    if os.path.isfile(holdout_path):
        meta["datasets"]["holdout"] = {
            "path": os.path.relpath(holdout_path),
            "rows": int(len(pd.read_csv(holdout_path))),
            "sha256": _sha256(holdout_path),
        }

    with open(os.path.join(MODEL_DIR, "training_meta.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)

    from intelligence._model_store import clear_cache
    clear_cache()
    return {"tasks": artifacts, "meta": meta}


if __name__ == "__main__":  # pragma: no cover
    train_all()
