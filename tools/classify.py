#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Per-channel statistics and heuristic labelling of a capture.

Phase 0 uses this to verify the pipeline against a known signal (--expect).
Phase 2 uses it to classify unknown flex pins from a boot capture.

Input is a TerminalCapture CSV (header row of channel names, then one row per
sample with 0/1 per channel, no timestamp column) plus its sidecar JSON for the
sample rate.

Classification heuristics for the 8080 bus, from the project brief:
  WR    busiest line
  CS    frames write bursts (long idle, low duty envelope)
  D/C   flips between short groups (commands) and long groups (params/pixels)
  TE    lonely ~60 Hz tick appearing after init completes
  RESET single early transition
  RD    rare activity (NOTE: Rockbox never reads -- S5L_LCD_WITH_READID is
        undefined for ipod6g -- so silence here proves nothing)
  data  a cluster of 17-18 similarly busy lines
  silent -> power / ID strap / bad contact, never NC on silence alone
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capio

REPO = Path(__file__).resolve().parent.parent


def load(csv_path: Path):
    """Return (names, samples[n_samples, n_channels] uint8, sample_rate)."""
    names, data = capio.load(csv_path)
    return names, data, capio.sample_rate(csv_path)


def runs(col: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (values, lengths) of constant runs in a 0/1 column."""
    change = np.flatnonzero(np.diff(col)) + 1
    bounds = np.concatenate(([0], change, [len(col)]))
    return col[bounds[:-1]], np.diff(bounds)


def analyse(name: str, col: np.ndarray, rate: int | None) -> dict:
    n = len(col)
    edges = int(np.count_nonzero(np.diff(col.astype(np.int8))))
    rising = int(np.count_nonzero(np.diff(col.astype(np.int8)) == 1))
    duty = float(col.mean())
    vals, lens = runs(col)

    st: dict = {
        "channel": name,
        "samples": n,
        "edges": edges,
        "rising_edges": rising,
        "duty": round(duty, 6),
        "constant": edges == 0,
        "level": int(col[0]) if edges == 0 else None,
    }

    if edges:
        first = int(np.flatnonzero(np.diff(col.astype(np.int8)))[0]) + 1
        last = int(np.flatnonzero(np.diff(col.astype(np.int8)))[-1]) + 1
        st["first_edge_sample"] = first
        st["last_edge_sample"] = last
        # Drop the first and last runs: both are truncated by the capture window
        # (and the first is also truncated by an unfilled pre-trigger buffer), so
        # including them reports a boundary artifact as a real minimum pulse width.
        # Phase 5 reads WR high/low widths straight off these numbers.
        iv, il = vals[1:-1], lens[1:-1]
        highs, lows = il[iv == 1], il[iv == 0]
        st["min_high_samples"] = int(highs.min()) if highs.size else None
        st["min_low_samples"] = int(lows.min()) if lows.size else None
        # Medians as well: a single worst-case run should not define a timing spec.
        # The dry run showed ~3 samples of jitter at 100 MS/s.
        st["med_high_samples"] = float(np.median(highs)) if highs.size else None
        st["med_low_samples"] = float(np.median(lows)) if lows.size else None
        st["max_idle_samples"] = int(il.max()) if il.size else int(lens.max())
        st["n_runs_measured"] = int(il.size)

        # Duty measured only over the active span. The device zero-fills the
        # pre-trigger buffer when the trigger fires before that buffer has filled,
        # so a whole-capture mean is diluted by dead samples that were never
        # sampled from the wire. Verified in the phase 0 dry run: 511 leading zero
        # samples on a free-running 10 kHz signal, which is physically impossible.
        st["duty_active"] = round(float(col[first:last].mean()), 6) if last > first else None

        # Dominant period from the modal full cycle (a high run + the next low run).
        if rising >= 2:
            idx = np.flatnonzero(np.diff(col.astype(np.int8)) == 1)
            periods = np.diff(idx)
            st["modal_period_samples"] = int(np.bincount(periods).argmax())
            st["period_jitter_samples"] = int(periods.max() - periods.min())
            # Whole-cycle duty: an exact integer number of periods, so this is the
            # measurement to trust for a periodic signal.
            st["duty_cycles"] = round(float(col[idx[0]:idx[-1]].mean()), 6)

        # A constant pre-trigger region in front of an active signal means the
        # pre-trigger buffer never filled; those samples are not real data.
        if first > 1 and not np.any(np.diff(col[:first - 1].astype(np.int8))):
            st["pretrigger_unfilled"] = True
            st["valid_from_sample"] = first

        if rate:
            st["first_edge_us"] = round(first / rate * 1e6, 3)
            st["min_high_ns"] = round(st["min_high_samples"] / rate * 1e9, 1) if highs.size else None
            st["min_low_ns"] = round(st["min_low_samples"] / rate * 1e9, 1) if lows.size else None
            st["med_high_ns"] = round(st["med_high_samples"] / rate * 1e9, 1) if highs.size else None
            st["med_low_ns"] = round(st["med_low_samples"] / rate * 1e9, 1) if lows.size else None
            if "modal_period_samples" in st and st["modal_period_samples"]:
                st["dominant_freq_hz"] = round(rate / st["modal_period_samples"], 2)
            st["mean_edge_rate_hz"] = round(edges / (n / rate) / 2, 1)
    return st


def label(st: dict, all_stats: list[dict]) -> tuple[str, str]:
    """Return (label, confidence). Deliberately conservative."""
    if st["constant"]:
        return (f"silent-{'high' if st['level'] else 'low'}",
                "none")  # power / strap / bad contact / genuinely idle -- unresolved

    busiest = max(s["edges"] for s in all_stats)
    if st["edges"] == busiest and st["edges"] > 4 * np.median([s["edges"] for s in all_stats]):
        return "WR?", "low"
    if st["edges"] <= 2:
        return "RESET? / one-shot", "low"
    f = st.get("dominant_freq_hz")
    if f and 30 <= f <= 120 and st["duty"] < 0.5:
        return "TE?", "low"
    return "active", "none"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    ap.add_argument("--expect", action="append", default=[],
                    help="assertion NAME:freq_hz:duty_pct, e.g. SIG_50:10000:50 "
                         "(phase 0 acceptance test; may be repeated)")
    ap.add_argument("--tol-freq", type=float, default=1.0, help="frequency tolerance %%")
    ap.add_argument("--tol-duty", type=float, default=2.0, help="duty tolerance, percentage points")
    args = ap.parse_args()

    names, data, rate = load(args.csv)
    stats = [analyse(nm, data[:, i], rate) for i, nm in enumerate(names)]
    for s in stats:
        s["label"], s["confidence"] = label(s, stats)

    if args.json:
        print(json.dumps({"capture": args.csv.name, "sample_rate": rate, "channels": stats}, indent=2))
    else:
        print(f"capture: {args.csv.name}   rate: {rate/1e6:g} MS/s   "
              f"samples: {data.shape[0]}   window: {data.shape[0]/rate*1e3:.3f} ms\n")
        hdr = f"{'ch':>3} {'name':<8} {'edges':>7} {'duty':>7} {'freq_Hz':>11} " \
              f"{'min_hi_ns':>10} {'min_lo_ns':>10} {'1st_edge_us':>11}  label"
        print(hdr)
        print("-" * len(hdr))
        for i, s in enumerate(stats):
            d = s.get("duty_cycles")
            if d is None:
                d = s.get("duty_active")
            if d is None:
                d = s["duty"]
            print(f"{i:>3} {s['channel']:<8} {s['edges']:>7} {d:>7.3f} "
                  f"{s.get('dominant_freq_hz', float('nan')):>11.2f} "
                  f"{(s.get('min_high_ns') or float('nan')):>10.1f} "
                  f"{(s.get('min_low_ns') or float('nan')):>10.1f} "
                  f"{(s.get('first_edge_us') or float('nan')):>11.3f}  {s['label']}")

        unfilled = [s for s in stats if s.get("pretrigger_unfilled")]
        if unfilled:
            v = max(s["valid_from_sample"] for s in unfilled)
            print(f"\nNOTE: pre-trigger buffer did not fill on "
                  f"{len(unfilled)}/{len(stats)} channels; samples before {v} are not "
                  f"real data. Duty is reported over whole cycles / the active span.")
        silent = [s for s in stats if s["constant"]]
        if silent:
            print(f"NOTE: {len(silent)} channel(s) never toggled "
                  f"({', '.join(s['channel'] for s in silent)}). Per project ground "
                  f"rules this is NOT evidence of NC: it may be power, an ID strap, a "
                  f"bad probe contact, or a genuinely idle signal such as /RD.")

    failures = []
    for exp in args.expect:
        nm, f_exp, d_exp = exp.split(":")
        f_exp, d_exp = float(f_exp), float(d_exp)
        match = next((s for s in stats if s["channel"] == nm), None)
        if match is None:
            failures.append(f"{nm}: channel not present in capture")
            continue
        f_got = match.get("dominant_freq_hz")
        # Prefer whole-cycle duty, then active-span, then raw. See duty_cycles above.
        d_src = ("duty_cycles" if match.get("duty_cycles") is not None
                 else "duty_active" if match.get("duty_active") is not None else "duty")
        d_got = match[d_src] * 100
        if f_got is None:
            failures.append(f"{nm}: no periodic signal detected")
            continue
        f_err = abs(f_got - f_exp) / f_exp * 100
        d_err = abs(d_got - d_exp)
        ok = f_err <= args.tol_freq and d_err <= args.tol_duty
        print(f"\n{'PASS' if ok else 'FAIL'}  {nm}: "
              f"freq {f_got:.2f} Hz (expected {f_exp:.2f}, err {f_err:.3f}%), "
              f"duty {d_got:.2f}% (expected {d_exp:.2f}, err {d_err:.2f} pp) "
              f"[duty from {d_src}]")
        if not ok:
            failures.append(f"{nm}: freq err {f_err:.3f}%, duty err {d_err:.2f} pp")

    if args.expect:
        if failures:
            print("\nACCEPTANCE FAILED:")
            for f in failures:
                print(f"  - {f}")
            return 1
        print("\nACCEPTANCE PASSED: capture matches the known signal.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
