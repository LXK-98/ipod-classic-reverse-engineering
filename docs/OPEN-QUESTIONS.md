# Open questions

Everything in the original scope is complete. These are the remaining loose ends, none of
which block driving the panel.

---

## 1. Which of pins 30 and 32 is /RD, and which is /RESET?

**Status:** both identified as active-low control lines, assignment between them unknown.

Both sit constant high across a 164 ms window. That is expected rather than suspicious:
Rockbox never issues a read (`S5L_LCD_WITH_READID` is undefined for `ipod6g`) and /RESET
only moves at power-on. They were placed as a pair by elimination — every other function
on the 34-pin flex is accounted for.

**How to resolve.** Capture a **cold boot**; /RESET pulses low early in the sequence while
/RD does not.

**The obstacle.** The shifter's `VREF` is currently fed from the iPod's own 1.8 V rail
(pin 26), so as the target powers down VREF collapses, every channel goes high-Z, and the
collapse trips the edge trigger. This was tried and produced 24 channels of flat zero.

**The fix.** Derive VREF independently — a divider off the analyzer's 3v3 rail gives
1.8 V, and the TXU0104's VCCA draws only microamps, so tolerance is irrelevant. Roughly
12 kΩ over 10 kΩ. Then arm before power-on.

**Impact if left unresolved:** low. A driver must deassert both anyway; only the *order*
of reset release versus first write would matter, and that is knowable from the ILI9320
family datasheets.

---

## 2. What is pin 34?

**Status:** unidentified analog node.

Reads **~1.5 V with ~100 mV ripple at roughly 80 µs (~12.5 kHz)**. Not logic — it sits
permanently above the shifter's ~1.23 V threshold, so a logic analyzer reads it as a
constant high and cannot see the ripple. Characterising it needs a scope.

**Leading hypothesis: VCOM**, the LCD common-electrode drive. A DC level of a couple of
volts with a small AC component from inversion drive fits. If so its frequency should be a
harmonic of the line rate, which is known exactly from TE:

```
TE = 67.93 Hz  →  240 lines × 67.93 = 16.3 kHz (61.3 µs)
                  with ~262 total lines ≈ 17.8 kHz (56 µs)
```

The rough 80 µs estimate fits neither cleanly, so an accurate frequency is the decisive
measurement — it either lands on a line-rate harmonic or it does not.

**Alternatives:** a panel-internal charge-pump node for gate drive (would be a fixed
frequency unrelated to the line rate, and triangular rather than square), or something in
the backlight feedback path (would shift with brightness).

**How to resolve.** Scope pin 34 and record: DC level, ripple amplitude, **accurate
frequency**, waveform shape, and whether any of it changes with backlight brightness.

**Impact if left unresolved:** low-to-moderate. If it is VCOM it is generated on the panel
side and a driver need not produce it. If it is a bias the panel *expects* to receive, a
replacement driver would have to supply it — so this should be settled before Phase 6
hardware is committed.

---

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

## 5. Minor

- **Green MSB position.** Pin 15 carries APB bit 10 in frame mode but APB bit 9 during
  command writes — consistent with the mode-dependent lane behaviour of finding 3 in
  [FINDINGS.md](FINDINGS.md), but not independently confirmed for green as it was for red.
- **Panel module marking** `LS025Q7UX05A` suggests a Sharp 2.5" module. No datasheet
  located; a sibling `LS025Q7UX01` is indexed by panel-spec sites but the host was
  unreachable. Recorded as a lead only — nothing in this repository depends on it.
- **LA‑A still has a dead translator** (`U2`, CH13–16). Same OE cold joint that was fixed
  on LA‑B; reflowing pin 8 should restore it.
