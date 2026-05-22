"""
ScenarioManager — named session management for My Retirement Life.

Scenarios are JSON exports stored as files in {data_dir}/scenarios/.
active_scenario.json in {data_dir}/ tracks the name and saved state of the
currently loaded scenario.

Architecture (ADR-014):
  - Each scenario file IS a standard export_all_data() JSON payload.
  - The Oxigraph data graph always holds the active scenario's data.
  - Switching scenarios = restore a different JSON into the data graph.
  - Dirty state is managed by the HTTP middleware in app.py; individual
    routes do not need to call mark_dirty() themselves.
"""

import json
import re
from datetime import datetime
from pathlib import Path


class ScenarioManager:
    """Manages named scenario files and active-session state."""

    ACTIVE_FILE = "active_scenario.json"
    SCENARIOS_DIR = "scenarios"
    MAX_NAME_LENGTH = 100

    def __init__(self, data_dir: Path) -> None:
        self.data_dir      = Path(data_dir)
        self.scenarios_dir = self.data_dir / self.SCENARIOS_DIR
        self.active_file   = self.data_dir / self.ACTIVE_FILE
        self._bootstrap()

    # ------------------------------------------------------------------
    # Bootstrap
    # ------------------------------------------------------------------

    def _bootstrap(self) -> None:
        """Ensure required directories and files exist."""
        self.scenarios_dir.mkdir(parents=True, exist_ok=True)
        if not self.active_file.exists():
            self._write_active({"name": "", "saved": False})

    # ------------------------------------------------------------------
    # Active state
    # ------------------------------------------------------------------

    def _write_active(self, state: dict) -> None:
        with open(self.active_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

    def _read_active(self) -> dict:
        try:
            with open(self.active_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"name": "", "saved": False}

    def get_state(self) -> dict:
        """Return current scenario state for Jinja2 template rendering.

        Keys:
            name          — raw scenario name (empty string if no saved name)
            saved         — True if current data matches the saved file
            display_name  — human-readable label for the nav header
            is_named      — True if the session has a saved name
            is_clean      — True if named AND saved (no unsaved changes)
        """
        state = self._read_active()
        name  = state.get("name", "")
        saved = state.get("saved", False)
        return {
            "name":         name,
            "saved":        saved,
            "display_name": name if name else "Unsaved session",
            "is_named":     bool(name),
            "is_clean":     bool(name) and saved,
        }

    def mark_dirty(self) -> None:
        """Record that the current session has unsaved changes."""
        state = self._read_active()
        if state.get("saved", False):
            state["saved"] = False
            self._write_active(state)

    def set_new_session(self) -> None:
        """Mark the current session as a new unnamed scenario."""
        self._write_active({"name": "", "saved": False})

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def list_scenarios(self) -> list[dict]:
        """Return all saved scenarios sorted alphabetically.

        Each entry contains: name, filename, modified (human date), size_kb.
        """
        scenarios = []
        for path in sorted(self.scenarios_dir.glob("*.json"),
                           key=lambda p: p.stem.lower()):
            try:
                stat = path.stat()
                scenarios.append({
                    "name":     path.stem,
                    "filename": path.name,
                    "modified": datetime.fromtimestamp(stat.st_mtime)
                                       .strftime("%d %b %Y %H:%M"),
                    "size_kb":  round(stat.st_size / 1024, 1),
                })
            except Exception:
                pass
        return scenarios

    def save(self, name: str, data: dict) -> tuple[bool, str]:
        """Write scenario data to disk and update active state.

        Returns (success, message).
        """
        name = name.strip()
        if not name:
            return False, "Scenario name cannot be empty."
        try:
            path = self.scenarios_dir / f"{self._safe_filename(name)}.json"
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._write_active({"name": name, "saved": True})
            return True, f"Saved as '{name}'."
        except Exception as e:
            return False, f"Save failed: {e}"

    def load(self, name: str) -> tuple[dict | None, str]:
        """Load scenario data from disk.

        Returns (data_dict, message). data_dict is None on failure.
        Does NOT update active state — the caller should do that after a
        successful restore_all_data() call.
        """
        path = self.scenarios_dir / f"{self._safe_filename(name)}.json"
        if not path.exists():
            return None, f"Scenario '{name}' not found."
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            return data, f"Loaded '{name}'."
        except Exception as e:
            return None, f"Load failed: {e}"

    def mark_loaded(self, name: str) -> None:
        """Record that a scenario has been successfully restored."""
        self._write_active({"name": name, "saved": True})

    def rename(self, old_name: str, new_name: str) -> tuple[bool, str]:
        """Rename a scenario file on disk."""
        old_name = old_name.strip()
        new_name = new_name.strip()
        if not new_name:
            return False, "New name cannot be empty."

        old_path = self.scenarios_dir / f"{self._safe_filename(old_name)}.json"
        new_path = self.scenarios_dir / f"{self._safe_filename(new_name)}.json"

        if not old_path.exists():
            return False, f"'{old_name}' does not exist."
        if new_path.exists():
            return False, f"'{new_name}' already exists."

        try:
            old_path.rename(new_path)
            state = self._read_active()
            if state.get("name") == old_name:
                self._write_active({"name": new_name, "saved": True})
            return True, f"Renamed to '{new_name}'."
        except Exception as e:
            return False, f"Rename failed: {e}"

    def delete(self, name: str) -> tuple[bool, str]:
        """Delete a scenario file from disk."""
        path = self.scenarios_dir / f"{self._safe_filename(name)}.json"
        if not path.exists():
            return False, f"'{name}' not found."
        try:
            path.unlink()
            state = self._read_active()
            if state.get("name") == name:
                self._write_active({"name": "", "saved": False})
            return True, f"Deleted '{name}'."
        except Exception as e:
            return False, f"Delete failed: {e}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _safe_filename(cls, name: str) -> str:
        """Return a filesystem-safe version of the scenario name."""
        safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name.strip())
        safe = safe.strip(". ")
        return safe[:cls.MAX_NAME_LENGTH] if safe else "unnamed"


# ---------------------------------------------------------------------------
# Module-level singleton — imported by routes and app.py middleware
# ---------------------------------------------------------------------------

from src.config import settings as _app_settings          # noqa: E402
scenario_manager = ScenarioManager(_app_settings.data_dir)
