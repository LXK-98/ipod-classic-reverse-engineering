# iPod Classic LCD flex pinout

Generated from `pinout.json` v4.1 (2026-08-01) by `tools/report.py`.
Do not edit by hand.

## Device

- **model**: Apple iPod Classic 2009 'thin' 160GB, A1238
- **logic board**: 820-2437-A
- **revision**: freemyipod 'Classic Rev B' (2009)
- **soc**: Samsung S5L8702
- **rockbox target**: ipod6g
- **panel**: 2.5in 320x240, 8080-series parallel MPU, 18-bit data bus

## Panel

- **Type 2** (**high** confidence) — ILI9320/ILI9326-like 16-bit index/register set
- Command set: **16-bit** register interface
- Interface I/O voltage (VDDIO): **1.8 V**
- Module marking: `LS025Q7UX05A S20 1227 003256 Z20 A1 RC`

## Numbering convention

> Board oriented as in the 2026-08-01 photo: silkscreen title readable top-left, 'Logic board'/J2 at LEFT, 'Display'/J3 at RIGHT, probe header vertical in middle. FLEX pin N == probe-header pin N == net /(N+1), for N = 1..34. Header pin 1 is TOP-LEFT; odd pins are the LEFT column, even pins the RIGHT column; numbering increases downward, two pins per row, 17 rows. FLEX pin 1 is the TOPMOST live conductor. The 35th (topmost) connector position is unused on both FPC connectors (J2 pad 1, J3 pad 35) and is not part of this numbering. This is an internal convention anchored to physical geometry; it is NOT claimed to match Apple's own pin-1 designation.

## Pinout — 34 pins

