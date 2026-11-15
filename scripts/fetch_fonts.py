"""Download the self-hosted variable fonts for the SmartWaste type system.

Plus Jakarta Sans (display) + Inter (text), latin subset, one variable woff2
each -> static/fonts/, then print the @font-face block for style.css.
Idempotent; requires internet on first run only.

Note: Google's css2 endpoint serves the *variable* font file for both the
per-weight and range syntax (byte-identical), so one file per family covers
every weight via a font-weight range.
"""

import os
import re
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "static", "fonts")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

FAMILIES = [
    ("Inter", "100 900", "inter-var.woff2",
     "https://fonts.googleapis.com/css2?family=Inter:wght@100..900&display=swap"),
    ("Plus Jakarta Sans", "200 800", "jakarta-var.woff2",
     "https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@200..800&display=swap"),
]


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print("file                      bytes")
    for family, weight_range, filename, css_url in FAMILIES:
        css = fetch(css_url).decode("utf-8")
        # keep the latin subset face only
        match = re.search(
            r"/\*\s*latin\s*\*/\s*@font-face\s*\{[^}]*"
            r"url\((https://[^)]+\.woff2)\)", css)
        if not match:
            raise SystemExit(f"latin woff2 not found for {family}")
        path = os.path.join(OUT_DIR, filename)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            with open(path, "wb") as fh:
                fh.write(fetch(match.group(1)))
        print(f"{filename:<25} {os.path.getsize(path)}   ({family}, {weight_range})")

    print("\n/* @font-face block for style.css */")
    for family, weight_range, filename, _ in FAMILIES:
        print(
            "@font-face{font-family:'%s';font-style:normal;font-weight:%s;"
            "font-display:swap;src:url('fonts/%s') format('woff2')}"
            % (family, weight_range, filename)
        )


if __name__ == "__main__":
    main()
