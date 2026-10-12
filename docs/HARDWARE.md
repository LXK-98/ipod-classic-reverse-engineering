# Hardware and bench setup

## Target

| | |
|---|---|
| Device | iPod Classic 2009 "thin" 160 GB, model **A1238** |
| Logic board | **820‑2437‑A** |
| Revision | freemyipod "Classic Rev B" (2009), colloquially 7th gen |
| SoC | Samsung **S5L8702** |
| Rockbox target | `ipod6g` — covers the whole Classic family |
| Panel | 2.5" 320×240, **type 2** of Apple's four variants |
| Module marking | `LS025Q7UX05A S20 1227 003256 Z20 A1 RC` (Sharp; no datasheet located) |
| Flex | **34 pins**, 0.3 mm pitch |

Firmware during all measurements: **Rockbox**, so every captured byte corresponds to
public source.

## Interposer

A passive 1:1 break-out board sitting between the panel flex and the logic board, bringing
all conductors out to a 2.54 mm header. KiCad project in
[`hardware/interposer/`](../hardware/interposer) (`v0.1b`, designed by the collaborator).

| ref | part | role |
|---|---|---|
| J2 | 35-pos 0.3 mm FPC | logic board side |
| J3 | 35-pos 0.3 mm FPC | display side |
| J1 | 2×17 header, SMD | probe header |
| J4 | 2×17 header, TH | alternate, identical nets |

Verified **passive and 1:1** from the netlist — no series components, no lifted pins — so
DMM readings reflect the panel and board, not the interposer.

The connectors are **35-position** while the iPod flex is **34**; the surplus position is
the topmost on both connectors and is unconnected by design. J3's pad order is mirrored
relative to J2, which is correct: they face opposite board edges, so mirroring keeps a
given conductor aligned end to end.

### Pin numbering convention

```
FLEX pin N  =  probe-header pin N  =  net /(N+1)        N = 1..34
```

With the board oriented as built — silkscreen title readable top-left, "Logic board"/J2 at
left, "Display"/J3 at right, header vertical in the middle:

- **Header pin 1 is TOP-LEFT**
- **Odd pins are the LEFT column, even pins the RIGHT**
- 17 rows, numbering increases downward, two pins per row
- Row *r* holds pins *2r−1* (left) and *2r* (right)

This is an internal convention anchored to physical geometry. It is **not** claimed to
match Apple's own pin-1 designation, which remains unknown and does not matter provided
everything stays consistent. Full derivation in
[`probe_maps/v1-interposer-convention.md`](../probe_maps/v1-interposer-convention.md).

## Instrumentation

### Logic analyzers

