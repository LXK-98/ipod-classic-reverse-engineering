# Display protocol

> Building a driver? Start with **[DRIVING.md](DRIVING.md)**, which collects everything
> needed in implementation order. This document covers how the protocol was characterised.

Everything needed to drive this panel. All figures measured on the target unless marked
otherwise.

## Interface

8080-series parallel MPU interface, **18 data lanes**, **1.8 V** logic.

| signal | pin | polarity |
|---|---|---|
| /WR | 27 | active low, **data latched on the rising edge** |
| D/C (RS) | 28 | **0 = command, 1 = data** |
| /CS | 29 | active low, asserted for the duration of a transfer burst |
| /RD, /RESET | 30, 32 | active low, idle high (assignment between them unresolved) |
| TE | 7 | panel output, 67.9 Hz |
| D0–D17 | 1, 2, 9–16, 18–25 | see [pixel format](#pixel-format) |

## Panel variant

This unit is **type 2** of the four Apple shipped. The SoC selects the variant from two
GPIO strap bits, `(PDAT6 & 0x30) >> 4`, read here as `GPIO 6 = 0x6b` → **2**, and
confirmed independently by Rockbox's own debug menu reporting `LCD type: 2`.

Type 2 uses a **16-bit index/register command set** in the ILI9320/ILI9326 family. The
straps are **board-side**, not on the flex — no ID pin among the 34.

Rockbox drives types 2 and 3 identically, so bus traffic alone can never distinguish
them; the GPIO reading is what settles it.

## Bus timing

Measured at 100 MS/s during DMA pixel bursts:

| parameter | value |
|---|---|
| /WR low | **70–80 ns** |
| /WR high | **530–540 ns** |
| cycle | **610 ns** → **1.64 MHz** |
| full frame | 76 800 writes ≈ **46.9 ms** |

Command writes are slower and less regular — 610–1110 ns apart, median ~780 ns — because
the CPU polls `LCD_STATUS` between them rather than using DMA.

`LCD_PHTIME = 0x33` is set by `lcd_init_device()` for this target.

### Timing traps

A sample rate below ~13 MS/s **cannot** reliably catch the 70–80 ns /WR low pulse. At
20 MS/s (50 ns period) the pulse is longer than one sample interval, so at least one
sample is guaranteed to land inside it — that is the practical floor.

Undersampling does not look like noise. A 1 MS/s capture of this 1.64 MHz strobe produced
a clean, entirely convincing **91 kHz** signal with perfectly uniform run lengths, because
the beat between the two rates re-aligned every 11 samples. **Run-length regularity is not
evidence against aliasing.**

## Transaction structure

### Window setup before every blit

`displaylcd_setup()` emits exactly 13 writes — six register+data pairs and one bare
command:

```
CMD 0x210  DATA x0        horizontal start
CMD 0x211  DATA x1        horizontal end
CMD 0x212  DATA y0        vertical start
CMD 0x213  DATA y1        vertical end
CMD 0x200  DATA x0        GRAM address, horizontal
CMD 0x201  DATA y0        GRAM address, vertical
CMD 0x202                 write to GRAM — pixel data follows
```

A full-screen update reads `0x0000 / 0x013F / 0x0000 / 0x00EF` (0…319, 0…239).

**There is a gap of >1.6 ms between the `0x202` command and the first pixel**, while
Rockbox `memcpy`s 153 KB into the DMA buffer. Any capture window shorter than that will
see the setup and then apparent silence.

### Initialisation

Byte-exact sequences for all four panel variants are parsed from the Rockbox source into
[`refs/sequences.json`](../refs/sequences.json) by `tools/rockbox_seq.py`.

For type 2:

| sequence | writes | when |
|---|---|---|
| `lcd_init_seq_23` (bootloader) | **146** | cold boot only |
| `lcd_init_seq_23` (firmware) | **152** | on wake — same array, plus a 6× NOP prefix |
| `lcd_deepstandby_seq_23` | 18 | on sleep |

Two consequences that matter in practice:

- **Only the bootloader runs an init.** `lcd_run_seq(seq_init)` is `#ifdef BOOTLOADER`;
  the main firmware never initialises the panel.
- **On type 2, `seq_awake` *is* the init sequence**, so an LCD sleep/wake cycle replays a
  full initialisation on demand — a repeatable trigger that needs no reboot. This is by
  far the easiest way to capture the init.

The two variants are distinguishable at a glance: a cold init opens `CMD 0x008,
DATA 0x0808`, while a wake replay opens with **six `CMD 0x0000` NOPs spaced 1.28 ms
apart** — a 7.7 ms prefix that is unmistakable, and long enough to swallow a short
capture window whole.

### Reads

Rockbox never reads the panel: `S5L_LCD_WITH_READID` is undefined for `ipod6g`, so
`lcd_read_display_id()` is not compiled in. **/RD stays idle for an entire Rockbox boot**,
which means silence on that line proves nothing about whether it is connected.

## Pixel format

The bus carries **RGB666 — 18 lanes, 6 bits per channel**, MSB first:

```
RED   = pins  9  10  11  12  13  14        pin 14 = hardware replica of pin 9
GREEN = pins 15  16   1  18  19  20
BLUE  = pins 21  22  23  24  25   2        pin  2 = hardware replica of pin 21
```

Rockbox's framebuffer is RGB565, and the SoC expands it:

```
6bit = (5bit << 1) | (5bit >> 4)      # MSB replicated into the LSB
```

Red and blue are 5-bit in RGB565 and are expanded this way; green is already 6-bit and
passes through unchanged. **This is why pins 9/14 and 21/2 carry byte-identical data in
every capture** — they are not shorted, they are the two ends of a replicated channel.

**One bus transfer per pixel.** Confirmed by a measured frame time of 46.92 ms against
76 800 × 610 ns = 46.85 ms, a 0.1 % match — two transfers per pixel would take twice as
long.

### Verification

![Reconstructed status bar](frame-example-magnified.png)

*Rows 0–3 of a live Rockbox screen, reconstructed from a raw bus capture by
`tools/frame2png.py` (pixels stretched 4×24 for legibility; true-scale version in
`frame-example.png`). The blue icon, text glyph tops and the grey battery outline with its
red low-charge fill are all recovered from the 18 data lanes with no post-processing.*

The mapping is verified against nine captures of known colours, including three
asymmetric ones that would expose any ordering error:

| fill | RGB565 | expected R/G/B (6-bit) | measured |
|---|---|---|---|
| red | `0xF800` | 63 / 0 / 0 | ✅ |
| green | `0x07E0` | 0 / 63 / 0 | ✅ |
| blue | `0x001F` | 0 / 0 / 63 | ✅ |
| white | `0xFFFF` | 63 / 63 / 63 | ✅ |
| **indigo** | `0x4810` | **18 / 0 / 33** | ✅ |
| **violet** | `0xEC1D` | **59 / 32 / 59** | ✅ |
| **orange** | `0xFD20` | **63 / 41 / 0** | ✅ |
| custom G=16 | — | 0 / 16 / 0 | ✅ |
| menu status bar | — | 12 / 12 / 12 → RGB(48,48,48) | ✅ neutral grey, matching the screen |

## Backlight

| parameter | value |
|---|---|
| Anode (pin 4) | **12.76 V** at full brightness (10.7 V at low duty) |
| Cathode (pin 5) | via a **25.6 Ω** sense resistor |
| Current | **19.5 mA** (500 mV across the sense resistor, flat = 100 % duty) |
| String | **4 white LEDs** in series — 12.26 V / 4 = 3.07 V each |
| Dimming | **PWM on the low side**, constant peak current |

The brightness control is perceptual rather than linear: setting 7 of 63 gives ~5.4 %
duty where a linear map would give 11.1 % (gamma ≈ 1.3). Because dimming is PWM at
constant current, colour temperature stays constant across the range.

**Driver requirement:** constant-current boost, ~20 mA into a 4-LED string, output
reaching 12.8 V under load — design for ≥14 V compliance. PWM the low side.

## Power

| pin | rail |
|---|---|
| 26 | **1.8 V** — VDDIO, the logic domain |
| 33 | **3.0 V** — analog/panel supply |
| 34 | **~1.54 V analog reference — an INPUT the panel expects.** A replacement driver must supply it |
| 3, 6, 8, 17, 31 | GND |

Pin 34 is board-supplied: it remains at ~1.54 V with the display disconnected. It reads
1 MΩ to ground unpowered, i.e. a high-impedance decoupled reference rather than a rail.
Any apparent AC on it is charger noise — measure on battery.

The iPod bonds **chassis ground to signal ground through ~300 Ω**. Instruments must
reference signal ground (the flex GND pins or the HDD case), not the case or dock shell.
