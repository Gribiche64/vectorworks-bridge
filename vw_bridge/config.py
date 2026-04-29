"""Active-file persistence — remembers which XML the watcher should follow.

Stored at ~/.config/vw-bridge/config.json so the path survives MCP server restarts.
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "vw-bridge"
CONFIG_PATH = CONFIG_DIR / "config.json"

# Where to look for show plots when auto-detecting or fuzzy-matching by show name.
# Override by writing {"shows_root": "..."} into config.json.
SHOWS_ROOT_DEFAULT = Path.home() / "Documents" / "Shows"


def load_shows_root() -> Path:
    """Return the configured shows root, or the default."""
    if not CONFIG_PATH.exists():
        return SHOWS_ROOT_DEFAULT
    try:
        data = json.loads(CONFIG_PATH.read_text())
        custom = data.get("shows_root")
        return Path(custom).expanduser() if custom else SHOWS_ROOT_DEFAULT
    except (json.JSONDecodeError, OSError):
        return SHOWS_ROOT_DEFAULT


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


def _read() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def save_active_file(path: Path) -> None:
    """Persist the active XML path, preserving other config keys."""
    data = _read()
    data["active_file"] = str(path)
    _write(data)


def clear_active_file() -> None:
    """Forget the active file (keeps other config keys)."""
    data = _read()
    data.pop("active_file", None)
    if data:
        _write(data)
    elif CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
