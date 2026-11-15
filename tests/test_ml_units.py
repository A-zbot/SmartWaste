"""Unit tests for the ML/intelligence layer (master prompt Phase 9).

Covers: text preprocessing, category prediction, urgency prediction,
forecasting honest-path behaviour, the public rate limiter, e-mail header
sanitisation and image magic-byte validation.
"""

import os
import re
import sys
import tempfile

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(tempfile.mkdtemp(prefix="smartwaste-mlunits-"), "test.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402,F401
from config import CATEGORIES, PRIORITIES  # noqa: E402
from intelligence.complaint_classifier import classify  # noqa: E402
from intelligence.priority_predictor import predict_urgency  # noqa: E402


@pytest.fixture(scope="session")
def app():
    application = app_module.app
    application.config["TESTING"] = True
    return application


# ---------------------------------------------------------------------------
# Text preprocessing
# ---------------------------------------------------------------------------
def test_clean_text_strips_markup_urls_and_folds_accents():
    from intelligence.preprocessing import clean_text

    cleaned = clean_text("Hello <b>World</b> — visit http://spam.example/x NOW Café")
    assert "<b>" not in cleaned
    assert "http" not in cleaned
    assert "cafe" in cleaned
    assert cleaned == cleaned.lower()


def test_preprocess_is_deterministic():
    from intelligence.preprocessing import preprocess

    text = "Overflowing garbage bins near the market street for three days"
    assert preprocess(text) == preprocess(text)
    assert "  " not in preprocess(text)


def test_tokenize_regex_fallback_when_nltk_unavailable(monkeypatch):
    import intelligence.preprocessing as pp

    monkeypatch.setattr(pp, "_ensure_nltk", lambda: False)
    monkeypatch.setattr(pp, "_word_tokenize", None)
    assert pp.tokenize("hello world 123") == ["hello", "world", "123"]


def test_extract_keywords_returns_non_empty_terms():
    from intelligence import _model_store
    from intelligence.preprocessing import extract_keywords

    pipeline = _model_store.load_pipeline("category")
    assert pipeline is not None
    terms = extract_keywords(
        "construction debris blocking the road near the school gate",
        pipeline.named_steps.get("tfidf"),
        top_k=4,
    )
    assert isinstance(terms, list)
    assert 0 < len(terms) <= 4


# ---------------------------------------------------------------------------
# Category / urgency prediction
# ---------------------------------------------------------------------------
def test_classify_returns_taxonomy_label_with_confidence():
    out = classify("Dead animals and rotting garbage piled outside the school gate")
    assert out["available"] is True
    assert out["category"] in CATEGORIES
    assert 0.0 <= out["confidence"] <= 1.0
    assert out["needs_review"] in (True, False)
    assert out["model_version"]  # model version travels with every prediction
    assert set(out["probabilities"]) <= set(CATEGORIES)


def test_classify_empty_text_is_unavailable_not_invented():
    out = classify("")
    assert out["available"] is False
    assert out["category"] is None
    assert out["needs_review"] is True


def test_classify_degrades_gracefully_when_model_missing(monkeypatch):
    import intelligence.complaint_classifier as cc

    monkeypatch.setattr(cc._model_store, "load_pipeline", lambda task: None)
    out = cc.classify("any complaint text at all")
    assert out["available"] is False
    assert out["reason"] == "model_not_trained"
    assert out["category"] is None
    assert out["needs_review"] is True


def test_predict_urgency_returns_valid_level_and_fallback(monkeypatch):
    out = predict_urgency("Sewage entering homes from a blocked drain on the main road")
    assert out["available"] is True
    assert out["urgency"] in PRIORITIES
    assert out["model_version"]

    import intelligence.priority_predictor as pp

    monkeypatch.setattr(pp._model_store, "load_pipeline", lambda task: None)
    down = pp.predict_urgency("Sewage entering homes")
    assert down["available"] is False
    assert down["urgency"] is None
    assert down["needs_review"] is True


# ---------------------------------------------------------------------------
# Forecasting honest paths
# ---------------------------------------------------------------------------
def test_forecast_refuses_to_fabricate_on_short_history():
    from intelligence.forecasting import forecast

    payload = forecast(horizon=7, days=5)
    assert payload["status"] == "insufficient"
    assert payload["forecast"] is None
    assert "no forecast is generated" in payload["message"]
    assert payload["metrics"] is None


def test_forecast_baseline_only_between_thresholds():
    from intelligence.forecasting import forecast

    payload = forecast(horizon=7, days=20)
    assert payload["status"] == "baseline_only"
    assert payload["forecast"] is not None
    assert payload["forecast"]["values"]
    # Both baselines must be scored, chronologically held out.
    assert any("baseline" in name for name in payload["metrics"])


def test_forecast_payload_has_methodology_and_split_disclosure():
    from intelligence.forecasting import forecast

    payload = forecast(horizon=7, days=40)
    assert "chronological" in payload["methodology"]["split"]
    assert "RMSE" in payload["methodology"]["uncertainty"]


# ---------------------------------------------------------------------------
# Security helpers
# ---------------------------------------------------------------------------
def test_rate_limit_hit_blocks_over_limit_and_is_bounded():
    import security

    bucket = "unit-test"
    identifier = "x" * 200  # must be truncated, never stored raw
    key_prefix = f"{bucket}:"
    try:
        assert security.rate_limit_hit(bucket, identifier, max_attempts=2, window=60) is False
        assert security.rate_limit_hit(bucket, identifier, max_attempts=2, window=60) is False
        assert security.rate_limit_hit(bucket, identifier, max_attempts=2, window=60) is True
        stored_keys = [k for k in security._public_hits if k.startswith(key_prefix)]
        assert stored_keys, "attempt should have been recorded"
        # identifier part of the key is truncated to 64 chars
        assert all(len(k) <= len(key_prefix) + 64 for k in stored_keys)
    finally:
        for k in [k for k in security._public_hits if k.startswith(key_prefix)]:
            security._public_hits.pop(k, None)


def test_email_header_safe_strips_crlf():
    from modules.complaints.email_service import _header_safe

    assert _header_safe("High") == "High"
    hostile = "High\r\nBcc: attacker@evil.com"
    safe = _header_safe(hostile)
    assert "\r" not in safe and "\n" not in safe
    assert "Bcc:" in safe  # text kept, header break removed


# ---------------------------------------------------------------------------
# Upload content validation
# ---------------------------------------------------------------------------
def test_image_magic_byte_signatures():
    from modules.complaints.services import _has_valid_signature

    assert _has_valid_signature(b"\x89PNG\r\n\x1a\nrest", "png")
    assert not _has_valid_signature(b"<script>alert(1)</script>", "png")
    assert _has_valid_signature(b"\xff\xd8\xff\xe0junk", "jpg")
    assert _has_valid_signature(b"\xff\xd8\xff\xe0junk", "jpeg")
    assert not _has_valid_signature(b"GIF89a junk", "jpg")
    assert _has_valid_signature(b"RIFF\x10\x00\x00\x00WEBPdata", "webp")
    assert not _has_valid_signature(b"RIFF\x10\x00\x00\x00WAVEdata", "webp")
    assert not _has_valid_signature(b"anything", "exe")


# ---------------------------------------------------------------------------
# Input validation (taxonomy allowlist)
# ---------------------------------------------------------------------------
def _valid_form(**overrides):
    form = {
        "name": "Unit Tester",
        "mobile": "9876543210",
        "location": "12 Test Street",
        "waste_type": "Open Garbage",
        "priority": "High",
        "description": "Garbage has been lying on the road for three days.",
    }
    form.update(overrides)
    return form


def test_validate_accepts_taxonomy_values():
    from modules.complaints import services

    assert services.validate(_valid_form()) is None
    assert services.validate(_valid_form(waste_type="Garbage")) is None  # legacy alias


def test_validate_rejects_unknown_category_and_priority():
    from modules.complaints import services

    error = services.validate(_valid_form(waste_type="<script>x</script>"))
    assert error is not None and "categor" in error.lower()

    error = services.validate(_valid_form(priority="Critical"))
    assert error is not None and "priority" in error.lower()


def test_validate_rejects_short_or_oversized_description():
    from modules.complaints import services

    assert services.validate(_valid_form(description="too short")) is not None
    assert services.validate(_valid_form(description="x" * 2001)) is not None
