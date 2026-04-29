"""Tests for vw_bridge.discovery."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from vw_bridge.discovery import (
    PlotCandidate,
    find_plots,
    fuzzy_match_show,
    most_recent_plot_per_show,
)


def _touch(path: Path, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")
    if mtime is not None:
        import os
        os.utime(path, (mtime, mtime))


@pytest.fixture
def shows_root(tmp_path):
    """Build a fake shows tree:

        shows/
          26_309_Celine Dion/1. CAD/celine.xml + celine.vwx
          26_410_Eternal Sunshine/1. CAD/sunshine.xml + sunshine.vwx
          26_410_Eternal Sunshine/10. Old/old.xml + old.vwx   (skipped)
          26_500_Hilary Duff/1. CAD/duff.xml                   (no .vwx — skipped)
    """
    root = tmp_path / "shows"
    _touch(root / "26_309_Celine Dion" / "1. CAD" / "celine.xml", mtime=1000)
    _touch(root / "26_309_Celine Dion" / "1. CAD" / "celine.vwx", mtime=1000)

    _touch(root / "26_410_Eternal Sunshine" / "1. CAD" / "sunshine.xml", mtime=2000)
    _touch(root / "26_410_Eternal Sunshine" / "1. CAD" / "sunshine.vwx", mtime=2000)

    _touch(root / "26_410_Eternal Sunshine" / "10. Old" / "old.xml", mtime=3000)
    _touch(root / "26_410_Eternal Sunshine" / "10. Old" / "old.vwx", mtime=3000)

    # XML without sibling vwx — should be excluded.
    _touch(root / "26_500_Hilary Duff" / "1. CAD" / "duff.xml", mtime=4000)
    return root


class TestFindPlots:
    def test_returns_only_xmls_with_sibling_vwx(self, shows_root):
        plots = find_plots(shows_root)
        names = {p.xml_path.name for p in plots}
        assert names == {"celine.xml", "sunshine.xml"}

    def test_skips_old_directory(self, shows_root):
        plots = find_plots(shows_root)
        assert all("old" not in p.xml_path.name.lower() for p in plots)

    def test_sorted_newest_first(self, shows_root):
        plots = find_plots(shows_root)
        assert plots[0].xml_path.name == "sunshine.xml"
        assert plots[1].xml_path.name == "celine.xml"

    def test_show_folder_extracted_from_top_level(self, shows_root):
        plots = find_plots(shows_root)
        folders = {p.show_folder for p in plots}
        assert folders == {"26_309_Celine Dion", "26_410_Eternal Sunshine"}

    def test_returns_empty_for_missing_root(self, tmp_path):
        assert find_plots(tmp_path / "does-not-exist") == []


class TestFuzzyMatchShow:
    def test_substring_match_case_insensitive(self, shows_root):
        plots = find_plots(shows_root)
        result = fuzzy_match_show("celine", plots)
        assert len(result) == 1
        assert "Celine" in result[0].show_folder

    def test_partial_substring(self, shows_root):
        plots = find_plots(shows_root)
        result = fuzzy_match_show("eternal", plots)
        assert len(result) == 1
        assert "Sunshine" in result[0].show_folder

    def test_falls_back_to_fuzzy(self, shows_root):
        plots = find_plots(shows_root)
        # Misspelled — substring fails, fuzzy should still find Celine
        result = fuzzy_match_show("celin dion", plots)
        assert any("Celine" in c.show_folder for c in result)

    def test_no_match_returns_empty(self, shows_root):
        plots = find_plots(shows_root)
        assert fuzzy_match_show("xyz123nothing", plots) == []

    def test_empty_query_returns_empty(self, shows_root):
        plots = find_plots(shows_root)
        assert fuzzy_match_show("", plots) == []


class TestMostRecentPlotPerShow:
    def test_collapses_duplicates(self, tmp_path):
        c1 = PlotCandidate(
            xml_path=tmp_path / "a.xml",
            vwx_path=None,
            show_folder="ShowA",
            modified_at=2000,
        )
        c2 = PlotCandidate(
            xml_path=tmp_path / "a-old.xml",
            vwx_path=None,
            show_folder="ShowA",
            modified_at=1000,
        )
        c3 = PlotCandidate(
            xml_path=tmp_path / "b.xml",
            vwx_path=None,
            show_folder="ShowB",
            modified_at=1500,
        )
        # Input is newest-first
        result = most_recent_plot_per_show([c1, c3, c2])
        assert [r.show_folder for r in result] == ["ShowA", "ShowB"]
        # Keeps the first (newest) one for ShowA
        assert result[0].xml_path.name == "a.xml"


class TestPlotCandidateToDict:
    def test_serialises_paths_and_iso_timestamp(self, tmp_path):
        c = PlotCandidate(
            xml_path=tmp_path / "x.xml",
            vwx_path=tmp_path / "x.vwx",
            show_folder="Show",
            modified_at=time.time(),
        )
        d = c.to_dict()
        assert d["xml_path"].endswith("x.xml")
        assert d["vwx_path"].endswith("x.vwx")
        assert d["show_folder"] == "Show"
        # ISO format with T separator
        assert "T" in d["modified_at"]
