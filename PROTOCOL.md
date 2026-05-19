# Vectorworks ↔ Lightwright XML Exchange — Protocol Spec

Reverse-engineered specification of the Lightwright Data Exchange XML format Vectorworks Spotlight writes alongside `.vwx` files when "Use automatic Lightwright Data Exchange" is enabled. Decoded end-to-end against VW 2026 in May 2026.

This doc explains what the bytes mean. It's the reference for anyone implementing a tool that reads or writes this XML — Lightwright the application is not required in the loop.

## Goal

Mutate fixture data in a Vectorworks drawing by writing the Lightwright Data Exchange XML directly. VW's file watcher imports the patch and applies it to the drawing (data fields, on-canvas symbol geometry, the lot).

## What we verified

1. **VW full snapshot export → readable baseline.** Trigger via *Spotlight → Preferences → Lightwright → OK* with "Perform a full export…" checked. Produces an XML with `<Action>Entire Plot</Action>` at the top of `<InstrumentData>` and full field data for every fixture.
2. **Field edit, LW → VW.** A 2 KB sparse patch carrying one `<Channel>` change is imported cleanly by VW with no side effects.
3. **Field edit, VW → LW.** VW emits its own delta when fixtures change in the drawing; Lightwright ingests it.
4. **Inst_Type swap, LW → VW.** A patch with `<Inst_Type>` + `<Symbol_Name>` + `<Use_Legend/>` on an existing UID causes VW to swap the on-canvas symbol geometry while preserving UID, position, and unrelated fields.
5. **External hand-crafted patch → VW.** A patch written by a script (no Lightwright running) is imported by VW identically to an LW-emitted patch. **This is the MCP path.**

## Why earlier attempts at writing this protocol failed

If you find this brief because your own attempts didn't work, here's the diagnosis:

- **ElementTree rewrite ("VW ignored the file").** Common hypothesis: ET drops `standalone="no"` from the XML declaration. **Not the issue.** Lightwright itself emits `<?xml version="1.0" encoding="UTF-8"?>` without `standalone="no"` and VW accepts it. The actual cause was usually a virtual-machine FS mount eating FSEvents (see next).
- **Writes via VM mount.** Writes through certain VM mounts (CI runners, containerised dev environments) don't propagate macOS FSEvents to the host, so VW's file watcher never fires. **Write via a native macOS filesystem path.**
- **`osascript` write — VW crashes.** The target `<Symbol_Name>` wasn't in the VW resource library. **The target Symbol_Name must already exist as a resource in the .vwx.** Pre-place one fixture of the target type before patching, or validate the symbol's presence beforehand.
- **Patch import — fixtures became unselectable / disappeared.** A stale Lightwright `.lw6` database carried phantom UIDs and emitted `<Action>Delete</Action>` entries on fixtures that no longer existed in its current view. VW honoured the deletes. **Don't go through Lightwright the application — write to the XML directly against a freshly-read VW snapshot.**

## File envelope

```xml
<?xml version="1.0" encoding="UTF-8"?>                  ← standalone="no" optional; both work
<SLData>
  <Inventory>                                           ← LW-origin marker; VW only writes if "Include inventory" is checked in Spotlight Prefs
    <AppStamp xmlns:xml="http://www.w3.org/XML/1998/namespace">Lightwright</AppStamp>
  </Inventory>
  <ExportFieldList>                                     ← field schema, preserved across writes
    <AppStamp>Vectorworks</AppStamp>
    <TimeStamp>20260519182159</TimeStamp>               ← VW's last full-export time
    <Absolute_Address>Absolute Address</Absolute_Address>
    <Inst_Type>Instrument Type</Inst_Type>
    ... 20 more field-name / display-name pairs ...
  </ExportFieldList>
  <InstrumentData>
    <AppStamp>Lightwright</AppStamp>                    ← writer signature for this section
    <VWVersion>3150</VWVersion>
    <VWBuild>862586</VWBuild>
    <AutoRot2D>false</AutoRot2D>
    <UID_1246_1_1_0_0>                                  ← per-fixture block, tag is UID_<UID with dots replaced by underscores>
      ... fixture fields ...
    </UID_1246_1_1_0_0>
  </InstrumentData>
</SLData>
```

