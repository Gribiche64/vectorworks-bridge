"""Tests for vw_bridge.parser against a real Celine Dion show plot."""

from __future__ import annotations

from pathlib import Path

import pytest

from vw_bridge.parser import (
    FIXTURE_DEVICE_TYPES,
    ParseError,
    _parse_wattage,
    _universe_from_address,
    parse_file,
)

SAMPLE = Path(__file__).parent / "fixtures" / "celine_sample.xml"


@pytest.fixture(scope="module")
def fixtures():
    return parse_file(SAMPLE)


class TestParseFile:
    def test_returns_expected_total_count(self, fixtures):
        # 741 lights + 63 moving lights + 4 SFX = 808
        assert len(fixtures) == 808

    def test_excludes_static_accessories_from_top_level(self, fixtures):
        # Static Accessories are nested inside a parent's <Accessories> block,
        # not counted as standalone fixtures.
        assert all(f["device_type"] in FIXTURE_DEVICE_TYPES for f in fixtures)

    def test_layers_present(self, fixtures):
        layers = {f["layer"] for f in fixtures}
        assert layers == {"Lighting - Overhead", "Lighting - Stage", "OLD", "SFX"}

    def test_device_types_present(self, fixtures):
        types = {f["device_type"] for f in fixtures}
        assert types == {"Light", "Moving Light", "SFX"}

    def test_layer_counts_match_known_values(self, fixtures):
        from collections import Counter
        layer_counts = Counter(f["layer"] for f in fixtures)
        assert layer_counts["Lighting - Overhead"] == 585
        assert layer_counts["Lighting - Stage"] == 164
        assert layer_counts["OLD"] == 55
        assert layer_counts["SFX"] == 4

    def test_top_inst_type_is_eaglestrike(self, fixtures):
        from collections import Counter
        top = Counter(f["inst_type"] for f in fixtures).most_common(1)[0]
        assert top == ("Ayrton EagleStrike", 412)

    def test_wattage_parsed_to_float(self, fixtures):
        # All fixtures in this plot have a wattage value.
        wattages = [f["wattage_w"] for f in fixtures if f["wattage_w"] is not None]
        assert len(wattages) == len(fixtures)
        # Sum should be around 691 kW for the Celine plot.
        assert 600_000 < sum(wattages) < 800_000

    def test_unpatched_fixtures_have_no_address(self, fixtures):
        # Rob's Celine plot is unpatched.
        assert all(f["absolute_address"] is None for f in fixtures)
        assert all(f["universe"] is None for f in fixtures)
        assert all(f["is_patched"] is False for f in fixtures)

    def test_accessories_attached_to_parent(self, fixtures):
        # At least one fixture has clamp accessories.
        with_acc = [f for f in fixtures if f["accessories"]]
        assert len(with_acc) > 0
        clamp_fixture = next(
            f for f in with_acc
            if any("Clamp" in (a.get("inst_type") or "") for a in f["accessories"])
        )
        assert clamp_fixture["accessories"][0]["device_type"] == "Static Accessory"

    def test_uid_present_for_every_fixture(self, fixtures):
        uids = [f["uid"] for f in fixtures]
        assert all(uid is not None for uid in uids)
        assert len(set(uids)) == len(uids)  # All unique

    def test_locations_are_floats(self, fixtures):
        f = fixtures[0]
        assert isinstance(f["x_location_mm"], float)
        assert isinstance(f["y_location_mm"], float)
        assert isinstance(f["z_location_mm"], float)


class TestParseWattage:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("700 W", 700.0),
            ("340W", 340.0),
            ("2800 W", 2800.0),
            ("2.5kW", 2500.0),
            ("1 kW", 1000.0),
            ("", None),
            (None, None),
            ("not a number", None),
        ],
    )
    def test_handles_common_formats(self, raw, expected):
        assert _parse_wattage(raw) == expected


class TestUniverseFromAddress:
    @pytest.mark.parametrize(
        "addr,expected_universe",
        [
            (1, 1),
            (512, 1),
            (513, 2),
            (1024, 2),
            (1025, 3),
            (None, None),
            (0, None),
            (-1, None),
        ],
    )
    def test_correct_universe(self, addr, expected_universe):
        assert _universe_from_address(addr) == expected_universe


class TestParseError:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(Exception):
            parse_file(tmp_path / "nope.xml")

    def test_malformed_xml_raises_parse_error(self, tmp_path):
        bad = tmp_path / "bad.xml"
        bad.write_text("<not valid xml")
        with pytest.raises(ParseError):
            parse_file(bad)

    def test_missing_instrument_data_raises(self, tmp_path):
        empty = tmp_path / "empty.xml"
        empty.write_text("<?xml version='1.0'?><SLData></SLData>")
        with pytest.raises(ParseError, match="InstrumentData"):
            parse_file(empty)
