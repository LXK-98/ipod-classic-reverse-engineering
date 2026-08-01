# Notable findings

Results that are surprising, that correct published information, or that would cost
someone else a lot of time to rediscover. The chronological log with all the dead ends is
in [LAB-NOTEBOOK.md](LAB-NOTEBOOK.md).

---

## 1. The bus is RGB666, not raw RGB565

**What Rockbox says.** `lcd-s5l8702.c` documents frame mode as
`APB[15:0] -> D[17:10, 8:1]` and marks it *"TBC"*. That mapping would place the 16-bit
RGB565 word onto 16 of the 18 lanes and leave **D9 and D0 undriven**.

**What we measure.** All 18 lanes are driven. Saturating one colour channel drives
**exactly six** lanes high — 6/6/6, not the 5/6/5 the documented mapping implies. The SoC
performs a genuine 5→6 bit expansion:

```
6bit = (5bit << 1) | (5bit >> 4)      # replicate the MSB into the LSB
```

Red and blue (5-bit in RGB565) are expanded; green (already 6-bit) passes through.

**Evidence.** Nine captures of known colours, including three asymmetric ones —
indigo (`R5=01001, B5=10000`), violet (`G6=100000`) and orange (`G6=101001`) — where a
wrong model fails visibly. All match exactly.

---

## 2. Two pin pairs are identical by design and look exactly like a short

**Pins 9 and 14 carry byte-identical data in every capture. So do pins 21 and 2.**

They measure **6.66 MΩ apart** (open), the wiring is confirmed correct, and the display
works perfectly. They are the two ends of a replicated colour channel: pin 14 is a
hardware copy of pin 9 (red MSB), pin 2 a copy of pin 21 (blue MSB).

This cost hours. Every hardware hypothesis was tested and rejected first — solder bridge,
mis-landed probe wire, crosstalk, bus contention. The clue that broke it: a short with one
driver winning contention fits the colour fills but **cannot** fit the init capture, where
the two pins tracked a *varying* signal that one of them should not have carried.

**If you see two data lanes on this panel that never disagree, this is why.**

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

### A dead group of exactly four channels means one translator's OE pin

Both gusmanb LogicAnalyzer V2 boards had **exactly four adjacent channels stuck at 0**,
in different groups. The TXU0104 is a 4-bit device and `OE` gates all four outputs, so a
single unsoldered pin kills a whole group while **both supply rails still measure a
perfect 3.3 V**.

`OE` is pin 8, adjacent to `GND` on pin 7 — the corner a drag-solder pass most easily
skips. Reflowing fixed it; no part replacement.

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
