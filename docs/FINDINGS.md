# Notable findings

Results that are surprising, that correct published information, or that would cost
someone else a lot of time to rediscover. The chronological log with all the dead ends is
in [LAB-NOTEBOOK.md](LAB-NOTEBOOK.md).

---

## 1. All 18 lanes are driven; the bus behaves as RGB666

**What Rockbox says.** `lcd-s5l8702.c` describes frame mode as
`APB[15:0] -> D[17:10, 8:1]`, which would place the 16-bit RGB565 word onto 16 of the 18
lanes and leave two carrying nothing.

**Important context:** that comment block opens with `XXX: WIP, TBC`. The authors marked
it unconfirmed, and **the Rockbox driver is correct regardless** — it sets `LCD_MODE_P16`
and DMAs RGB565, so whatever the SoC does internally is transparent to it. This is a
mismatch between measurement and an explicitly-provisional comment, **not a bug in
Rockbox**.

**What we measure.** Every one of the 18 lanes is observed **both high and low** across
solid-colour fills — none is stuck at a level. An undriven line floats and cannot track
colour data in both directions, so no lane is idle. Saturating one channel drives
**exactly six** lanes high: 6/6/6, not the 5/6/5 the description implies. The data is
consistent with a 5→6 bit expansion:

```
6bit = (5bit << 1) | (5bit >> 4)      # replicate the MSB into the LSB
```

Red and blue (5-bit in RGB565) are expanded; green (already 6-bit) passes through.

**Evidence.** Nine captures of known colours, including three asymmetric ones —
indigo (`R5=01001, B5=10000`), violet (`G6=100000`) and orange (`G6=101001`) — where a
wrong model fails visibly. All match exactly, plus a reconstructed image that matches the
physical screen.

**Limit of the claim.** Our pin numbering is anchored to the interposer and has **no known
mapping to the SoC's `D0`–`D17`**. So the finding is "no lane is undriven", not "D9 and D0
specifically are driven". The contradiction is with observable behaviour, not with their
pin names.

---

## 2. Two pin pairs carry identical data and look exactly like a short

**Pins 9 and 14 carry byte-identical data in every capture. So do pins 21 and 2.**

They measure **6.66 MΩ apart** (open), the wiring is confirmed correct, and the display
works perfectly. They are the two ends of a replicated colour channel: pin 14 is a
hardware copy of pin 9 (red MSB), pin 2 a copy of pin 21 (blue MSB).

This cost hours. Every hardware hypothesis was tested and rejected first — solder bridge,
mis-landed probe wire, crosstalk, bus contention. The clue that broke it: a short with one
driver winning contention fits the colour fills but **cannot** fit the init capture, where
the two pins tracked a *varying* signal that one of them should not have carried.

**If you see two data lanes on this panel that never disagree, this is why.**

**Not yet verified:** whether those pairs can be driven *independently* to obtain true
6-bit-per-channel colour. Every capture we have comes from an RGB565 framebuffer, where
they are identical by construction, so we have never observed — nor caused — them to
differ. They are not shorted (6.66 MΩ) and the interface is 18 lanes wide, which makes
independent drive likely, but it is an inference. Settling it requires driving the panel
(phase 6).

---

## 3. The same pin carries different signals in command and frame mode

Pin 14 decodes as **APB bit 10** during 16-bit command writes, and as the **replicated red
MSB** during pixel writes. Both are correct; the SoC drives the lanes differently in the
two output modes (`LCD_MODE_P18` for commands, `LCD_MODE_P16` for frames).

A lane map derived from the init sequence is therefore **not** a valid model for decoding
pixels, and vice versa. Conflating them produces a phantom one-bit error that appears only
in colours where the two interpretations diverge.

---

## 4. One transfer per pixel

`lcd-s5l8702.c` describes frame mode as "RGB565 / 1-transfer" but marks the surrounding
detail "TBC". Confirmed by timing: a full-screen blit measures **46.92 ms**, and
76 800 pixels × 610 ns = **46.85 ms** — a 0.1 % match. Two transfers per pixel would take
twice as long.

---

## 5. Saturated colours cannot validate bit order within a channel

Red, green, blue and white fills all drive **every lane of a channel to the same level**,
so any permutation of the lanes within that channel decodes identically. Four "perfect"
colour matches proved the *field membership* and said nothing whatsoever about the
*ordering*.

The error surfaced only when the reconstructed image was compared against the physical
screen: the status bar rendered green when it is visibly grey.

**Nine byte-exact protocol matches did not catch this. Looking at the screen did.**

Resolving it needed colours that isolate single bits — `G6 = 32` (violet) identifies the
green MSB outright, `G6 = 41` (orange) fixes two more positions, and a custom `G = 16`
pins the last one.

---

## 6. Rockbox's LCD sleep setting is both the best tool and a trap