Notes:
- `<Inventory>` block at the top is the LW-origin marker. A tool masquerading as Lightwright should emit it.
- `<ExportFieldList>` defines which fields are exchanged. Configurable in *Spotlight Prefs → Lightwright*. Preserve verbatim from the last VW snapshot.
- `<InstrumentData>` root-level `<AppStamp>` identifies who wrote this section. Use `Lightwright` for write-tool patches.
- `<VWVersion>` and `<VWBuild>` are VW's identifying numbers. Preserve from snapshot.
- Element order within `<InstrumentData>` doesn't matter to VW. LW puts fixture blocks before its header on single-fixture deltas; VW puts header first. Both are accepted.

## Per-fixture block — patch shape

To change fields on an existing fixture:

```xml
<UID_1246_1_1_0_0>
  <Wattage>1250 W</Wattage>                             ← only the fields you're changing
  <Inst_Type>Robe iForte LTX</Inst_Type>
  <Symbol_Name>1826_Spot Robe iForte LTX</Symbol_Name>
  <Use_Legend/>                                          ← reset when type changes
  <Lightwright_ID>155226:2C4:1C:1:Vecto</Lightwright_ID>  ← preserve from snapshot
  <UID>1246.1.1.0.0</UID>                                ← dotted form; matches the tag's underscore form
  <AppStamp>Lightwright</AppStamp>
  <TimeStamp>YYYYMMDDhhmmss</TimeStamp>                  ← UTC time of this write
  <Action>Update</Action>
</UID_1246_1_1_0_0>
```

Rules:
- **`<Action>Update</Action>` means "apply these fields, leave others alone."** Fields not listed are not touched in the drawing.
- **Fields not in the patch are not deleted from the fixture.** Absence is not deletion.
- **Only emit fixtures you're changing.** Untouched fixtures don't need to appear at all.
- **Lightwright_ID and UID must be preserved exactly** from the last VW snapshot. Don't invent them.
- **TimeStamp format:** UTC, `YYYYMMDDhhmmss`, 14 digits, no separators.
- **`xmlns:xml="http://www.w3.org/XML/1998/namespace"` attribute** appears intermittently on changed-field elements in LW's writes. It's non-functional decoration — the `xml:` prefix is implicitly bound by the XML 1.0 spec. Safe to omit on tool writes.

## Per-fixture block — delete

```xml
<UID_1246_1_1_0_0>
  <Action>Delete</Action>
  <UID>1246.1.1.0.0</UID>
  <Lightwright_ID>155226:2C4:1C:1:Vecto</Lightwright_ID>
  <AppStamp>Lightwright</AppStamp>
  <TimeStamp>YYYYMMDDhhmmss</TimeStamp>
</UID_1246_1_1_0_0>
```

VW removes the fixture from the drawing. **Use sparingly and only when intentional.** The "lost two fixtures" failure mode from early protocol-decode attempts was caused by LW emitting Delete actions from a stale database — keep this in mind when designing a write tool.

## Handshake / ack pattern

When a delta is written, the receiver imports it and writes an empty `<InstrumentData>` back as an acknowledgement. The originator's file watcher then sees the empty file and writes its own empty ack. Net 4-message handshake per edit:

```
Originator writes delta  →  receiver imports  →  receiver writes empty ack  →  originator writes empty ack
```

An empty `<InstrumentData>` block (no `<UID_…>` children) is a heartbeat / "all caught up" signal, **NOT** a "drawing emptied" signal. A write tool can write empty acks after observing the receiver's response, but probably doesn't need to — VW seems happy without one.

## Wattage and the frankenfixture risk

When swapping fixture type via `<Inst_Type>` + `<Symbol_Name>`, **Vectorworks does NOT auto-update Wattage from the new symbol's default**. The old wattage carries forward.

Observed result on a type swap (Ayrton EagleStrike 1450W → Robe iForte LTX): correct symbol on canvas, correct Inst_Type label, **wrong wattage (1450W stale)**. Two LTX fixtures sitting side by side, one at 1250W, one at 1450W — paperwork is wrong, electricians will revolt.

**A write tool must emit Wattage explicitly when changing type.** Options for sourcing the target type's wattage, in order of cleanliness:

1. **Read another fixture of the target type already in the drawing** — works only if such a fixture exists; copy its Wattage value verbatim.
2. **Look up VW's symbol record** via a Vectorworks plugin / API — cleanest but requires extra integration.
3. **Static fixture-spec table** — easy to start, drifts over time as fixture libraries change.

The vw-bridge MCP in this repo uses option 1 (`find_fixture_of_type` returns Symbol_Name + Wattage strings to copy into a swap patch).

