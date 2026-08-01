# Methodology

How each result was obtained, and how to reproduce or extend it.

The organising principle: **Rockbox source is public, so the bytes on the bus are known in
advance.** That turns most of the problem from "what is this signal?" into "which physical
pin carries this known bit?", which is a matching problem rather than a guessing one.

## Tools

All re-runnable, all reading state from files rather than from memory.

| tool | purpose |
|---|---|
| `rockbox_seq.py` | parses the Rockbox driver into byte-exact bus transaction tables for all four panel variants × two build configs → `refs/sequences.json` |
| `capture.py` | wrapper around `TerminalCapture`; presets, port autodetection, sample-budget guard, JSON sidecar per capture |
| `classify.py` | per-channel statistics and conservative heuristic labels |
| `decode8080.py` | latches the bus on /WR, splits command/data by D/C, assembles words from the lane map |
| `frame2png.py` | reconstructs an image from a capture; recovers the update rectangle from the window-setup commands |
| `record_dmm.py` | ingests DMM sweeps (TSV) into `pinout.json` with classification |
| `report.py` | regenerates `PINOUT.md` from `pinout.json` |
| `index_captures.py` | regenerates `captures/INDEX.md` from the sidecars |
| `capio.py` | shared capture I/O; `.csv` and `.csv.gz` interchangeable |
| `picogen.py` | drives a Pico as a known-signal generator for pipeline validation |

## Sequence of work

### 0 — Validate the pipeline before trusting it

A Pico generating a known PWM (exact frequency, two different duty cycles) was captured
and checked end to end. Acceptance was **0.000 % frequency error and 0.00 pp duty error**
at both 1 MS/s and 100 MS/s.

This is worth the time: it caught the ModemManager fault (see
[FINDINGS](FINDINGS.md#modemmanager-silently-breaks-usb-logic-analyzers)) in a context
where the correct answer was known. The same fault appearing later, as garbled data from
an unknown flex, would have been attributed to probe contact.

It also established two artefacts that would otherwise have been read as real:
pre-trigger buffers are zero-filled when the trigger fires immediately, and the first and
last runs in a capture are truncated by the window and must be excluded from pulse-width
statistics.

### 1 — DMM triage

With the battery **disconnected**, resistance from every pin to signal ground; then with
the battery connected and the device booted, DC voltage on every pin.

Use the **resistance range, not continuity/beeper mode.** The beeper collapses everything
above ~50 Ω into "OL" and hid all the structure — including the 25.6 Ω backlight sense
resistor, which is the single most informative reading in the sweep.

Pin groups emerged clearly: five grounds at 0.6–1.5 Ω, one pin at 25.6 Ω, a cluster at
0.5–0.6 MΩ and a larger one at 3.7–3.8 MΩ. Megohm values are leakage through unpowered
semiconductor structures — the **clustering** is meaningful, the absolute values are not.

The powered sweep then separated rails (steady), signals (fluctuating) and the backlight
anode (far above logic level).

### 2 — Panel identification

Read directly from Rockbox's debug menu — *System → Debug (Keep Out!) → View HW info* —
which prints `LCD type: N`, cross-checked against *View I/O ports* showing `GPIO 6`, since
the driver selects the variant with `(PDAT6 & 0x30) >> 4`.

No capture required. If Rockbox will not boot, the same value is readable from the GPIO
dump reachable from the ATA-error screen.

### 3 — Capturing the initialisation

The init is the richest known-value stimulus available: 146–152 writes of documented
content.

**Trigger it by LCD sleep/wake, not by rebooting.** For a type‑2 panel `seq_awake` *is*
the init sequence, so a wake replays it in full with the iPod already powered — which
matters because VREF is derived from the target (see
[HARDWARE](HARDWARE.md#level-shifting--the-critical-setting)).

**Burst mode is what makes it fit.** The wake sequence opens with six NOPs spaced 1.28 ms
apart — a 7.7 ms prefix, where the entire capture budget at 100 MS/s is 328 µs. Seven
bursts solve it: the first six are each consumed by one NOP, and the seventh lands on the
register block, capturing ~69 consecutive writes.

That the first six bursts each contain **exactly one write** is itself the proof that the
capture began at the sequence's true start, so the alignment is anchored rather than
assumed.

### 4 — Solving the lane map

With alignment fixed, each physical channel's bit history across the captured writes must
equal exactly one expected bit column. Matching is O(n²) and unambiguous: over 69 writes a
false match has probability 2⁻⁶⁹.

**What this cannot do:** bits that never change during the init (6, 14, 15 were constant
zero) are invisible to it — a limitation predicted from the source *before* any hardware
was connected, which is why colour fills were planned from the start rather than improvised.

### 5 — Colour fills

Rockbox's **`lamp` plugin** is the ideal stimulus: a full-screen solid colour from a
hard-coded palette (`apps/plugins/lamp.c`), so the expected bus word is known exactly.

**Saturated colours are not enough.** Red, green, blue and white drive every lane of a
channel to the same level, so they validate *which* pins belong to a channel and say
nothing about their *order*. Non-saturated colours are required:

| colour | RGB565 | what it isolates |
|---|---|---|
| indigo | `0x4810` | R5 = `01001`, B5 = `10000` → blue MSB outright |
| violet | `0xEC1D` | G6 = `100000` → green MSB outright |
| orange | `0xFD20` | G6 = `101001` → two more green positions |
| custom `G=16` | — | G6 = `010000` → the last green position |

Rockbox's colour picker works in **RGB565 units directly** (R 0–31, G 0–63, B 0–31), so a
target value can be dialled in without conversion.

### 6 — Verify by reconstruction, against reality

`frame2png.py` renders captured pixels as an image. This is the only check in the whole
project that is **independent of expectation**: it either looks like the screen or it does
not.

It is what caught the bit-order error. Nine byte-exact protocol matches had already
"passed" — the reconstruction rendering a grey status bar as green is what exposed the
problem. **Compare against the physical device, not only against predictions.**

## Practical notes

- **Capture only during activity.** A static screen produces *zero* bus traffic; Rockbox
  writes only on change. Scroll a menu to force redraws.
- **Burst mode always starts at the first pixel of a frame** (rows 0–3), and row 0 is the
  status bar, which keeps its own colour regardless of theme background. Reaching lower
  rows means arming during an active blit.
- **There is a >1.6 ms gap** between the `0x202` GRAM-write command and the first pixel,
  while 153 KB is copied into the DMA buffer. A window shorter than that sees the setup
  and then silence.
- **Stop a capture with SIGINT, never SIGTERM** — SIGTERM leaves the analyzer armed and it
  will refuse the next capture until replugged.
- **Sample rate floor is ~13 MS/s** for this bus and realistically 20 MS/s. Below that the
  70–80 ns /WR pulse is missed, and undersampling produces *convincing* wrong answers, not
  obvious noise.

## Reproducing

```bash
pip install -r requirements.txt
python3 tools/rockbox_seq.py --summary          # ground truth, no hardware needed
python3 tools/decode8080.py captures/20260801_215011_dryrun.csv
python3 tools/frame2png.py captures/20260801_222433_dryrun.csv -o frame.png
python3 tools/report.py                          # regenerate PINOUT.md
```

Every capture in `captures/` has a JSON sidecar recording its settings, the probe-map
version in force and a free-text note; `captures/INDEX.md` tabulates them.
