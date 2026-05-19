"""Tests for vw_bridge.writer — patch construction and protocol compliance."""

from __future__ import annotations

from pathlib import Path

import pytest

from vw_bridge import parser, writer

SAMPLE = Path(__file__).parent / "fixtures" / "celine_sample.xml"


@pytest.fixture(scope="module")
def fixtures():
    return parser.parse_file(SAMPLE)


class TestUidToTag:
    def test_dotted_to_underscored(self):
        assert writer.uid_to_tag("1246.1.1.0.0") == "UID_1246_1_1_0_0"


class TestUtcTimestamp:
    def test_format_is_14_digits(self):
        ts = writer.utc_timestamp()
        assert len(ts) == 14
        assert ts.isdigit()


class TestBuildPatch:
    def test_single_field_change(self, fixtures):
        sample = fixtures[0]
        uid = sample["uid"]
        patch = writer.build_patch(
            changes=[{"uid": uid, "fields": {"Channel": "42"}}],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "<?xml" in patch
        assert "<Inventory>" in patch
        assert "<AppStamp" in patch and "Lightwright" in patch
        assert "<ExportFieldList>" in patch
        assert writer.uid_to_tag(uid) in patch
        assert "<Channel>42</Channel>" in patch
        assert "<Action>Update</Action>" in patch
        # LWID may be None on fixtures that haven't been seen by LW yet — the
        # writer still emits an empty <Lightwright_ID></Lightwright_ID>.
        if sample["lightwright_id"]:
            assert sample["lightwright_id"] in patch
        else:
            assert "<Lightwright_ID></Lightwright_ID>" in patch

    def test_type_swap_includes_all_three_fields(self, fixtures):
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[
                {
                    "uid": sample["uid"],
                    "fields": {
                        "Inst_Type": "New Type",
                        "Symbol_Name": "new symbol",
                        "Wattage": "1234 W",
                    },
                }
            ],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "<Inst_Type>New Type</Inst_Type>" in patch
        assert "<Symbol_Name>new symbol</Symbol_Name>" in patch
        assert "<Wattage>1234 W</Wattage>" in patch

    def test_type_swap_auto_emits_use_legend_reset(self, fixtures):
        """When Inst_Type changes, the writer must emit <Use_Legend/> to reset
        any stale legend bound to the old symbol. Without this, VW loses
        drawing-wide fixture selectability on import (the selectability bug)."""
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[
                {
                    "uid": sample["uid"],
                    "fields": {"Inst_Type": "New Type", "Symbol_Name": "new"},
                }
            ],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "<Use_Legend/>" in patch

    def test_caller_can_override_use_legend(self, fixtures):
        """If caller explicitly passes Use_Legend, the auto-inject doesn't double up."""
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[
                {
                    "uid": sample["uid"],
                    "fields": {
                        "Inst_Type": "New Type",
                        "Use_Legend": "some-legend-id",
                    },
                }
            ],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        # The caller's value should be present, and the auto-empty should NOT
        # appear (no duplicate Use_Legend elements).
        assert "<Use_Legend>some-legend-id</Use_Legend>" in patch
        assert patch.count("Use_Legend") == 2  # one open tag, one close tag

    def test_no_use_legend_on_non_type_swap(self, fixtures):
        """Field-only edits (no Inst_Type change) must NOT inject Use_Legend."""
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[{"uid": sample["uid"], "fields": {"Channel": "42"}}],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "Use_Legend" not in patch

    def test_empty_string_field_becomes_self_closing(self, fixtures):
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[{"uid": sample["uid"], "fields": {"Use_Legend": ""}}],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "<Use_Legend/>" in patch

    def test_xml_escapes_special_chars(self, fixtures):
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[
                {
                    "uid": sample["uid"],
                    "fields": {"Position": "Stage Left & House <Right>"},
                }
            ],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert "Stage Left &amp; House &lt;Right&gt;" in patch

    def test_refuses_unknown_uid(self, fixtures):
        with pytest.raises(writer.WriteError, match="not found"):
            writer.build_patch(
                changes=[{"uid": "9999.9.9.9.9", "fields": {"Channel": "1"}}],
                source_xml_path=SAMPLE,
                cache_fixtures=fixtures,
            )

    def test_refuses_unknown_field_name(self, fixtures):
        sample = fixtures[0]
        with pytest.raises(writer.WriteError, match="Unknown field"):
            writer.build_patch(
                changes=[{"uid": sample["uid"], "fields": {"NotARealField": "x"}}],
                source_xml_path=SAMPLE,
                cache_fixtures=fixtures,
            )

    def test_refuses_action_in_fields(self, fixtures):
        sample = fixtures[0]
        with pytest.raises(writer.WriteError, match="Action"):
            writer.build_patch(
                changes=[{"uid": sample["uid"], "fields": {"Action": "Delete"}}],
                source_xml_path=SAMPLE,
                cache_fixtures=fixtures,
            )

    def test_refuses_empty_changes(self, fixtures):
        with pytest.raises(writer.WriteError, match="No changes"):
            writer.build_patch(
                changes=[],
                source_xml_path=SAMPLE,
                cache_fixtures=fixtures,
            )

    def test_refuses_empty_fields(self, fixtures):
        sample = fixtures[0]
        with pytest.raises(writer.WriteError, match="no fields"):
            writer.build_patch(
                changes=[{"uid": sample["uid"], "fields": {}}],
                source_xml_path=SAMPLE,
                cache_fixtures=fixtures,
            )

    def test_preserves_vwversion_from_source(self, fixtures):
        sample = fixtures[0]
        patch = writer.build_patch(
            changes=[{"uid": sample["uid"], "fields": {"Channel": "1"}}],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        # celine_sample.xml has VWVersion 3140
        assert "<VWVersion>3140</VWVersion>" in patch

    def test_multi_fixture_patch(self, fixtures):
        a = fixtures[0]
        b = fixtures[1]
        patch = writer.build_patch(
            changes=[
                {"uid": a["uid"], "fields": {"Channel": "1"}},
                {"uid": b["uid"], "fields": {"Channel": "2"}},
            ],
            source_xml_path=SAMPLE,
            cache_fixtures=fixtures,
        )
        assert writer.uid_to_tag(a["uid"]) in patch
        assert writer.uid_to_tag(b["uid"]) in patch
        assert "<Channel>1</Channel>" in patch
        assert "<Channel>2</Channel>" in patch


class TestFindSiblingOfType:
    def test_returns_matching_fixture(self, fixtures):
        sample = fixtures[0]
        result = writer.find_sibling_of_type(fixtures, sample["inst_type"])
        assert result is not None
        assert result["inst_type"] == sample["inst_type"]

    def test_returns_none_for_missing(self, fixtures):
        result = writer.find_sibling_of_type(fixtures, "Definitely Not A Real Type 9999")
        assert result is None
