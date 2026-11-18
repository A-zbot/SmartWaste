"""Google Gemini integration for SmartWaste AI.

Design rules:
    * The API key never leaves this module's process memory - it is read from
      the environment by config.py and never rendered into HTML/JS.
    * The model id is configurable (GEMINI_MODEL) and verified against the
      models actually available to the API account before first use; an
      unverified/unknown id degrades to a verified fallback instead of
      crashing the app.
    * Every failure mode is surfaced as ``GeminiUnavailable`` with a stable
      ``reason`` code so the chat layer can show a localised, safe message
      while the rest of SmartWaste keeps working.
    * A single lazy, thread-safe client is reused across requests.
"""

import logging
import threading

import config

logger = logging.getLogger(__name__)

# Stable reason codes consumed by the chat routes / frontend.
REASON_DISABLED = "disabled"
REASON_NO_KEY = "no_key"
REASON_INVALID_KEY = "invalid_key"
REASON_MODEL_UNAVAILABLE = "model_unavailable"
REASON_QUOTA = "quota"
REASON_TIMEOUT = "timeout"
REASON_API_ERROR = "api_error"

# Preference order used when the configured model is not available on the
# account (verified candidates only - we never guess blindly).
_FALLBACK_PREFERENCE = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
)


class GeminiUnavailable(Exception):
    """Raised when a Gemini call cannot be completed; ``reason`` is stable."""

    def __init__(self, reason, message="The AI service is temporarily unavailable."):
        super().__init__(message)
        self.reason = reason
        self.message = message


_state_lock = threading.Lock()
_client = None
_model_verified = False
_verified_model = None
_models_cache = None


def is_configured():
    return bool(config.GEMINI_API_KEY)


def reset():
    """Drop cached client/model state (used by tests)."""
    global _client, _model_verified, _verified_model, _models_cache
    with _state_lock:
        _client = None
        _model_verified = False
        _verified_model = None
        _models_cache = None


def _build_client():
    from google import genai
    from google.genai import types

    timeout_ms = int(max(1.0, config.AI_CHAT_TIMEOUT_SECONDS) * 1000)
    return genai.Client(
        api_key=config.GEMINI_API_KEY,
        http_options=types.HttpOptions(timeout=timeout_ms),
    )


def _get_client():
    global _client
    if not is_configured():
        raise GeminiUnavailable(
            REASON_NO_KEY,
            "The AI assistant is enabled but no GEMINI_API_KEY is configured "
            "on the server.",
        )
    with _state_lock:
        if _client is None:
            try:
                _client = _build_client()
            except Exception:  # pragma: no cover - SDK construction failure
                logger.exception("Could not construct the Gemini client")
                raise GeminiUnavailable(
                    REASON_API_ERROR, "The AI assistant could not start."
                )
        return _client


def _normalise_model_name(name):
    name = (name or "").strip()
    if name.startswith("models/"):
        name = name[len("models/"):]
    return name


def _list_available_models(client):
    """Return {model_name} for every model this account can generate with."""
    global _models_cache
    if _models_cache is not None:
        return _models_cache
    names = set()
    try:
        for model in client.models.list():
            name = _normalise_model_name(getattr(model, "name", ""))
            if not name:
                continue
            actions = getattr(model, "supported_actions", None) or []
            if not actions or "generateContent" in actions:
                names.add(name)
    except Exception:
        logger.exception("model listing failed - skipping verification")
        return None
    _models_cache = names
    return names


def current_model():
    """Resolve (and cache) the model id to actually call."""
    global _model_verified, _verified_model
    if _model_verified:
        return _verified_model

    configured = config.GEMINI_MODEL
    client = _get_client()
    available = _list_available_models(client)

    chosen = configured
    if available is not None:
        if configured in available:
            chosen = configured
        else:
            chosen = None
            for candidate in _FALLBACK_PREFERENCE:
                if candidate in available:
                    chosen = candidate
                    break
            if chosen is None:
                # Last resort: any flash-class generateContent model.
                flashes = sorted(
                    n for n in available
                    if "flash" in n and "preview" not in n and "lite" not in n
                )
                chosen = flashes[0] if flashes else None
            if chosen is None:
                _model_verified = True
                _verified_model = configured
                raise GeminiUnavailable(
                    REASON_MODEL_UNAVAILABLE,
                    "No text-generation model is available on this API account.",
                )
            logger.warning(
                "GEMINI_MODEL '%s' is not available to this account - "
                "using verified model '%s'.", configured, chosen,
            )
    else:
        # Listing failed (offline/permissions): trust the configured id and
        # let the generate call surface any real problem.
        logger.warning("Could not verify GEMINI_MODEL against the account.")

    _model_verified = True
    _verified_model = chosen
    return chosen


def _map_api_error(exc):
    """Translate an SDK/API exception into a stable reason code."""
    code = getattr(exc, "code", None)
    if code is None:
        inner = getattr(exc, "response", None)
        code = getattr(inner, "status_code", None)
    text = str(exc).lower()

    if code in (401, 403) or "api key not valid" in text or "unauthenticated" in text:
        return GeminiUnavailable(
            REASON_INVALID_KEY,
            "The configured GEMINI_API_KEY was rejected by Google Gemini.",
        )
    if code == 429 or "quota" in text or "resource has been exhausted" in text:
        return GeminiUnavailable(
            REASON_QUOTA,
            "The AI assistant has reached its Gemini API quota. Please try "
            "again later.",
        )
    if code in (404, 400) and ("model" in text or "not found" in text):
        return GeminiUnavailable(
            REASON_MODEL_UNAVAILABLE,
            "The configured Gemini model is not available on this API account.",
        )
    if "timeout" in text or "timed out" in text or "deadline" in text:
        return GeminiUnavailable(
            REASON_TIMEOUT,
            "The AI assistant timed out while contacting Gemini. Please try "
            "again.",
        )
    return GeminiUnavailable(
        REASON_API_ERROR,
        "The AI assistant could not reach Gemini right now. Please try again.",
    )


def generate_text(system, messages, json_mode=False, temperature=0.4,
                  max_output_tokens=900):
    """Send a chat turn to Gemini and return the plain text answer.

    ``messages`` is a list of ``(role, text)`` tuples with role in
    ``user``/``assistant`` (oldest first). Raises ``GeminiUnavailable``.
    """
    from google.genai import types

    client = _get_client()
    model = current_model()

    contents = [
        types.Content(
            role="user" if role == "user" else "model",
            parts=[types.Part(text=text)],
        )
        for role, text in messages if (text or "").strip()
    ]
    if not contents:
        raise GeminiUnavailable(REASON_API_ERROR, "Empty conversation.")

    cfg_kwargs = {
        "system_instruction": system,
        "temperature": temperature,
        "max_output_tokens": max_output_tokens,
    }
    if json_mode:
        cfg_kwargs["response_mime_type"] = "application/json"

    try:
        response = client.models.generate_content(
            model=model,
            contents=contents,
            config=types.GenerateContentConfig(**cfg_kwargs),
        )
    except GeminiUnavailable:
        raise
    except Exception as exc:  # SDK errors, transport errors, timeouts
        logger.warning("Gemini generate failed (%s): %s", type(exc).__name__, exc)
        raise _map_api_error(exc)

    text = (getattr(response, "text", None) or "").strip()
    if not text:
        raise GeminiUnavailable(
            REASON_API_ERROR, "Gemini returned an empty response. Please retry."
        )
    return text
