# Open questions

Everything in the original scope is complete. These are the remaining loose ends, none of
which block driving the panel.

---

## 1. Which of pins 30 and 32 is /RD, and which is /RESET?

**Status:** unresolved, but **no longer untested** — the two pins are now known to behave
differently at power-up (see below). The five "failed" 2026-08-02 attempts never armed.

Both are confirmed active-low control lines, idle high, never exercised during normal
operation. They were placed as a pair by elimination: every other function on the 34-pin
flex is accounted for.

### What was tried

| attempt | trigger | recorded result |
|---|---|---|
| warm reset (Menu+Select) | P30 falling, then P32 falling | aborted (SIGINT) |
| cold boot | P30 falling, then P32 falling | aborted (SIGINT) |
| cold boot | P30 **rising** | aborted (SIGINT) |
| cold boot | **/CS falling** (P29), 30 ms pre-trigger | aborted (SIGINT) |
| cold boot | /CS falling, after rig validation | aborted (SIGINT) |

> ⚠️ **CORRECTED 2026-10-12 — none of these is a negative result.** All five sidecars
> (`20260802_125222`, `_125453`, `_125835`, `_130138`, `_130459`) record
> `returncode: -2`, SIGINT: the captures were killed from the keyboard while still armed,
> and `TerminalCapture` shows the same message whether waiting or downloading. All five
> also used a pre-trigger of 8000 or 30000 samples, and **no capture in this project has
> ever armed with a pre-trigger above 1024**
> ([finding 14](FINDINGS.md#14-a-silent-no-arm-is-indistinguishable-from-no-trigger-yet)).
> Whether these lines move during a cold boot is simply **unmeasured**.

### What was established along the way

- **(F) The panel is not reset on a warm reboot.** The SoC restarts and the bootloader
  re-runs the LCD init, but neither line moves. A replacement driver must therefore drive
  reset itself at power-up; it cannot rely on a warm reset.
- **(F) A resistive divider on `VRF` is unusable for cold-boot work at 10 kΩ.** It reads
  0.60 V — a junction drop — because with the iPod powered down the TXU0104 A-side inputs
  are clamped to a dead board, presenting roughly 2.9 kΩ on VCCA. At **1 kΩ** the divider
  holds **1.6 V** even with the target off, which is sufficient.
- **(F) The 1 kΩ divider reference works.** Validated against known traffic: the
  window-setup commands decode byte-exactly at VREF = 1.6 V.
- **(F) VREF on the `3v3` switch position does NOT work** — see FINDINGS.

### ~~The unexplained part~~ — WITHDRAWN 2026-10-12

This section previously argued that /CS demonstrably goes low, yet a /CS falling-edge
trigger never fires during a cold boot, and treated that as an unexplained anomaly.

**There is nothing to explain.** Both /CS attempts were SIGINT aborts carrying a
30 000-sample pre-trigger — a configuration that has never armed. The analyzer was most
probably never listening. The two candidate causes previously floated, VREF sag during the
power-up transient and indeterminate inputs at arm time, remain untested but are no longer
motivated by any evidence.

### NEW 2026-10-12: the two pins behave differently at power-up

The gap 1 rail-sequencing captures separate them for the first time, across two cold starts:

| pin | crosses threshold | relative to |
|---|---|---|
| **P32** | +0.09–0.10 ms | with the **analog** rails |
| **P30** | +218.31–218.32 ms | 10 µs **after VDDIO** |

This does not yet say which is which, but it is the first measured asymmetry. P30 rising
just after the logic rail settles is the more reset-like behaviour of the two.

⚠️ **P32's early crossing needs confirming before it is believed.** The method is a ~1.1 V
threshold detector, which cannot distinguish 1.8 V logic from 3.0 V from leakage. A pin
reading high 218 ms before VDDIO exists is odd for a VDDIO-referenced line — measure the
actual voltage on pin 32 during that window with a DMM or the scope.

**Also (F): neither pin pulses.** Both show exactly one 0→1 edge and never return low
across 322 ms, which supports reset being asserted by the rail being down and released by
the line rising rather than by the SoC driving it low.

### Impact: low, with a trivial workaround

Nothing here blocks Phase 6. A driver can hold **both** pins high permanently and operate
the panel correctly, since Rockbox never reads and reads are not required. The only
capability lost is resetting the panel — and if that is ever needed, the identification is
a five-second experiment on live hardware: pull one pin low and observe whether the
display re-initialises.

Five boots looked disproportionate — but none of them actually tested anything, so the
question is cheaper than its history suggests. One correctly-configured cold-boot capture
would answer it, and the Stage 2 rail-sequencing capture records P30 and P32 anyway, so it
may fall out for free.

## 2. ~~What is pin 34?~~ — RESOLVED 2026-08-02

**Answer: an analog reference input to the panel, ~1.54 V, supplied by the logic board.**

With the display flex disconnected the board still holds pin 34 at ~1.54 V, so the panel
*receives* it rather than generating it. Its 1 MΩ-to-ground reading (unpowered) fits a
high-impedance decoupled reference rather than a supply rail.

**Phase 6 impact:** a replacement driver **must supply this**. Feed ~1.54 V from a
low-impedance buffered source with local decoupling. The required tolerance is unknown —
the panel's sensitivity to it has not been tested.

**Everything previously reported as activity on this pin was charger noise.** See
[FINDINGS](FINDINGS.md#11-charger-noise-contaminated-every-analog-measurement).

## 3. Why is the green channel's lane order irregular?

**Status:** measured, but unexplained.

Red and blue map onto consecutive pins in order. Green does not:

```
RED   =  9  10  11  12  13  14      consecutive
BLUE  = 21  22  23  24  25   2      consecutive, then the replica
GREEN = 15  16   1  18  19  20      pin 1 sits in the middle, at position 3
```

Every position is independently verified (violet, orange, the custom `G=16` fill and the
grey status bar), so the mapping is correct — but the reason pin 1 lands at bit position 3
rather than at one end is not understood. It may reflect flex routing rather than
electrical structure.

**Impact:** none for driving the panel; the map is what matters. Noted because an
unexplained irregularity is worth flagging in case it indicates a mistake nobody has
spotted yet.

---

## 4. Full-frame capture is out of reach — for *content*. Timing is reachable.

**Status:** a hardware limit on content, **lifted for timing** as of 2026-10-12.

> **Amended 2026-10-12.** The limit below is real for frame *content*: you cannot sample
> 70 ns strobes across a whole frame with 131 071 samples. But frame *timing* is reachable
> by going the other way — at **25 kS/s** the 32 767-sample budget spans **1.31 s**, which
> holds several complete pixel bursts. Individual writes are invisible at 40 µs, but the
> **/CS envelope of an entire burst** is not. That gave the first measured burst duration,
> 23.44–23.48 ms ([DRIVING.md §3](DRIVING.md#3-bus-protocol)). Resolution and span trade
> against each other; pick the one the question needs.

A full frame is 76 800 pixels × 610 ns = **46.9 ms**, and reliably catching the 70–80 ns
/WR pulse needs ≥20 MS/s → ~940 000 samples. The analyzer's deepest mode holds **131 071**.
Short by about 7×.

Partial reconstruction works and is validated: `tools/frame2png.py` recovers the update
rectangle from the window-setup commands and renders whatever rows were captured.

| mode | depth | at 20 MS/s | rows of 320 |
|---|---|---|---|
| 24-channel | 32 767 | 1.64 ms | ~8 |
| 16-channel | 65 535 | 3.28 ms | ~17 |
| 8-channel | 131 071 | 6.55 ms | ~33 |

Two further constraints on which rows you get: burst mode always begins at the **first
pixel of a frame** (rows 0–3), and row 0 is the **status bar**, which keeps its own colour
independent of the theme background. Reaching rows further down requires arming *during* an
active blit.

---

## 5. ~~Why did a post-wake redraw emit 7 window-setup writes instead of 13?~~ — RESOLVED 2026-08-03

**Answer: it emitted all 13. Six /WR pulses were too short to sample at 20 MS/s.**

Raised and closed the same day, from the existing capture — no new bench work. See
[FINDINGS §12](FINDINGS.md#12-the-bus-has-two-command-write-speeds-and-the-fast-one-needs-33-mss).

**D/C is the witness.** Across the region it makes **13 transitions in the pattern
`0,1,0,1,…,0`** — exactly one run per write, starting and ending on a command, which is
precisely the shape of `displaylcd_setup()`'s 13 writes. Only 7 /WR pulses were sampled.
The writes happened; the strobe was not seen.

**The reasoning that dismissed undersampling was wrong.** Balanced falling/rising edge
counts prove nothing here: a pulse shorter than the sample interval vanishes entirely,
taking *both* its edges with it. `tools/seqmatch.py` now cross-checks /WR pulses against
D/C transitions per burst, which catches exactly this.

---

## 6. Minor

- **Green MSB position.** Pin 15 carries APB bit 10 in frame mode but APB bit 9 during
  command writes — consistent with the mode-dependent lane behaviour of finding 3 in
  [FINDINGS.md](FINDINGS.md), but not independently confirmed for green as it was for red.
- **Panel module marking** `LS025Q7UX05A` suggests a Sharp 2.5" module. No datasheet
  located; a sibling `LS025Q7UX01` is indexed by panel-spec sites but the host was
  unreachable. Recorded as a lead only — nothing in this repository depends on it.
- **LA‑A still has a dead translator** (`U2`, CH13–16). Same OE cold joint that was fixed
  on LA‑B; reflowing pin 8 should restore it.
