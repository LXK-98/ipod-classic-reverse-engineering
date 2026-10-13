#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check firmware/bus.py's encoder against a capture, pin for pin on all 18 lanes.

seqmatch.py verifies a sequence over the 14 lanes in pinout.json's lane map;
the pair pins P09/P10/P01/P02 are never compared. This aligns writes exactly as
seqmatch does, then compares EVERY lane against bus.reg() -- the function the
Pico firmware runs.

  * Against the iPod's own init capture (the default) it shows the encoder
    reproduces what the SoC put on the bus: 151/151 on 2026-10-13.
  * Against the driver's milestone-2 capture it shows the driver put exactly
    that on the bus.

    tools/encoder_check.py
    tools/encoder_check.py captures/<driver-init>.csv.gz --config bootloader --sequence init
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tools"))
sys.path.insert(0, str(REPO / "firmware"))
import bus  # noqa: E402
import capio  # noqa: E402
import seqmatch  # noqa: E402

IPOD_INIT = REPO / "captures" / "20260803_203836_init-burst.csv.gz"


def std(v: int) -> int:
    """The encoder WITHOUT the SoC's DATA-write pair copy, for contrast."""
    return bus.reg(bus.CMD, v)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", type=Path, default=IPOD_INIT)
    ap.add_argument("--config", default="firmware", choices=("firmware", "bootloader"))
    ap.add_argument("--sequence", default="awake")
    args = ap.parse_args()

    reason = capio.invalid_reason(args.csv)
    if reason:
        raise SystemExit(f"{args.csv.name} is marked INVALID: {reason}")
    lanes = seqmatch.load_lane_map(REPO / "pinout.json")
    got, rise, _ = seqmatch.decode(args.csv, lanes, "P27", "P28")
    exp, _ = seqmatch.expected(REPO / "refs" / "sequences.json", args.config, "2", args.sequence)
    names, data = capio.load(args.csv)
    idx = {n: i for i, n in enumerate(names)}
    missing = [p for p in bus.FLEX if f"P{p:02d}" not in idx]
    if missing:
        raise SystemExit(f"capture lacks flex pins {missing}; all 18 lanes are needed")

    matched = exact = exact_std = 0
    per_pin = {p: 0 for p in bus.FLEX}
    for op, a0, a1, b0, b1 in difflib.SequenceMatcher(a=exp, b=got, autojunk=False).get_opcodes():
        if op != "equal":
            print(f"  not aligned: {op} expected[{a0}:{a1}] decoded[{b0}:{b1}]")
            continue
        for k in range(a1 - a0):
            kind, v = exp[a0 + k]
            s = rise[b0 + k]
            pins = sum(int(data[s, idx[f"P{p:02d}"]]) << n for n, p in enumerate(bus.FLEX))
            want = bus.reg(kind, v) & ~bus.DC        # D/C is checked by the alignment
            matched += 1
            exact += pins == want
            exact_std += pins == (std(v) & ~bus.DC)
            for n, p in enumerate(bus.FLEX):
                per_pin[p] += ((pins ^ want) >> n) & 1

    print(f"capture  : {capio.resolve(args.csv).name}")
    print(f"expected : configs.{args.config}.types.2.sequences.{args.sequence} ({len(exp)} writes)")
    print(f"aligned  : {matched} writes ({len(got)} decoded)")
    print(f"pin-exact, firmware/bus.py encoder : {exact}/{matched}")
    print(f"pin-exact, without the pair copy   : {exact_std}/{matched}")
    bad = {f"P{p:02d}": n for p, n in per_pin.items() if n}
    if bad:
        print(f"mismatches by pin: {bad}")
    return 0 if matched and exact == matched else 1


if __name__ == "__main__":
    sys.exit(main())
