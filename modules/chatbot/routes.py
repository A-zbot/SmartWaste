"""SmartWaste AI chat HTTP API.

Every endpoint derives the user id and role from the authenticated session -
nothing client-supplied is trusted for authorisation. Conversation ownership
is re-checked on every read/write, requests are size-limited and rate
limited, and the Gemini API key never leaves the backend.
"""

import re

from flask import Blueprint, jsonify, request, session

import config
from ai.language import SUPPORTED_LANGUAGES, detect
from security import rate_limit_hit
from modules.chatbot import flows, services

bp = Blueprint("chat", __name__)

_ERROR_BY_REASON = {
    "auth_required": ("Please sign in to use SmartWaste AI.", 401),
    "disabled": ("AI chat is currently disabled on this deployment.", 503),
    "not_found": ("Conversation not found.", 404),
    "rate_limited": ("Too many messages - please wait a moment and try again.", 429),
}


def _session_role():
    """'admin' | 'citizen' | None, derived only from the server session."""
    if session.get("admin") is True:
        return "admin"
    if session.get("user_id"):
        return "citizen"
    return None


def _session_user_id():
    return session.get("user_id") if _session_role() == "citizen" else None


def _require_auth():
    """Return ``(role, error)``; ``error`` is a ready-to-send Flask response."""
    role = _session_role()
    if role is None:
        return None, (jsonify({
            "ok": False, "code": "auth_required",
            "error": _ERROR_BY_REASON["auth_required"][0],
        }), 401)
    if not config.chat_available():
        return None, (jsonify({
            "ok": False, "code": "disabled",
            "error": _ERROR_BY_REASON["disabled"][0],
        }), 503)
    return role, None


def _throttled(role):
    identifier = f"{role}:{_session_user_id() or 'admin'}"
    return rate_limit_hit(
        "chat", identifier,
        max_attempts=config.AI_CHAT_RATE_MAX,
        window=config.AI_CHAT_RATE_WINDOW,
    )


def _clean_language(value, fallback="en"):
    value = (value or "").strip().lower()
    if value in SUPPORTED_LANGUAGES:
        return value
    return fallback if fallback in SUPPORTED_LANGUAGES else "en"


def _conversation_or_404(conversation_id, role):
    conversation = services.get_conversation(
        conversation_id, _session_user_id(), role
    )
    if conversation is None:
        return None, (jsonify({
            "ok": False, "code": "not_found",
            "error": _ERROR_BY_REASON["not_found"][0],
        }), 404)
    return conversation, None


# ---------------------------------------------------------------------------
# Status / bootstrap
# ---------------------------------------------------------------------------
@bp.route("/chat/api/status")
def status():
    role = _session_role()
    if role is None:
        return jsonify({
            "ok": False, "code": "auth_required",
            "error": _ERROR_BY_REASON["auth_required"][0],
        }), 401
    if not config.chat_available():
        return jsonify({
            "ok": False, "code": "disabled",
            "error": _ERROR_BY_REASON["disabled"][0],
        }), 503
    from ai import rag
    return jsonify({
        "ok": True,
        "role": role,
        "enabled": True,
        # Only the *presence* of credentials is disclosed - never the key.
        "ai_configured": bool(config.GEMINI_API_KEY),
        "model": config.GEMINI_MODEL if config.GEMINI_API_KEY else None,
        "languages": list(SUPPORTED_LANGUAGES),
        "suggestions": _suggestions(role),
        "knowledge_sources": rag.sources(),
        "max_message_chars": config.AI_CHAT_MAX_MESSAGE_CHARS,
    })


def _suggestions(role):
    if role == "admin":
        return [
            "Show pending complaints",
            "Identify high-priority areas",
            "Summarize complaint statistics",
            "Explain hotspot analysis",
        ]
    return [
        "Help me segregate waste",
        "Register a complaint",
        "Track my complaint",
        "Learn about recycling",
    ]


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
@bp.route("/chat/api/conversations", methods=["GET"])
def list_conversations():
    role, error = _require_auth()
    if error:
        return error
    rows = services.list_conversations(_session_user_id(), role)
    return jsonify({
        "ok": True,
        "conversations": [dict(row) for row in rows],
    })


@bp.route("/chat/api/conversations", methods=["POST"])
def create_conversation():
    role, error = _require_auth()
    if error:
        return error
    if _throttled(role):
        return jsonify({
            "ok": False, "code": "rate_limited",
            "error": _ERROR_BY_REASON["rate_limited"][0],
        }), 429
    payload = request.get_json(silent=True) or {}
    language = _clean_language(payload.get("language"), "en")
    conversation_id, _created = services.maybe_create_conversation(
        _session_user_id(), role, language
    )
    return jsonify({"ok": True, "conversation_id": conversation_id})


