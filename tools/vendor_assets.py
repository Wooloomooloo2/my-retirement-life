"""
vendor_assets.py — Download all front-end assets currently pulled from CDNs
into the repository so the packaged app can run offline.

WHERE THIS GOES:  my-retirement-life/tools/vendor_assets.py
HOW TO RUN (from the repo root, with internet available):

    python tools/vendor_assets.py

NOT HANDLED HERE (ADR-022): Tailwind and DaisyUI. They used to be vendored as
`tailwind.play.min.js` (the Play CDN — a runtime in-browser compiler) and
`daisyui.full.min.css` (2.9 MB, all 32 themes). They are now compiled at build
time into src/static/css/app.css by `npm run build:css`. Do not re-add them
here: doing so would reintroduce the runtime compile and its flash of unstyled
content.

WHAT IT CREATES (relative to the repo root):

    src/static/vendor/
        htmx.min.js
        chart.umd.min.js
        tabler/
            tabler-icons.min.css        (font url()s rewritten to ./fonts/...)
            fonts/
                tabler-icons.woff2
                tabler-icons.woff
                ...whatever the CSS actually references...

The URLs below are byte-for-byte the same ones base.html loads today, so what
this script downloads is exactly what your browser currently fetches. The only
clever bit is the Tabler step: instead of hard-coding font filenames (which
differ between versions), it parses the downloaded CSS, follows every url(...)
reference, downloads those files, and rewrites the CSS to point at the local
copies.

Run this whenever you want to refresh the bundled versions. It overwrites.
"""

from __future__ import annotations

import re
import sys
import urllib.request
import urllib.error
from pathlib import Path
from urllib.parse import urljoin, urlparse

# ---------------------------------------------------------------------------
# Resolve paths relative to this script, NOT the current working directory,
# so it works no matter where you invoke it from.
#   this file:   <repo>/tools/vendor_assets.py
#   target dir:  <repo>/src/static/vendor
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "src" / "static" / "vendor"
TABLER_DIR = VENDOR_DIR / "tabler"
TABLER_FONTS_DIR = TABLER_DIR / "fonts"

# (source URL, output path relative to VENDOR_DIR)
# These mirror base.html exactly.
# Tailwind + DaisyUI are deliberately absent — they are a build-time step now
# (ADR-022). See the module docstring.
SIMPLE_ASSETS = [
    ("https://unpkg.com/htmx.org@1.9.12",     "htmx.min.js"),
    ("https://cdn.jsdelivr.net/npm/chart.js", "chart.umd.min.js"),
]

TABLER_CSS_URL = "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css"

# Some CDNs reject the default urllib User-Agent. Present a normal one.
_HEADERS = {"User-Agent": "Mozilla/5.0 (vendor_assets.py asset fetcher)"}

# Matches url(...) with optional single/double quotes.
_URL_RE = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)""")


def _fetch(url: str) -> bytes:
    """Download a URL and return its raw bytes. Raises on HTTP/network error."""
    req = urllib.request.Request(url, headers=_HEADERS)
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError(f"Downloaded 0 bytes from {url}")
    return data


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  wrote {path.relative_to(REPO_ROOT)}  ({len(data):,} bytes)")


def _local_font_name(raw_ref: str) -> str:
    """Strip query string and fragment from a url() reference to get a clean
    local filename. e.g. './fonts/tabler-icons.woff2?v=3.1.0' -> 'tabler-icons.woff2'."""
    parsed = urlparse(raw_ref)
    return Path(parsed.path).name


def vendor_simple_assets() -> None:
    print("Downloading core assets...")
    for url, out_rel in SIMPLE_ASSETS:
        try:
            data = _fetch(url)
        except (urllib.error.URLError, RuntimeError) as exc:
            print(f"  FAILED {url}\n         {exc}", file=sys.stderr)
            raise SystemExit(1)
        _write(VENDOR_DIR / out_rel, data)


def vendor_tabler() -> None:
    print("Downloading Tabler Icons (CSS + fonts)...")
    try:
        css_bytes = _fetch(TABLER_CSS_URL)
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"  FAILED {TABLER_CSS_URL}\n         {exc}", file=sys.stderr)
        raise SystemExit(1)

    css_text = css_bytes.decode("utf-8")

    # Find every url(...) reference, download the referenced font, and build a
    # map of original-reference -> new local reference for rewriting.
    downloaded: dict[str, str] = {}   # absolute_url -> local filename (dedup)
    replacements: list[tuple[str, str]] = []

    for match in _URL_RE.finditer(css_text):
        raw_ref = match.group(2).strip()

        # Skip data: URIs and anything already local.
        if raw_ref.startswith("data:"):
            continue

        absolute_url = urljoin(TABLER_CSS_URL, raw_ref)
        local_name = _local_font_name(raw_ref)

        if absolute_url not in downloaded:
            try:
                font_bytes = _fetch(absolute_url)
            except (urllib.error.URLError, RuntimeError) as exc:
                print(f"  FAILED font {absolute_url}\n         {exc}", file=sys.stderr)
                raise SystemExit(1)
            _write(TABLER_FONTS_DIR / local_name, font_bytes)
            downloaded[absolute_url] = local_name

        # Preserve any #fragment (the legacy svg font uses one); drop the
        # version query string since the local file has no query.
        fragment = urlparse(raw_ref).fragment
        new_ref = f"./fonts/{local_name}"
        if fragment:
            new_ref += f"#{fragment}"

        # Replace this exact url(...) occurrence.
        old_url_expr = match.group(0)
        new_url_expr = f"url('{new_ref}')"
        replacements.append((old_url_expr, new_url_expr))

    for old, new in replacements:
        css_text = css_text.replace(old, new, 1)

    _write(TABLER_DIR / "tabler-icons.min.css", css_text.encode("utf-8"))
    print(f"  rewrote {len(downloaded)} font reference(s) to local paths")


def main() -> None:
    print(f"Repo root:   {REPO_ROOT}")
    print(f"Vendor dir:  {VENDOR_DIR}\n")
    vendor_simple_assets()
    vendor_tabler()
    print("\nDone. All front-end assets are now vendored under src/static/vendor/.")
    print("Next: base.html must point at /static/vendor/... and app.py must mount /static.")


if __name__ == "__main__":
    main()