Same caveat probably applies to other type-derived fields: Device_Type, Voltage, Beam Angle, DMX Footprint, etc. Untested in the original decode session; smoke-test before relying.

## Other constraints learned

- **Target Symbol_Name must already exist as a resource in the .vwx.** If VW can't find the symbol, it faults. Validate or pre-place a fixture of the target type before patching.
- **File writes must go through a native macOS filesystem path** so FSEvents propagate to VW's file watcher. Don't write through VM mounts.
- **Don't go through Lightwright the application.** A stale `.lw6` will inject phantom Deletes. Write patches directly against a freshly-read VW snapshot.
- **VW saves on quit by default in VW 2026.** A "don't save corrupt state" plan needs explicit `File → Close → Don't Save` discipline, not just a quit.

## Write recipe

Minimum viable implementation:

1. **Read current state.** Trigger a full VW snapshot (or use the existing `.xml` if it's current). Parse `<ExportFieldList>` schema and all `<UID_…>` blocks for current UID, Lightwright_ID, type, symbol, wattage, etc.
2. **Plan the change.** What UID(s) to touch, what fields to change. For type swaps: source target type's Symbol_Name (must exist in VW), Wattage, and any other type-derived fields.
3. **Emit the patch.** File envelope (XML decl, SLData, Inventory, copied ExportFieldList, InstrumentData with `<AppStamp>Lightwright</AppStamp>`). For each changed fixture, one `<UID_…>` block with only the changed fields plus the required metadata (Action=Update, TimeStamp, AppStamp=Lightwright, UID, Lightwright_ID).
4. **Write to the XML path** (sibling of the .vwx by default, configurable in Spotlight Prefs). Native filesystem path only.
5. **Wait for VW to ack.** VW will write an empty InstrumentData back when import is done (~1-2 sec). Optionally read the ack to confirm.

The `vw_bridge/writer.py` module in this repo implements this recipe; see source for the reference build.

## Capture pattern for further protocol probing

When studying any file-based inter-app protocol where both apps watch the file, neither side will leave intermediate writes alone long enough to inspect. Use a polling capture loop that snapshots the file on any change:

```bash
#!/bin/bash
TARGET="$1"; DEST_DIR="$(dirname "$TARGET")"
prev_mtime=""; prev_size=""; seq=0
while true; do
  if [ -f "$TARGET" ]; then
    mtime=$(stat -f %m "$TARGET"); size=$(stat -f %z "$TARGET")
    if [ "$mtime" != "$prev_mtime" ] || [ "$size" != "$prev_size" ]; then
      seq=$((seq + 1)); stamp=$(date +%H%M%S)
      cp "$TARGET" "$DEST_DIR/$(basename "$TARGET" .xml).cap_${seq}_${stamp}_${size}B.xml"
      prev_mtime=$mtime; prev_size=$size
    fi
  fi
  sleep 0.1
done
```

100ms tick catches fast handshake exchanges. Filenames embed seq + timestamp + size for easy chronological reading.

## Untested (as of the original decode session)

- Position, Dimmer, Circuit Number, User Fields 1-6, Color, Gobo 1/2 — expected to work identically to Channel/Wattage but unverified end-to-end.
- Text fields with special characters (apostrophes, ampersands, accented UTF-8) — need XML escaping; smoke test before relying.
- Bulk operations on 200+ fixtures in a single patch — expected to scale fine, handshake timing unmeasured.
- Creating brand-new fixtures from a patch (new UID) — Lightwright_ID assignment semantics unclear. Probably easier to pre-place fixtures in VW then patch their fields.

## Why this protocol, not MVR

MVR (GDTF's My Virtual Rig) was considered as a possible alternative — full-state snapshot interchange instead of the LW Exchange's delta-patch model. The LW path won because:

- LW Exchange is real-time, watched, automatic — the write becomes a Vectorworks edit within seconds with no menu interaction.
- MVR is export/import, requires menu commands on both ends, much heavier per change.

MVR remains a reasonable fallback for use cases the LW path doesn't cover (e.g. creating fixtures from scratch, multi-show interchange).

## Further reading

- McKernon troubleshooting: <https://www.mckernon.com/supportmenu/vwdataexchange.html>
- Lightwright user guide (VW exchange): <https://www.lightwright.com/docs/user-guide/14-external-integration/01-vectorworks.html>
