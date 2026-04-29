"""Plot discovery — finds Lightwright XML files under the configured shows root.

Used by the auto-detect-on-startup behaviour and by the list_plots /
set_active_plot tools.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from . import config as cfg

# Folder names we never recurse into when scanning shows.
SKIP_DIRS = {"10. Old", "OLD", ".git", "__pycache__", "node_modules", ".cowork"}


@dataclass
class PlotCandidate:
    """One discovered XML file with a sibling .vwx."""

    xml_path: Path
    vwx_path: Path | None
    show_folder: str
    """Top-level folder under the shows root (e.g. '26_309_Celine Dion')."""
    modified_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "xml_path": str(self.xml_path),
            "vwx_path": str(self.vwx_path) if self.vwx_path else None,
            "show_folder": self.show_folder,
            "modified_at": datetime.fromtimestamp(self.modified_at).isoformat(
                timespec="seconds"
            ),
        }


def find_plots(shows_root: Path | None = None) -> list[PlotCandidate]:
    """Find every XML under shows_root that has a sibling .vwx, sorted newest first."""
    root = (shows_root or cfg.load_shows_root()).expanduser()
    if not root.exists():
        return []

    candidates: list[PlotCandidate] = []
    for xml_path in _walk_xmls(root):
        siblings = list(xml_path.parent.glob("*.vwx"))
        if not siblings:
            continue
        try:
            relative = xml_path.relative_to(root)
            show_folder = relative.parts[0] if relative.parts else "(unknown)"
        except ValueError:
            show_folder = "(unknown)"

        try:
            mtime = xml_path.stat().st_mtime
        except OSError:
            continue

        candidates.append(
            PlotCandidate(
                xml_path=xml_path,
                vwx_path=siblings[0],
                show_folder=show_folder,
                modified_at=mtime,
            )
        )

    candidates.sort(key=lambda c: -c.modified_at)
    return candidates


def _walk_xmls(root: Path):
    """Yield .xml paths under root, skipping SKIP_DIRS."""
    for path in root.iterdir():
        if path.is_dir():
            if path.name in SKIP_DIRS:
                continue
            yield from _walk_xmls(path)
        elif path.suffix.lower() == ".xml":
            yield path


def fuzzy_match_show(
    query: str, candidates: list[PlotCandidate]
) -> list[PlotCandidate]:
    """Filter candidates whose show_folder matches the query.

    1. Case-insensitive substring match (preferred — fast and predictable).
    2. Falls back to difflib ratio >= 0.45 if no substring matches.
    """
    q = query.lower().strip()
    if not q:
        return []

    substring = [c for c in candidates if q in c.show_folder.lower()]
    if substring:
        return substring

    scored = [
        (c, SequenceMatcher(None, q, c.show_folder.lower()).ratio())
        for c in candidates
    ]
    scored.sort(key=lambda s: -s[1])
    fuzzy = [c for c, score in scored if score >= 0.45]
    return fuzzy


def most_recent_plot_per_show(
    candidates: list[PlotCandidate],
) -> list[PlotCandidate]:
    """Collapse to one PlotCandidate per show_folder (the most recent one).

    Preserves the input order (which is newest-first across all shows), so the
    result is also newest-first across shows.
    """
    seen: set[str] = set()
    result: list[PlotCandidate] = []
    for c in candidates:
        if c.show_folder in seen:
            continue
        seen.add(c.show_folder)
        result.append(c)
    return result


# Convenience for the asdict-loving — currently unused but handy for tests.
__all__ = [
    "PlotCandidate",
    "find_plots",
    "fuzzy_match_show",
    "most_recent_plot_per_show",
    "asdict",
]
