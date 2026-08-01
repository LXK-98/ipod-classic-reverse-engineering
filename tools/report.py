#!/usr/bin/env python3
"""Regenerate PINOUT.md from pinout.json.

Single source of truth is pinout.json; this file is derived and should never be
hand-edited. Confidence is carried through verbatim so a reader can tell measured
facts from inferences.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

CONF = {"high": "**high**", "medium": "medium", "low": "low", "none": "—"}


def main() -> int:
    d = json.loads((REPO / "pinout.json").read_text())
    p = d["pins"]
    n = d.get("flex_pin_count", len(p))
    out: list[str] = []
    A = out.append

    A(f"# iPod Classic LCD flex pinout\n")
    A(f"Generated from `pinout.json` {d['version']} ({d['updated']}) by `tools/report.py`.")
    A("Do not edit by hand.\n")

    dev = d["device"]
    A("## Device\n")
    for k, v in dev.items():
        A(f"- **{k.replace('_', ' ')}**: {v}")
    A("")

    A("## Panel\n")
    pt = d["panel_type"]
    A(f"- **Type {pt['value']}** ({CONF[pt['confidence']]} confidence) — "
      f"{pt['implications']['cmdset_family']}")
    A(f"- Command set: **{pt['implications']['cmdset_bits']}-bit** register interface")
    A(f"- Interface I/O voltage (VDDIO): **{d['vddio']['value']} V**")
    if "panel_module_marking" in d:
        A(f"- Module marking: `{d['panel_module_marking']['value']}`")
    A("")

    A("## Numbering convention\n")
    A(f"> {d['numbering_convention']}\n")

    A(f"## Pinout — {n} pins\n")
    A("| pin | function | confidence | notes |")
    A("|----:|----------|:----------:|-------|")
    for i in range(1, n + 1):
        e = p[str(i)]
        note = (e.get("notes") or "").replace("\n", " ").replace("|", "/").strip()
        if len(note) > 110:
            note = note[:107] + "…"
        A(f"| {i} | {e['function']} | {CONF.get(e['confidence'], '—')} | {note} |")
    A("")

    if "pixel_format" in d:
        pf = d["pixel_format"]
        A("## Pixel format\n")
        A(f"**{pf['bus']}**\n")
        for fld, pins in pf["fields"].items():
            A(f"- **{fld}**: pins {', '.join(str(int(x[1:])) for x in pins)}")
        A(f"\n{pf['rockbox_side']}\n")
        if pf.get("open_question"):
            A(f"> **Open:** {pf['open_question']}\n")

    if "timing" in d:
        t = d["timing"]
        A("## Bus timing (measured at 100 MS/s)\n")
        A(f"- /WR low: **{t['wr_low_ns'][0]}–{t['wr_low_ns'][1]} ns**")
        A(f"- /WR high: **{t['wr_high_ns'][0]}–{t['wr_high_ns'][1]} ns**")
        A(f"- /WR cycle: **{t['wr_cycle_ns']} ns** ({t['wr_rate_hz']/1e6:.2f} MHz)")
        A(f"- Transfers per pixel: **{t['transfers_per_pixel']}**")
        A(f"- Full frame: {t['full_frame_writes']} writes ≈ {t['full_frame_ms']} ms")
        A(f"- D/C polarity: **0 = command, 1 = data**")
        A(f"- Data latched on the **rising edge of /WR**\n")

    if "backlight" in d:
        b = d["backlight"]
        A("## Backlight\n")
        A(f"- Anode **pin {b['anode_pin']}** at **{b['anode_volts']} V** — "
          f"⚠️ never connect to a 5 V-max analyzer input")
        A(f"- Cathode **pin {b['cathode_pin']}** through a **{b['sense_resistor_ohms']} Ω** "
          f"sense resistor")
        A(f"- {b['note']}\n")

    if "analyzers" in d:
        A("## Instrumentation notes\n")
        for k, v in d["analyzers"].items():
            if isinstance(v, dict):
                A(f"- **{k}** (`{v['serial']}`): good {v['good']}; "
                  f"dead group {', '.join(v['dead_group'])}")
        A(f"\n> {d['analyzers']['note']}\n")

    (REPO / "PINOUT.md").write_text("\n".join(out) + "\n")
    print(f"wrote PINOUT.md ({len(out)} lines) from pinout.json {d['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
