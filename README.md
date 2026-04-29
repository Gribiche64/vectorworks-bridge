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

```bash
claude mcp add vw-bridge -- uv run --directory ~/Documents/Vibe\ coding/vw-bridge python -m vw_bridge.server
```

## Tools

| Tool | What it does |
|---|---|
| `set_active_file` | Point the watcher at a specific `.xml` (current show) |
| `get_active_file` | Show watched file + last update timestamp |
| `get_fixture_counts` | Counts per fixture type, optional layer filter |
| `get_fixture_summary` | Grand totals: count, weight, wattage |
| `get_layers` | Per-layer rollup |
| `get_channels` | Channel/universe list, filterable |
| `get_equipment_list` | Rental-ready rollup |
| `plot_qc` | Audit: duplicate channels, missing addresses, unpatched fixtures |

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

## Phase 2 (future)

Write-back: a Vectorworks Python script that reads a changes file from this server and applies fixture swaps by layer. Deferred until the read pipeline is solid.