@bp.route("/chat/api/conversations/<int:conversation_id>", methods=["GET"])
def get_conversation(conversation_id):
    role, error = _require_auth()
    if error:
        return error
    conversation, err = _conversation_or_404(conversation_id, role)
    if err:
        return err
    messages = services.get_messages(conversation_id)
    return jsonify({
        "ok": True,
        "conversation": {
            "id": conversation["id"],
            "title": conversation["title"],
            "language": conversation["language"],
            "created_at": conversation["created_at"],
            "updated_at": conversation["updated_at"],
        },
        "messages": [
            {
                "id": m["id"],
                "sender": m["sender"],
                "message": m["message"],
                "meta": m["meta"],
                "created_at": m["created_at"],
            }
            for m in messages
        ],
    })


@bp.route("/chat/api/conversations/<int:conversation_id>", methods=["DELETE"])
def delete_conversation(conversation_id):
    role, error = _require_auth()
    if error:
        return error
    ok = services.delete_conversation(conversation_id, _session_user_id(), role)
    if not ok:
        return jsonify({
            "ok": False, "code": "not_found",
            "error": _ERROR_BY_REASON["not_found"][0],
        }), 404
    return jsonify({"ok": True})


@bp.route("/chat/api/conversations/<int:conversation_id>/clear", methods=["POST"])
def clear_conversation(conversation_id):
    role, error = _require_auth()
    if error:
        return error
    ok = services.clear_messages(conversation_id, _session_user_id(), role)
    if not ok:
        return jsonify({
            "ok": False, "code": "not_found",
            "error": _ERROR_BY_REASON["not_found"][0],
        }), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# The main send-message endpoint
# ---------------------------------------------------------------------------
@bp.route("/chat/api/message", methods=["POST"])
def send_message():
    role, error = _require_auth()
    if error:
        return error
    if _throttled(role):
        return jsonify({
            "ok": False, "code": "rate_limited",
            "error": _ERROR_BY_REASON["rate_limited"][0],
        }), 429

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({
            "ok": False, "code": "bad_request",
            "error": "Expected a JSON body.",
        }), 400
    if not isinstance(payload, dict):
        payload = {}

    text = payload.get("message")
    if not isinstance(text, str) or not text.strip():
        return jsonify({
            "ok": False, "code": "empty_message",
            "error": "Please type a message before sending.",
        }), 400
    if len(text) > config.AI_CHAT_MAX_MESSAGE_CHARS:
        return jsonify({
            "ok": False, "code": "too_long",
            "error": f"Message must be {config.AI_CHAT_MAX_MESSAGE_CHARS} "
                     "characters or fewer.",
        }), 400
    text = services.sanitise_text(text)
    if not text:
        return jsonify({
            "ok": False, "code": "empty_message",
            "error": "Please type a message before sending.",
        }), 400

    user_id = _session_user_id()
    language = _clean_language(payload.get("language"), detect(text))

    conversation_id = payload.get("conversation_id")
    conversation = None
    if conversation_id not in (None, "", 0):
        try:
            conversation_id = int(conversation_id)
        except (TypeError, ValueError):
            return jsonify({
                "ok": False, "code": "bad_request",
                "error": "Invalid conversation id.",
            }), 400
        conversation, err = _conversation_or_404(conversation_id, role)
        if err:
            return err
        # The stored language follows an explicit user choice.
        if payload.get("language") in SUPPORTED_LANGUAGES:
            language = _clean_language(payload.get("language"),
                                       conversation["language"])
        else:
            language = _clean_language(conversation["language"], language)
    else:
        conversation_id, _created = services.maybe_create_conversation(
            user_id, role, language
        )
        conversation = services.get_conversation(conversation_id, user_id, role)

    # --- persist the user turn ------------------------------------------
    services.save_user_message(conversation_id, text)
    history = services.history_for_model(
        conversation_id, config.AI_CHAT_HISTORY_WINDOW
    )

    # --- handle the turn (data first, then model) ------------------------
    try:
        reply, meta, new_state = flows.handle_turn(
            role, user_id, conversation, text, language, history=history
        )
    except Exception:  # pragma: no cover - the chat must never 500 the app
        import logging
        logging.getLogger(__name__).exception("chat turn failed")
        reply, meta, new_state = (
            flows._error_text("api_error", language),
            {"type": "error", "reason": "api_error"},
            None,
        )

    reply = services.sanitise_text(reply)
    if not reply:  # pragma: no cover - defensive
        reply = flows._error_text("api_error", language)
        meta = {"type": "error", "reason": "api_error"}

    # --- persist the assistant turn + conversation mutations -------------
    services.record_assistant_message(conversation_id, reply, meta=meta)
    title = None
    if conversation and (conversation["title"] in ("New conversation", "")):
        title = re.sub(r"\s+", " ", text)[:services.MAX_TITLE_CHARS]
    services.touch_conversation(
        conversation_id, language=language, title=title, state=new_state
    )

    return jsonify({
        "ok": True,
        "conversation_id": conversation_id,
        "language": language,
        "message": {
            "sender": "assistant",
            "message": reply,
            "meta": meta,
        },
    })
