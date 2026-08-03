#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Match a burst-mode capture against a known Rockbox sequence.

`decode8080.py` answers "what is on the bus?"; this answers "is it the sequence
we expected, in order, with nothing missing?" -- which is the check that makes a
burst plan verifiable rather than merely plausible.

Two things make that possible:

  * The expected transactions are known byte-exactly from `refs/sequences.json`.
  * Burst boundaries are at known sample offsets, so the per-burst write counts
    can be compared against the sleep structure of the sequence. A burst plan is
    designed so each boundary lands inside a sleep; if it did, the observed
    structure matches the expected one exactly, and that agreement is what
    anchors the alignment rather than an assumption about where the capture
    started.

The comparison is a real diff (difflib), not a fixed offset, so a write dropped
in a burst re-arm gap is reported as a deletion at a known index instead of
silently shifting everything after it and reading as a wall of mismatches.

    tools/seqmatch.py captures/<id>.csv
    tools/seqmatch.py captures/<id>.csv --config bootloader --sequence init
"""
from __future__ import annotations

import argparse
import difflib
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capio

REPO = Path(__file__).resolve().parent.parent


def load_lane_map(pinout: Path) -> dict[int, int]:
    """flex pin -> APB bit, command-mode map.

    Only the confirmed lanes: bits 14/15 are constant zero throughout
    `lcd_init_seq_23`, so they are unobservable from an init capture and are
    correctly assembled as zero here.
    """
    lm = json.loads(pinout.read_text()).get("lane_map", {})
    return {int(k): v for k, v in lm.get("confirmed", {}).items()}


def expected(seqs: Path, config: str, ptype: str, name: str) -> tuple[list[tuple[int, int]], list]:
    doc = json.loads(seqs.read_text())
    try:
        seq = doc["configs"][config]["types"][ptype]["sequences"][name]
    except KeyError:
        raise SystemExit(f"no such sequence: configs.{config}.types.{ptype}.sequences.{name}")
    tx = seq["transactions"]
    writes = [(0 if e["kind"] == "cmd" else 1, e["value"]) for e in tx if e["kind"] != "sleep"]

    # Run/sleep structure: the number of writes between sleeps is the burst
    # structure a correctly-sized plan should reproduce.
    runs, cur = [], 0
    for e in tx:
        if e["kind"] == "sleep":
            runs.append(cur)
            cur = 0
        else:
            cur += 1
    runs.append(cur)
    return writes, runs


def decode(path: Path, lanes: dict[int, int], wr: str, dc: str):
    names, data = capio.load(path)
    idx = {n: i for i, n in enumerate(names)}
    for ch in (wr, dc):
        if ch not in idx:
            raise SystemExit(f"channel {ch} not in capture ({', '.join(names)})")
    missing = [p for p in lanes if f"P{p:02d}" not in idx]
    if missing:
        raise SystemExit(f"lane map needs pins not in the capture: {missing}")

    w = data[:, idx[wr]]
    rise = np.where((w[:-1] == 0) & (w[1:] == 1))[0] + 1  # 8080 latches on /WR rising
    bits = np.zeros(len(rise), dtype=np.uint16)
    for pin, bit in lanes.items():
        bits |= data[rise, idx[f"P{pin:02d}"]].astype(np.uint16) << bit
    return [(int(data[s, idx[dc]]), int(v)) for s, v in zip(rise, bits)], rise, data[:, idx[dc]]


def undersampling_check(dc_trace, samples, pre: int, post: int, bursts: int) -> list[str]:
    """Flag bursts where /WR pulses were missed.

    Balanced falling/rising edge counts do NOT prove a capture is complete -- a
    pulse shorter than the sample interval vanishes entirely, taking both its
    edges with it. D/C is the independent witness: it changes only between
    writes of different kinds, so within one burst

        writes >= D/C transitions + 1

    always holds. A violation means writes happened that /WR never showed, i.e.
    the sample rate is too low for the traffic in that burst. This bus has a
    fast command regime (~309 ns/write, 30-40 ns /WR low) that needs >=33 MS/s;
    20 MS/s only covers the ~818 ns regime.

    Only transitions *between* the first and last observed pulse of a burst
    count. Anything before the first or after the last lies outside the observed
    write span -- in burst 1 that region is the pre-trigger buffer, whose D/C
    state belongs to whatever preceded the sequence and proves nothing.
    """
    warn = []
    for b in range(bursts):
        lo = 0 if b == 0 else pre + post + (b - 1) * post
        hi = pre + post if b == 0 else lo + post
        inb = samples[(samples >= lo) & (samples < hi)]
        if len(inb) < 2:
            continue
        seg = dc_trace[int(inb[0]):int(inb[-1]) + 1]
        trans = int(np.sum(seg[:-1] != seg[1:]))
        if len(inb) < trans + 1:
            warn.append(f"  burst {b + 1}: {len(inb)} /WR pulses but {trans} D/C transitions "
                        f"between the first and last -> at least {trans + 1 - len(inb)} "
                        f"write(s) missed; raise the sample rate")
    return warn


def burst_index(sample: int, pre: int, post: int) -> int:
    """Burst 0 carries the pre-trigger buffer; every later burst is `post` long."""
    first = pre + post
    return 0 if sample < first else 1 + (sample - first) // post


def fmt(t: tuple[int, int]) -> str:
    return f"{'CMD ' if t[0] == 0 else 'DATA'} 0x{t[1]:04X}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="capture to match (explicit path, not a glob)")
    ap.add_argument("--config", default="firmware", choices=("firmware", "bootloader"))
    ap.add_argument("--type", dest="ptype", default="2", help="panel variant (default 2)")
    ap.add_argument("--sequence", default="awake", help="init / awake / sleep (default awake)")
    ap.add_argument("--wr", default="P27")
    ap.add_argument("--dc", default="P28")
    ap.add_argument("--pinout", default=str(REPO / "pinout.json"))
    ap.add_argument("--sequences", default=str(REPO / "refs" / "sequences.json"))
    args = ap.parse_args()

    path = Path(args.csv)
    lanes = load_lane_map(Path(args.pinout))
    got, samples, dc_trace = decode(path, lanes, args.wr, args.dc)
    exp, runs = expected(Path(args.sequences), args.config, args.ptype, args.sequence)

    sc = capio.sidecar(path).get("session", {})
    pre = sc.get("PreTriggerSamples", 0)
    post = sc.get("PostTriggerSamples", 0)
    bursts = sc.get("LoopCount", 0) + 1

    print(f"capture  : {capio.resolve(path).name}")
    print(f"expected : configs.{args.config}.types.{args.ptype}.sequences.{args.sequence}"
          f"  ({len(exp)} writes)")
    print(f"decoded  : {len(got)} writes over {len(lanes)} confirmed lanes")

    if post:
        per = [0] * bursts
        for s in samples:
            b = burst_index(int(s), pre, post)
            if b < bursts:
                per[b] += 1
        print(f"\nburst structure : {per}")
        print(f"expected (runs) : {runs}")
        print("                  " + ("MATCH — boundaries landed in the sleeps"
                                       if per == runs else
                                       "DIFFERS — see the diff below before trusting alignment"))

        warn = undersampling_check(dc_trace, samples, pre, post, bursts)
        if warn:
            print("\nUNDERSAMPLED — D/C moved more often than /WR pulsed:")
            print("\n".join(warn))

    print()
    sm = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
    matched = extra = lost = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            matched += i2 - i1
        elif tag in ("delete", "replace"):
            for i in range(i1, i2):
                lost += 1
                print(f"  MISSING at expected #{i}: {fmt(exp[i])}")
        if tag in ("insert", "replace"):
            for j in range(j1, j2):
                extra += 1
                where = f" (burst {burst_index(int(samples[j]), pre, post) + 1})" if post else ""
                print(f"  EXTRA   at decoded  #{j}: {fmt(got[j])}{where}")

    print(f"\nmatched {matched}/{len(exp)} expected writes"
          f"  ({lost} missing, {extra} extra decoded)")
    if matched == len(exp) and not extra:
        print("EXACT MATCH")
    return 0 if matched == len(exp) else 1


if __name__ == "__main__":
    raise SystemExit(main())
