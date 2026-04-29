"""MCP server — exposes Vectorworks fixture data to Claude Code Co-Work sessions.

Reads from the in-memory Cache that the Watcher keeps fresh. All tools return
JSON-serialisable data. Tools that need fixture data refuse politely if no file
is being watched yet, pointing the caller at `set_active_file`.

Run via stdio:

    python -m vw_bridge.server
"""

from __future__ import annotations

import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from . import config as cfg
from . import discovery
from .cache import Cache, FixtureData
from .watcher import Watcher

log = logging.getLogger("vw-bridge")

# Singleton cache + watcher. FastMCP doesn't have a great place to stash these,
# so module-level it is.
_cache = Cache()
_watcher = Watcher(_cache)

mcp = FastMCP("vw-bridge")


# ─── helpers ──────────────────────────────────────────────────────────────────

def _require_loaded() -> FixtureData | dict[str, str]:
    """Return current snapshot, or an error-shaped dict if no file is loaded."""
    if not _cache.is_loaded():
        return {
            "error": (
                "No active plot. Call list_plots to see recent plots, or "
                "set_active_plot('show name') to switch by show, or "
                "set_active_file(path) for a specific XML path."
            )
        }
    return _cache.snapshot()


def _watch_candidate(candidate: discovery.PlotCandidate) -> dict[str, Any]:
    """Start watching a candidate's XML and persist the choice."""
    try:
        _watcher.watch(candidate.xml_path)
    except Exception as e:
        return {"error": f"Failed to watch {candidate.xml_path}: {e}"}
    cfg.save_active_file(candidate.xml_path)
    snap = _cache.snapshot()
    return {
        "show_folder": candidate.show_folder,
        "active_file": str(candidate.xml_path),
        "fixtures_loaded": len(snap.fixtures),
        "parsed_at": _format_timestamp(snap.parsed_at),
        "modified_at": candidate.to_dict()["modified_at"],
    }


def _format_timestamp(ts: datetime | None) -> str | None:
    return ts.isoformat(timespec="seconds") if ts else None


def _filter_fixtures(
    snapshot: FixtureData,
    layer: str | None = None,
    inst_type: str | None = None,
    include_old: bool = False,
) -> list[dict[str, Any]]:
    fixtures = snapshot.fixtures
    if not include_old:
        fixtures = [f for f in fixtures if (f.get("layer") or "").upper() != "OLD"]
    if layer is not None:
        fixtures = [f for f in fixtures if f.get("layer") == layer]
    if inst_type is not None:
        fixtures = [f for f in fixtures if f.get("inst_type") == inst_type]
    return fixtures


# ─── tools: file management ───────────────────────────────────────────────────

@mcp.tool()
def set_active_file(path: str) -> dict[str, Any]:
    """Point the watcher at a Lightwright Data Exchange XML file.

    The file is the .xml that Vectorworks writes alongside your .vwx (in the
    same folder) when "Use automatic Lightwright Data Exchange" is enabled in
    Spotlight Preferences. It updates whenever you switch focus away from
    Vectorworks.
    """
    p = Path(path).expanduser()
    if not p.exists():
        return {"error": f"File not found: {p}"}
    if p.suffix.lower() != ".xml":
        return {"error": f"Not an XML file: {p}"}
    try:
        _watcher.watch(p)
    except Exception as e:
        return {"error": f"Failed to watch {p}: {e}"}
    cfg.save_active_file(p)
    snap = _cache.snapshot()
    return {
        "active_file": str(p),
        "fixtures_loaded": len(snap.fixtures),
        "parsed_at": _format_timestamp(snap.parsed_at),
    }


@mcp.tool()
def get_active_file() -> dict[str, Any]:
    """Show which XML file is being watched and when it was last parsed."""
    snap = _cache.snapshot()
    return {
        "active_file": str(snap.source_path) if snap.source_path else None,
        "parsed_at": _format_timestamp(snap.parsed_at),
        "fixtures_loaded": len(snap.fixtures),
        "parse_error": snap.parse_error,
    }


@mcp.tool()
def list_plots(limit: int = 10) -> dict[str, Any]:
    """List Lightwright XML files under the shows root, newest first.

    Each entry has show_folder, xml_path, vwx_path, modified_at.
    Useful for picking which plot to watch when you have multiple shows
    open or when set_active_plot returns ambiguous matches.
    """
    candidates = discovery.find_plots()
    collapsed = discovery.most_recent_plot_per_show(candidates)
    plots = [c.to_dict() for c in collapsed[:limit]]
    return {
        "shows_root": str(cfg.load_shows_root()),
        "total_shows_with_plots": len(collapsed),
        "plots": plots,
    }