| pin | function | confidence | notes |
|----:|----------|:----------:|-------|
| 1 | D-bus (GREEN field) | **high** | Idles LOW, bursts to ~1.8-2 V every 1s. / Frame mode: GREEN channel (driven high only by the green fill). |
| 2 | D-bus (BLUE field) | **high** | Idles LOW, bursts to ~1.8-2 V every 1s. / Frame mode: BLUE channel (driven high only by the blue fill). |
| 3 | GND | **high** | 0 V powered; 0.6-1.5 ohm to signal ground unpowered. |
| 4 | BL+ (backlight anode) | **high** | 10.7 V with backlight on. FAR above logic. NEVER connect to an analyzer input: TXU0104 A-side absolute max … |
| 5 | BL- (backlight cathode) | **high** | 27.1 mV backlight ON, 0 mV OFF - perfectly correlated with backlight state. 25.6 ohm sense resistor to grou… |
| 6 | GND | **high** | 0 V powered; 0.6-1.5 ohm to signal ground unpowered. |
| 7 | TE (tearing effect) | **high** | 60 us pulse every 14.72 ms = 67.9 Hz, the panel refresh rate. Panel output. |
| 8 | GND | **high** | 0 V powered; 0.6-1.5 ohm to signal ground unpowered. |
| 9 | D-bus RED field (dup. of pin 14) | **high** | Red channel. Byte-identical to pin 14 in every capture, and NOT shorted (6.66 MOhm) - this is the replicate… |
| 10 | D-bus RED field | **high** | Red channel: high only on red and white fills. |
| 11 | D-bus APB bit 13 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[13]. / Frame mode: RED channel (driven hi… |
| 12 | D-bus APB bit 12 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[12]. / Frame mode: RED channel (driven hi… |
| 13 | D-bus APB bit 11 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[11]. / Frame mode: RED channel (driven hi… |
| 14 | D-bus APB bit 10 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[10]. / Frame mode: RED channel (driven hi… |
| 15 | D-bus APB bit 9 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[9]. / Frame mode: GREEN channel (driven h… |
| 16 | D-bus APB bit 8 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[8]. / Frame mode: GREEN channel (driven h… |
| 17 | GND | **high** | 0 V powered; 0.6-1.5 ohm to signal ground unpowered. |
| 18 | D-bus APB bit 7 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[7]. / Frame mode: GREEN channel (driven h… |
| 19 | D-bus GREEN field (APB bit 6) | **high** | CONFIRMED: 0x00EF (vertical end = 239) decodes correctly only with this pin as bit 6; excluding it yields 0… |
| 20 | D-bus APB bit 5 | **high** | CONFIRMED on LA-B: exact 68-write match to bit5. / Frame mode: GREEN channel (driven high only by the green… |
| 21 | D-bus APB bit 4 | **high** | CONFIRMED by swap test onto known-good CH17: exact match to bit4 (21/68 ones). / Frame mode: BLUE channel (… |
| 22 | D-bus APB bit 3 | **high** | CONFIRMED on LA-B: exact 68-write match to bit3. / Frame mode: BLUE channel (driven high only by the blue f… |
| 23 | D-bus APB bit 2 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[2]. / Frame mode: BLUE channel (driven hi… |
| 24 | D-bus APB bit 1 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[1]. / Frame mode: BLUE channel (driven hi… |
| 25 | D-bus APB bit 0 | **high** | Exact 69-write match against lcd_init_seq_23 (firmware wake). APB[0]. / Frame mode: BLUE channel (driven hi… |
| 26 | VDDIO 1.8V rail | **high** | Stable 1.8 V; used all session as the shifter VREF with no instability. |
| 27 | /WR | **high** | 1.64 MHz strobe: 70-80 ns low, 530-540 ns high, 610 ns cycle @100 MS/s. Burst span 46.92 ms matches 320x240… |
| 28 | D/C (RS) | **high** | 0 = command, 1 = data. Exact match over 69 writes. |
| 29 | /CS (chip select, active low) | **high** | Idles high; asserted low in long envelopes framing write bursts (85.7% duty over 164 ms). |
| 30 | /RD or /RESET (active low, idle high) | medium | Constant high over 164 ms. Assigned by elimination: all other functions are placed, and these are the only … |
| 31 | GND | **high** | 0 V powered; 0.6-1.5 ohm to signal ground unpowered. |
| 32 | /RD or /RESET (active low, idle high) | medium | Constant high over 164 ms. Assigned by elimination: all other functions are placed, and these are the only … |
| 33 | PWR 3.0V rail | **high** | 3.0 V - too high for the 1.8 V logic domain, so a genuine supply. |
| 34 | unresolved-analog | low | ~1.5 V with ~100 mV ripple at ~80 us (12.5 kHz). Switching/charge-pump or bias node rather than logic. |

## Pixel format

**RGB666 - 18 lanes, 6 bits per colour channel**

- **RED**: pins 9, 10, 11, 12, 13, 14
- **GREEN**: pins 1, 15, 16, 18, 19, 20
- **BLUE**: pins 2, 21, 22, 23, 24, 25

framebuffer is RGB565; the SoC expands 5-bit R and B to 6 lanes

> **Open:** blue shows no duplicate pair though a 5->6 expansion needs one; the expansion is not symmetric between red and blue. P02's role is also unclear (only 2 ones across the 69-write init).

## Bus timing (measured at 100 MS/s)

- /WR low: **70–80 ns**
- /WR high: **530–540 ns**
- /WR cycle: **610 ns** (1.64 MHz)
- Transfers per pixel: **1**
- Full frame: 76800 writes ≈ 46.9 ms
- D/C polarity: **0 = command, 1 = data**
- Data latched on the **rising edge of /WR**

## Backlight

- Anode **pin 4** at **10.7 V** — ⚠️ never connect to a 5 V-max analyzer input
- Cathode **pin 5** through a **25.6 Ω** sense resistor
- PWM-dimmed. 10.7 V is consistent with a 3-LED white string plus headroom.

## Instrumentation notes

- **LA-A** (`5033592792565F9F`): good CH1-12, CH17-24; dead group CH13, CH14, CH15, CH16
- **LA-B** (`5033592712586E1F`): good CH1-20; dead group CH21, CH22, CH23, CH24

> Each board has exactly one dead 4-bit TXU0104 group, in different positions. Never chain them: multidevice allows pattern triggers only, and burst mode requires an Edge trigger.

