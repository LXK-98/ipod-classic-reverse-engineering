# iPod Classic (6G/7G) LCD — reverse-engineered pinout and protocol

Complete pinout, bus protocol and electrical characterisation of the 2.5" 320×240 LCD
in the **iPod Classic 2009 "thin" 160 GB** (model A1238, logic board 820‑2437‑A,
Samsung S5L8702 — the revision Rockbox calls `ipod6g`).

Everything here was **measured**, not inferred from documentation. Where the results
disagree with the Rockbox source they are marked as such, with the evidence.

**Status:** all six original goals complete, and the panel's initialisation sequence is
now verified write-by-write on the bus (152/152). Remaining loose ends — none of which block
building a driver — are in [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md).

---

## Results at a glance

| property | value |
|---|---|
| Flex connector | **34 pins**, 0.3 mm pitch |
| Panel variant | **type 2** (of Apple's four) — ILI9320/9326-style 16-bit register command set |
| Logic level | **1.8 V** |
| Bus | 8080-series parallel, **18-bit RGB666**, data latched on **rising edge of /WR** |
| Write cycle | **610 ns** (1.64 MHz) — 70–80 ns low, 530–540 ns high |
| Command writes | two regimes: **818 ns** (60–80 ns low) and **309 ns** (30–40 ns low) — both accepted by the panel |
| Full frame | 76 800 writes ≈ **46.9 ms**, **one transfer per pixel** |
| Init sequence | **146 writes**, 240 ms of sleeps — **all 152 wake writes verified byte-exact on the bus** |
| Refresh (TE) | **67.9 Hz** |
| Backlight | **4 white LEDs**, **19.5 mA**, **12.76 V** at full brightness, low-side PWM |

**[→ Full pinout: PINOUT.md](PINOUT.md)** (generated from [`pinout.json`](pinout.json))

![Reconstructed status bar](docs/frame-example-magnified.png)

*End-to-end proof: rows 0–3 of a live screen, reconstructed from a raw logic-analyzer
capture — blue icon, text glyphs, and the battery outline with its red low-charge fill.*

### Pin summary

| pins | function |
|---|---|
| 1, 2, 9–16, 18–25 | 18-lane RGB666 data bus |
| 3, 6, 8, 17, 31 | GND |
| 4, 5 | Backlight anode (**12.76 V ⚠️**) / cathode via 25.6 Ω sense |
| 7 | TE (tearing effect, 67.9 Hz) |
| 26, 33 | VDDIO 1.8 V / 3.0 V rail |
| 27, 28, 29 | /WR, D/C, /CS |
| 30, 32 | /RD and /RESET — both active-low, idle high ([which is which: open](docs/OPEN-QUESTIONS.md)) |
| 34 | ~1.54 V analog reference — an **input** the panel expects |

> ⚠️ **Pin 4 reaches 12.76 V.** Never connect it to a logic analyzer — a TXU0104
> level shifter is rated 5.5 V absolute maximum on its input side.

---

## Documentation

| document | contents |
|---|---|
| [PINOUT.md](PINOUT.md) | the pinout table, generated from `pinout.json` |
| **[docs/DRIVING.md](docs/DRIVING.md)** | **how to build a driver — start here for Phase 6** |
| [docs/HARDWARE.md](docs/HARDWARE.md) | target device, interposer, instrumentation, safety rules |
| [docs/PROTOCOL.md](docs/PROTOCOL.md) | bus protocol, init sequences, timing, pixel format |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | how each result was obtained and how to reproduce it |
| [docs/FINDINGS.md](docs/FINDINGS.md) | notable findings, including where reality differs from the Rockbox source |
| [docs/OPEN-QUESTIONS.md](docs/OPEN-QUESTIONS.md) | what is still unresolved |
| [docs/LAB-NOTEBOOK.md](docs/LAB-NOTEBOOK.md) | the full chronological log, wrong turns included |

---

## Repository layout

```
PINOUT.md              generated pinout reference
pinout.json            single source of truth — everything else derives from this
docs/                  documentation (above) + the ModemManager udev rule
tools/                 capture, decode and reporting tools (Python, re-runnable)
refs/                  Rockbox sources used as ground truth (GPL v2, see refs/README.md)
captures/              every logic-analyzer capture, gzipped, with JSON sidecars
measurements/          DMM sweeps as TSV
probe_maps/            probe wiring conventions
hardware/interposer/   KiCad project for the 34-pin passive interposer board
```

## Quick start

```bash
pip install -r requirements.txt

python3 tools/rockbox_seq.py --summary      # parse Rockbox into sequence tables
python3 tools/report.py                     # regenerate PINOUT.md from pinout.json
python3 tools/index_captures.py             # regenerate captures/INDEX.md

# decode any capture against the known lane map
python3 tools/decode8080.py captures/20260801_215011_dryrun.csv

# check a capture against the expected Rockbox sequence, write by write
python3 tools/seqmatch.py captures/20260803_203836_init-burst.csv

# reconstruct an image from a captured frame
python3 tools/frame2png.py captures/20260801_222433_dryrun.csv -o frame.png
```

Capturing new data needs the [gusmanb LogicAnalyzer](https://github.com/gusmanb/logicanalyzer)
binaries in `vendor/` (gitignored — download from that project's Releases).

---

## Headline findings

Three results contradict or resolve things the Rockbox source leaves open. Details and
evidence in [docs/FINDINGS.md](docs/FINDINGS.md).

1. **All 18 lanes are actively driven — none is idle.** Every lane is observed both high
   and low across solid-colour fills. `lcd-s5l8702.c` describes frame mode as
   `APB[15:0] -> D[17:10, 8:1]`, which would leave two lanes carrying nothing; a lane that
   is never driven cannot track colour data in both directions, and none behaves that way.
   The lanes group as **6 per colour channel (RGB666)**, and the data is consistent with
   the SoC expanding 5-bit channels by `6bit = (5bit << 1) | (5bit >> 4)`.
   *Caveat: that Rockbox comment block is headed `XXX: WIP, TBC` — its authors flagged it
   as unconfirmed, and their driver is correct regardless, since nothing in it depends on
   the comment.*
2. **Two pin pairs carry identical data under Rockbox** — pins 9/14 and 21/2 — consistent
   with each being the replicated MSB of a 5-bit channel widened to 6. They measure
   6.66 MΩ apart, so this is not a short. **Untested:** whether a driver can give those
   pairs *different* values for true 6-bit colour. All our data comes from an RGB565
   source, where they are identical by construction.
3. **One bus transfer per pixel**, confirmed by a 46.92 ms measured frame time matching
   76 800 × 610 ns to 0.1 %.

## Safety

- **Pin 4 (backlight anode) reaches 12.76 V** — destroys 5.5 V-rated shifter inputs
- Panel logic is **1.8 V**; a level shifter referenced to 3.3 V will *not* read it
  reliably (TXU0104 V<sub>T+</sub> max is 1.92 V at a 3 V reference, above a 1.8 V logic high)
- Ground instruments to **signal** ground (any of pins 3/6/8/17/31), not the chassis —
  the iPod bonds chassis to signal ground through **~300 Ω**
- Disconnect the battery before continuity testing; "powered off" still leaves PMU
  standby rails live

## Licensing

**This project is MIT licensed** — see [LICENSE](LICENSE). That covers the tools,
documentation, measurements, captures, `pinout.json` and the interposer hardware design.

**One exception:** the vendored Rockbox sources in [`refs/`](refs/) are **GPL v2** and are
redistributed under those terms, with the licence text at [`refs/COPYING`](refs/COPYING)
and provenance in [`refs/README.md`](refs/README.md). `refs/sequences.json` is generated
from them and is treated as a derived work under the same terms.

These sit alongside the project as separate works — GPL v2 §2 "mere aggregation" — so they
do not place the rest of the repository under the GPL. Nothing outside `refs/` contains
Rockbox code; `tools/rockbox_seq.py` only parses those files.

## Credits

Built on prior work by the [Rockbox](https://www.rockbox.org/) and
[freemyipod](https://freemyipod.org/) projects, whose driver source made byte-exact
validation possible. Capture hardware and firmware:
[gusmanb/logicanalyzer](https://github.com/gusmanb/logicanalyzer).
