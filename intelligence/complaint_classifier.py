"""AI-powered complaint categorisation (Module B).

Loads the TF-IDF + classifier pipeline trained by ``intelligence.
model_training`` and turns complaint text into:

* a predicted waste category,
* the model's actual probability (confidence) for that class,
* the full probability distribution over the taxonomy,
* TF-IDF keywords that drive the decision,
* a review flag when confidence is too low for automatic handling.

If no model has been trained the function returns ``available=False`` - it
never invents a prediction.
"""

from config import MAX_KEYWORDS, ML_CONFIDENCE_THRESHOLD, ML_LOW_CONFIDENCE
from intelligence import _model_store
from intelligence.preprocessing import extract_keywords

TASK = "category"


def is_trained():
    return _model_store.is_trained(TASK)


def model_info():
    report = _model_store.load_report(TASK) or {}
    best = report.get("best_model") or {}
    return {
        "trained": _model_store.is_trained(TASK),
        "model_name": best.get("name"),
        "trained_at": report.get("trained_at"),
        "n_samples": report.get("n_samples"),
        "test_f1_macro": (report.get("test_metrics") or {}).get("f1_macro"),
        "labels": report.get("labels"),
        "confidence_threshold": ML_CONFIDENCE_THRESHOLD,
    }


def _unavailable(reason):
    return {
        "available": False,
        "reason": reason,
        "category": None,
        "confidence": None,
        "probabilities": {},
        "needs_review": True,
        "low_confidence": True,
        "keywords": [],
        "model_name": None,
    }


def classify(text):
    """Classify one complaint description. Returns a JSON-safe dict."""
    text = (text or "").strip()
    if not text:
        return _unavailable("empty_text")

    pipeline = _model_store.load_pipeline(TASK)
    if pipeline is None:
        return _unavailable("model_not_trained")

    report = _model_store.load_report(TASK) or {}
    best = (report.get("best_model") or {}).get("name")
    labels = list(report.get("labels") or getattr(pipeline["clf"], "classes_", []))

    try:
        proba_row = pipeline.predict_proba([text])[0]
    except Exception as exc:  # pragma: no cover - defensive
        return _unavailable(f"prediction_failed: {exc.__class__.__name__}")

    classes = list(getattr(pipeline["clf"], "classes_", labels))
    probabilities = {
        str(label): round(float(p), 4) for label, p in zip(classes, proba_row)
    }
    best_label, best_p = max(probabilities.items(), key=lambda kv: kv[1])

    confidence = float(best_p)
    vectorizer = pipeline.named_steps.get("tfidf")

    return {
        "available": True,
        "category": best_label,
        "confidence": round(confidence, 4),
        "probabilities": probabilities,
        "needs_review": confidence < ML_CONFIDENCE_THRESHOLD,
        "low_confidence": confidence < ML_LOW_CONFIDENCE,
        "keywords": extract_keywords(text, vectorizer, top_k=MAX_KEYWORDS),
        "model_name": best,
        "model_version": report.get("trained_at"),
        "threshold": ML_CONFIDENCE_THRESHOLD,
    }
