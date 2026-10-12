#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Capture wrapper around gusmanb TerminalCapture.

Release 6.0.0.1 ships TerminalCapture, not the CLCapture the project brief
assumed. TerminalCapture is settings-file driven:

    TerminalCapture capture <serial-port> <settings.tcs> <output.csv>

where .tcs is a JSON serialisation of SharedDriver.CaptureSession. This script
generates that JSON from a named preset, runs the capture, and writes both the
CSV and a sidecar JSON recording every setting, the probe-map version in force,
and free-text notes.

CSV format produced by TerminalCapture (FileOperations.SaveCSV): one header row
of channel names, then one row per sample with a 0/1 per channel. There is NO
timestamp column -- time is implicit at 1/Frequency.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CAPTURES = REPO / "captures"
TC = REPO / "vendor" / "TerminalCapture"

# TriggerType enum from SharedDriver/CaptureSession.cs
TRIGGER_TYPES = {"edge": 0, "complex": 1, "fast": 2, "blast": 3}

# Per-device sample limits. Channels must be the FIRST n of the device.
def max_post_samples(n_channels: int) -> int:
    if n_channels <= 8:
        return 131071
    if n_channels <= 16:
        return 65535
    return 32767


# Documented device limits (gusmanb logicanalyzer, 04/02/2023 update upstream).
MIN_FREQUENCY = 3_100
MAX_FREQUENCY = 100_000_000


def max_pre_samples(n_channels: int) -> int:
    """Documented pre-trigger ceiling per channel-count mode (min is 2)."""
    if n_channels <= 8:
        return 98_303
    if n_channels <= 16:
        return 49_151
    return 24_576


# Conservative EMPIRICAL guard, well below the documented ceilings above, and
# deliberately so. The device silently fails to arm on some configurations that
# the documentation permits: it reports nothing, and TerminalCapture waits forever
# showing the same message it shows while armed, so the failure is
# indistinguishable from "no trigger yet". That cost five cold-boot captures on
# 2026-08-02.
#
# What is actually established (see FINDINGS 14):
#  - Every capture that has ever produced data used pre in {64, 512, 1024}.
#  - A controlled pair differing ONLY in pre (65536 vs 1024, 8 ch, 131071 total,
#    same trigger channel, 1 MS/s, same session) failed and succeeded resp.
#  - But 65536 is BELOW the documented 8-channel ceiling of 98303, and the
#    pre=8000 cold-boot attempts were below the 24-channel ceiling of 24576, so
#    "pre too large" cannot be the whole explanation.
#  - 5 kS/s is above the documented 3.1 kHz floor yet also failed to arm with an
#    otherwise-proven config, which points away from pre-trigger size entirely.
#
# So the cause is NOT understood. This cap just keeps new captures close to
# configurations known to work. Raise it only alongside a capture proving a
# larger value arms, and prefer lowering --frequency to widen the pre-trigger
# window in time.
MAX_PRE_SAMPLES = 1024


