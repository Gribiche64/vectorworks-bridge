"""Parser for the Vectorworks Lightwright Data Exchange XML format.

The XML schema (discovered, not officially documented):

    <SLData>
      <ExportFieldList>...</ExportFieldList>
      <InstrumentData>
        <Action>Entire Plot</Action>
        <AppStamp>...</AppStamp>
        <VWVersion>...</VWVersion>
        <UID_1687_1_1_0_1>          ← one element per fixture, tag includes UID
          <UID>1687.1.1.0.1</UID>
          <Device_Type>Light</Device_Type>
          <Layer>Lighting - Overhead</Layer>
          <Inst_Type>Martin MAC Aura XIP</Inst_Type>
          <Channel>101</Channel>
          <Dimmer>1</Dimmer>
          <Absolute_Address>1</Absolute_Address>
          <Position>Truss 1</Position>
          <Purpose>Wash</Purpose>
          <Color>R132</Color>
          <Wattage>340W</Wattage>          ← string with unit suffix
          <Unit_Number>1</Unit_Number>
          <Symbol_Name>Martin MAC Aura XIP</Symbol_Name>
          <Class>3 Lighting - Floor</Class>
          <System>A</System>
          <X_Location_mm>...</X_Location_mm>
          <Y_Location_mm>...</Y_Location_mm>
          <Z_Location_mm>...</Z_Location_mm>
          <Accessories>
            <UID_1687_1_1_1_1>        ← nested static accessories (clamps etc.)
              <Device_Type>Static Accessory</Device_Type>
              ...
            </UID_1687_1_1_1_1>
          </Accessories>
        </UID_1687_1_1_0_1>
        ...
      </InstrumentData>
    </SLData>

We only care about top-level UID blocks under InstrumentData whose Device_Type is
in FIXTURE_DEVICE_TYPES — the Static Accessories nested inside <Accessories>
are clamps and gel frames, not fixtures.

Universe is computed from Absolute_Address (DMX): universe = (addr - 1) // 512 + 1.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# Top-level device types we count as fixtures. Static Accessory is nested inside
# the parent fixture's <Accessories> block and is intentionally excluded.
FIXTURE_DEVICE_TYPES = {"Light", "Moving Light", "SFX"}

# Fields we copy verbatim (string, may be empty). Empty becomes None.
STRING_FIELDS = (
    "UID",
    "Device_Type",
    "Symbol_Name",
    "Inst_Type",
    "Layer",
    "Class",
    "Unit_Number",
    "Channel",
    "Dimmer",
    "Position",
    "Purpose",
    "Color",
    "Template",       # Gobo 1
    "Template2",      # Gobo 2
    "Circuit_Name",
    "Circuit_Number",
    "System",
    "Mark",
    "Focus",
    "Lightwright_ID",
)

NUMERIC_FIELDS = (
    "X_Location_mm",
    "Y_Location_mm",
    "Z_Location_mm",
    "Rotation",
)


class ParseError(Exception):
    """Raised when the XML can't be parsed at all (vs. partially)."""


def parse_file(path: Path) -> list[dict[str, Any]]:
    """Parse a Lightwright Data Exchange XML and return one dict per fixture."""
    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise ParseError(f"XML parse failed: {e}") from e

    root = tree.getroot()
    instrument_data = root.find("InstrumentData")
    if instrument_data is None:
        raise ParseError("Missing <InstrumentData> element")

    fixtures: list[dict[str, Any]] = []
    for child in instrument_data:
        # Only top-level UID_* elements are fixtures. Skip Action, AppStamp, etc.
        if not child.tag.startswith("UID_"):
            continue
        device_type = _text(child.find("Device_Type"))
        if device_type not in FIXTURE_DEVICE_TYPES:
            continue
        fixtures.append(_parse_fixture(child))

    return fixtures


def _parse_fixture(elem: ET.Element) -> dict[str, Any]:
    """Convert one <UID_...> element to a normalised dict."""
    fixture: dict[str, Any] = {}

    for field in STRING_FIELDS:
        fixture[field.lower()] = _text(elem.find(field))

    for field in NUMERIC_FIELDS:
        fixture[field.lower()] = _to_float(_text(elem.find(field)))

    # Wattage is a string like "700 W", "340W", "2800 W" — extract the number.
    fixture["wattage_w"] = _parse_wattage(_text(elem.find("Wattage")))

    # Absolute_Address is a DMX address as integer (or "0"/"" for unpatched).
    addr = _to_int(_text(elem.find("Absolute_Address")))
    fixture["absolute_address"] = addr if (addr or 0) > 0 else None
    fixture["universe"] = _universe_from_address(fixture["absolute_address"])

    # Accessories — list of nested static accessories with their own inst_type.
    fixture["accessories"] = _parse_accessories(elem.find("Accessories"))

    # Boolean: is this fixture actually patched?
    fixture["is_patched"] = (
        fixture["absolute_address"] is not None
        or _to_int(fixture.get("dimmer")) is not None
    )

    return fixture


def _parse_accessories(acc_elem: ET.Element | None) -> list[dict[str, Any]]:
    if acc_elem is None:
        return []
    result = []
    for child in acc_elem:
        if not child.tag.startswith("UID_"):
            continue
        result.append(
            {
                "uid": _text(child.find("UID")),
                "device_type": _text(child.find("Device_Type")),
                "inst_type": _text(child.find("Inst_Type")),
                "symbol_name": _text(child.find("Symbol_Name")),
            }
        )
    return result


def _text(elem: ET.Element | None) -> str | None:
    """Element text, treating empty/whitespace as None."""
    if elem is None:
        return None
    txt = elem.text
    if txt is None:
        return None
    txt = txt.strip()
    return txt or None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        # Try float-then-int (some VW versions write "1.0" for ints)
        try:
            return int(float(value))
        except ValueError:
            return None


_WATTAGE_RE = re.compile(r"(\d+(?:\.\d+)?)")


def _parse_wattage(value: str | None) -> float | None:
    """Extract numeric watts from strings like '700 W', '340W', '2.8kW'.

    Handles 'kW' suffix by multiplying by 1000.
    """
    if value is None:
        return None
    m = _WATTAGE_RE.search(value)
    if not m:
        return None
    n = float(m.group(1))
    if "kw" in value.lower():
        n *= 1000
    return n


def _universe_from_address(addr: int | None) -> int | None:
    """DMX universe from absolute address (1-indexed, 512 channels per universe)."""
    if addr is None or addr <= 0:
        return None
    return (addr - 1) // 512 + 1
