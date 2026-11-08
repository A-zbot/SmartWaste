"""Retrain the SmartWaste complaint models.

Usage:
    python scripts/train_models.py

Trains (and evaluates) the category and urgency models from the labelled
dataset in data/, then writes the joblib pipelines + JSON evaluation reports
to models/. The Flask app loads those artifacts at request time.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.model_training import train_all  # noqa: E402


def main():
    summary = train_all()
    print("\nTraining complete. Best models:")
    for task, best in summary["tasks"].items():
        print(f"  {task:10s} -> {best['name']} "
              f"(CV F1-macro {best['cv_f1_macro_mean']}, "
              f"test F1-macro {best['test_metrics']['f1_macro']})")
    print(f"\nArtifacts written to models/ at {summary['meta']['trained_at']}")


if __name__ == "__main__":
    main()