PRESETS: dict[str, dict] = {
    # Phase 0 pipeline validation against a known signal.
    # Pico GP15 = 10 kHz 50% duty, GP14 = 10 kHz 25% duty (same PWM slice).
    # At 1 MS/s that is 100 samples per period; 4608 samples covers ~46 periods.
    "dryrun": {
        "description": "Pipeline validation against a Pico PWM of known freq and duty.",
        "frequency": 1_000_000,
        "pre": 512,
        "post": 4096,
        "loops": 0,
        "channels": ["SIG_50", "SIG_25"],
        "trigger": {"type": "edge", "channel": 0, "inverted": False},
    },
    # Phase 2: wide, slow survey of unknown pins across a boot.
    "survey": {
        "description": "Phase 2 broad survey: 24 ch, long window over a boot.",
        "frequency": 10_000_000,
        "pre": 1024,
        "post": 31743,
        "loops": 0,
        "channels": [f"P{i:02d}" for i in range(24)],
        "trigger": {"type": "edge", "channel": 0, "inverted": False},
    },
    # Phase 3: burst-mode capture of the whole init sequence.
    # 50 bursts x 512 post = 25600 + pre, inside the 32767 24-ch budget.
    "init-burst": {
        "description": "Phase 3 init capture: WR + D/C + 18 data lanes, burst mode.",
        "frequency": 100_000_000,
        "pre": 64,
        "post": 512,
        "loops": 49,
        "channels": ["WR", "DC"] + [f"D{i:02d}" for i in range(18)],
        "trigger": {"type": "edge", "channel": 0, "inverted": True},
    },
    # Phase 6 gap 1: rail order at cold boot, plus the reset lines and the start
    # of init traffic in the same window.
    #
    # Keeps the documented 24-channel map and displaces only THREE leads, so the
    # existing rig is barely disturbed: the rails take over CH2 (was P02), CH9
    # (was P14) and CH19 (was P25). P02 and P14 are the blue/red MSB replicas and
    # P25 one blue lane -- none load-bearing now the bus mapping is established.
    #
    # The pre-trigger must stay <= MAX_PRE_SAMPLES, so the window BEFORE the
    # trigger is bought with sample RATE, not sample count. At 100 kS/s:
    # 5.1 ms pre, 322.6 ms post, 10 us resolution.
    #
    # Deliberately wide and coarse -- the timescale of rail sequencing is entirely
    # unknown and a first measurement should not risk missing the event.
    # Consequence: /WR (30-80 ns) and per-write /CS framing (~650 ns) are both
    # invisible at 10 us. This preset answers RAIL ORDER, and locates the first
    # long /CS burst to tens of microseconds. Reset pulse width and first-write
    # timing need a second, faster pass once this one fixes the timescale.
    #
    # If the first init traffic turns out to fall beyond 322 ms, repeat at 8
    # channels for 4x the depth (1.31 s) -- verified working on 2026-10-12, when
    # 20261012_161634 returned the full 131071 samples -- at the cost of moving
    # eight leads onto CH1-CH8:
    #   --channels V18_P26,V30_P33,VREF_P34,P30,P32,WR_P27,DC_P28,CS_P29 \
    #   --post 130047 --trigger-channel 1
    #
    # Trigger is the 3.0 V rail rising: the largest swing, so the most margin over
    # the shifter's ~1.1 V threshold at VREF=1.6 V. Any rail leading it by under
    # 5.1 ms still lands in the pre-trigger window. Re-run with
    # --trigger-channel 21 --trigger-inverted to trigger on /CS falling instead.
    "power-seq": {
        "description": "Phase 6 gap 1: rail sequencing at cold boot, 24 ch, 328 ms.",
        "frequency": 100_000,
        "pre": 512,
        "post": 32_255,
        "loops": 0,
        # Positions match the documented 24ch map with CH2/CH9/CH19 reassigned.
        "channels": [
            "P01", "V18_P26", "TE_P07", "P09", "P10", "P11", "P12", "P13",
            "V30_P33", "P15", "P16", "P18", "P19", "P20", "P21", "P22",
            "P23", "P24", "VREF_P34", "WR_P27", "DC_P28", "CS_P29",
            "P30", "P32",
        ],
        "trigger": {"type": "edge", "channel": 8, "inverted": False},
    },
    # Phase 5: full-rate timing measurement, short window.
    #
    # pre was 4096 until 2026-10-12. That default was never actually run -- every
    # Phase 5 capture overrode it -- and it is above MAX_PRE_SAMPLES, so it would
    # not have armed. Lowered to 1024, the largest value proven to work.
    "blit-timing": {
        "description": "Phase 5 timing: max rate, single short window in a pixel burst.",
        "frequency": 100_000_000,
        "pre": 1024,
        "post": 28671,
        "loops": 0,
        "channels": ["WR", "DC"] + [f"D{i:02d}" for i in range(18)],
        "trigger": {"type": "edge", "channel": 0, "inverted": True},
    },
}


