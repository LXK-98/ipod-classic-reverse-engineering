#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tabulate every channel's transitions relative to a reference edge.

This is the analysis behind the gap 1 / power-down tables in DRIVING.md section 1,
which were previously computed ad hoc. Having it as a tool means the driver's
own rail captures go through exactly the same arithmetic as the iPod's -- the
comparison that milestone 1 of the breadboard bring-up depends on.

The reference defaults to the capture's own trigger: the first transition on
the trigger channel in the trigger's direction. Times are threshold crossings
(~1.1 V at VREF = 1.6 V), so they give ORDER, not ramp shapes.

    tools/railseq.py captures/20261012_171537_power-seq.csv.gz
    tools/railseq.py captures/<id>.csv.gz --ref V18_P26 --falling
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capio


def transitions(col: np.ndarray) -> np.ndarray:
    """Sample indices where the level changes (index of the first new sample)."""
    return np.flatnonzero(np.diff(col.astype(np.int8))) + 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="capture (explicit path, not a glob)")
    ap.add_argument("--ref", help="reference channel (default: the sidecar's trigger channel)")
    ap.add_argument("--falling", action="store_true", default=None,
                    help="reference on a falling edge (default: the sidecar's trigger polarity)")
    ap.add_argument("--show", type=int, default=4,
                    help="transitions listed per channel before summarising (default 4)")
    args = ap.parse_args()

    reason = capio.invalid_reason(args.csv)
    if reason:
        raise SystemExit(f"{args.csv.name} is marked INVALID and must not be analysed: {reason}")

    names, data = capio.load(args.csv)
    sess = capio.sidecar(args.csv).get("session", {})
    rate = sess.get("Frequency")
    if not rate:
        raise SystemExit("no sample rate in the sidecar; cannot convert to time")

    ref = args.ref or names[sess.get("TriggerChannel", 0)]
    if ref not in names:
        raise SystemExit(f"reference channel {ref!r} not in capture ({', '.join(names)})")
    falling = args.falling if args.falling is not None else bool(sess.get("TriggerInverted"))

    rc = data[:, names.index(ref)]
    want = 0 if falling else 1
    t_ref = next((int(s) for s in transitions(rc) if rc[s] == want), None)
    if t_ref is None:
        raise SystemExit(f"no {'falling' if falling else 'rising'} edge on {ref}")

    us = 1e6 / rate
    print(f"capture   : {capio.resolve(args.csv).name}")
    print(f"rate      : {rate / 1e3:g} kS/s  ({us:g} us per sample = the resolution of every time below)")
    print(f"reference : {ref} {'falling' if falling else 'rising'} at sample {t_ref}")
    print(f"window    : {-t_ref * us / 1e3:+.3f} .. {(len(rc) - t_ref) * us / 1e3:+.3f} ms\n")

    rows = []
    for i, n in enumerate(names):
        tr = transitions(data[:, i])
        first = (int(tr[0]) - t_ref) * us / 1e3 if len(tr) else None
        rows.append((first if first is not None else float("inf"), n, data[0, i], tr))

    print(f"{'channel':<10} {'start':>5} {'edges':>6}  transitions (ms from reference, ^ rise v fall)")
    for _, n, start, tr in sorted(rows, key=lambda r: r[0]):
        col = data[:, names.index(n)]
        shown = "  ".join(f"{'^' if col[s] else 'v'}{(int(s) - t_ref) * us / 1e3:+.3f}"
                          for s in tr[: args.show])
        if len(tr) > args.show:
            shown += f"  ... last {(int(tr[-1]) - t_ref) * us / 1e3:+.3f}"
        print(f"{n:<10} {int(start):>5} {len(tr):>6}  {shown or '(constant)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
