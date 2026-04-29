"""File watcher — keeps the Cache fresh as Vectorworks rewrites the XML.

VW writes the LW exchange XML whenever focus switches away from VW. We watch
for those writes, debounce briefly to let VW finish, then re-parse and update
the cache.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .cache import Cache
from .parser import ParseError, parse_file

log = logging.getLogger(__name__)

DEBOUNCE_SECONDS = 0.4  # Lets VW finish writing before we read.


class _Handler(FileSystemEventHandler):
    def __init__(self, target: Path, cache: Cache) -> None:
        self._target = target.resolve()
        self._cache = cache
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def on_modified(self, event: FileSystemEvent) -> None:
        self._maybe_reparse(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._maybe_reparse(event)

    def _maybe_reparse(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        try:
            if Path(event.src_path).resolve() != self._target:
                return
        except OSError:
            return
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(DEBOUNCE_SECONDS, self._reparse)
            self._timer.daemon = True
            self._timer.start()

    def _reparse(self) -> None:
        try:
            fixtures = parse_file(self._target)
            self._cache.update(fixtures, self._target)
            log.info("Re-parsed %s — %d fixtures", self._target.name, len(fixtures))
        except ParseError as e:
            self._cache.record_parse_error(str(e))
            log.warning("Parse error on %s: %s", self._target.name, e)
        except OSError as e:
            self._cache.record_parse_error(f"OS error: {e}")
            log.warning("OS error on %s: %s", self._target.name, e)


class Watcher:
    """Owns a watchdog Observer that monitors a single XML file's directory."""

    def __init__(self, cache: Cache) -> None:
        self._cache = cache
        self._observer: Observer | None = None
        self._target: Path | None = None

    def watch(self, path: Path) -> None:
        """Start (or switch) watching a file. Triggers an initial parse."""
        path = path.expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(f"XML file not found: {path}")

        self.stop()

        # Initial parse so tools work immediately, before any focus-switch event.
        try:
            fixtures = parse_file(path)
            self._cache.update(fixtures, path)
            log.info("Initial parse of %s — %d fixtures", path.name, len(fixtures))
        except ParseError as e:
            self._cache.record_parse_error(str(e))
            log.warning("Initial parse failed on %s: %s", path.name, e)

        handler = _Handler(path, self._cache)
        observer = Observer()
        # Watch the parent dir, filter on filename in handler — watching a single
        # file directly is unreliable on macOS when editors write+rename.
        observer.schedule(handler, str(path.parent), recursive=False)
        observer.daemon = True
        observer.start()
        self._observer = observer
        self._target = path

    def stop(self) -> None:
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
            self._target = None

    @property
    def target(self) -> Path | None:
        return self._target
