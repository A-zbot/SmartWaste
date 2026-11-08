"""SmartWaste intelligence package.

Machine-learning and geospatial modules:

    preprocessing.py        NLTK text normalisation
    complaint_classifier.py TF-IDF + classifier category prediction
    priority_predictor.py   urgency prediction
    model_training.py       reproducible training/evaluation pipeline
    model_evaluation.py     real metrics produced by training
    explainability.py       model-grounded explanation of predictions
    duplicate_detection.py  TF-IDF cosine similarity + geo distance
    hotspot_detection.py    DBSCAN clustering of complaint coordinates
    geospatial_analysis.py  distance/coordinate/map helpers
    forecasting.py          baseline vs ML complaint-volume forecasting
    recommender.py          decision-support recommendations from real data
"""

__all__ = [
    "preprocessing",
    "complaint_classifier",
    "priority_predictor",
    "model_training",
    "model_evaluation",
    "explainability",
    "duplicate_detection",
    "hotspot_detection",
    "geospatial_analysis",
    "forecasting",
    "recommender",
]
