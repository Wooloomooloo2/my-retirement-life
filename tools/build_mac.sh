#!/usr/bin/env bash
#
# Build the macOS distributable: PyInstaller .app -> hdiutil .dmg.
#
# Usage:
#     ./tools/build_mac.sh                 # produces dist/MyRetirementLife-dev.dmg
#     VERSION=0.2.0 ./tools/build_mac.sh   # produces dist/MyRetirementLife-0.2.0.dmg
#
# Requires: macOS, .venv with PyInstaller installed
# (pip install -r requirements-build.txt).
#
# See docs/adr/ADR-002-packaging-strategy.md.

set -euo pipefail

if [[ "$(uname)" != "Darwin" ]]; then
    echo "build_mac.sh: this script only runs on macOS (uname=$(uname))." >&2
    exit 1
fi

# tools/ -> repo root
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

PYINSTALLER="$REPO_ROOT/.venv/bin/pyinstaller"
if [[ ! -x "$PYINSTALLER" ]]; then
    echo "build_mac.sh: .venv/bin/pyinstaller not found." >&2
    echo "  Run:  ./.venv/bin/pip install -r requirements-build.txt" >&2
    exit 1
fi

VERSION="${VERSION:-dev}"
APP_NAME="My Retirement Life"
APP_BUNDLE="dist/${APP_NAME}.app"
DMG_PATH="dist/MyRetirementLife-${VERSION}.dmg"
DMG_STAGE="dist/dmg-stage"

echo "==> Cleaning build/ and dist/"
rm -rf build dist

echo "==> Running PyInstaller"
"$PYINSTALLER" tools/MyRetirementLife.spec --clean --noconfirm

if [[ ! -d "$APP_BUNDLE" ]]; then
    echo "build_mac.sh: expected $APP_BUNDLE was not produced." >&2
    exit 1
fi

echo "==> Staging DMG contents"
rm -rf "$DMG_STAGE"
mkdir -p "$DMG_STAGE"
cp -R "$APP_BUNDLE" "$DMG_STAGE/"
ln -s /Applications "$DMG_STAGE/Applications"

echo "==> Creating $DMG_PATH"
rm -f "$DMG_PATH"
hdiutil create \
    -volname "$APP_NAME" \
    -srcfolder "$DMG_STAGE" \
    -ov \
    -format UDZO \
    "$DMG_PATH" >/dev/null

rm -rf "$DMG_STAGE"

echo
echo "Build complete:"
echo "  App:  $REPO_ROOT/$APP_BUNDLE"
echo "  DMG:  $REPO_ROOT/$DMG_PATH"
