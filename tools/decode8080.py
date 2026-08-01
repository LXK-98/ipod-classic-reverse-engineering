#!/usr/bin/env python3
"""Decode an 8080-bus capture into command/data transactions.

Takes an EXPLICIT capture path -- never guesses at "the newest file", which
previously caused a stale capture to be analysed as if it were a fresh one.

Latches the bus on the /WR rising edge (8080 convention, confirmed for this
target), splits commands from data using D/C, and assembles 16-bit words from
the lane map in pinout.json.

    tools/decode8080.py captures/<id>.csv
    tools/decode8080.py captures/<id>.csv --expect-word 0xF800
    tools/decode8080.py captures/<id>.csv --raw          # before a lane map exists
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent


def load_lane_map(pinout: Path, include_predicted: bool) -> tuple[dict[int, int], set[int]]:
    doc = json.loads(pinout.read_text())
    lm = doc.get("lane_map", {})
    m = {int(k): v for k, v in lm.get("confirmed", {}).items()}
    predicted = set()
    if include_predicted:
        for k, v in lm.get("predicted", {}).items():
            m[int(k)] = v
            predicted.add(v)
    return m, predicted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path, help="capture to decode (explicit path, not a glob)")
    ap.add_argument("--wr", default="P27", help="channel name of /WR")
    ap.add_argument("--dc", default="P28", help="channel name of D/C")
    ap.add_argument("--pinout", type=Path, default=REPO / "pinout.json")
    ap.add_argument("--no-predicted", action="store_true",
                    help="use only confirmed lanes; leave predicted bits out of the word")
    ap.add_argument("--expect-word", type=lambda s: int(s, 0),
                    help="assert the dominant DATA word equals this value")
    ap.add_argument("--top", type=int, default=8, help="how many frequent words to show")
    ap.add_argument("--raw", action="store_true",
                    help="dump raw per-lane bit patterns instead of assembled words")
    args = ap.parse_args()

    if not args.csv.exists():
        raise SystemExit(f"capture not found: {args.csv}")
    names = args.csv.open().readline().strip().split(",")
    data = np.loadtxt(args.csv, delimiter=",", skiprows=1, dtype=np.uint8, ndmin=2)
    if args.wr not in names:
        raise SystemExit(f"/WR channel {args.wr!r} not in capture ({names})")

    wr = names.index(args.wr)
    rise = np.flatnonzero(np.diff(data[:, wr].astype(np.int8)) == 1) + 1
    print(f"capture      : {args.csv.name}")
    print(f"samples      : {len(data)}   channels: {len(names)}")
    print(f"/WR writes   : {len(rise)}")
    if len(rise) == 0:
        print("\nNo write strobes in this capture - nothing to decode.")
        return 1

    have_dc = args.dc in names
    if have_dc:
        dcv = data[rise, names.index(args.dc)]
        is_data = dcv == 1          # D/C: 0 = command, 1 = data (confirmed)
        print(f"split by D/C : {int(is_data.sum())} data / {int((~is_data).sum())} command")
    else:
        is_data = np.ones(len(rise), dtype=bool)
        print(f"D/C channel {args.dc!r} absent - treating every write as data")

    if args.raw:
        print("\nper-lane bit history at latch points (first 60):")
        for i, n in enumerate(names):
            if i == wr:
                continue
            col = data[rise, i]
            print(f"  {n:>5}: {''.join(map(str, col[:60]))}")
        return 0

    lanes, predicted = load_lane_map(args.pinout, not args.no_predicted)
    if not lanes:
        raise SystemExit("no lane map in pinout.json; use --raw")
    idx = {int(n[1:]): i for i, n in enumerate(names) if n.startswith("P") and n[1:].isdigit()}
    missing = [p for p in lanes if p not in idx]
    if missing:
        print(f"WARNING: lane-map pins not present in this capture: {missing}")

    def words(rows: np.ndarray) -> np.ndarray:
        w = np.zeros(len(rows), dtype=np.uint32)
        for pin, bit in lanes.items():
            if pin in idx:
                w |= data[rows, idx[pin]].astype(np.uint32) << bit
        return w

    if predicted:
        print(f"NOTE: word includes PREDICTED bits {sorted(predicted)} "
              f"(use --no-predicted to exclude)")

    for label, sel in (("COMMAND", ~is_data), ("DATA", is_data)):
        rows = rise[sel]
        if not len(rows):
            continue
        cnt = collections.Counter(words(rows).tolist())
        print(f"\n{label}: {len(rows)} writes, {len(cnt)} distinct values")
        for v, n in cnt.most_common(args.top):
            print(f"   0x{v:04X}  {n:7d}  ({n / len(rows) * 100:5.1f}%)")

    if args.expect_word is not None:
        rows = rise[is_data]
        if not len(rows):
            print("\nFAIL: no data writes to compare against --expect-word")
            return 1
        cnt = collections.Counter(words(rows).tolist())
        top, n = cnt.most_common(1)[0]
        ok = top == args.expect_word
        print(f"\n{'PASS' if ok else 'FAIL'}: dominant data word 0x{top:04X} "
              f"({n / len(rows) * 100:.1f}%) vs expected 0x{args.expect_word:04X}")
        if not ok:
            print("  per-bit comparison (got vs expected):")
            for bit in sorted(set(lanes.values())):
                pin = next(p for p, b in lanes.items() if b == bit)
                g, e = (top >> bit) & 1, (args.expect_word >> bit) & 1
                flag = "" if g == e else "   <-- MISMATCH"
                tag = " (predicted)" if bit in predicted else ""
                print(f"    bit{bit:>2} pin {pin:>2}: got {g} expected {e}{flag}{tag}")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
