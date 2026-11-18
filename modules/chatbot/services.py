"""Conversation persistence and input handling for SmartWaste AI.

Ownership rules (enforced on every read/write, never trusted from the
frontend):
    * citizen conversations  -> user_id must equal session["user_id"]
    * administrator conversations -> role='admin' AND user_id IS NULL, and
      the caller must hold the admin session flag.

No secrets, API keys or tokens are ever written to these tables - only the
message text, a small structured ``meta`` blob for rich rendering and the
JSON flow state used by the complaint-registration machine.
"""

import json
import re
import sqlite3

from db import execute, get_connection, loads, query

MAX_TITLE_CHARS = 60
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# Sentinel so ``state=None`` can *clear* the flow state while an omitted
# ``state`` argument leaves it untouched.
_UNSET = object()


def sanitise_text(text, max_chars=None):
    """Strip control characters and normalise whitespace for storage."""
    import config
    max_chars = max_chars or config.AI_CHAT_MAX_MESSAGE_CHARS
    text = CONTROL_CHARS_RE.sub("", text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]


def role_label(role):
    return "admin" if role == "admin" else "citizen"


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
def create_conversation(user_id, role, language="en", title="New conversation"):
    role = role_label(role)
    if role == "admin":
        user_id = None  # administrators are not rows in users
    conv_id = execute(
        "INSERT INTO chat_conversations (user_id, role, title, language, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, datetime('now'), datetime('now'))",
        (user_id, role, sanitise_text(title, MAX_TITLE_CHARS) or "New conversation",
         language if language in ("en", "hi", "hinglish") else "en"),
    )
    return conv_id


def _ownership_clause(user_id, role):
    role = role_label(role)
    if role == "admin":
        return "role='admin' AND user_id IS NULL", ()
    return "role='citizen' AND user_id=?", (user_id,)


def get_conversation(conversation_id, user_id, role):
    """Fetch a conversation only when it belongs to this session."""
    clause, params = _ownership_clause(user_id, role)
    rows = query(
        f"SELECT * FROM chat_conversations WHERE id=? AND {clause}",
        (conversation_id, *params),
    )
    return rows[0] if rows else None


def list_conversations(user_id, role, limit=30):
    import config
    limit = min(int(limit), config.AI_CHAT_MAX_CONVERSATIONS)
    clause, params = _ownership_clause(user_id, role)
    return query(
        f"SELECT id, title, language, created_at, updated_at, state IS NOT NULL AS active "
        f"FROM chat_conversations WHERE {clause} "
        "ORDER BY updated_at DESC, id DESC LIMIT ?",
        (*params, limit),
    )


def touch_conversation(conversation_id, language=None, title=None, state=_UNSET):
    """Update mutable conversation fields (language/title/flow state).

    ``state=None`` clears an active flow; omitting ``state`` leaves it alone.
    """
    sets, params = ["updated_at=datetime('now')"], []
    if language in ("en", "hi", "hinglish"):
        sets.append("language=?")
        params.append(language)
    if title is not None:
        sets.append("title=?")
        params.append(sanitise_text(title, MAX_TITLE_CHARS) or "New conversation")
    if state is not _UNSET:
        sets.append("state=?")
        params.append(json.dumps(state, ensure_ascii=False) if state else None)
    params.append(conversation_id)
    execute(
        f"UPDATE chat_conversations SET {', '.join(sets)} WHERE id=?", params
    )


def read_state(conversation):
    return loads(conversation["state"], None) if conversation else None


def delete_conversation(conversation_id, user_id, role):
    conversation = get_conversation(conversation_id, user_id, role)
    if conversation is None:
        return False
    # chat_messages cascade via ON DELETE CASCADE (foreign_keys=ON).
    execute("DELETE FROM chat_conversations WHERE id=?", (conversation_id,))
    return True


def clear_messages(conversation_id, user_id, role):
    conversation = get_conversation(conversation_id, user_id, role)
    if conversation is None:
        return False
    execute("DELETE FROM chat_messages WHERE conversation_id=?", (conversation_id,))
    touch_conversation(conversation_id, title="New conversation", state=None)
    return True


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------
def add_message(conversation_id, sender, message, meta=None):
    if sender not in ("user", "assistant"):
        raise ValueError("invalid sender")
    text = sanitise_text(message)
    if not text:
        raise ValueError("empty message")
    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None
    message_id = execute(
        "INSERT INTO chat_messages (conversation_id, sender, message, meta, created_at) "
        "VALUES (?, ?, ?, ?, datetime('now'))",
        (conversation_id, sender, text, meta_json),
    )
    execute(
        "UPDATE chat_conversations SET updated_at=datetime('now') WHERE id=?",
        (conversation_id,),
    )
    return message_id


def get_messages(conversation_id, limit=200):
    rows = query(
        "SELECT * FROM chat_messages WHERE conversation_id=? "
        "ORDER BY id DESC LIMIT ?",
        (conversation_id, int(limit)),
    )
    messages = []
    for row in reversed(rows):
        payload = dict(row)
        payload["meta"] = loads(row["meta"], None)
        messages.append(payload)
    return messages


def history_for_model(conversation_id, window):
    """Newest ``window`` turns as [(role, text)] for the Gemini call."""
    rows = query(
        "SELECT sender, message FROM chat_messages "
        "WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, int(window) * 2),
    )
    pairs = [(row["sender"], row["message"]) for row in reversed(rows)]
    return pairs


def conversation_count(user_id, role):
    clause, params = _ownership_clause(user_id, role)
    rows = query(
        f"SELECT COUNT(*) AS n FROM chat_conversations WHERE {clause}", params
    )
    return int(rows[0]["n"]) if rows else 0


def maybe_create_conversation(user_id, role, language, limit=None):
    """Reuse the most recent conversation when it is still empty and fresh."""
    import config
    limit = limit or config.AI_CHAT_MAX_CONVERSATIONS
    clause, params = _ownership_clause(user_id, role)
    existing = query(
        f"SELECT id FROM chat_conversations WHERE {clause} "
        "ORDER BY updated_at DESC, id DESC LIMIT 1",
        params,
    )
    if existing:
        conv_id = existing[0]["id"]
        count = query(
            "SELECT COUNT(*) AS n FROM chat_messages WHERE conversation_id=?",
            (conv_id,),
        )[0]["n"]
        if count == 0:
            touch_conversation(conv_id, language=language)
            return conv_id, False
    if conversation_count(user_id, role) >= limit:
        # Oldest conversation is recycled instead of growing unbounded.
        oldest = query(
            f"SELECT id FROM chat_conversations WHERE {clause} "
            "ORDER BY updated_at ASC, id ASC LIMIT 1",
            params,
        )
        if oldest:
            execute("DELETE FROM chat_conversations WHERE id=?", (oldest[0]["id"],))
    conv_id = create_conversation(user_id, role, language=language)
    return conv_id, True


def record_assistant_message(conversation_id, text, meta=None):
    return add_message(conversation_id, "assistant", text, meta=meta)


def save_user_message(conversation_id, text):
    return add_message(conversation_id, "user", text)
