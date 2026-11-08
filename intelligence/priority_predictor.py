"""Urgency (priority) prediction for complaints (Module B).

A separate supervised model estimates how urgent a complaint is from its
text. It runs alongside - never instead of - the citizen's own priority
choice; administrators see both values and any disagreement between them.

``recommend_action`` only maps the *predicted labels* onto dispatch guidance
for the UI; it is presentation logic, not a source of predictions.
"""

from config import MAX_KEYWORDS, ML_CONFIDENCE_THRESHOLD, PRIORITIES
from intelligence import _model_store
from intelligence.preprocessing import extract_keywords

TASK = "urgency"

_ACTION_MATRIX = {
    "Emergency": {
        "Medical Waste": "Immediate dispatch: hazardous waste removal within hours",
        "Drain & Sewer Waste": "Immediate dispatch: drain/overflow response team",
        "Open Garbage": "Immediate dispatch: emergency cleanup and inspection",
        "Construction Debris": "Immediate dispatch: clear blocked passage",
        "default": "Immediate dispatch: emergency response team",
    },
    "High": {
        "Open Garbage": "Prioritize municipal inspection this shift",
        "Drain & Sewer Waste": "Prioritize drain clearance inspection",
        "Food Waste": "Schedule cleanup within 24 hours",
        "Plastic Waste": "Schedule cleanup within 24 hours and check drain flow",
        "Street Sweeping": "Add to priority sweeping route",
        "Construction Debris": "Schedule debris removal within 24 hours",
        "E-Waste": "Arrange safe e-waste pickup within 24 hours",
        "Medical Waste": "Escalate to health & safety desk",
        "default": "Prioritize municipal inspection",
    },
    "Medium": {
        "default": "Assign to the area sanitation team in the next cycle",
    },
    "Low": {
        "default": "Queue for routine area maintenance",
    },
}


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


def predict_urgency(text):
    """Predict urgency for one complaint. JSON-safe dict."""
    text = (text or "").strip()
    pipeline = _model_store.load_pipeline(TASK)
    if not text or pipeline is None:
        return {
            "available": False,
            "reason": "empty_text" if not text else "model_not_trained",
            "urgency": None,
            "confidence": None,
            "probabilities": {},
            "needs_review": True,
            "keywords": [],
            "model_name": None,
        }

    report = _model_store.load_report(TASK) or {}
    try:
        proba_row = pipeline.predict_proba([text])[0]
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "available": False,
            "reason": f"prediction_failed: {exc.__class__.__name__}",
            "urgency": None,
            "confidence": None,
            "probabilities": {},
            "needs_review": True,
            "keywords": [],
            "model_name": None,
        }

    classes = list(getattr(pipeline["clf"], "classes_", []))
    probabilities = {
        str(label): round(float(p), 4) for label, p in zip(classes, proba_row)
    }
    urgency, confidence = max(probabilities.items(), key=lambda kv: kv[1])

    return {
        "available": True,
        "urgency": urgency,
        "confidence": round(float(confidence), 4),
        "probabilities": probabilities,
        "needs_review": float(confidence) < ML_CONFIDENCE_THRESHOLD,
        "keywords": extract_keywords(
            text, pipeline.named_steps.get("tfidf"), top_k=MAX_KEYWORDS
        ),
        "model_name": (report.get("best_model") or {}).get("name"),
        "model_version": report.get("trained_at"),
        "priority_rank": PRIORITIES.index(urgency) if urgency in PRIORITIES else None,
    }


def recommend_action(category, urgency):
    """Dispatch guidance derived from the predicted labels (display only)."""
    table = _ACTION_MATRIX.get(urgency, {})
    return table.get(category) or table.get("default") or \
        _ACTION_MATRIX["Medium"]["default"]


def effective_urgency(citizen_priority, predicted_urgency):
    """The more urgent of the citizen's own choice and the model's output."""
    values = [p for p in (citizen_priority, predicted_urgency) if p in PRIORITIES]
    if not values:
        return citizen_priority if citizen_priority in PRIORITIES else "Medium"
    return max(values, key=PRIORITIES.index)
