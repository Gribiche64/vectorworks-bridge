# vw-bridge

MCP server that exposes Vectorworks Spotlight fixture data to Claude Code Co-Work sessions. Watches the Lightwright Data Exchange XML file that Vectorworks writes alongside `.vwx` files, parses it, and serves queries (counts per layer, channels, weights, plot QC).

No manual export step — VW writes the XML automatically whenever focus switches away from VW.

## One-time Vectorworks setup

1. Open any plot in Vectorworks
2. **File ▸ Document Settings ▸ Spotlight Preferences ▸ Lightwright tab**
3. Tick **"Use automatic Lightwright Data Exchange"**
4. Save the XML file in the same folder as the `.vwx`
5. Move all desired fields (Inst Type, Channel, Universe, Position, Purpose, Color, Weight, Wattage, Unit Number) from "Available Fields" to "Export Fields"
6. Click **Save as default** so all future files use this configuration

You don't need to own Lightwright — this is a built-in VW feature that just writes XML.

## Install

```bash
make install   # installs into ~/.config/vw-bridge/venv
```

## Register with Claude Code

From the directory you cloned this repo into:

```bash
claude mcp add vw-bridge -- uv run --directory "$(pwd)" python -m vw_bridge.server
```

Or with an explicit path:

```bash
claude mcp add vw-bridge -- uv run --directory /path/to/vectorworks-bridge python -m vw_bridge.server
```

## Tools

| Tool | What it does |
|---|---|
| `set_active_file` | Point the watcher at a specific `.xml` (current show) |
| `set_active_plot` | Switch by show name (fuzzy match against folder names) |
| `list_plots` | List Lightwright XML files under the shows root, newest first |
| `get_active_file` | Show watched file + last update timestamp |
| `get_fixture_counts` | Counts per fixture type, optional layer filter |
| `get_fixture_summary` | Grand totals: count, weight, wattage |
| `get_layers` | Per-layer rollup |
| `get_channels` | Channel/universe list, filterable |
| `get_equipment_list` | Rental-ready rollup |
| `plot_qc` | Audit: duplicate channels, missing addresses, unpatched fixtures |
| `get_fixture_details` | Full parsed data for one fixture by UID — use before planning a write |
| `find_fixture_of_type` | Find a sibling fixture of a given Inst_Type — source Symbol_Name + Wattage for type swaps |
| `write_fixture_patch` | **Write changes back to VW** — emits an LW-style patch the file watcher picks up |

## Usage in a Co-Work session

```
You: How many VL3600 IPs do I have on Truss 1?
Claude: [calls get_fixture_counts(layer="Truss 1")] You have 12 VL3600 IPs on Truss 1.
```

When you make changes in VW and switch focus to Claude Code, the data refreshes automatically.

## Development

```bash
make dev    # installs dev deps into .venv
make test   # runs pytest
make lint   # runs ruff
```

## Write-back (added 2026-05-19)

The MCP now writes patches directly to the Lightwright Data Exchange XML — Vectorworks' file watcher picks them up and applies the changes. No Lightwright application, no Python-in-VW script required.

**Recipe for a fixture type swap:**

```python
# 1. Find an existing fixture of the target type (gives you Symbol_Name + Wattage)
target = find_fixture_of_type("Robe iForte LTX")
# {"found": True, "count": 4, "symbol_name": "1826_Spot Robe iForte LTX",
#  "wattage": "1250 W", "sample_uid": "1244.1.1.0.0"}

# 2. Confirm the source fixture
src = get_fixture_details("1246.1.1.0.0")
# {"found": True, "fixture": {"inst_type": "Ayrton EagleStrike", ...}}

# 3. Write the patch
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

VW will apply the change when it next gains focus: the on-canvas symbol swaps, the data fields update, the watcher refreshes the cache.

**Safety:** the writer refuses Delete operations, unknown field names, and UIDs not in the current snapshot. It warns (does not refuse) when Inst_Type changes without Wattage — the "frankenfixture" risk where the symbol swaps but the wattage stays stale.

**Protocol spec:** see [PROTOCOL.md](PROTOCOL.md) for the full reverse-engineered protocol, the LW-vs-VW writer asymmetry, and known constraints (native FS path required for FSEvents, symbol must exist in resource library, etc.).
