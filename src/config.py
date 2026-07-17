"""
Application configuration - reads from environment variables and .env file.
All path handling uses pathlib (ADR-004).
"""
import os
import sys
from pathlib import Path

from platformdirs import user_data_dir
from dotenv import load_dotenv

load_dotenv()


# ---------------------------------------------------------------------------
# Resource location: development vs. PyInstaller-frozen build
#
# In development, read-only resources (templates, static assets, the ontology
# TTL) live in their normal places relative to this file. When the app is
# frozen by PyInstaller, those resources are extracted at runtime under
# sys._MEIPASS, so paths must be resolved from there instead. The helper below
# returns the right base in both cases.
#
# data_dir / store_path are deliberately NOT affected — they always point at a
# writable per-user directory (platformdirs), which is correct whether running
# from source or from a frozen build.
# ---------------------------------------------------------------------------

_SRC_DIR = Path(__file__).parent          # dev: <repo>/src
_REPO_ROOT = _SRC_DIR.parent              # dev: <repo>


def _frozen_base() -> Path | None:
    """Return the PyInstaller extraction root when frozen, else None."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return None


# Stable machine-readable identity for this app, reported by /health and checked
# by the launcher before it points a window at a server. Deliberately NOT
# env-overridable: app_name is cosmetic and configurable, so it cannot be used
# to tell our server apart from another app that happens to hold the port.
APP_ID = "my-retirement-life"


class Settings:
    app_name: str = os.getenv("APP_NAME", "My Retirement Life")
    app_host: str = os.getenv("APP_HOST", "127.0.0.1")
    # Not 8000: that default is shared with several sibling apps on this
    # machine, and whichever starts second silently loses the bind.
    app_port: int = int(os.getenv("APP_PORT", "8817"))
    debug: bool = os.getenv("DEBUG", "true").lower() == "true"

    @property
    def data_dir(self) -> Path:
        """
        Returns the platform-appropriate user data directory.
        Can be overridden by setting DATA_DIR in .env
        """
        custom = os.getenv("DATA_DIR", "").strip()
        if custom:
            return Path(custom)
        return Path(user_data_dir("MyRetirementLife", appauthor=False))

    @property
    def store_path(self) -> Path:
        """Path to the Oxigraph triple store."""
        path = self.data_dir / "store"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def templates_dir(self) -> Path:
        base = _frozen_base()
        if base is not None:
            return base / "src" / "templates"
        return _SRC_DIR / "templates"

    @property
    def static_dir(self) -> Path:
        base = _frozen_base()
        path = (base / "src" / "static") if base is not None else (_SRC_DIR / "static")
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def ontology_ttl(self) -> Path:
        """
        Path to the ontology TTL loaded at runtime. In development this is the
        master copy under docs/ontology/; in a frozen build it is that same
        file bundled under the PyInstaller extraction root.
        """
        base = _frozen_base()
        if base is not None:
            return base / "docs" / "ontology" / "mrl-ontology.ttl"
        return _REPO_ROOT / "docs" / "ontology" / "mrl-ontology.ttl"


settings = Settings()