@mcp.tool()
def set_active_plot(show_name: str) -> dict[str, Any]:
    """Switch the active plot by show name (fuzzy-matched against folder names).

    Examples: 'Celine', 'Eternal Sunshine', 'Hilary Duff'. Picks the most
    recently-modified XML in the matching show's folder.
    """
    candidates = discovery.find_plots()
    if not candidates:
        return {
            "error": (
                f"No plots found under {cfg.load_shows_root()}. "
                "Make sure 'Use automatic Lightwright Data Exchange' is enabled "
                "in Vectorworks Spotlight Preferences and that your show folder "
                "lives under that root."
            )
        }

    matches = discovery.fuzzy_match_show(show_name, candidates)
    if not matches:
        return {
            "error": f"No show matched '{show_name}'.",
            "available_shows": sorted(
                {c.show_folder for c in candidates}
            ),
        }

    # Collapse to one match per show, then pick newest.
    collapsed = discovery.most_recent_plot_per_show(matches)
    if len(collapsed) > 1:
        return {
            "error": f"Ambiguous match for '{show_name}'. Pick a more specific name.",
            "matched_shows": [c.to_dict() for c in collapsed],
        }

    return _watch_candidate(collapsed[0])


# ─── tools: queries ───────────────────────────────────────────────────────────

@mcp.tool()
def get_fixture_counts(
    layer: str | None = None,
    include_old: bool = False,
) -> dict[str, Any]:
    """Counts of each fixture type, optionally scoped to one layer.

    By default the "OLD" parking layer is excluded. Pass include_old=True to
    include it.
    """
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(snap, layer=layer, include_old=include_old)
    counts = Counter(f.get("inst_type") or "(unknown)" for f in fixtures)
    return {
        "layer": layer,
        "total": sum(counts.values()),
        "counts": dict(counts.most_common()),
    }


@mcp.tool()
def get_fixture_summary(include_old: bool = False) -> dict[str, Any]:
    """Grand totals: fixture count, total wattage, layer count, device-type breakdown."""
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(snap, include_old=include_old)
    total_wattage = sum(f.get("wattage_w") or 0 for f in fixtures)
    by_device = Counter(f.get("device_type") or "(unknown)" for f in fixtures)
    layers = sorted({f.get("layer") for f in fixtures if f.get("layer")})
    return {
        "total_fixtures": len(fixtures),
        "total_wattage_w": total_wattage,
        "total_wattage_kw": round(total_wattage / 1000, 2),
        "by_device_type": dict(by_device),
        "layers": layers,
        "fixture_types": len({f.get("inst_type") for f in fixtures if f.get("inst_type")}),
        "source_file": str(snap.source_path) if snap.source_path else None,
        "parsed_at": _format_timestamp(snap.parsed_at),
    }


@mcp.tool()
def get_layers(include_old: bool = False) -> dict[str, Any]:
    """Per-layer rollup: fixture count, wattage, and unique fixture types."""
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(snap, include_old=include_old)
    by_layer: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "wattage_w": 0.0, "types": Counter()}
    )
    for f in fixtures:
        layer = f.get("layer") or "(no layer)"
        by_layer[layer]["count"] += 1
        by_layer[layer]["wattage_w"] += f.get("wattage_w") or 0
        by_layer[layer]["types"][f.get("inst_type") or "(unknown)"] += 1

    result = []
    for layer, info in sorted(by_layer.items()):
        result.append(
            {
                "layer": layer,
                "count": info["count"],
                "wattage_w": info["wattage_w"],
                "wattage_kw": round(info["wattage_w"] / 1000, 2),
                "types": dict(info["types"].most_common()),
            }
        )
    return {"layers": result}


@mcp.tool()
def get_channels(
    layer: str | None = None,
    inst_type: str | None = None,
    include_old: bool = False,
) -> dict[str, Any]:
    """Channel + DMX address listing, filterable by layer and/or fixture type.

    Includes only patched fixtures. Each entry has channel, dimmer, absolute
    address, universe, layer, position, inst_type.
    """
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(
        snap, layer=layer, inst_type=inst_type, include_old=include_old
    )
    patched = [f for f in fixtures if f.get("is_patched")]
    rows = [
        {
            "channel": f.get("channel"),
            "dimmer": f.get("dimmer"),
            "absolute_address": f.get("absolute_address"),
            "universe": f.get("universe"),
            "layer": f.get("layer"),
            "position": f.get("position"),
            "inst_type": f.get("inst_type"),
            "unit_number": f.get("unit_number"),
        }
        for f in patched
    ]
    rows.sort(key=lambda r: (r.get("absolute_address") or 0, r.get("channel") or ""))
    return {
        "filtered_total": len(fixtures),
        "patched_total": len(patched),
        "channels": rows,
    }


