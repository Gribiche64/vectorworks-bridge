"""Thread-safe in-memory cache for parsed fixture data.

The watcher writes to it; MCP tools read from it. RLock keeps reads/writes coherent
when the watcher fires while a tool call is in flight.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class FixtureData:
    """Parsed snapshot of one XML file."""

    fixtures: list[dict[str, Any]] = field(default_factory=list)
    """One dict per fixture, normalised by parser.py."""

    source_path: Path | None = None
    """The XML file this snapshot came from."""

    parsed_at: datetime | None = None
    """When parser.py last produced this snapshot."""

    parse_error: str | None = None
    """If the most recent parse failed, the error message. Snapshot is still last-good."""


class Cache:
    """Thread-safe holder for the latest FixtureData."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._data = FixtureData()

    def update(
        self,
        fixtures: list[dict[str, Any]],
        source_path: Path,
    ) -> None:
        """Replace cached fixtures with a fresh parse."""
        with self._lock:
            self._data = FixtureData(
                fixtures=fixtures,
                source_path=source_path,
                parsed_at=datetime.now(),
                parse_error=None,
            )

    def record_parse_error(self, error: str) -> None:
        """Note a parse failure without discarding the last-good snapshot."""
        with self._lock:
            self._data.parse_error = error

    def snapshot(self) -> FixtureData:
        """Return a shallow copy of current state for safe reads."""
        with self._lock:
            return FixtureData(
                fixtures=list(self._data.fixtures),
                source_path=self._data.source_path,
                parsed_at=self._data.parsed_at,
                parse_error=self._data.parse_error,
            )

    def is_loaded(self) -> bool:
        """True once a successful parse has populated the cache."""
        with self._lock:
            return self._data.parsed_at is not None
