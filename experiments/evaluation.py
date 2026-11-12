"""Experimental evaluation for the SmartWaste 2.0 research section.

Runs every evaluation the MCA report quotes and writes the numbers it
actually measured - nothing in this file invents a metric.

Outputs:
    models/duplicate_report.json   precision/recall/F1 for Module C
    experiments/RESULTS.md         human-readable summary of all modules

Usage:
    python experiments/evaluation.py

Modules covered:
    B  classification      - measured metrics read from models/*_report.json
                             (produced by scripts/train_models.py)
    C  duplicate detection  - scored against data/duplicate_pairs.csv
    D  hotspot detection    - DBSCAN silhouette on the live database
    E  forecasting          - MAE/RMSE from the chronological backtest
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)

DATA_DIR = os.path.join(REPO_ROOT, "data")
MODELS_DIR = os.path.join(REPO_ROOT, "models")
EXPERIMENTS_DIR = os.path.join(REPO_ROOT, "experiments")

PAIRS_CSV = os.path.join(DATA_DIR, "duplicate_pairs.csv")
DUPLICATE_REPORT = os.path.join(MODELS_DIR, "duplicate_report.json")
RESULTS_MD = os.path.join(EXPERIMENTS_DIR, "RESULTS.md")

TEXT_GATE_SWEEP = [0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60]


# ---------------------------------------------------------------------------
# Metric helpers
# ---------------------------------------------------------------------------
def precision_recall_f1(y_true, y_pred):
    tp = sum(1 for t, p in zip(y_true, y_pred) if t and p)
    fp = sum(1 for t, p in zip(y_true, y_pred) if not t and p)
    fn = sum(1 for t, p in zip(y_true, y_pred) if t and not p)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)
          if (precision + recall) else 0.0)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": tp, "fp": fp, "fn": fn,
        "support_positives": sum(1 for t in y_true if t),
        "support_negatives": sum(1 for t in y_true if not t),
    }


def _load_json(path):
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# Module B - classification (read the measured training reports)
# ---------------------------------------------------------------------------
def classification_summary():
    summary = {}
    for task in ("category", "urgency"):
        report = _load_json(os.path.join(MODELS_DIR, f"{task}_report.json"))
        if not report:
            summary[task] = {"available": False}
            continue
        best = report.get("best_model") or {}
        summary[task] = {
            "available": True,
            "algorithm": best.get("name"),
            "selection_rule": "highest 5-fold CV F1-macro on the training split",
            "cv_f1_macro": best.get("cv_f1_macro_mean"),
            "cv_f1_std": best.get("cv_f1_macro_std"),
            "test_metrics": report.get("test_metrics"),
            "holdout": {
                "rows": (report.get("holdout") or {}).get("rows"),
                "metrics": (report.get("holdout") or {}).get("metrics"),
            },
            "candidates": [
                {
                    "name": c.get("name"),
                    "cv_f1_macro": c.get("cv_f1_macro_mean"),
                    "test_f1_macro": (c.get("test_metrics") or {}).get("f1_macro"),
                }
                # The training report stores per-model entries under "models"
                # (intelligence/model_training.py); "candidates" was never
                # written, so this table used to render empty.
                for c in report.get("models", [])
            ],
            "confusion_matrix_test": report.get("test_confusion_matrix"),
            "confusion_matrix_holdout": (report.get("holdout") or {}).get("confusion_matrix"),
            "data_note": report.get("data_note") or report.get("notes"),
        }
    return summary


# ---------------------------------------------------------------------------
# Module C - duplicate detection on the labelled pair set
# ---------------------------------------------------------------------------
def duplicate_summary():
    if not os.path.isfile(PAIRS_CSV):
        return {"available": False, "reason": f"{PAIRS_CSV} not found - "
                                              "run scripts/build_duplicate_pairs.py"}

    from config import DUPLICATE_SIMILARITY_THRESHOLD
    from intelligence.duplicate_detection import pair_similarity, score_duplicate
    from intelligence.geospatial_analysis import haversine_km

    with open(PAIRS_CSV, encoding="utf-8", newline="") as fh:
        pairs = list(csv.DictReader(fh))

    records = []
    for row in pairs:
        similarity = pair_similarity(row["text_a"], row["text_b"])
        distance = haversine_km(
            float(row["lat_a"]), float(row["lon_a"]),
            float(row["lat_b"]), float(row["lon_b"]),
        )
        same_category = row["category_a"] == row["category_b"]
        verdict = score_duplicate(similarity, distance, same_category)
        records.append({
            "label": int(row["label"]),
            "similarity": similarity,
            "distance_km": distance,
            "text_gate": similarity >= DUPLICATE_SIMILARITY_THRESHOLD,
            "predicted_likely": bool(verdict and verdict["is_likely"]),
            "construction": row["construction"],
        })

    y_true = [r["label"] for r in records]
    text_preds = [1 if r["text_gate"] else 0 for r in records]
    combined_preds = [1 if r["predicted_likely"] else 0 for r in records]

    sweep = []
    for threshold in TEXT_GATE_SWEEP:
        preds = [1 if r["similarity"] >= threshold else 0 for r in records]
        sweep.append({"threshold": threshold,
                      **precision_recall_f1(y_true, preds)})

    by_construction = {}
    for record in records:
        group = record["construction"].split("/")[0]
        bucket = by_construction.setdefault(group, {"labels": [], "text_gate": [],
                                                    "predicted_likely": []})
        bucket["labels"].append(record["label"])
        bucket["text_gate"].append(1 if record["text_gate"] else 0)
        bucket["predicted_likely"].append(1 if record["predicted_likely"] else 0)
    construction_metrics = {
        group: {
            "text_gate": precision_recall_f1(values["labels"], values["text_gate"]),
            "combined": precision_recall_f1(values["labels"], values["predicted_likely"]),
        }
        for group, values in by_construction.items()
    }

    report = {
        "available": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dataset": {
            "path": os.path.relpath(PAIRS_CSV, REPO_ROOT).replace("\\", "/"),
            "pairs": len(records),
            "positives": sum(y_true),
            "negatives": len(y_true) - sum(y_true),
            "provenance": (
                "Synthetic corpus with constructed pair labels and constructed "
                "coordinates - see data/duplicate_pairs.csv `construction` column "
                "and data/ANNOTATION.md. Measures the scoring rule on this "
                "corpus, not real-world accuracy."
            ),
        },
        "method": {
            "text": "TF-IDF (1-2 grams, NLTK preprocessing) + cosine similarity",
            "geographic": "haversine distance, 2.0 km hard gate, neutral 0.4 when unknown",
            "category": "bonus 0.10 when both complaints share a category",
            "weights": {"text": 0.65, "geographic": 0.25, "category": 0.10},
            "text_gate_threshold": DUPLICATE_SIMILARITY_THRESHOLD,
        },
        "text_gate_only": precision_recall_f1(y_true, text_preds),
        "combined_rule": precision_recall_f1(y_true, combined_preds),
        "text_threshold_sweep": sweep,
        "by_construction": construction_metrics,
    }

    os.makedirs(MODELS_DIR, exist_ok=True)
    with open(DUPLICATE_REPORT, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    return report


# ---------------------------------------------------------------------------
# Module D - hotspot cluster quality on the live database
# ---------------------------------------------------------------------------
def hotspot_summary():
    from db import init_db
    from intelligence.hotspot_detection import run_clustering, stored_run_params

    init_db()
    summary = run_clustering(persist=False)
    stored = stored_run_params()
    return {
        "available": True,
        "insufficient": summary.get("insufficient"),
        "n_clusters": summary.get("n_clusters"),
        "clustered_points": summary.get("clustered_points"),
        "noise_points": summary.get("noise_points"),
        "quality": summary.get("quality"),
        "stored_quality": (stored or {}).get("quality"),
        "params": {k: summary.get(k) for k in ("eps_meters", "min_samples", "metric")},
        "notes": summary.get("notes"),
    }


# ---------------------------------------------------------------------------
# Module E - forecasting backtest on the live database
# ---------------------------------------------------------------------------
def forecasting_summary():
    from db import init_db
    from intelligence.forecasting import forecast

    init_db()
    payload = forecast(horizon=7)
    return {
        "available": True,
        "status": payload.get("status"),
        "message": payload.get("message"),
        "history_days": (payload.get("history") or {}).get("window_days"),
        "days_with_reports": (payload.get("history") or {}).get("days_with_reports"),
        "metrics": payload.get("metrics"),
        "data_note": payload.get("data_note"),
    }


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------
def _fmt_metrics(metrics):
    if not metrics:
        return "n/a"
    return (f"MAE {metrics.get('mae')} / RMSE {metrics.get('rmse')} "
            f"over {metrics.get('n_test_days')} test days")


def write_results(classification, duplicates, hotspots, forecasting):
    os.makedirs(EXPERIMENTS_DIR, exist_ok=True)
    lines = [
        "# SmartWaste 2.0 - Experimental Results",
        "",
        f"Generated by `python experiments/evaluation.py` on "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.",
        "",
        "Every number below was measured by that run. Metrics for the",
        "classification models are read from `models/*_report.json`, which is",
        "written by `scripts/train_models.py`; the other sections are computed",
        "live. Nothing here is hand-entered.",
        "",
        "## B. Complaint classification",
        "",
    ]

    for task, block in classification.items():
        lines.append(f"### {task.title()} task")
        lines.append("")
        if not block.get("available"):
            lines.append("Model not trained - run `python scripts/train_models.py`.")
            lines.append("")
            continue
        lines.append(f"- Algorithm: **{block['algorithm']}** ({block['selection_rule']})")
        if block.get("cv_f1_macro") is not None:
            lines.append(f"- 5-fold CV F1-macro: **{block['cv_f1_macro']:.4f}** "
                         f"(± {block.get('cv_f1_std') or 0:.4f})")
        test = block.get("test_metrics") or {}
        if test:
            lines.append(f"- Held-out test split: accuracy **{test.get('accuracy')}**, "
                         f"F1-macro **{test.get('f1_macro')}**, "
                         f"precision-macro {test.get('precision_macro')}, "
                         f"recall-macro {test.get('recall_macro')}")
        holdout = block.get("holdout") or {}
        if holdout.get("metrics"):
            hm = holdout["metrics"]
            lines.append(f"- Independent handwritten holdout ({holdout.get('rows')} rows): "
                         f"accuracy **{hm.get('accuracy')}**, F1-macro **{hm.get('f1_macro')}**")
        if block.get("confusion_matrix_test"):
            lines.append("- Confusion matrices: stored in "
                         "`models/*_report.json` and rendered on `/admin/models`")
        lines.append("")
    lines.append("> **Data caveat:** training data is synthetic "
                 "(`data/README.md`); these scores are pipeline checks, not "
                 "real-world accuracy claims.")
    lines.append("")

    lines += ["## C. Duplicate detection", ""]
    if not duplicates.get("available"):
        lines += [f"Unavailable: {duplicates.get('reason')}", ""]
    else:
        dataset = duplicates["dataset"]
        gate = duplicates["text_gate_only"]
        combined = duplicates["combined_rule"]
        lines += [
            f"- Evaluated on **{dataset['pairs']} labelled pairs** "
            f"({dataset['positives']} duplicate / {dataset['negatives']} not duplicate).",
            f"- {dataset['provenance']}",
            "",
            "| Decision rule | Precision | Recall | F1 | TP | FP | FN |",
            "|---|---|---|---|---|---|---|",
            f"| Text gate (cosine ≥ {duplicates['method']['text_gate_threshold']}) | "
            f"{gate['precision']} | {gate['recall']} | {gate['f1']} | "
            f"{gate['tp']} | {gate['fp']} | {gate['fn']} |",
            f"| Full combined rule (text + geo + category) | "
            f"{combined['precision']} | {combined['recall']} | {combined['f1']} | "
            f"{combined['tp']} | {combined['fp']} | {combined['fn']} |",
            "",
            "### Text-threshold sweep",
            "",
            "| Threshold | Precision | Recall | F1 |",
            "|---|---|---|---|",
        ]
        for row in duplicates["text_threshold_sweep"]:
            lines.append(f"| {row['threshold']} | {row['precision']} | "
                         f"{row['recall']} | {row['f1']} |")
        lines.append("")

    lines += ["## D. Hotspot detection (DBSCAN)", ""]
    if not hotspots.get("available"):
        lines += ["Unavailable.", ""]
    elif hotspots.get("insufficient"):
        lines += ["Not enough geocoded complaints in the database to form "
                  "clusters - no quality score is reported rather than a "
                  "fabricated one.", ""]
    else:
        quality = hotspots.get("quality") or {}
        lines += [
            f"- Parameters: eps **{hotspots['params']['eps_meters']} m**, "
            f"min-samples **{hotspots['params']['min_samples']}**, "
            f"metric **{hotspots['params']['metric']}**",
            f"- Clusters: **{hotspots['n_clusters']}** "
            f"({hotspots['clustered_points']} clustered, "
            f"{hotspots['noise_points']} noise points)",
        ]
        if quality.get("silhouette") is not None:
            lines.append(f"- Silhouette (haversine): **{quality['silhouette']}** "
                         f"over {quality['scored_points']} clustered points "
                         "(1.0 = tight, 0 = overlapping)")
        elif quality:
            lines.append(f"- Silhouette: not computable - {quality.get('reason')}")
        for note in hotspots.get("notes") or []:
            lines.append(f"- Note: {note}")
        lines.append("")

    lines += ["## E. Forecasting", ""]
    if forecasting.get("status") in ("insufficient", "baseline_only"):
        lines += [f"Status: **{forecasting['status']}** - {forecasting.get('message')}", ""]
    else:
        lines += [f"- History window: {forecasting.get('history_days')} days "
                  f"({forecasting.get('days_with_reports')} with reports)", ""]
        if not forecasting.get("days_with_reports"):
            lines += ["> The database contains no complaints yet, so every series "
                      "is all zeros - the backtest measures the harness, not "
                      "forecast skill. Re-run after real reports exist.", ""]
        for name, metrics in (forecasting.get("metrics") or {}).items():
            lines.append(f"- {name}: {_fmt_metrics(metrics)}")
        if forecasting.get("data_note"):
            lines.append(f"- {forecasting['data_note']}")
        lines.append("")
        lines.append("Chronological split - the test window is never used for "
                     "fitting; the uncertainty band is ±1.96 × measured test RMSE.")
        lines.append("")

    with open(RESULTS_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return RESULTS_MD


def main():
    print("Evaluating Module B (classification reports) ...")
    classification = classification_summary()
    print("Evaluating Module C (duplicate pairs) ...")
    duplicates = duplicate_summary()
    print("Evaluating Module D (hotspot clustering) ...")
    hotspots = hotspot_summary()
    print("Evaluating Module E (forecasting backtest) ...")
    forecasting = forecasting_summary()

    path = write_results(classification, duplicates, hotspots, forecasting)
    print(f"\nWrote {DUPLICATE_REPORT}")
    print(f"Wrote {path}")

    gate = duplicates.get("text_gate_only") or {}
    print(f"\nDuplicate text gate: precision {gate.get('precision')} "
          f"recall {gate.get('recall')} f1 {gate.get('f1')}")
    quality = hotspots.get("quality") or {}
    print(f"Cluster silhouette: {quality.get('silhouette') or quality.get('reason')}")
    print(f"Forecast status: {forecasting.get('status')}")


if __name__ == "__main__":
    main()
