"""Writer for the Vectorworks Lightwright Data Exchange XML format.

Emits Lightwright-style patches that VW's file watcher picks up and applies to the
drawing. See `~/Documents/Shows/26_309_Celine Dion/1. CAD/VW_XML_EXCHANGE_BRIEF.md`
for the full protocol spec.

Patch shape:

    <SLData>
      <Inventory>
        <AppStamp xmlns:xml="...">Lightwright</AppStamp>
      </Inventory>
      <ExportFieldList>...copied verbatim from current XML...</ExportFieldList>
      <InstrumentData>
        <UID_1246_1_1_0_0>
          <Inst_Type>Robe iForte LTX</Inst_Type>
          <Symbol_Name>1826_Spot Robe iForte LTX</Symbol_Name>
          <Wattage>1250 W</Wattage>
          <Use_Legend/>
          <Lightwright_ID>preserved-from-baseline</Lightwright_ID>
          <UID>1246.1.1.0.0</UID>
          <AppStamp>Lightwright</AppStamp>
          <TimeStamp>YYYYMMDDhhmmss</TimeStamp>
          <Action>Update</Action>
        </UID_1246_1_1_0_0>
        <AppStamp>Lightwright</AppStamp>
        <VWVersion>3150</VWVersion>
        <VWBuild>862586</VWBuild>
        <AutoRot2D>false</AutoRot2D>
      </InstrumentData>
    </SLData>

Receiver semantics: VW applies the listed fields to the matching UID, leaves all
other fields untouched. Fixtures not mentioned in the patch are not affected.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape


class WriteError(Exception):
    """Raised when a patch can't be built or written."""


# Fields the protocol expects in the per-fixture metadata block. Validated against
# this list to catch typos in caller-supplied field names.
KNOWN_DATA_FIELDS = {
    "Absolute_Address",
    "Inst_Type",
    "Unit_Number",
    "Template2",
    "Template",
    "Color",
    "Circuit_Name",
    "Circuit_Number",
    "Dimmer",
    "Channel",
    "Position",
    "Wattage",
    "Purpose",
    "User_Field_1",
    "User_Field_2",
    "User_Field_3",
    "User_Field_4",
    "User_Field_5",
    "User_Field_6",
    "System",
    "Mark",
    "Symbol_Name",
    "Layer",
    "Class",
    "Focus",
    "Use_Legend",
    "Device_Type",
}