For a type‑2 panel, `seq_awake` **is** the init sequence, so an LCD sleep/wake cycle
replays a full 152-write initialisation without rebooting. That makes Phase 3 easy.

The same setting then actively obstructs frame capture: with sleep enabled the panel drops
back to sleep within seconds, so every interaction begins with a **7.7 ms NOP prefix**
(six `CMD 0x0000` spaced 1.28 ms apart) before any pixel moves. A short capture window
lands entirely inside the prefix and returns two writes.

---

## 7. Instrumentation findings

### ModemManager silently breaks USB logic analyzers

On systemd distributions, udev tags any CDC-ACM device — **including the logic
analyzer** — with `ID_MM_CANDIDATE=1`, and ModemManager probes it with AT commands. On a
Pico-class USB stack this wedges the port: it stays enumerated, descriptors read
correctly, and the data path goes deaf in both directions.

Fix in [`docs/99-bench-instruments.rules`](99-bench-instruments.rules). Note that
`ID_MM_CANDIDATE` legitimately *stays* set — the property that matters is
`ID_MM_DEVICE_IGNORE`.

Had this first appeared as garbled data from an unknown 33-pin flex, the obvious suspects
would have been probe contact or undersampling.

### The highest sample rate is usually the wrong one

Sample rate buys pulse fidelity and costs window, and on a fixed-depth analyzer the window
is what is normally scarce. Capturing the init at the maximum 100 MS/s gave 46.7 µs per
burst and returned **69 of the 140** writes in the register block, which needs ~98 µs.

The failure mode is the dangerous kind: all 69 writes were *correct*, byte-exact against
the source, and the capture reported success. It read as a hardware ceiling for two days.
Dropping to **20 MS/s** — still 2.5× the rate needed to catch a 70–80 ns pulse — quadrupled
the window and captured **151 of 152** writes.

**Spend only what the narrowest pulse needs, then spend the rest on window.** Compute the
longest contiguous run you must hold *before* choosing a rate.

