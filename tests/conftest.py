"""Session-wide pytest configuration.

Runs before any test module imports ``app``/``config``, so environment
variables set here are picked up by ``config.py`` at import time.

``PUBLIC_RATE_MAX`` is raised for tests because every test client shares the
same client IP (127.0.0.1) and the suite intentionally makes many more public
POSTs (report/signup/contact/duplicate-check) than a human would in the
throttle window. The throttle mechanism itself is unit-tested directly in
``tests/test_security.py`` with explicit limits.
"""

import os

os.environ.setdefault("PUBLIC_RATE_MAX", "100000")
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

# SmartWaste AI chat: the widget and its APIs are exercised in tests, but the
# suite must never call the real Gemini API - the key is forced empty here
# (load_dotenv does not override existing environment variables) and every
# AI-generated answer is mocked inside tests/test_chatbot.py.
os.environ.setdefault("AI_CHAT_ENABLED", "true")
os.environ["GEMINI_API_KEY"] = ""
os.environ.setdefault("GEMINI_MODEL", "gemini-2.0-flash")
