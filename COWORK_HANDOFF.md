# vw-bridge — Cowork session handoff

A practical guide for using vw-bridge's write capability on a real show in a Cowork session. Companion to [README.md](README.md) (tool list, install, swap recipe) and [PROTOCOL.md](PROTOCOL.md) (deep dive on how the XML exchange actually works).

## Pre-flight in a Cowork session

Before writing anything:

1. **Confirm an active plot is loaded** — `get_active_file()`. If it returns no path, call `set_active_plot("show name")` first.
2. **Confirm the user has Vectorworks open on the right .vwx.** Writes go to the XML file alongside the .vwx; if VW isn't running, the patch sits on disk until VW next opens (which is fine, just delayed).
3. **Confirm the user expects the change.** Writes propagate to the on-canvas drawing in seconds. Cmd-Z in VW undoes, but the user shouldn't be surprised.

## The two write patterns

### Pattern A — field-only edit (Channel, Position, Dimmer, User Fields, etc.)

The simplest case. You're changing data fields on existing fixtures without touching the symbol or fixture type.

```python
write_fixture_patch([
    {"uid": "1237.1.1.0.0", "fields": {"Channel": "101"}},
    {"uid": "1244.1.1.0.0", "fields": {"Channel": "102"}},
])
```

Multiple changes in one call is fine and preferred — one patch write, one VW import cycle, one cache refresh.

### Pattern B — fixture type swap (Inst_Type)

Three fields must move together: **Inst_Type, Symbol_Name, Wattage**. Skipping Wattage produces a frankenfixture (new symbol on canvas, stale wattage in paperwork). The writer warns but does not refuse.

> **Important — selectability bug guards added in writer ≥ 2026-05-19 evening:**
>
> A type-swap patch whose `Symbol_Name` doesn't exist in the .vwx resource library causes VW to lose drawing-wide fixture selectability on import (click/marquee do nothing; Cmd-Z reverts). The writer now **hard-refuses** any patch whose `Symbol_Name` isn't in use by some existing fixture in the current snapshot. If you see `Symbol_Name X is not in the drawing's resource library`, ask the user to pre-place one fixture of the target type in VW (an `LX - MCP Example` parking layer is conventional) and retry.
>
> The writer also auto-emits `<Use_Legend/>` whenever `Inst_Type` is in the patch (matches Lightwright's observed behaviour). Defensive — you don't need to pass it explicitly.
>
> See `PROTOCOL.md` for the full diagnosis. The first symptom of this bug on Celine Dion 2026-05-19 was selectability loss after a 3-fixture MCP swap whose target symbols weren't in the resource library.
>
> **Critical:** if this validation is ever bypassed and the bug occurs, **a follow-up MCP patch cannot fix it.** The damage lives in the .vwx binary layer, below the LW Exchange protocol. Recovery requires a .vwx backup from before the corrupting save. Don't try to "patch your way out" — restore the file.

```python
# 1. Verify the target type already exists in the drawing.
target = find_fixture_of_type("Robe iForte LTX")
if not target["found"]:
    # The symbol probably isn't in VW's resource library.
    # The writer will hard-refuse if Symbol_Name isn't in current fixtures
    # — stop here and ask the user to pre-place one Robe iForte LTX in VW.
    return "Pre-place a Robe iForte LTX in VW first."

# 2. Write the swap.
write_fixture_patch([
    {
        "uid": "1246.1.1.0.0",
        "fields": {
            "Inst_Type": target["inst_type"],
            "Symbol_Name": target["symbol_name"],
            "Wattage": target["wattage"],
        },
    }
])
```

For **bulk swaps** ("swap all Ayrtons on Truss 1 to LTXes"):

```python
# Find candidates
rows = get_channels(inst_type="Ayrton EagleStrike", layer="Truss 1")["channels"]
candidates = [r for r in rows]  # or filter further by some user criterion

# Get target type's reference data once
target = find_fixture_of_type("Robe iForte LTX")
if not target["found"]:
    return "Pre-place a Robe iForte LTX in VW first."

# One patch with N fixtures
changes = [
    {
        "uid": _resolve_uid_for_channel_row(r),  # use get_fixture_details / cross-reference
        "fields": {
            "Inst_Type": target["inst_type"],
            "Symbol_Name": target["symbol_name"],
            "Wattage": target["wattage"],
        },
    }
    for r in candidates
]
write_fixture_patch(changes)
```

Note that `get_channels` doesn't return UIDs directly today — you'll either need to add UID to its output or look up by other means. (TODO worth picking up: thread UIDs through the channel listing.)

## Verifying changes

After a write, the cache refreshes automatically when VW next has focus and the watcher fires. To verify:

1. Have the user switch focus to VW. The on-canvas fixtures should update visibly.
2. Then back to Claude. The cache should reflect the new state. `get_fixture_details(uid)` will show the changed fields.

If you need to confirm before the user switches away, `get_active_file()` shows `parsed_at` — if it's older than your write time, VW hasn't picked it up yet.

## Common failure modes and what they mean

| Error from `write_fixture_patch` | What it means | Recovery |
|---|---|---|
| `UID X not found in current XML` | Cache is stale or you typo'd the UID | Refresh: have user switch to VW and back. Re-check with `get_fixture_details(uid)`. |
| `Unknown field 'X'` | Field name typo. The writer's KNOWN_DATA_FIELDS lists what's valid | Check the brief or `writer.KNOWN_DATA_FIELDS`. Common ones: Inst_Type, Symbol_Name, Wattage, Channel, Position, Dimmer, Color, Purpose, User_Field_1..6. |
| `Action` rejected | You tried to set Action directly (probably trying Delete) | The writer is patch-only. Deletes are not exposed — they need a different conversation with the user. |
| `Source XML missing <ExportFieldList>` | The active file isn't a valid Lightwright Data Exchange XML | Verify VW's Spotlight Prefs has "Use automatic Lightwright Data Exchange" enabled, and that the file you set as active is the .xml VW writes. |

## What NOT to do

- **Don't issue Deletes.** The writer refuses; if you find yourself wanting to delete fixtures from outside VW, stop and talk to the user. Deletion in VW is destructive and the LW exchange protocol's delete semantics are dangerous (the failed early attempts in the brief).
- **Don't use Lightwright the application alongside this MCP.** Lightwright will maintain its own .lw6 database that gets out of sync with the MCP's writes, and on next "Update Vectorworks" from LW it'll inject phantom Deletes to "fix" the discrepancy. The MCP path replaces Lightwright, not augments it.
- **Don't write to a Cowork VM mount path.** Writes must go through a native macOS path so FSEvents propagate to VW's file watcher. The MCP runs locally so this is handled, but be aware if you ever extend the architecture.
- **Don't auto-write on every chat turn.** Writes have side effects in the user's drawing. Confirm intent before issuing them, especially for type swaps and bulk operations.

## Limits, untested cases

We haven't (as of 2026-05-19) tested:
- Creating brand-new fixtures via patch (only modifying existing). Probably possible by emitting a new UID, but Lightwright_ID assignment and UID conflict avoidance need real testing.
- Text fields with apostrophes, ampersands, or accented characters. The writer escapes via `xml.sax.saxutils.escape` so it should be safe, but no end-to-end VW import test yet.
- Bulk operations on 100+ fixtures in one patch — handshake timing may matter.
- Cross-show interactions if the user has multiple .vwx open in different VW windows.

If you hit any of these in a real Cowork session, capture the patch you tried to write + VW's response, and update the brief.