⚠️ **But know what the narrowest pulse actually is.** 20 MS/s was chosen against the
70–80 ns /WR low of the slow regime. The bus also has a **fast** command regime with a
**30–40 ns** low, which 20 MS/s misses outright — see
[finding 12](#12-the-bus-has-two-command-write-speeds-and-the-fast-one-needs-33-mss). The
init itself is entirely slow-regime, so that capture is unaffected, but the general rule
needs the faster figure: **≥33 MS/s** unless you know the traffic is slow.

### A dead group of exactly four channels means one translator's OE pin

Both gusmanb LogicAnalyzer V2 boards had **exactly four adjacent channels stuck at 0**,
in different groups. The TXU0104 is a 4-bit device and `OE` gates all four outputs, so a
single unsoldered pin kills a whole group while **both supply rails still measure a
perfect 3.3 V**.

`OE` is pin 8, adjacent to `GND` on pin 7 — the corner a drag-solder pass most easily
skips. Reflowing fixed it; no part replacement.

**A dead group can survive a capture that otherwise looks convincing.** Re-running
`tools/seqmatch.py` over `20260801_200739_dryrun` — taken on LA-B *before* the U4 reflow —
reports every DATA write decoding as CMD. Channels 20–23 (silkscreen CH21–24 = P28, P29,
P30, P32) have **exactly zero edges** for the whole capture: D/C was dead throughout. The
capture still produced a plausible 74-write sequence with correct data values. Comparing
against the expected sequence is what surfaces it; eyeballing the decode does not.

The V2 chip-to-channel map is **not** in physical order, so identifying a chip by eye
misleads:

| position (top→bottom) | ref | channels | flanking caps |
|---|---|---|---|
| 1 | U1 | CH1–4 | C1, C7 |
| 2 | U4 | **CH21–24** | C4, C10 |
| 3 | U6 | CH5–8 | C6, C12 |
| 4 | U5 | CH17–20 | C5, C11 |
| 5 | U3 | CH9–12 | C3, C9 |
| 6 | U2 | **CH13–16** | C2, C8 |

### The analyzer intermittently drops off USB

Observed twice in one session: the LogicAnalyzer disappears from the USB bus entirely — no
`/dev/serial/by-id` entry, nothing in `lsusb` — and returns after a reseat or on its own.

This matters because of how it presents during a long armed wait: a capture that is armed
when the device drops looks identical to **"the trigger never fired."** Several
inconclusive cold-boot captures in this project may have been affected; it was never
established either way.

**Practical rule:** before interpreting a non-triggering capture as a fact about the
target, confirm the analyzer is still enumerated. `tools/capture.py --list-ports` is the
one-line check.

### A level shifter referenced too high fails silently

At a 3.3 V reference the TXU0104's V<sub>T+</sub> maximum is **1.92 V** — *above* a 1.8 V
logic high. Probing 1.8 V logic on a 3v3 reference gives intermittent, plausible-looking,
wrong data. Referenced to 1.8 V the threshold drops to ~1.23 V with comfortable margin.

The complementary failure is loud and therefore safe: with `VREF` absent the TXU0104's
`Ioff-float` feature forces every output high-Z, producing an unmistakable field of zeros
rather than subtly bad data.

### VREF cannot come from the device under test

Referencing the shifter to the iPod's own 1.8 V rail works while the iPod is running, but
makes a **cold-boot capture impossible**: as the target powers down, VREF collapses, every
channel goes high-Z, and the collapse itself trips the edge trigger. For cold-boot work,
derive VREF from the analyzer's own 3v3 through a divider.

### Killing a capture with SIGTERM leaves the analyzer armed

`TerminalCapture` handles SIGINT by calling `StopCapture()`, but a `timeout`-issued
SIGTERM does not — the device stays armed and refuses the next capture until it is
unplugged. Send SIGINT.

### The pre-trigger buffer is not filled if the trigger fires immediately

Samples before the trigger are zero-filled unless the device was armed long enough to
fill that buffer. On a free-running signal this is obvious (a physically impossible run of
silence); on a sporadic one it is not. `tools/classify.py` flags it as
`pretrigger_unfilled`.

---

## 8. Two distinct grounds

Signal ground (the flex GND pins and the HDD case) is bonded to chassis ground (dock
shell, rear shell) through **~300 Ω** — a deliberate ESD/EMI measure, not a fault.

Instruments must reference **signal** ground. Grounding a logic analyzer to the case or
dock shell puts 300 Ω in the return path, which degrades captures and produces
common-mode artefacts easily misread as bad probe contact.

The rear shell and headphone jack additionally read open because they are anodised.

---

## 9. Corrections to the original project brief

| brief said | actually |
|---|---|
| 33-pin LCD flex | **34 pins** |
| Rockbox can read a display ID | `S5L_LCD_WITH_READID` is **undefined** for `ipod6g`; /RD never moves |
| Use `CLCapture` | removed in release 6.0.0.1; **`TerminalCapture`** replaces it, settings-file driven |
| Stop if VDDIO < 2.3 V | a configuration change (shifter VREF), not a blocker |
| Panel type needs protocol decoding | readable directly from Rockbox's debug menu |

---

## 10. Measurements taken at the wrong operating point give wrong answers

The backlight anode reads **10.7 V at brightness 7** and **12.76 V at brightness 63**,
because the LED string is PWM-dimmed and the boost converter is barely loaded at low duty.

Deriving the LED count from the low-brightness figure gave **3 LEDs**. The correct figure
gives **4** (12.26 V across the string ÷ 3.07 V per LED). A driver designed against the
first number would target ~11 V and fail to light the panel at all.

---

## 11. Charger noise contaminated every analog measurement

Pin 34 was chased for a long time on the strength of an apparent signal: a "~80 µs square
wave", then a "~12.5 kHz ripple", then bursts of ringing and a 125 Hz frequency readout.
Different timebases produced different, mutually inconsistent descriptions — which should
have been the clue.

**None of it was real.** Every one of those observations disappears when the USB charger
is unplugged and returns when it is reconnected. The pin is a quiet DC reference; the
"signal" was switching noise from the charging circuit coupling onto a high-impedance
node.

**Take analog measurements on battery power.** Digital captures are largely immune —
they are threshold-based and the noise is far below a logic swing — but anything measured
with a scope or read as a small AC component needs the charger disconnected.

The tell, in hindsight: a signal whose apparent period changes with the timebase you view
it at is not a signal.

---

## 12. The bus has two command-write speeds, and the fast one needs 33 MS/s

The documented "610 ns cycle, 70–80 ns /WR low" is **not the only regime**. The same
13-write `displaylcd_setup()` block was captured at both:

| regime | write cycle | /WR low | minimum sample rate |
|---|---|---|---|
| slow | **818 ns** | **60–80 ns** | 16.7 MS/s |
| fast | **309 ns** | **30–40 ns** | **33.3 MS/s** |

Measured on 100 MS/s captures of the identical command sequence; both regimes appear
across the capture set, and which one a given redraw uses is not yet understood.

**A 30 ns pulse is shorter than the 50 ns sample interval at 20 MS/s, so it can be missed
entirely.** That is not a marginal risk, it is a certainty for some phase alignments: in
`20260803_203836_init-burst`, **6 of 13** window-setup writes left no trace on /WR.

**Correcting a claim made earlier in this project:** balanced falling and rising /WR edge
counts were treated as proof that no pulse was missed. They are not. A pulse that falls
entirely between two samples removes *both* of its edges, so the counts stay balanced and
the write disappears silently. The check only rules out pulses **clipped at a window
boundary**.

**The sound check is D/C.** It changes only between writes of different kinds, so within
one burst `writes ≥ D/C transitions + 1` always holds. A violation proves writes occurred
that /WR never showed. `tools/seqmatch.py` applies this per burst.

**Two consequences.**

- **For capture:** use **≥33 MS/s** for command traffic of unknown provenance. 20 MS/s is
  sufficient only for the slow regime and for pixel bursts (610 ns, 70–80 ns low).
- **For a driver:** the panel demonstrably accepts **309 ns write cycles with a 30–40 ns
  /WR low** — the SoC itself does this routinely. The known-good operating point is
  therefore considerably faster than the 610 ns figure suggests. See
  [DRIVING §3](DRIVING.md#3-bus-protocol).

---

## 13. The evidence set was searched by intent, never by content

The full init sequence — 151 of 152 writes — sat in `20260801_212943_dryrun` from the
evening it was taken. Its sidecar note says *"post-reflow check: burst capture of ordinary
screen activity"*. It was armed for an unrelated reason while the display happened to wake,
and swept up the whole sequence.

Nobody knew, because the project had a tool that answered **"what is on the bus"**
(`decode8080.py`) and none that answered **"is this the sequence we expected"**. Captures
were located by reading the note column of `INDEX.md`, which records the *intent* of a
capture and not what it actually contains. For two days the init was treated as blocked at
69 of 140 writes.

Writing `seqmatch.py` and running it across all 40 captures — five minutes — found it
immediately, and also retro-flagged a capture with a dead D/C channel (see finding 7).

**Rule: when you build a new analysis, run it over the whole existing evidence set before
collecting more data.** A capture taken for one purpose routinely contains the answer to
another, and only a content-based search will find it.

A useful side effect: the two init captures lose *different* writes (#105 and #150), so
their union covers **152/152**. Redundant captures of the same event are not waste — the
losses are uncorrelated.

---

## 14. A silent no-arm is indistinguishable from "no trigger yet"

An over-large capture configuration makes the device fail to arm, and nothing in the
toolchain says so. `TerminalCapture` prints `Capture started, press Ctrl+C to stop.` and
then waits — identical output whether it is armed and waiting, downloading samples, or
refusing the configuration outright. `capture.py` runs it with **no timeout**, so it waits
forever.

The failure therefore presents as operator patience running out. Five cold-boot captures
on 2026-08-02 were recorded in both the notebook and OPEN-QUESTIONS as "did not fire".
All five sidecars record `returncode: -2` — SIGINT. They were killed from the keyboard.
Nothing about the analyzer's cold-boot behaviour was ever established, and an open question
was parked on the strength of it.

**Two diagnostics close this hole, and both were already available.**

- **`/proc/<pid>/io`** — `rchar` static means still armed; `rchar` climbing means the
  trigger fired and samples are transferring. The only reliable progress signal there is.
- **The returncode in the sidecar** — `0` success, `1` genuine tool-reported failure,
  `-2` SIGINT (operator Ctrl+C), `143` SIGTERM (killed). `capture.py` has been writing
  this into every sidecar all along. It had simply never been read.

**The cause is an oversized pre-trigger, confirmed by controlled test.** `20261012_161426`
and `20261012_161634` are identical — 8 channels, 131071 total samples, same trigger
channel, 1 MS/s, same rig, same session — and differ only in pre-trigger, 65536 against
1024. The first sat armed for 128 s with its trigger signal demonstrably present and never
fired; the second completed with `rc=0` and a full 131071 rows.

The whole record agrees. Across 44 sidecars, **every one of the 35 successes used
`pre` ∈ {64, 512, 1024}**, and **no capture with `pre > 1024` has ever produced data** —
0 of 7 (8000 ×3, 30000 ×2, 65536 ×2). Only two failures sit below the ceiling, both
independently explained: `20260801_213713` (`rc=1`, a genuine tool error) and
`20260801_222235` (aborted, degenerate `pre=1`).

The true ceiling lies somewhere in **(1024, 8000]** and has not been bisected; 1024 is
simply the largest value ever observed to work, and `capture.py` now refuses anything above
it. To widen the pre-trigger window in *time*, lower the sample rate instead.

Two things this is **not**: the 8-channel tier works — that controlled test was the first
8-channel capture ever taken here and it returned full depth — and a 131071-sample total is
legal, since both captures requested it.

**This also fully explains the five cold-boot attempts.** They used `pre` of 8000 (×3) and
30000 (×2), above the ceiling. They could never have armed however long anyone waited. The
SIGINT in each sidecar records an operator correctly observing nothing happen; the root
cause was this bug, not impatience and not the hardware.

**The general point:** a tool that cannot distinguish "waiting" from "broken" converts
every configuration error into a false negative about the hardware. Record the returncode,
and never read "no data" as "the signal was absent".
