#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Ingest a DMM sweep (TSV) into pinout.json, with classification.

Keeps bench measurements as files rather than conversation state, per the project
data conventions. Re-runnable: re-ingesting the same file is idempotent.

    tools/record_dmm.py measurements/2026-08-01_ground-sweep.tsv --kind resistance
    tools/record_dmm.py measurements/....tsv --kind voltage --dry-run

TSV format: comment lines start with '#', then a 'pin<TAB>value' header and rows.
Values may use engineering suffixes (k, M) or 'OL' for open.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def parse_value(s: str) -> float | None:
    """Return ohms/volts as float, or None for open-loop."""
    s = s.strip()
    if s.upper() in ("OL", "OPEN", "INF", "-"):
        return None
    m = re.fullmatch(r"([-\d.]+)\s*([kKmMuU]?)", s)
    if not m:
        raise ValueError(f"cannot parse value {s!r}")
    v = float(m.group(1))
    return v * {"": 1, "k": 1e3, "K": 1e3, "M": 1e6, "m": 1e-3, "u": 1e-6, "U": 1e-6}[m.group(2)]


def classify_resistance(ohms: float | None, floor: float) -> tuple[str, str]:
    """(function, confidence) from resistance to signal ground.

    Thresholds are set from the observed clustering of the 2026-08-01 sweep, not
    from theory. Megohm-range values on an unpowered board are leakage paths through
    semiconductor structures: the grouping is meaningful, the absolute value is not.
    """
    if ohms is None:
        return "unknown-floating", "none"
    if ohms <= floor + 4:
        # Cannot yet distinguish true GND from a pin the PANEL ties low (e.g. an ID
        # strap). Resolved by re-measuring with the display flex disconnected.
        return "GND-or-panel-tied-low", "medium"
    if ohms <= 1e3:
        # Far too low for a logic pull-down; a current-sense resistor sits here.
        return "low-Z-to-GND", "low"
    if ohms <= 1e5:
        return "mid-Z-100k-or-less", "none"
    if ohms <= 2e6:
        return "sub-megohm", "none"
    return "high-Z-baseline", "none"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tsv", type=Path)
    ap.add_argument("--kind", choices=["resistance", "voltage"], default="resistance")
    ap.add_argument("--floor", type=float, default=2.0,
                    help="meter lead-resistance baseline in ohms (default 2)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rows: dict[int, float | None] = {}
    for line in args.tsv.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.lower().startswith("pin\t"):
            continue
        pin_s, val_s = re.split(r"\s+", line, maxsplit=1)
        rows[int(pin_s)] = parse_value(val_s)

    doc = json.loads((REPO / "pinout.json").read_text())
    pins = doc["pins"]
    evidence = args.tsv.name

    summary: dict[str, list[int]] = {}
    for pin, val in sorted(rows.items()):
        key = str(pin)
        if key not in pins:
            raise SystemExit(f"pin {pin} is outside the {len(pins)}-pin map")
        if args.kind == "resistance":
            fn, conf = classify_resistance(val, args.floor)
            pins[key]["r_to_gnd_ohms"] = val
            # Only overwrite function while it is still unresolved.
            if pins[key]["function"] in (
                    "unknown", "unknown-floating", "GND-or-panel-tied-low",
                    "low-Z-to-GND", "pulldown-or-strap", "mid-Z-100k-or-less",
                    "sub-megohm", "high-Z-baseline"):
                pins[key]["function"] = fn
                pins[key]["confidence"] = conf
        else:
            pins[key]["voltage"] = val
        if evidence not in pins[key]["evidence"]:
            pins[key]["evidence"].append(evidence)
        summary.setdefault(pins[key]["function"], []).append(pin)

    print(f"ingested {len(rows)} readings from {args.tsv.name} ({args.kind})\n")
    for fn, pl in sorted(summary.items(), key=lambda kv: -len(kv[1])):
        print(f"  {fn:<26} {len(pl):>2} pin(s): {', '.join(map(str, pl))}")

    if args.dry_run:
        print("\n--dry-run: pinout.json not written.")
        return 0
    doc["version"] = "v1"
    (REPO / "pinout.json").write_text(json.dumps(doc, indent=2))
    print("\nwrote pinout.json (v1)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
