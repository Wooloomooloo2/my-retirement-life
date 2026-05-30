# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec for My Retirement Life (macOS).
#
# Build with the wrapper script:
#     ./tools/build_mac.sh
#
# Or directly:
#     pyinstaller tools/MyRetirementLife.spec --clean --noconfirm
#
# Bundled read-only resources land under sys._MEIPASS at runtime; src/config.py
# already reconstructs templates_dir / static_dir / ontology_ttl from that root.
#
# See docs/adr/ADR-002-packaging-strategy.md for the overall strategy.

from pathlib import Path

# tools/ -> repo root
REPO_ROOT = Path(SPECPATH).resolve().parent

datas = [
    (str(REPO_ROOT / "src" / "templates"), "src/templates"),
    (str(REPO_ROOT / "src" / "static"),    "src/static"),
    (str(REPO_ROOT / "docs" / "ontology" / "mrl-ontology.ttl"), "docs/ontology"),
]

# Routes are imported by string in src/api/app.py — PyInstaller's static analysis
# should pick them up, but list them explicitly so a future indirect-import refactor
# can't silently drop one from the bundle.
hiddenimports = [
    "src.api.routes.profile",
    "src.api.routes.accounts",
    "src.api.routes.budget",
    "src.api.routes.life_events",
    "src.api.routes.projection",
    "src.api.routes.income",
    "src.api.routes.settings_route",
    "src.api.routes.investments",
    "src.api.routes.scenarios",
    # uvicorn loads these via importlib at runtime
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # pywebview's Cocoa backend on macOS. pyinstaller-hooks-contrib usually
    # picks this up, but be explicit so the bundle never silently misses it.
    "webview.platforms.cocoa",
]


a = Analysis(
    [str(REPO_ROOT / "main.py")],
    pathex=[str(REPO_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MyRetirementLife",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,   # inherit build-machine arch (ADR-002)
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="MyRetirementLife",
)

app = BUNDLE(
    coll,
    name="My Retirement Life.app",
    icon=None,
    bundle_identifier="app.myretirementlife",
    info_plist={
        "CFBundleName": "My Retirement Life",
        "CFBundleDisplayName": "My Retirement Life",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
    },
)