Two [gusmanb LogicAnalyzer V2](https://github.com/gusmanb/logicanalyzer) boards
(integrated RP2040 + six TXU0104 level shifters, 24 channels each).

| board | serial | notes |
|---|---|---|
| LA‑A | `5033592792565F9F` | `U2` (CH13–16) dead — OE cold joint, unrepaired |
| LA‑B | `5033592712586E1F` | `U4` (CH21–24) was dead, **repaired by reflow** |

**Silkscreen `CHn` = software `ChannelNumber n−1`** (verified empirically in the phase 0
dry run). Header labels on this revision run `24…13 / 1…12` plus `3V3`, `5V0`, `TRG`,
`VRF`, `GND`.

Software: release **6.0.0.1**, which ships `TerminalCapture`, *not* the `CLCapture` older
documentation describes. It is settings-file driven:

```
TerminalCapture capture <serial-port> <settings.tcs> <output.csv>
```

`.tcs` is a JSON serialisation of `SharedDriver.CaptureSession`; `tools/capture.py`
generates it. Output CSV is a header row of channel names then one row per sample with
`0`/`1` per channel — **no timestamp column**, time is implicit at `1/Frequency`.

Sample depth: **131 071** (≤8 channels) / **65 535** (≤16) / **32 767** (≤24), and the
channels used must be the first N of the device.

The full documented limits (upstream, 04/02/2023). Minimum pre is 2, minimum post 512, and
**frequency must be between 3.1 kHz and 100 MHz**:

| mode | max pre | max post | max total |
|---|---|---|---|
| 8 channels | 98 303 | 131 069 | 131 071 |
| 16 channels | 49 151 | 65 533 | 65 535 |
| 24 channels | 24 576 | 32 765 | 32 767 |

⚠️ **The device silently fails to arm on some configurations it documents as legal, and the
cause is not understood.** It does not error: it simply never arms, and `TerminalCapture`
waits forever showing the same message it shows while armed. Observed no-arms include
`pre=65536` at 8 channels and `pre=8000` at 24 channels (both legal), and a capture at
**5 kS/s** (legal) whose pre/post/channel shape worked minutes earlier at 25 kS/s. Every
capture that *has* produced data used `pre` in {64, 512, 1024} and a rate of 20 kS/s or
above. `tools/capture.py` enforces the documented limits and additionally guards `pre` at
1024 — not a device limit, just proximity to what is known to work. Prefer lowering
`--frequency` to widen the pre-trigger window in *time*, but note that 5 kS/s has failed.
See
[finding 14](FINDINGS.md#14-a-silent-no-arm-is-indistinguishable-from-no-trigger-yet).

**Telling "armed" from "downloading":** there is no progress output, so read
`/proc/<pid>/io` on the `TerminalCapture` process — `rchar` static means still waiting for
a trigger, `rchar` climbing means the trigger fired and samples are transferring.

### The TRG pin, and cascading

`TRG` is a trigger **output**, not an input. The complex/fast trigger GPIOs are exposed
through a diode so the signal can trigger an external instrument such as an oscilloscope,
at 20 ns (`fast`) / 35 ns (`complex`) delay. It cannot start a capture: the driver's
`TriggerType` enum holds only `Edge`, `Complex`, `Fast` and `blast`, with no external
member and no external-trigger field in the session schema. Because it is driven from the
complex/fast GPIOs it does **not** assert on `edge`, which is what every preset in
`tools/capture.py` currently uses.

Cascading analyzers uses the **separate 3-pin connector pair** — male header and female
socket on opposite board edges, joined with two or three Dupont wires, central pin unused
and reserved. Up to five boards can be chained. Chaining LA‑A and LA‑B would give 48
channels, enough to capture all 18 data lanes together with the rails and every control
line, which one board cannot do.

### Level shifting — the critical setting

Panel logic is **1.8 V**. The shifter's reference switch has `3v3`, `5v0` and `EXT`
positions; it **must** be on `EXT` fed with 1.8 V.

| reference | TXU0104 V<sub>T+</sub> max | 1.8 V logic high | result |
|---|---|---|---|
| `3v3` | **1.92 V** | 1.8 V | **below threshold — unreliable** |
| `EXT` @ 1.8 V | ~1.23 V | 1.8 V | 0.57 V margin ✅ |

`VRF` was fed from **header pin 26** (the panel's own VDDIO). VCCA draws only microamps,
so it does not load the rail — but see
[open question 1](OPEN-QUESTIONS.md#1-which-of-pins-30-and-32-is-rd-and-which-is-reset):
this makes cold-boot capture impossible, because VREF collapses with the target.

### Other instruments

- **Voltcraft VC‑1008** — multimeter with a single-channel scope. Adequate for rails,
  ripple and slow signals; not for a 1.64 MHz strobe with 70 ns pulses.
- **Raspberry Pi Pico** running MicroPython as a known-signal generator
  (`tools/picogen.py`), used to validate the capture pipeline before any real data.

### Host

Fedora Linux 42, Python 3.10. **ModemManager must be prevented from probing the
instruments** — see [`99-bench-instruments.rules`](99-bench-instruments.rules) and
[finding 7](FINDINGS.md#7-instrumentation-findings).

## Safety rules

1. **Pin 4 (backlight anode) reaches 12.76 V.** Never connect it to an analyzer input —
   the TXU0104 A-side absolute maximum is 5.5 V. Pin 4 sits next to pin 3 (a convenient
   ground) and pin 7 (TE), so that corner of the header needs care.
2. **Measure a pin's voltage before probing it.** The backlight was located by voltage
   sweep, not by diode test — a 4-LED series string needs ~12 V to conduct, far above a
   multimeter's ~3 V diode range, so it reads open in both directions and the test is
   useless here.
3. **Ground instruments to signal ground**, not chassis: the two are bonded through
   ~300 Ω. Any flex GND pin (3, 6, 8, 17, 31) or the HDD case works.
4. **Disconnect the battery before continuity testing.** "Powered off" still leaves PMU
   standby rails live, and a slipped probe across 2.54 mm pins can short a live rail.
5. **Power off before changing probe wiring**; do not hot-plug the flex in its ZIF
   connectors.
