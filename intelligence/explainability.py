"""Explainable AI helpers (Module F).

Explanations are derived from the trained model itself:

* linear models (Logistic Regression)  -> signed feature coefficients
  multiplied by the document's TF-IDF weight;
* tree ensembles (Random Forest)       -> impurity-based feature importance
  scaled by the document's TF-IDF weight (documented as such - it is not a
  Shapley attribution).

Contextual factors (time since submission, nearby similar complaints,
hotspot membership) are computed from the database, not from the model, and
are labelled separately in the payload.
"""

import numpy as np

from intelligence import _model_store
from intelligence.preprocessing import preprocess

METHODS = {
    "linear": "logistic_regression_coefficient_x_tfidf_weight",
    "forest": "random_forest_importance_x_tfidf_weight",
}


def model_method(task):
    pipeline = _model_store.load_pipeline(task)
    if pipeline is None:
        return None
    clf = pipeline["clf"]
    if hasattr(clf, "coef_"):
        return "linear"
    if hasattr(clf, "feature_importances_"):
        return "forest"
    return None


def feature_contributions(text, task="category", top_k=8):
    """Top model features that pushed the prediction, for one complaint."""
    pipeline = _model_store.load_pipeline(task)
    if pipeline is None or not (text or "").strip():
        return {
            "available": False,
            "reason": "model_not_trained" if pipeline is None else "empty_text",
            "method": None,
            "features": [],
        }

    tfidf = pipeline.named_steps["tfidf"]
    clf = pipeline.named_steps["clf"]
    matrix = tfidf.transform([preprocess(text)])
    values = np.asarray(matrix.todense()).ravel()
    names = tfidf.get_feature_names_out()

    predicted = str(clf.predict(matrix)[0])
    classes = [str(c) for c in getattr(clf, "classes_", [])]

    if hasattr(clf, "coef_"):
        coefficients = np.asarray(clf.coef_, dtype=float)
        if coefficients.shape[0] == 1 and len(classes) == 2:
            row = coefficients[0]
        else:
            row = coefficients[classes.index(predicted)]
        contributions = row * values
        method = METHODS["linear"]
        method_note = (
            "Signed Logistic Regression coefficients multiplied by this "
            "document's TF-IDF weight: positive values support the predicted "
            "class, negative values argue against it."
        )
    elif hasattr(clf, "feature_importances_"):
        contributions = np.asarray(clf.feature_importances_, dtype=float) * values
        method = METHODS["forest"]
        method_note = (
            "Random Forest impurity-based feature importance scaled by this "
            "document's TF-IDF weight. It shows which model-relevant terms "
            "are present in the complaint (not a Shapley/counterfactual "
            "attribution)."
        )
    else:
        return {
            "available": False,
            "reason": "unsupported_model_type",
            "method": None,
            "features": [],
        }

    non_zero = np.nonzero(values)[0]
    if non_zero.size == 0:
        return {
            "available": True,
            "method": method,
            "method_note": method_note,
            "predicted": predicted,
            "features": [],
            "note": "No recognised content terms in this complaint.",
        }

    order = non_zero[np.argsort(-np.abs(contributions[non_zero]))][:top_k]
    features = [
        {
            "term": str(names[i]),
            "tfidf_weight": round(float(values[i]), 4),
            "contribution": round(float(contributions[i]), 5),
            "direction": "supports" if contributions[i] >= 0 else "opposes",
        }
        for i in order
    ]
    return {
        "available": True,
        "method": method,
        "method_note": method_note,
        "predicted": predicted,
        "model_name": (clf.__class__.__name__),
        "features": features,
    }


def explain_prediction(text, category_prediction, urgency_prediction, context=None):
    """Full stored explanation payload (model + context) for one prediction.

    ``context`` is supplied by the caller with facts taken from the database:
    hours_since_submission, similar_nearby_count, hotspot_label,
    hotspot_size, citizen_category, citizen_priority.
    """
    context = context or {}
    category_block = feature_contributions(text, task="category")
    urgency_block = feature_contributions(text, task="urgency")

    factors = []
    if category_prediction.get("available"):
        factors.append({
            "label": "Model confidence",
            "value": f"{category_prediction['confidence']:.0%}",
            "detail": (
                f"Threshold for automatic handling is "
                f"{category_prediction.get('threshold', 0):.0%}; below it the "
                "complaint is flagged for manual review."
            ),
        })
    if context.get("citizen_category"):
        agreement = context["citizen_category"] == category_prediction.get("category")
        factors.append({
            "label": "Citizen category vs AI category",
            "value": "agree" if agreement else "differ",
            "detail": (
                f"Citizen selected '{context['citizen_category']}'; model "
                f"predicted '{category_prediction.get('category')}'."
            ),
        })
    if context.get("citizen_priority"):
        factors.append({
            "label": "Declared priority",
            "value": context["citizen_priority"],
            "detail": "Citizen's own urgency selection on the report form.",
        })
    if context.get("hours_since_submission") is not None:
        factors.append({
            "label": "Time since submission",
            "value": f"{context['hours_since_submission']:.1f} h",
            "detail": "Aging pressure applied by decision support (not a model input).",
        })
    if context.get("similar_nearby_count") is not None:
        factors.append({
            "label": "Similar complaints nearby",
            "value": str(context["similar_nearby_count"]),
            "detail": "Text-similar complaints within the duplicate distance window.",
        })
    if context.get("hotspot_label"):
        factors.append({
            "label": "Recurring hotspot",
            "value": context["hotspot_label"],
            "detail": (
                f"Location falls in a DBSCAN cluster with "
                f"{context.get('hotspot_size', '?')} complaints."
            ),
        })

    return {
        "model": {
            "category": {
                "name": (category_prediction.get("model_name") or
                         (category_block.get("model_name") if category_block.get("available") else None)),
                "confidence": category_prediction.get("confidence"),
                "needs_review": category_prediction.get("needs_review"),
                "keywords": category_prediction.get("keywords", []),
            },
            "urgency": {
                "name": urgency_prediction.get("model_name"),
                "confidence": urgency_prediction.get("confidence"),
                "urgency": urgency_prediction.get("urgency"),
            },
        },
        "text_features": {
            "category_task": category_block,
            "urgency_task": urgency_block,
        },
        "context_factors": factors,
    }
