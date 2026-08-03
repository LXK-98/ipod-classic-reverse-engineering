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
| `seqmatch.py` | diffs a decoded capture against a known sequence in `refs/sequences.json`; checks per-burst write counts against that sequence's run/sleep structure, and cross-checks /WR pulses against D/C transitions to catch undersampling |
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
apart — a 7.7 ms prefix, where the entire capture budget at 100 MS/s is 328 µs. Bursts
solve it: each NOP is consumed by one burst, and the next burst lands on the register
block.

That the first six bursts each contain **exactly one write** is itself the proof that the
capture began at the sequence's true start, so the alignment is anchored rather than
assumed.

#### Size the plan from the sequence, then pick the rate to fit

The run/sleep structure of the target sequence *is* the burst plan. Read it out of
`refs/sequences.json` before capturing — for type-2 `seq_awake` it is:

```
1,1,1,1,1,1 (NOPs, 1.28 ms apart) → 140 → 30 ms → 2 → 60 ms → 2 → 150 ms → 2
```

Nine gaps, therefore **ten bursts**, and the observed per-burst counts must come back as
`[1,1,1,1,1,1,140,2,2,2]`. `tools/seqmatch.py` checks exactly that, so the plan
self-validates.

Then three constraints fix the rate, and **the binding one is usually the burst
duration, not the sample rate**:

| constraint | value here |
|---|---|
| burst must hold the longest run | 140 writes ≈ **98 µs** at ~700 ns/write |
| burst must end before the next event, so re-arm falls in a sleep | shortest gap **1.28 ms** |
| rate must catch the 70–80 ns /WR low | **≥20 MS/s** |

`burst_samples = budget / bursts`, so `rate ≤ budget / (bursts × longest_run_duration)`.
At 24 channels: 32 767 / (10 × 98 µs) ≈ 33 MS/s. **20 MS/s** was used, giving 163.5 µs per
burst — 68 % headroom on the 97.5 µs the block actually took.

This sum is what the first attempt got wrong. It ran at 100 MS/s with seven bursts, giving
46.7 µs per burst, and returned 69 of the 140 writes — not a fault, just a window shorter
than the run. **Sample rate buys pulse fidelity; it costs window. Spend only what the
narrowest pulse needs.**

**Sizing bursts is a real tradeoff, and getting it wrong corrupts results silently.**
After each burst the device re-arms and waits for the *next* trigger edge, so **a write can
be lost at every burst boundary**:

| arrangement | effect |
|---|---|
| many small bursts | more total coverage of activity, but a risk of a dropped write at every boundary |
| few large bursts | fewer boundaries, long contiguous runs |

This is observed, not theoretical: in the 10-burst capture the write that should have
triggered burst 10 was lost, the burst opening mid-cycle with D/C already low and /WR
already high.

**But the loss rate is much lower than one-per-boundary.** `20260801_212943_dryrun` chops
the same 140-write block across roughly twenty boundaries and loses **one** write in total.
Treat one-per-boundary as a worst case, not an expectation. The design rule still stands —
put boundaries inside known sleeps — because *which* write is lost is unpredictable, and
one lost write in the wrong place is enough to matter.

For **sequence matching** the cost is now bounded rather than fatal — `seqmatch.py` diffs
instead of assuming a fixed offset, so a dropped write reports as one deletion at a known
index rather than shifting everything after it into a wall of false mismatches. For
**image reconstruction** a dropped write shifts every subsequent pixel and shears the
picture diagonally — two bursts were used there, so the image comes entirely from one
contiguous run.

### Attempts that failed, and why

Worth knowing before repeating this:

- **Arming before a cold boot does not work** if VREF is taken from the target. The
  shifter loses its reference as the iPod powers down, every output goes high-Z, and the
  collapse itself trips the trigger — 24 channels of flat zero. Use the sleep/wake trigger,
  or derive VREF independently (a 1 kΩ divider off the analyzer's 3v3 holds 1.6 V).
- **A contiguous capture at 100 MS/s lands inside the NOP prefix.** The wake sequence opens
  with six NOPs spread over 7.7 ms; the entire sample budget is 328 µs. Such a capture
  returns two writes and looks like a failure when it is really a window-size problem.
- **Running burst mode at the maximum rate truncates the register block.** The same
  window-size mistake one level down: 100 MS/s over seven bursts gives 46.7 µs each, and
  the 140-write block needs ~98 µs. It returns 69 writes that are all *correct*, which is
  why it read as a hardware ceiling for two days rather than as a parameter to change.
- **Triggering on /WR during idle catches the wrong thing.** With a static screen there is
  no traffic at all, so the trigger fires on the *next* screen update — which begins with
  `displaylcd_setup()`, not the init. That accident is how the 13-write window-setup
  sequence was first identified, but it is not the init.

**One that looked like a failure and was not.** The init writes sat at 69 of 140 for two
days, filed alongside the cold-boot problems above. They were never a cold-boot problem:
the sleep/wake trigger reaches them with the target powered and VREF valid. Only the
burst-sizing sum was wrong, and redoing it captured **151 of 152 writes byte-exactly**.
Check which unknown a failure actually belongs to before inheriting its blockers.

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
- **Sample rate floor is ~33 MS/s** for command traffic of unknown provenance. 20 MS/s
  covers the slow regime (70–80 ns /WR low) and pixel bursts, but the bus also has a **fast
  command regime with a 30–40 ns low**, which is *shorter than the 50 ns sample interval at
  20 MS/s* and vanishes without trace. Undersampling produces *convincing* wrong answers,
  not obvious noise — see [FINDINGS §12](FINDINGS.md#12-the-bus-has-two-command-write-speeds-and-the-fast-one-needs-33-mss).
- **Balanced /WR edge counts are not proof of a complete capture.** A pulse falling between
  two samples takes both its edges with it. Cross-check against D/C, which changes only
  between writes of different kinds: within one burst `writes ≥ D/C transitions + 1` must
  hold. `seqmatch.py` checks this automatically.

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
