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
| **34** | **~1.54 V** | **analog reference INPUT** — the panel expects to receive this. High impedance (1 MΩ to GND unpowered), so a buffered divider with local decoupling suffices. **Required tolerance unknown.** |
| 3, 6, 8, 17, 31 | **GND** | five pins; connect all |
| 4, 5 | backlight | see [§5](#5-backlight) |

Pin 34 is easy to overlook. It is not a rail the panel generates — the logic board drives
it, confirmed by it still reading 1.54 V with the display flex disconnected.

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
> **Test it early.** Write a value where a pair differs — e.g. red = `0b111110` — and see
> whether the panel renders the expected shade. If the pairs turn out to be tied inside
> the panel, fall back to driving each pair together, which reduces you to 5 effective
> bits on red and blue and exactly reproduces Rockbox's behaviour. Either way the panel
> works; only the achievable colour depth differs.

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

1. **Power-up sequencing is not characterised.** The order and timing of 1.8 V, 3.0 V and
   the 1.54 V reference were never captured. Panels in this family are usually tolerant,
   but if the panel fails to initialise this is the first thing to investigate.
2. **Reset pulse width and post-reset delay are unknown** — never observed.
3. **Which of pins 30/32 is /RESET is unresolved.**
4. **The tolerance on pin 34's 1.54 V reference is untested.**
5. **Panel datasheet minima are unknown.** All timing here is what the SoC does, which the
   panel accepts — not the panel's limits. Do not treat 610 ns as a floor; it may go
   faster, or may not.
6. **True 6-bit colour on red and blue is unverified** — see the warning in
   [§4](#4-pixel-format). Worst case you get 5 effective bits per channel on red and blue,
   matching Rockbox.
7. **Our pin numbering has no known mapping to the SoC's `D0`–`D17`.** Everything here is
   expressed in flex-pin numbers anchored to the interposer
   ([HARDWARE.md](HARDWARE.md#pin-numbering-convention)). That is sufficient to drive the
   panel, but do not try to correlate it with pin names in the Rockbox source.
