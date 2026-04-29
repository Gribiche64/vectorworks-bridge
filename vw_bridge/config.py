"""Active-file persistence — remembers which XML the watcher should follow.

Stored at ~/.config/vw-bridge/config.json so the path survives MCP server restarts.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "vw-bridge"
CONFIG_PATH = CONFIG_DIR / "config.json"


def load_active_file() -> Path | None:
    """Return the persisted active XML path, or None if unset / invalid."""
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text())
        path_str = data.get("active_file")
        if not path_str:
            return None
        return Path(path_str).expanduser()
    except (json.JSONDecodeError, OSError):
        return None


def save_active_file(path: Path) -> None:
    """Persist the active XML path."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps({"active_file": str(path)}, indent=2))


def clear_active_file() -> None:
    """Forget the active file."""
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