def utc_timestamp() -> str:
    """Format current UTC as YYYYMMDDhhmmss (no separators, the LW convention)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def uid_to_tag(uid: str) -> str:
    """Convert dotted UID '1246.1.1.0.0' to the tag form 'UID_1246_1_1_0_0'."""
    return "UID_" + uid.replace(".", "_")


def _extract_block(xml_text: str, tag: str) -> str | None:
    """Return the verbatim text of <tag>...</tag> from xml_text, or None if missing."""
    pattern = re.compile(rf"<{re.escape(tag)}\b.*?</{re.escape(tag)}>", re.DOTALL)
    m = pattern.search(xml_text)
    return m.group(0) if m else None


def _extract_simple(xml_text: str, tag: str) -> str | None:
    """Return inner text of first <tag>...</tag>, or None."""
    m = re.search(rf"<{re.escape(tag)}\b[^>]*>([^<]*)</{re.escape(tag)}>", xml_text)
    return m.group(1) if m else None


def build_patch(
    changes: list[dict],
    source_xml_path: Path,
    cache_fixtures: list[dict],
) -> str:
    """Build an LW-style patch from a list of changes.

    Args:
        changes: list of dicts, each with:
            - "uid": dotted form, e.g. "1246.1.1.0.0"
            - "fields": dict of XML field name -> string value
              (e.g. {"Inst_Type": "Robe iForte LTX", "Wattage": "1250 W"})
        source_xml_path: path to the current XML (used to copy ExportFieldList + VWVersion)
        cache_fixtures: parser.py output (used to resolve Lightwright_ID per UID)

    Returns:
        The patch as an XML string, ready to write.

    Raises:
        WriteError if any UID is not found in cache, any field name is unknown,
        or any change tries to issue a Delete.
    """
    if not changes:
        raise WriteError("No changes to apply.")

    if not source_xml_path.exists():
        raise WriteError(f"Source XML not found: {source_xml_path}")

    xml_text = source_xml_path.read_text()

    # Index cache by UID for Lightwright_ID lookup.
    by_uid = {f.get("uid"): f for f in cache_fixtures if f.get("uid")}

    # Copy ExportFieldList + VWVersion / VWBuild from the source.
    export_field_list = _extract_block(xml_text, "ExportFieldList")
    if not export_field_list:
        raise WriteError("Source XML missing <ExportFieldList>")
    vw_version = _extract_simple(xml_text, "VWVersion") or "3150"
    vw_build = _extract_simple(xml_text, "VWBuild") or "862586"

    ts = utc_timestamp()

    # Set of Symbol_Names known to exist in the drawing's resource library
    # (proxied by "at least one fixture currently uses this Symbol_Name").
    # Used to validate type-swap targets — see Attempt 3 in PROTOCOL.md.
    existing_symbols = {
        f.get("symbol_name")
        for f in cache_fixtures
        if f.get("symbol_name")
    }

    # Validate every change before emitting any of them.
    for ch in changes:
        uid = ch.get("uid")
        fields = ch.get("fields") or {}
        if not uid:
            raise WriteError(f"Change missing 'uid': {ch}")
        if not fields:
            raise WriteError(f"Change for UID {uid} has no fields to update.")
        if uid not in by_uid:
            raise WriteError(
                f"UID {uid} not found in current XML. Refresh the cache or "
                f"check the UID."
            )
        for name in fields:
            if name not in KNOWN_DATA_FIELDS:
                raise WriteError(
                    f"Unknown field '{name}' for UID {uid}. Known fields: "
                    f"{sorted(KNOWN_DATA_FIELDS)}"
                )
            if name == "Action":
                raise WriteError(
                    f"UID {uid}: writes must not set <Action> directly. "
                    f"The writer emits Action=Update; Delete is intentionally "
                    f"unsupported."
                )

        # Symbol_Name validation — the target symbol MUST exist in the
        # drawing's resource library. We proxy that by "at least one current
        # fixture uses this Symbol_Name." If you're swapping to a symbol that
        # isn't currently in use, pre-place one fixture of that type in VW
        # first (an "LX - MCP Example" parking layer is the conventional spot).
        #
        # Failure mode if we don't catch this: VW imports the patch, can't
        # resolve the Symbol_Name against any loaded resource, leaves fixtures
        # in a half-broken state with dangling symbol references — visually
        # the swap may or may not appear, but the broken refs cascade into
        # VW's selection hit-test and break selectability drawing-wide. This
        # is the Attempt 3 / 4 failure mode from PROTOCOL.md, observed again
        # via the MCP path on 26_309 Celine Dion on 2026-05-19.
        target_symbol = fields.get("Symbol_Name")
        if target_symbol and target_symbol not in existing_symbols:
            raise WriteError(
                f"UID {uid}: target Symbol_Name {target_symbol!r} is not in "
                f"the drawing's resource library (no existing fixture uses "
                f"it). Pre-place at least one fixture of the target type in "
                f"VW (e.g. on an 'LX - MCP Example' layer) before swapping. "
                f"If you used find_fixture_of_type() to source the symbol "
                f"name, it would have surfaced count=0 with a hint about "
                f"this — re-check that path."
            )

    # Build the fixture blocks.
    fixture_blocks = []
    for ch in changes:
        uid = ch["uid"]
        fields = dict(ch["fields"])  # copy so we can augment
        lwid = by_uid[uid].get("lightwright_id") or ""
        tag = uid_to_tag(uid)

        # Type-swap protocol detail: when Inst_Type changes, Lightwright always
        # emits an empty <Use_Legend/> element to reset any custom legend
        # attached to the old symbol. Observed in Test.cap_8/9/10 during the
        # original protocol decode. Omitting it caused VW to lose drawing-wide
        # fixture selectability on import (hypothesis: VW's selection hit-test
        # references legend geometry, which after a symbol swap points at
        # geometry that no longer exists). Auto-inject if caller didn't.
        if "Inst_Type" in fields and "Use_Legend" not in fields:
            fields["Use_Legend"] = ""  # empty → self-closing tag

        lines = [f"    <{tag}>"]
        for name, value in fields.items():
            if value is None or value == "":
                lines.append(f"      <{name}/>")
            else:
                lines.append(f"      <{name}>{xml_escape(str(value))}</{name}>")
        lines.append(f"      <Lightwright_ID>{xml_escape(lwid)}</Lightwright_ID>")
        lines.append(f"      <UID>{xml_escape(uid)}</UID>")
        lines.append("      <AppStamp>Lightwright</AppStamp>")
        lines.append(f"      <TimeStamp>{ts}</TimeStamp>")
        lines.append("      <Action>Update</Action>")
        lines.append(f"    </{tag}>")
        fixture_blocks.append("\n".join(lines))

    # Compose the document.
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<SLData>",
        "  <Inventory>",
        '    <AppStamp xmlns:xml="http://www.w3.org/XML/1998/namespace">Lightwright</AppStamp>',
        "  </Inventory>",
        # ExportFieldList copied verbatim; pad to keep indentation consistent.
        "  " + export_field_list.strip().replace("\n", "\n  "),
        "  <InstrumentData>",
        *fixture_blocks,
        "    <AppStamp>Lightwright</AppStamp>",
        f"    <VWVersion>{vw_version}</VWVersion>",
        f"    <VWBuild>{vw_build}</VWBuild>",
        "    <AutoRot2D>false</AutoRot2D>",
        "  </InstrumentData>",
        "</SLData>",
        "",
    ]
    return "\n".join(parts)


def write_patch(xml_path: Path, patch_xml: str) -> int:
    """Write a patch to the XML path. Returns bytes written.

    Uses a direct write (no atomic rename) so VW's file watcher fires on the
    modification of the existing path rather than a replace. FSEvents triggers
    on close-after-write for the original inode.
    """
    if not xml_path.parent.exists():
        raise WriteError(f"Parent dir doesn't exist: {xml_path.parent}")
    xml_path.write_text(patch_xml)
    return len(patch_xml.encode("utf-8"))


def find_sibling_of_type(
    fixtures: list[dict], inst_type: str
) -> dict | None:
    """Find a fixture in the cache whose Inst_Type matches (exact, case-sensitive).

    Useful for sourcing Symbol_Name and Wattage values when planning a type swap:
    'I want UID X to become a Robe iForte LTX — find me any existing LTX fixture
    so I can copy its Symbol_Name and Wattage.'

    Returns the first match (a parsed fixture dict from parser.py), or None.
    """
    for f in fixtures:
        if f.get("inst_type") == inst_type:
            return f
    return None
