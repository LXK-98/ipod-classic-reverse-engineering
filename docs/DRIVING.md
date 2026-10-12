# Driving the panel — Phase 6 implementation guide

Everything needed to build a driver, in the order you need it. Figures are **measured on
this unit** unless marked otherwise. Where something is *not* known it says so explicitly
— see [Known gaps](#known-gaps) before committing hardware.

Companion documents: [PINOUT.md](../PINOUT.md) for the pin table,
[PROTOCOL.md](PROTOCOL.md) for how the protocol was characterised.

---

## 1. Electrical — what you must supply

| pin(s) | supply | notes |
|---|---|---|
| 26 | **1.8 V** | VDDIO, the logic domain. All bus signals swing to this. |
| 33 | **3.0 V** | analog/panel supply |
| **34** | **~1.35 V, adjustable** | **analog reference INPUT** — the panel expects to receive this. Weakly driven, so the value depends on load; see the caution below. **Required tolerance unknown.** |
| 3, 6, 8, 17, 31 | **GND** | five pins; connect all |
| 4, 5 | backlight | see [§5](#5-backlight) |

Pin 34 is easy to overlook. It is not a rail the panel generates — the logic board drives
it, confirmed by it still reading 1.54 V with the display flex disconnected.

⚠️ **Do not build to 1.54 V. That is the *unloaded* figure.** Three readings of the same
pin, all with a 10 MΩ DMM:

| condition | reading |
|---|---|
| flex **disconnected**, board unloaded | **1.54 V** |
| flex connected, panel running, charger **connected** | **1.26 V** |
| flex connected, panel running, charger **disconnected** | **1.36 V** |

The spread is the point: the node moves with load, with the charger
([finding 11](FINDINGS.md#11-charger-noise-contaminated-every-analog-measurement) striking
again on the very pin it was discovered on), and almost certainly with the DMM's own 10 MΩ
input — a drop of 0.18 V under a DMM alone implies a source impedance in the megohms. **So
no DMM reading gives the panel's true operating voltage**, and a scope would be worse at
1 MΩ.

**Design accordingly:**

1. **Target ~1.35 V**, the closest figure measured in operation on battery — not 1.54 V.
2. **Make it adjustable.** A trimmer into a buffer lets you tune against the panel once it
   runs, which is the only arbiter that matters given the measurement problem.
3. **To measure it properly**, buffer it: a CMOS-input op-amp (the `TLV9061` in the parts
   list draws picoamps) as a unity-gain follower reads the node without loading it. That
   also pre-tests the board's own reference buffer.

### Power-up sequencing — MEASURED 2026-10-12

The original board brings the **analog domain up first and the logic domain ~218 ms later**.
Times are threshold crossings relative to the 3.0 V rail, reproduced across two cold starts
to within one 10 µs sample:

| t | event |
|---|---|
| **0** | **3.0 V** panel supply (pin 33) |
| +0.09–0.10 ms | pin 32 (one of /RD, /RESET — see [§2](#2-reset)) |
| **+0.13 ms** | **1.54 V** analog reference (pin 34) |
| **+218.3 ms** | **1.8 V** VDDIO (pin 26), and /WR and /CS with it |
| +218.31 ms | pin 30 (the other of /RD, /RESET) |

**What a driver should copy:**

1. **3.0 V first, then the 1.54 V reference, then 1.8 V VDDIO last.** This order is what
   the panel has been powered with for its whole service life, so it is known-safe.
2. **Never drive VDDIO, or any bus signal, before the 3.0 V rail is up.** /WR and /CS do
   not rise until VDDIO does — they are referenced to it and cannot lead it.
3. **The buffer generating the 1.54 V reference must not be powered from VDDIO.** The
   reference leads VDDIO by 218 ms, so it has to run from the 3.0 V domain or its own
   earlier rail. This is a hard constraint on the driver board, not a preference.
4. **The 218 ms gap is almost certainly not required.** It reproduced to 0.005 %, so it is
   a deterministic programmed delay in the SoC's boot path rather than a panel requirement.
   Preserve the *order*; there is no evidence the panel needs the *delay*.

⚠️ **What this does NOT establish.** The measurement is threshold-based at ~1.1 V, so it
gives ordering, not ramp shapes, ramp rates or settling behaviour. It shows what the
original board does — which is sufficient to copy — but **not** that other orderings are
unsafe.

### Power-down sequencing — MEASURED 2026-10-12

**It is the exact mirror of power-up.** Times relative to VDDIO falling, on a Rockbox
software shutdown:

| t | event |
|---|---|
| **0** | **1.8 V VDDIO falls** — /WR, /CS and D/C fall in the same 40 µs sample |
| **+32.88 ms** | **1.54 V** analog reference |
| +34.04 ms | pin 32 |
| **+46.48 ms** | **3.0 V** panel supply |
| +47.08 ms | pin 30 |

Up is 3.0 V → reference → VDDIO; down is VDDIO → reference → 3.0 V. The whole descent takes
**46.5 ms**, against 218 ms on the way up.

**What a driver should copy:**

1. **Take the rails down in reverse: VDDIO first, then the reference, then 3.0 V.** Never
   leave VDDIO (or any driven bus signal) alive after the 3.0 V rail has gone.
2. **Stop driving the bus before VDDIO goes.** On the original every bus line collapses in
   the same sample as VDDIO, because they are referenced to it.
3. **Quiesce the panel before cutting power.** TE had already stopped more than 20.5 ms
   before VDDIO fell, so the panel was put to sleep by command first. The command itself
   has not been captured, but a driver should assume standby-then-power-off is expected.

⚠️ **Caveat specific to power-down.** These rails are not switched hard — they **decay**,
over seconds, through load and bulk capacitance. A ~1.1 V threshold crossing therefore
conflates the PMU's switch-off order with each rail's RC time constant: a rail with more
bulk capacitance crosses later even if it was cut first. So this is a faithful record of
**what the panel experiences**, which is what matters for safety, but not necessarily of the
PMU's switching order.

**Incidentally measured:** a cold start that aborts can leave the 3.0 V rail high for
**3.7 ms and then collapse** with nothing else following, and the panel tolerates it.

**Logic levels.** All bus signals are **1.8 V CMOS**. If you drive from a 3.3 V part you
need level shifting; note that a TXU0104 referenced to 3.3 V will **not** read 1.8 V
reliably (its V<sub>T+</sub> max is 1.92 V, above a 1.8 V logic high).

## 2. Reset

**You must drive reset yourself.** Measured: the panel is *not* reset on a warm reboot —
the SoC restarts, the bootloader re-runs the init, and neither control line moves. Reset
is asserted only at cold power-on.

**Which pin is which is UNRESOLVED.** Pins **30** and **32** are both active-low,
idle-high control lines: one is `/RD`, one is `/RESET`. Five capture attempts failed to
separate them ([OPEN-QUESTIONS §1](OPEN-QUESTIONS.md)).

**Practical approach:**
- Hold **both** pins **high** in normal operation. Reads are never needed — Rockbox never
  issues one, and nothing in a display driver requires reading back.
- To identify the reset pin, pull one low briefly on a running panel and see whether the
  display re-initialises. Five-second experiment on live hardware.
- **Do not pulse both simultaneously** — if one is `/RD`, asserting it makes the panel
  drive the data bus while your driver is also driving it. Bus contention on 18 lanes.

**Reset pulse width and post-reset delay are UNKNOWN** (we never observed a reset). The
ILI9320/ILI9326 family datasheets are the reference; typical is ≥10 µs assertion and
~10 ms before the first command, but that is *not* measured here.

## 3. Bus protocol

8080-series parallel, 18 data lanes, data latched on the **rising edge of /WR**.

```
        ┌─────────────┐         ┌───────
/WR ────┘             └─────────┘          low 70–80 ns, high 530–540 ns, cycle 610 ns
        │             │
D/C ────┤ stable ≥380 ns before the latch  0 = command, 1 = data
        │             ↑
DATA────┤ stable ≥60 ns  │  held ≥270 ns   latched HERE (rising edge)
```

| parameter | measured | use |
|---|---|---|
| /WR low | 70–80 ns | ≥80 ns is known-good |
| /WR high | 530–540 ns | |
| cycle | **610 ns** (1.64 MHz) | the SoC's rate; the panel accepts it |
| **data setup** before latch | min **30 ns**, typically 60–70 ns | design for ≥60 ns |
| **data hold** after latch | min **270 ns** | design for ≥270 ns |
| **D/C setup** before latch | min **380 ns** | change D/C well before /WR |

These are what the SoC does and the panel demonstrably accepts. They are **not** the
panel's datasheet minima, which are unknown — so treat them as a known-good operating
point rather than limits to optimise against.

**The panel is known to accept considerably faster than this.** The same command block was
measured in two regimes, and the SoC uses both routinely:

| regime | write cycle | /WR low |
|---|---|---|
| slow (the table above) | 818 ns | 60–80 ns |
| **fast** | **309 ns** | **30–40 ns** |

So **309 ns / 30 ns is also a measured, panel-accepted operating point**, 2.6× faster than
the conservative figures. What that buys on a full frame:

| write cycle | 76 800 writes | vs one TE period (14.73 ms) |
|---|---|---|
| 610 ns (SoC pixel rate) | 46.9 ms | 3.2× too slow |
| **309 ns (measured, accepted)** | **23.7 ms** | 1.6× too slow |
| 192 ns | 14.7 ms | tear-free, **untested** |

The 610 ns figure is nowhere near a ceiling — but 309 ns still does not reach a tear-free
full-frame update at the panel's native 67.9 Hz. Whether ~192 ns works remains open (gap 5
below); this only narrows the gap you have to close.

**A pixel burst's total duration is now measured**, which the analyzer's depth previously
made impossible. Four consecutive bursts during boot, from their /CS envelopes at 40 µs
resolution: **23.48, 23.44, 23.44, 23.48 ms**, starting every 25.40 ms.

⚠️ **That duration does not identify the write rate**, because it constrains only the
*product* of write count and cycle time. Two readings fit equally well:

| reading | writes | cycle | duration |
|---|---|---|---|
| half the panel at the measured pixel rate | 38 400 (= 76 800 / 2 exactly) | 610 ns | 23.42 ms |
| the whole panel in the fast regime | 76 800 | ~305 ns | 23.46 ms |

The first is more parsimonious — 610 ns is a *direct* measurement of pixel writes, and
38 400 is exactly half the panel. Settling it needs a high-rate capture triggered on /CS
falling, to count writes inside one burst rather than time its envelope.

**/CS** is held **low for the duration of a transfer burst** — measured at 99.6 % low
throughout a pixel burst. It is not toggled per write. Assert before the first write of a
burst, release after the last.

## 4. Pixel format

The bus is **RGB666 — 18 lanes, 6 bits per channel**, MSB first:

```
RED   = pins  9  10  11  12  13  14
GREEN = pins 15  16   1  18  19  20
BLUE  = pins 21  22  23  24  25   2
```

Rockbox's framebuffer is RGB565 and the SoC widens it with
`6bit = (5bit << 1) | (5bit >> 4)`. A consequence visible in every capture: **pins 9/14
and 21/2 carry identical data**, each being a replicated channel MSB.

> ⚠️ **Unverified: whether those pairs can be driven independently.**
>
> Every measurement in this project comes from an RGB565 source, where those lanes are
> identical *by construction*. We have never observed them differ, because nothing we
> captured could make them differ. So "drive all 18 independently and get true RGB666" is
> an **inference**, not a measurement.
>
> What supports it: the pairs are **not shorted** (6.66 MΩ between pins 9 and 14), the
> interface is 18 lanes wide, and RGB666 is the natural interpretation of 6 lanes per
> channel.
>
> **The SoC cannot perform this test — established 2026-10-12.** On data writes (D/C = 1)
> the SoC ties both pins of each pair to a *single* APB bit: **bit 10 drives pins 9 and 14,
> bit 4 drives pins 21 and 2.** The tie is structural, not value-dependent, so no 16-bit
> word splits a pair and no Rockbox change — including switching frame output to
> `LCD_MODE_P18` — can produce one. Confirmed across **14 896 data writes** spanning every
> colour ever observed: zero genuine splits.
>
> On *command* writes the same pins are independent, so the panel's input pins demonstrably
> receive differing levels and are not shorted. What remains untested is only whether the
> panel's **GRAM write path** treats 18 bits as 6-6-6.
>
> **Answering it therefore requires driving the panel externally** — an RP2040 or similar
> putting a crafted 18-bit word on the bus. If the pairs turn out to be tied inside the
> panel, fall back to driving each pair together, which reduces you to 5 effective bits on
> red and blue and exactly reproduces Rockbox's behaviour. Either way the panel works; only
> the achievable colour depth differs.
>
> **The original SoC cannot easily run this test (measured 2026-10-12).** It replicates
> the pairs on every D/C = 1 write — in `LCD_MODE_P18` command mode as well as frame mode —
> and drives them independently only on command writes, which the panel does not treat as
> pixels. See the [lab notebook](LAB-NOTEBOOK.md), 2026-10-12 (night).

**One bus transfer per pixel.** A full frame is 76 800 writes ≈ 46.9 ms at 610 ns.

## 5. Backlight

| parameter | value |
|---|---|
| String | **4 white LEDs in series** |
| Drive current | **19.5 mA** |
| Anode (pin 4) | **12.76 V** at full brightness |
| Sense | pin 5 through **25.6 Ω** on the original board |
| Dimming | **PWM on the low side**, constant peak current |

**Driver spec:** constant-current boost, ~20 mA, output reaching 12.8 V under load —
design for **≥14 V compliance**. PWM the low side; the original keeps peak current
constant so colour temperature does not shift with brightness.

⚠️ **Pin 4 reaches 12.76 V.** Never connect it to a logic analyzer or 5 V-rated part.

## 6. Initialisation

The exact sequence is in [`refs/sequences.json`](../refs/sequences.json), generated from
the Rockbox source by `tools/rockbox_seq.py`. For this panel use
**`configs.bootloader.types.2.sequences.init`** — 146 bus writes, 240 ms of embedded
sleeps.

**This is measured, not just source-derived.** All 152 writes of the wake variant have
been captured byte-exactly on the bus, across two captures that each got 151/152 and lost
different writes. That variant minus its six NOPs is byte-identical to the bootloader init
above. So the sequence you send is, write for write, the sequence the panel is known to
accept.

```python
import json
seq = json.load(open("refs/sequences.json"))
tx = seq["configs"]["bootloader"]["types"]["2"]["sequences"]["init"]["transactions"]
for e in tx:
    if e["kind"] == "sleep":   delay_ms(e["ms"])
    elif e["kind"] == "cmd":   write(dc=0, value=e["value"])   # 16-bit
    else:                      write(dc=1, value=e["value"])
```

It opens `CMD 0x008, DATA 0x0808`. Every value is a **16-bit** register index or datum —
this panel uses the 16-bit register command set, not 8-bit DCS.

### When the original board runs it — MEASURED 2026-10-12

Times are from the 3.0 V rail coming up (see [§1](#power-up-sequencing--measured-2026-10-12)):

| t | event |
|---|---|
| +218.3 ms | 1.8 V VDDIO up; /WR and /CS rise with it |
| **+615.6 ms** | **first LCD transfer** — /CS asserted 80 µs, the init register block |
| +628.1 ms | **TE starts**, at 67.91 Hz from its very first pulse |
| +877.6 ms | /CS asserted 40 µs — the init's trailing writes after its sleeps |
| +879.5 ms | first pixel burst begins |

The 261.8 ms gap between the two init blocks matches the sequence's own **240 ms of
embedded sleeps**, which corroborates that this is `lcd_init_seq_23` executing.

**This imposes no requirement on a driver.** The first transfer landing 397 ms after VDDIO
is simply when Rockbox's bootloader got round to it; nothing indicates the panel needs the
wait. The delay a driver actually has to respect is the post-reset one, which is still
unknown ([gap 2](#known-gaps)).

**TE is available 12.5 ms after the init block** and is correct immediately, so a driver can
synchronise on it as soon as initialisation completes.

The *firmware* variant of the same array (152 writes) is prefixed with six `CMD 0x0000`
NOPs spaced 1.28 ms apart; that prefix releases the panel from deep standby and is only
needed if you implement sleep/wake.

## 7. Blitting

Before each pixel run, set the window and address, then start the GRAM write:

```
CMD 0x210  DATA x0        horizontal start        e.g. 0x0000
CMD 0x211  DATA x1        horizontal end          e.g. 0x013F  (319)
CMD 0x212  DATA y0        vertical start          e.g. 0x0000
CMD 0x213  DATA y1        vertical end            e.g. 0x00EF  (239)
CMD 0x200  DATA x0        GRAM address horizontal
CMD 0x201  DATA y0        GRAM address vertical
CMD 0x202                 write to GRAM
```

then stream pixels with `D/C = 1`, one write per pixel, row-major within the window.

**TE (pin 7)** is a panel output at **67.9 Hz** — one ~60 µs pulse per frame. Use it to
synchronise blits and avoid tearing.

## 8. Suggested implementation

An **RP2040 PIO bridge** fits well: a 610 ns cycle with 70 ns pulses is comfortable at
125 MHz (≈76 cycles per bus cycle), PIO gives deterministic timing, and 20+ GPIOs are
needed for 18 data lanes plus control. A Pi's SMI peripheral (BCM2835–2711 only; removed
on Pi 5) is the alternative.

Whatever drives it needs **1.8 V I/O** or level shifting in the drive direction.

## Known gaps

Be aware of these before committing hardware:

1. ~~**Power-up sequencing is not characterised.**~~ **MEASURED 2026-10-12** — 3.0 V, then
   the 1.54 V reference at +0.13 ms, then 1.8 V VDDIO at +218.3 ms. Reproduced across two
   cold starts to within one sample. See
   [§1 Power-up sequencing](#power-up-sequencing--measured-2026-10-12).
   **Power-down measured too, and it mirrors power-up exactly** — VDDIO, then the
   reference, then 3.0 V, over 46.5 ms. See
   [§1 Power-down sequencing](#power-down-sequencing--measured-2026-10-12).
   **Still open from this:** ramp shapes and rates (the method is threshold-based, so it
   gives order only), whether other orderings would also work, and the standby command the
   original presumably issues before cutting power — inferred from TE having stopped, but
   not itself captured.
2. **Reset pulse width and post-reset delay are unknown** — never observed.
3. **Which of pins 30/32 is /RESET is unresolved.**
4. **The tolerance on pin 34's 1.54 V reference is untested.**
5. **Panel datasheet minima are unknown.** All timing here is what the SoC does, which the
   panel accepts — not the panel's limits. 610 ns is definitely not a floor: **309 ns with
   a 30–40 ns /WR low is measured and accepted**. Whether it goes to ~192 ns, the rate a
   tear-free full-frame update at 67.9 Hz needs, is untested.
6. **True 6-bit colour on red and blue is unverified, and the SoC cannot settle it** — see
   the warning in [§4](#4-pixel-format). The SoC ties each pair to one APB bit on data
   writes, so only an external driver can present a split pair. Worst case you get 5
   effective bits per channel on red and blue, matching Rockbox.
7. **Our pin numbering has no known mapping to the SoC's `D0`–`D17`**, but the **APB bit →
   flex pin** map for data writes is now derived (2026-10-12), which is the part that
   matters in practice:

   | APB bit | pin | APB bit | pin | APB bit | pin |
   |---|---|---|---|---|---|
   | 0 | P25 | 6 | P19 | 11 | P13 |
   | 1 | P24 | 7 | P18 | 12 | P12 |
   | 2 | P23 | 8 | P16 | 13 | P11 |
   | 3 | P22 | 9 | P15 | 14–15 | undetermined (P01/P10) |
   | 4 | **P21 + P02** | 10 | **P09 + P14** | | |

   Bits 14–15 are constant across the init data set, so they cannot be separated from each
   other or from P01/P10 by it. Everything else is expressed in flex-pin numbers anchored to
   the interposer ([HARDWARE.md](HARDWARE.md#pin-numbering-convention)). The map above is
   for **data** writes; command writes use a different arrangement (finding 3).