def find_ports() -> list[str]:
    """Locate logic analyzers only.

    Match on the /dev/serial/by-id name so a Pico or any other CDC device on the
    bus is never mistaken for an analyzer, and so a given physical unit keeps a
    stable identity across re-enumeration. Falls back to raw tty globbing only if
    by-id is unavailable.
    """
    byid = glob.glob("/dev/serial/by-id/*LogicAnalyzer*")
    if byid:
        return sorted(byid)
    return sorted(glob.glob("/dev/ttyACM*") + glob.glob("/dev/ttyUSB*"))


def build_session(preset: dict, overrides: dict) -> dict:
    freq = overrides.get("frequency") or preset["frequency"]
    pre = overrides.get("pre") if overrides.get("pre") is not None else preset["pre"]
    post = overrides.get("post") if overrides.get("post") is not None else preset["post"]
    loops = overrides.get("loops") if overrides.get("loops") is not None else preset["loops"]
    names = overrides.get("channels") or preset["channels"]
    trig = dict(preset["trigger"])
    if overrides.get("trigger_channel") is not None:
        trig["channel"] = overrides["trigger_channel"]
    if overrides.get("trigger_inverted") is not None:
        trig["inverted"] = overrides["trigger_inverted"]

    n = len(names)
    if not MIN_FREQUENCY <= freq <= MAX_FREQUENCY:
        raise SystemExit(
            f"frequency {freq} is outside the device's documented range "
            f"{MIN_FREQUENCY}-{MAX_FREQUENCY} Hz."
        )
    if pre > max_pre_samples(n):
        raise SystemExit(
            f"pre({pre}) exceeds the documented {n}-channel pre-trigger ceiling of "
            f"{max_pre_samples(n)}."
        )
    if pre > MAX_PRE_SAMPLES:
        raise SystemExit(
            f"pre({pre}) exceeds this project's conservative guard of {MAX_PRE_SAMPLES}\n"
            f"(the documented {n}-channel ceiling is {max_pre_samples(n)}, so this is NOT\n"
            f"a device limit). The device silently fails to arm on some configurations it\n"
            f"documents as legal, and the cause is not understood -- see FINDINGS 14.\n"
            f"Every capture that has produced data used pre in {{64, 512, 1024}}.\n"
            f"To widen the pre-trigger in TIME, lower --frequency instead."
        )
    total = post * (loops + 1) + pre
    cap = max_post_samples(n)
    if total > cap:
        raise SystemExit(
            f"sample budget exceeded: {n} channels allows {cap} total samples, "
            f"but pre({pre}) + post({post})*(loops({loops})+1) = {total}.\n"
            f"Reduce --post, --loops, or the channel count."
        )
    if trig["channel"] >= n:
        raise SystemExit(f"trigger channel {trig['channel']} is outside the {n} captured channels")

    return {
        "Frequency": freq,
        "PreTriggerSamples": pre,
        "PostTriggerSamples": post,
        "LoopCount": loops,
        "MeasureBursts": loops > 0,
        "CaptureChannels": [
            {"ChannelNumber": i, "ChannelName": nm, "Hidden": False}
            for i, nm in enumerate(names)
        ],
        "TriggerType": TRIGGER_TYPES[trig["type"]],
        "TriggerChannel": trig["channel"],
        "TriggerInverted": bool(trig["inverted"]),
        "TriggerBitCount": 1,
        "TriggerPattern": 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("preset", nargs="?", choices=sorted(PRESETS), help="capture preset")
    ap.add_argument("--port", help="serial port (default: autodetect if exactly one)")
    ap.add_argument("--probe-map", default="unset",
                    help="probe map version in force (recorded in the sidecar)")
    ap.add_argument("--note", default="", help="free-text note for the lab notebook")
    ap.add_argument("--frequency", type=int)
    ap.add_argument("--pre", type=int)
    ap.add_argument("--post", type=int)
    ap.add_argument("--loops", type=int, help="burst count - 1 (LoopCount)")
    ap.add_argument("--channels", help="comma-separated channel names, overrides preset")
    ap.add_argument("--trigger-channel", type=int)
    ap.add_argument("--trigger-inverted", action="store_true", default=None,
                    help="trigger on falling edge")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="write the .tcs and print the command, but do not capture")
    args = ap.parse_args()

    if args.list_ports:
        ports = find_ports()
        print("\n".join(ports) if ports else "no serial ports found")
        return 0

    if not args.preset:
        ap.error("preset is required unless --list-ports is used")
    if not TC.exists():
        raise SystemExit(f"TerminalCapture not found at {TC}")

    port = args.port
    if not port:
        ports = find_ports()
        if len(ports) != 1:
            raise SystemExit(
                f"cannot autodetect port (found {len(ports)}: {ports or 'none'}); "
                f"pass --port"
            )
        port = ports[0]

    overrides = {
        "frequency": args.frequency, "pre": args.pre, "post": args.post,
        "loops": args.loops, "trigger_channel": args.trigger_channel,
        "trigger_inverted": args.trigger_inverted,
        "channels": args.channels.split(",") if args.channels else None,
    }
    session = build_session(PRESETS[args.preset], overrides)

    CAPTURES.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = CAPTURES / f"{stamp}_{args.preset}"
    tcs, csv = base.with_suffix(".tcs"), base.with_suffix(".csv")
    tcs.write_text(json.dumps(session, indent=2))

    cmd = [str(TC), "capture", port, str(tcs), str(csv)]
    total = session["PostTriggerSamples"] * (session["LoopCount"] + 1) + session["PreTriggerSamples"]
    print(f"capture id : {base.name}")
    print(f"port       : {port}")
    print(f"channels   : {len(session['CaptureChannels'])} "
          f"({', '.join(c['ChannelName'] for c in session['CaptureChannels'])})")
    print(f"rate       : {session['Frequency']/1e6:g} MS/s")
    print(f"samples    : {total} (pre {session['PreTriggerSamples']}, "
          f"post {session['PostTriggerSamples']} x {session['LoopCount']+1} bursts)")
    print(f"window     : {total/session['Frequency']*1e3:.3f} ms of captured time")
    trig_ch = session["TriggerChannel"]
    print(f"trigger    : {'falling' if session['TriggerInverted'] else 'rising'} edge on "
          f"ch{trig_ch} ({session['CaptureChannels'][trig_ch]['ChannelName']})")
    print(f"command    : {' '.join(cmd)}")

    if args.dry_run:
        print("\n--dry-run: not capturing.")
        return 0

    print("\narming... (Ctrl+C aborts)")
    rc = subprocess.run(cmd).returncode

    sidecar = {
        "capture_id": base.name,
        "timestamp": dt.datetime.now().isoformat(timespec="seconds"),
        "preset": args.preset,
        "preset_description": PRESETS[args.preset]["description"],
        "probe_map": args.probe_map,
        "note": args.note,
        "port": port,
        "session": session,
        "command": cmd,
        "returncode": rc,
        "csv": csv.name if csv.exists() else None,
        "csv_bytes": csv.stat().st_size if csv.exists() else 0,
    }
    base.with_suffix(".json").write_text(json.dumps(sidecar, indent=2))

    if rc != 0 or not csv.exists():
        print(f"\nCAPTURE FAILED (rc={rc}); sidecar written to {base.name}.json")
        return 1

    with csv.open() as f:
        header = f.readline().rstrip("\n")
        rows = sum(1 for _ in f)
    print(f"\nwrote {csv.relative_to(REPO)}  ({csv.stat().st_size} bytes)")
    print(f"header : {header}")
    print(f"rows   : {rows} (expected {total})")
    if rows != total:
        print("WARNING: row count does not match the expected sample count.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