@mcp.tool()
def get_equipment_list(include_old: bool = False) -> dict[str, Any]:
    """Rental-style rollup: fixture type, quantity, total wattage.

    Sorted by quantity descending. Includes accessories (clamps, gel frames)
    aggregated separately.
    """
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(snap, include_old=include_old)

    by_type: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"qty": 0, "wattage_w": 0.0, "device_type": None}
    )
    accessories: Counter[str] = Counter()
    for f in fixtures:
        t = f.get("inst_type") or "(unknown)"
        by_type[t]["qty"] += 1
        by_type[t]["wattage_w"] += f.get("wattage_w") or 0
        by_type[t]["device_type"] = f.get("device_type")
        for acc in f.get("accessories") or []:
            name = acc.get("inst_type") or "(unknown)"
            accessories[name] += 1

    fixtures_list = [
        {
            "inst_type": t,
            "device_type": info["device_type"],
            "qty": info["qty"],
            "total_wattage_w": info["wattage_w"],
        }
        for t, info in by_type.items()
    ]
    fixtures_list.sort(key=lambda r: -r["qty"])

    return {
        "fixtures": fixtures_list,
        "accessories": [
            {"inst_type": name, "qty": qty}
            for name, qty in accessories.most_common()
        ],
    }


@mcp.tool()
def plot_qc(include_old: bool = False) -> dict[str, Any]:
    """Audit the plot for common QC issues.

    Reports:
      - duplicate channels (same channel value across multiple fixtures)
      - duplicate DMX addresses (same absolute_address across multiple fixtures)
      - unpatched fixtures (no channel and no DMX address)
      - missing positions
      - missing purposes
    """
    snap = _require_loaded()
    if isinstance(snap, dict):
        return snap
    fixtures = _filter_fixtures(snap, include_old=include_old)

    by_channel: dict[str, list[str]] = defaultdict(list)
    by_address: dict[int, list[str]] = defaultdict(list)
    unpatched: list[str] = []
    no_position: list[str] = []
    no_purpose: list[str] = []

    for f in fixtures:
        ch = f.get("channel")
        if ch:
            by_channel[ch].append(f.get("uid") or "(no uid)")
        addr = f.get("absolute_address")
        if addr:
            by_address[addr].append(f.get("uid") or "(no uid)")
        if not f.get("is_patched"):
            unpatched.append(f.get("uid") or "(no uid)")
        if not f.get("position"):
            no_position.append(f.get("uid") or "(no uid)")
        if not f.get("purpose"):
            no_purpose.append(f.get("uid") or "(no uid)")

    duplicate_channels = {
        ch: uids for ch, uids in by_channel.items() if len(uids) > 1
    }
    duplicate_addresses = {
        addr: uids for addr, uids in by_address.items() if len(uids) > 1
    }

    return {
        "total_fixtures": len(fixtures),
        "duplicate_channels": duplicate_channels,
        "duplicate_addresses": duplicate_addresses,
        "unpatched_count": len(unpatched),
        "missing_position_count": len(no_position),
        "missing_purpose_count": len(no_purpose),
        # Sample lists (cap to keep responses small).
        "unpatched_sample": unpatched[:20],
        "missing_position_sample": no_position[:20],
        "missing_purpose_sample": no_purpose[:20],
    }


# ─── entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # Try to resume the previously-active file first.
    persisted = cfg.load_active_file()
    resumed = False
    if persisted and persisted.exists():
        try:
            _watcher.watch(persisted)
            log.info("Resumed watching %s", persisted)
            resumed = True
        except Exception as e:
            log.warning("Could not resume watching %s: %s", persisted, e)

    # Otherwise, auto-pick the most recently-modified plot under the shows root.
    # This is the common case: Rob just worked on a show in VW and switched to
    # Cowork — that show's XML was rewritten on focus-out, so it's freshest.
    if not resumed:
        candidates = discovery.find_plots()
        if candidates:
            newest = candidates[0]
            try:
                _watcher.watch(newest.xml_path)
                cfg.save_active_file(newest.xml_path)
                log.info(
                    "Auto-selected most recent plot: %s (%s)",
                    newest.show_folder,
                    newest.xml_path,
                )
            except Exception as e:
                log.warning("Auto-select failed for %s: %s", newest.xml_path, e)
        else:
            log.info(
                "No plots found under %s — call list_plots or set_active_plot.",
                cfg.load_shows_root(),
            )

    mcp.run()


if __name__ == "__main__":
    main()
