"""Tests for the thread-safe in-memory Cache."""

from __future__ import annotations

import threading
from pathlib import Path

from vw_bridge.cache import Cache


def test_starts_empty():
    c = Cache()
    snap = c.snapshot()
    assert snap.fixtures == []
    assert snap.parsed_at is None
    assert snap.source_path is None
    assert c.is_loaded() is False


def test_update_populates_snapshot(tmp_path):
    c = Cache()
    c.update([{"uid": "1.1.1.0.1"}], tmp_path / "x.xml")
    snap = c.snapshot()
    assert snap.fixtures == [{"uid": "1.1.1.0.1"}]
    assert snap.source_path == tmp_path / "x.xml"
    assert snap.parsed_at is not None
    assert c.is_loaded() is True


def test_snapshot_is_isolated_from_internal_state(tmp_path):
    c = Cache()
    c.update([{"uid": "a"}], tmp_path / "x.xml")
    snap = c.snapshot()
    snap.fixtures.append({"uid": "tampered"})
    # Mutating the snapshot must not affect future reads.
    assert len(c.snapshot().fixtures) == 1


def test_parse_error_preserves_last_good_data(tmp_path):
    c = Cache()
    c.update([{"uid": "good"}], tmp_path / "x.xml")
    c.record_parse_error("bad XML")
    snap = c.snapshot()
    assert snap.fixtures == [{"uid": "good"}]
    assert snap.parse_error == "bad XML"


def test_concurrent_writes_dont_corrupt(tmp_path):
    c = Cache()

    def writer(n):
        for i in range(50):
            c.update([{"uid": f"{n}-{i}"}], tmp_path / f"{n}.xml")

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = c.snapshot()
    # Whoever wrote last wins, but state must be coherent.
    assert len(snap.fixtures) == 1
    assert snap.fixtures[0]["uid"].count("-") == 1
