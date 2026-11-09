"""Frontend quality tests (Phase 5).

Locks in the accessibility/responsiveness guarantees of the templates:

* every ``url_for()`` in every template resolves to a real endpoint
* every ``<img>`` carries an ``alt`` attribute
* both layout bases declare ``lang``, viewport, a skip link and a
  ``#main`` target, and announce flash messages with ``role="status"``
* the stylesheet honours keyboard focus and reduced-motion preferences
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

os.environ.setdefault(
    "DATABASE_PATH",
    os.path.join(os.environ.get("TEMP", "."), "smartwaste-frontend.db"),
)
os.environ.setdefault("AUTO_TRAIN_MODELS", "0")

import app as app_module  # noqa: E402

TEMPLATES = os.path.join(REPO_ROOT, "templates")


def _template_files():
    for root, dirs, files in os.walk(TEMPLATES):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in sorted(files):
            if name.endswith(".html"):
                yield os.path.join(root, name)


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ---------------------------------------------------------------------------
# Link integrity
# ---------------------------------------------------------------------------
def test_every_url_for_endpoint_exists():
    endpoints = {rule.endpoint for rule in app_module.app.url_map.iter_rules()}
    missing = {}
    for path in _template_files():
        rel = os.path.relpath(path, REPO_ROOT)
        for match in re.finditer(r"url_for\(\s*['\"]([^'\"]+)['\"]", _read(path)):
            endpoint = match.group(1)
            if endpoint not in endpoints:
                missing.setdefault(endpoint, set()).add(rel)
    assert not missing, f"templates reference unknown endpoints: {missing}"


def test_every_image_has_alt_text():
    offenders = []
    for path in _template_files():
        rel = os.path.relpath(path, REPO_ROOT)
        for match in re.finditer(r"<img\b[^>]*>", _read(path), re.I):
            if " alt=" not in match.group(0).lower():
                offenders.append((rel, match.group(0)[:100]))
    assert not offenders, f"images without alt: {offenders}"


def test_no_javascript_or_empty_hrefs():
    offenders = []
    for path in _template_files():
        rel = os.path.relpath(path, REPO_ROOT)
        for match in re.finditer(r'<a\b[^>]*href="([^"]*)"', _read(path), re.I):
            href = match.group(1)
            if href in ("#", "") or href.lower().startswith("javascript:"):
                offenders.append((rel, href))
    assert not offenders, f"dead anchors: {offenders}"


# ---------------------------------------------------------------------------
# Layout bases: language, skip link, live regions
# ---------------------------------------------------------------------------
def test_layout_bases_declare_language_and_viewport():
    for name in ("base.html", "admin_base.html"):
        markup = _read(os.path.join(TEMPLATES, name))
        assert 'lang="en"' in markup, name
        assert 'name="viewport"' in markup, name
        assert "<title>" in markup, name


def test_layout_bases_offer_skip_link_to_main():
    for name in ("base.html", "admin_base.html"):
        markup = _read(os.path.join(TEMPLATES, name))
        assert 'class="skip-link" href="#main"' in markup, name
        assert 'id="main"' in markup, f"{name} must define the skip target"


def test_flash_messages_are_announced_to_screen_readers():
    for name in ("base.html", "admin_base.html"):
        markup = _read(os.path.join(TEMPLATES, name))
        assert 'class="flash-wrap" role="status"' in markup, name
        assert 'aria-live="polite"' in markup, name


# ---------------------------------------------------------------------------
# Stylesheet guarantees
# ---------------------------------------------------------------------------
def test_stylesheet_supports_keyboard_focus_and_reduced_motion():
    css = _read(os.path.join(REPO_ROOT, "static", "style.css"))
    assert "prefers-reduced-motion" in css
    # global keyboard focus ring (beyond the button-specific rule)
    assert re.search(r"a:focus-visible", css)
    # tables scroll horizontally instead of stretching the page
    assert ".table-scroll{overflow:auto}" in css.replace(" ", "")
    # responsive breakpoints exist
    for breakpoint in ("1100px", "900px", "760px"):
        assert f"@media(max-width:{breakpoint})" in css.replace(" ", "")
