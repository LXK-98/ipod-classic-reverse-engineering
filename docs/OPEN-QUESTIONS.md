# Open questions

Everything in the original scope is complete. These are the remaining loose ends, none of
which block driving the panel.

---

## 1. Which of pins 30 and 32 is /RD, and which is /RESET?

**Status:** unresolved after five cold-boot attempts. Parked deliberately — see impact.

Both are confirmed active-low control lines, idle high, never exercised during normal
operation. They were placed as a pair by elimination: every other function on the 34-pin
flex is accounted for.

### What was tried

| attempt | trigger | result |
|---|---|---|
| warm reset (Menu+Select) | P30 falling, then P32 falling | neither fired |
| cold boot | P30 falling, then P32 falling | neither fired |
| cold boot | P30 **rising** | did not fire |
| cold boot | **/CS falling** (P29), 30 ms pre-trigger | did not fire |
| cold boot | /CS falling, after rig validation | did not fire |

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

### The unexplained part

**/CS demonstrably goes low** — it frames every write burst, and we watched it do so with
the same wiring minutes before and after. Yet a /CS falling-edge trigger never fires
during a cold boot, across two attempts including one after the rig was validated. No
explanation has been established. Candidate causes not yet tested: VREF sagging during the
target's power-up transient, or the analyzer's edge detection behaving differently when an
input is in an indeterminate state at arm time.

### Impact: low, with a trivial workaround

Nothing here blocks Phase 6. A driver can hold **both** pins high permanently and operate
the panel correctly, since Rockbox never reads and reads are not required. The only
capability lost is resetting the panel — and if that is ever needed, the identification is
a five-second experiment on live hardware: pull one pin low and observe whether the
display re-initialises.

Five boots is already disproportionate to what the distinction is worth.

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

## 4. Full-frame capture is out of reach

**Status:** a hardware limit, not a gap in knowledge.

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

## 5. Why did a post-wake redraw emit 7 window-setup writes instead of 13?

**Status:** observed once, unexplained. Does not affect anything currently relied on.

Burst 10 of `20260803_203836_init-burst` caught the start of a screen redraw immediately
after the init finished. It decodes as recognisable window-setup traffic that terminates
correctly:

```
CMD 0x0210  DATA 0x0000  DATA 0x0000  CMD 0x0213  CMD 0x0201  DATA 0x0000  CMD 0x0202
```

followed by ~97 µs of silence, consistent with the documented >1.6 ms memcpy gap after
`0x202`. But `displaylcd_setup()` emits **13** writes; `0x211`, `0x212`, `0x200` and their
data words are absent.

**It is not undersampling.** Falling and rising /WR edge counts balance across the entire
capture (158 each), and the region contains exactly seven pulses for seven decoded writes.
The 1400 ns gaps between them — about two write cycles — carry no pulses at all. All seven
sit inside one burst, so no re-arm boundary is involved.

**Impact: none established.** The 13-write structure was confirmed byte-exactly in earlier
captures and is what [DRIVING.md §7](DRIVING.md#7-blitting) specifies. Candidates not
tested: a partial-window update path in Rockbox that skips registers already holding the
right value, or a decode artefact specific to this burst. Worth one capture of a redraw in
isolation.

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
