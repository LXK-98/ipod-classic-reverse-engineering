# Breadboard driver — build and bring-up

How to build the RP2040 breadboard driver and bring the panel up in three gated
milestones. [DRIVING.md](DRIVING.md) is the spec; this is the build. Firmware is in
[`firmware/`](../firmware), host control in [`tools/drv.py`](../tools/drv.py).

**Status (2026-10-13): written, not yet built.** The firmware passes a host-side test of
its sequencing logic (`python3 firmware/test_host.py`), and its bus encoder reproduces the
iPod's init on all 18 lanes. Nothing has run on a Pico yet. Every electrical claim is either
a **(F)** measurement from this project, a **(datasheet)** figure, or marked **inference**.

The pair test (milestone 3) is the reason this exists. The SoC ties each RGB666 pair to one
APB bit on data writes, so only an external driver can present a split pair to the panel.

---

## 1. GPIO budget

18 data + D/C + /WR + /CS + 3 enables + TE = **25 of the Pico's 26** usable GPIOs. P30 and P32
are tied high with pull-ups, since they never move during operation. The status LED is the
Pico's own (`Pin("LED")`), which costs no GPIO.

| GPIO | net | via | flex pin |
|---|---|---|---|
| GP0–GP17 | D0–D17 | U1–U3 (8T245) | see §3c |
| GP18 | D/C | U3 | 28 |
| GP19 | /WR (PIO side-set) | U3 | 27 |
| GP20 | /CS | U3 | 29 |
| GP21 | EN 3.0 V (ME6211 CE) | 10 kΩ to GND | — |
| GP22 | reference hold (TLV9061 IN+) | direct | — |
| GP26 | EN 1.8 V (AP2112 EN) | 10 kΩ to GND | — |
| GP27 | TE in | U4 (1T45) | 7 |
| GP28 | **spare**, reserved | — | — |

GP0–GP18 must be consecutive: PIO writes all 18 lanes plus D/C with one `out pins, 19`.
GP*n* drives D*n*, where D17..D0 is the [DRIVING §4](DRIVING.md#4-pixel-format) pixel order
R5..R0 G5..G0 B5..B0. A pixel is then simply `r << 12 | g << 6 | b`.

**GP28 is reserved as a driven /RESET candidate.** If init does not take and reset timing
becomes the suspect, wire GP28 through a spare U3 channel to P30 or P32 in place of its
pull-up. Never drive both at once (DRIVING §2: one of them may be /RD).

## 2. Connection to the panel

> ⚠️ **Unplug the iPod logic board from the interposer (J2) first.** The driver replaces it.
> With the logic board in, its rails and the SoC fight the driver's.

The panel stays in **J3**. The driver connects to the header. The analyzer needs the same
pins at the same time, so either use J1 for one and J4 for the other (identical nets), or
piggy-back. Connect **all five grounds** (pins 3, 6, 8, 17, 31) to the Pico's ground, and
share that ground with the analyzer and the backlight supply.

| flex pin | driver net | | flex pin | driver net |
|---|---|---|---|---|
| 1 | D9 (U2 B2) | | 18 | D8 (U2 B1) |
| 2 | D0 (U1 B1) | | 19 | D7 (U1 B8) |
| 3, 6, 8, 17, 31 | GND | | 20 | D6 (U1 B7) |
| 4, 5 | backlight rig (§3g) | | 21 | D5 (U1 B6) |
| 7 | TE → U4 A | | 22 | D4 (U1 B5) |
| 9 | D17 (U3 B2) | | 23 | D3 (U1 B4) |
| 10 | D16 (U3 B1) | | 24 | D2 (U1 B3) |
| 11 | D15 (U2 B8) | | 25 | D1 (U1 B2) |
| 12 | D14 (U2 B7) | | 26 | **1.8 V VDDIO** (AP2112 out) |
| 13 | D13 (U2 B6) | | 27 | /WR (U3 B4) |
| 14 | D12 (U2 B5) | | 28 | D/C (U3 B3) |
| 15 | D11 (U2 B4) | | 29 | /CS (U3 B5) |
| 16 | D10 (U2 B3) | | 30, 32 | 10 kΩ pull-up to VDDIO each |
| | | | 33 | **3.0 V** (ME6211 out) |
| | | | 34 | **reference** (TLV9061 out via 10 kΩ) |

## 3. Circuit, block by block

All parts are from [`hardware/lcsc-order.csv`](../hardware/lcsc-order.csv). The SMD parts
go on the SMD-to-DIP adapters.

### 3a. Rails

Both LDOs run from the Pico's **VSYS** (pin 39, ≈4.7 V on USB). Put 1 µF on each LDO's input
and output (the BOM has six 1 µF X7R THT), and the 10 µF electrolytic on VSYS by the LDOs.

| part | pins (SOT-23-5) | enable |
|---|---|---|
| ME6211C30 → **3.0 V**, flex 33 | 1 VIN · 2 GND · 3 CE · 5 VOUT | GP21, **10 kΩ to GND** |
| AP2112K-1.8 → **VDDIO**, flex 26 | 1 VIN · 2 GND · 3 EN · 5 VOUT | GP26, 10 kΩ to GND |

Datasheet facts the design leans on:

- **(datasheet) The AP2112 discharges VOUT through ~60 Ω when EN is low**, and EN has a
  3 MΩ internal pull-down (V<sub>IH</sub> ≥ 1.5 V, start-up 20 µs typical). So VDDIO falls
  fast and first whenever its enable drops, including on a Pico reset or a USB unplug. That
  is the right failure order, by construction.
- **(datasheet) The ME6211 datasheet documents neither an output discharge nor a CE
  pull-down**, and gives no start-up time. CE high ≥ 1.0 V, low ≤ 0.5 V, CE ≤ VIN + 0.3 V.
  Hence the external 10 kΩ pull-down, and a 1 ms (not 0.13 ms) wait before the reference.
  The 3.0 V rail decays through its load after shutdown, which is slowest of the three.
  That is also the right order.

### 3b. Reference (flex 34)

**(datasheet) The TLV9061IDBVR we bought has no shutdown pin.** Only the 6-pin TLV9061S has
SHDN. So the reference cannot have an enable of its own. Instead the op-amp runs from the
**3.0 V rail**, and a GPIO holds its input low until released:

```
 3.0 V ──┬── 5 kΩ (2 × 10 kΩ ∥) ──┐
         │                         3296W 10 kΩ ── GND
         │                         └ wiper ── 10 kΩ ──┬── IN+ (3)
         │                                            └── GP22   (hold low = reference off)
         └── V+ (5), 100 nF to GND        V− (2) ── GND
            OUT (1) ──┬── IN− (4)          (unity-gain follower)
                      └── 10 kΩ ── flex 34
```

This satisfies the hard constraint structurally. The buffer is never powered from VDDIO,
and **the reference cannot exist without the 3.0 V rail**, whatever the firmware does.

- **GP22 only ever sinks or floats.** The firmware's `_Sink` class has no way to drive it
  high. That matters because the TLV9061's inputs are diode-clamped to its rails
  (abs. max ±10 mA). A GPIO driving 3.3 V into an unpowered op-amp would back-power the
  3.0 V rail through it. If you have a 1 kΩ to hand, put it in series with GP22 as a hardware
  guard: worst case ~2.8 mA, at the cost of an "off" level of ~0.12 V instead of 0 V.
- **Range is 0–2.0 V**, about 0.08 V per trimmer turn. The 5 kΩ top resistor is a ceiling as
  well as a scale: pin 34's absolute maximum is unknown, and this keeps it ≤ 2.0 V even with
  the trimmer fully up.
- **The 10 kΩ output resistor costs nothing.** The original drives this pin through 1–2 MΩ.
  The panel's draw, inferred from the DMM droop, is ~0.2 µA, which drops ~2 mV across 10 kΩ.
  The resistor also isolates the op-amp from whatever capacitance the panel puts on the pin.
- **Measure at the TLV9061 OUT, not at pin 34.** The buffer makes the level measurable at
  last, which is the point of having it.
- **Set it to ~1.5 V for milestone 1.** With no panel attached that matches the original's
  unloaded 1.54 V. It also keeps the analyzer's ~1.1 V threshold well clear: at 1.3 V the
  crossing would sit near the top of the ramp. **Then set ~1.3 V before connecting the panel**
  (DRIVING §1).

### 3c. Bus level shifting

Three **SN74LVC8T245** (TSSOP-24): 1 VCCA · 2 DIR · 3–10 A1–A8 · 11–13 GND · 14–21 **B8…B1**
(note the B port numbers *down*) · 22 /OE · 23–24 VCCB.

For each one: VCCA = Pico **3V3** (pin 36), VCCB = **VDDIO**, **DIR tied to VCCA** (A → B),
**/OE tied to GND**, and 100 nF on each supply. **Tie unused A inputs to GND**; leave unused
B outputs open.

| | A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8 |
|---|---|---|---|---|---|---|---|---|
| **U1** | GP0 | GP1 | GP2 | GP3 | GP4 | GP5 | GP6 | GP7 |
| → flex | 2 | 25 | 24 | 23 | 22 | 21 | 20 | 19 |
| **U2** | GP8 | GP9 | GP10 | GP11 | GP12 | GP13 | GP14 | GP15 |
| → flex | 18 | 1 | 16 | 15 | 14 | 13 | 12 | 11 |
| **U3** | GP16 | GP17 | GP18 | GP19 | GP20 | GND | GND | GND |
| → flex | 10 | 9 | 28 (D/C) | 27 (/WR) | 29 (/CS) | — | — | — |

Why no /OE control is needed: **(datasheet)** if either supply is below 100 mV, every I/O
goes high-impedance. The datasheet also specifies glitch-free power sequencing in any
order. So the bus is Hi-Z until VDDIO exists, and it follows the A-side levels as VDDIO
rises. The firmware idles the bus (/WR and /CS high, data low) *before* enabling any rail.
So /WR and /CS rise with VDDIO and collapse with it, which is exactly the original's
behaviour (DRIVING §1).

**Breadboard hygiene for /WR.** The panel latches on the /WR rising edge, so ringing on that
edge could clock a second write. Keep the /WR wire short. If writes misbehave, add a spare
68 Ω THT (from the backlight kit) in series at U3's /WR output.

### 3d. TE in (flex 7)

**SN74LVC1T45** (SOT-23-6): 1 VCCA · 2 GND · 3 A · 4 B · 5 DIR · 6 VCCB. Wire VCCA = **VDDIO**,
A = flex 7, **DIR to VCCA** (A → B), VCCB = Pico 3V3, B → GP27.

The shift is needed: **(datasheet)** the RP2040's V<sub>IH</sub> minimum at IOVDD = 3.3 V is
**2.0 V**, above a 1.8 V TE. While VDDIO is off the 1T45 is Hi-Z, and GP27's internal pull-down holds it low.

### 3e. P30 and P32

Each gets a **10 kΩ pull-up to VDDIO**. That never exceeds the panel's logic level, and each
line makes one transition up and one down, as measured on the original.

### 3f. Ground

This is one ground: the Pico, the LDOs, all four shifters, flex 3/6/8/17/31, the analyzer and
the backlight supply.

### 3g. Backlight

This is unchanged: the existing LM317 constant-current rig (18.4 mA) on pins 4/5, which is
not under Pico control. ⚠️ **Pin 4 reaches 12.76 V.** Keep it away from the analyzer and
from the 1.8 V wiring.

## 4. Firmware

The Pico needs **MicroPython** (any recent RP2040 build; the phase-0 Pico already runs it).
There is no C toolchain on this machine, and none is needed: the bus timing comes from PIO,
which is deterministic whatever language feeds it.

```bash
python3 firmware/test_host.py
```

```bash
~/.pyenv/versions/3.10.14/bin/python tools/drv.py deploy
```

(`drv.py` needs pyserial, which lives in that interpreter.) `deploy` powers down any driver
already loaded, removes a leftover `main.py` (picogen's PWM generator drives GP14/GP15,
which are two data lanes), uploads `bus.py` and `lcddrv.py`, and generates `initseq.py` from
`refs/sequences.json`.

**Importing the driver forces every rail off, in order.** Nothing powers up until asked.

| what | how | value |
|---|---|---|
| bus write | PIO at 25 MHz, 20 cycles | **800 ns**/write: /WR low 120 ns, data and D/C stable 520 ns before the latch, held 280 ns after (all beat DRIVING §3's known-good) |
| up | 3.0 V → +1 ms → reference → +218 ms → VDDIO | order from DRIVING §1; delays are knobs |
| first command | ≥ 400 ms after VDDIO | original 397 ms; bisect down later |
| down | sleep sequence (if initialised) → VDDIO → +33 ms → reference → +13 ms → 3.0 V | mirror; the sleep sequence is an **inference** |
| /CS | low for each burst, high between | as the original |

> ⚠️ **Do not soft-reset the Pico with the rails up** (Ctrl-D at its REPL). A soft reset
> releases the PIO pins while VDDIO may still be live. Run `tools/drv.py down` first. A USB
> unplug is safe: the enables fall, the AP2112 discharges VDDIO, and the shifters go Hi-Z.

## 5. Milestones

Do them in order. Each one de-risks the next.

### M1 — rails only, panel NOT connected

Build §3a and §3b. Leave the shifters out for the first pass.

1. Run `drv.py up`. With a DMM, read pin 33 ≈ 3.0 V, the TLV9061 OUT, and pin 26 ≈ 1.8 V.
   Set the trimmer for **~1.5 V** at OUT. Then run `drv.py down`. All three should read 0.
2. Capture with the analyzer wired as now (rails on CH2/CH9/CH19). Arm first, then cycle:

   ```bash
   python3 tools/capture.py power-seq --probe-map v1 --note "BREADBOARD M1: driver rail cycle, panel disconnected"
   ```

   ```bash
   ~/.pyenv/versions/3.10.14/bin/python tools/drv.py cycle --hold-ms 30
   ```

   The cycle takes ~295 ms, so **up and down both land in the one 322 ms window**.
3. Run `tools/railseq.py captures/<id>.csv.gz`, the same tool and arithmetic as the iPod's
   captures. **Pass:** V30_P33 at 0, VREF_P34 at about +1 ms, V18_P26 at about +219 ms. Then
   down: V18 first, VREF +33 ms after, V30 last. All single, monotonic transitions.
4. Add the shifters, TE translator and pull-ups (§3c–e) and repeat steps 2–3. Now WR_P27,
   CS_P29, P30 and P32 should rise **with** V18 and fall with it, while DC_P28 stays low.

**Bus check without the panel (recommended before M2).** Move the CH2/CH9/CH19 leads back
to pins 2/14/25. Then:

```bash
python3 tools/capture.py init-verify --probe-map v1 --note "BREADBOARD M2 pre-check: driver init, panel disconnected"
```

```bash
~/.pyenv/versions/3.10.14/bin/python tools/drv.py up
```

```bash
~/.pyenv/versions/3.10.14/bin/python tools/drv.py init
```

```bash
python3 tools/seqmatch.py captures/<id>.csv.gz --config bootloader --sequence init
```

```bash
python3 tools/encoder_check.py captures/<id>.csv.gz --config bootloader --sequence init
```

**Pass:** burst structure `[140, 2, 2, 2]`, 146/146 matched, and 146/146 pin-exact on all
18 lanes. That proves the encoding, the PIO timing and every shifter wire with nothing
attached that could be harmed. (`up` raises /WR, a rising edge, so only the first write
triggers the capture.) Finish with `drv.py down`.

### M2 — init, panel connected

1. With the panel still out, run `drv.py up`, set the reference to **~1.3 V** at OUT, then
   run `drv.py down`.
2. Seat the panel in J3, with the logic board still out of J2. Charger disconnected.
3. Arm `init-verify` as above. Then run `drv.py up` and `drv.py init`, which prints a TE
   measurement.
4. **Pass:** `seqmatch` and `encoder_check` as in the pre-check, and **TE at ~67.9 Hz**. On the
   original, TE starts 12.5 ms after init (DRIVING §6), so a live TE is the panel's own
   confirmation that init took.

If TE stays dead, the failure is soft: init did not take. These are the candidates in the
order I'd try them. None of them is a diagnosis:

- the reference level: sweep the trimmer 1.1–1.6 V
- reset timing on P30/P32: GP28 is reserved for this
- the known deviations in §6
- `--variant awake`

Change one at a time, and say which.

### M3 — fills, then the pair test

1. Run `drv.py fill 63 0 0`, then `0 63 0`, `0 0 63`, `63 63 63` and `0 0 0`. Each channel
   should land where DRIVING §4 says it does.
2. Run `drv.py ramp`, which stacks red, green and blue ramps in thirds. Each has 64 steps of
   5 px. **Green is the control** and sits between the two channels under test.
   - **Photo:** take it macro, square-on, at manual exposure. Count bands in the red and
     blue thirds against the green third.
   - **64 bands in red and blue:** the pairs are independent, and the panel does true RGB666.
   - **32 double-width bands:** the pairs are tied inside the panel. Drive each pair together
     (5 effective bits on red and blue, exactly as Rockbox does), which settles the board
     architecture.
3. **Bus capture, to prove the driver really split the pairs:** arm
   `capture.py init-verify --loops 0`, then run `drv.py ramp r`. One burst holds the window
   plus about 190 pixels of row 0, which is red values 0–38. Then run
   `tools/decode8080.py <capture> --raw`. It lists the first 60 writes: the window, then red
   0–9. **P14 should go high from red = 1 while P09 stays low.** No SoC data write has ever
   done that. Repeat with `ramp b` for P02 against P21.

Commit each milestone's capture and finding separately.

## 6. Known deviations from the original board

These are deliberate or unavoidable. Each is a suspect only if something fails, not a
reason to change the design beforehand.

| | original (F) | breadboard |
|---|---|---|
| P32 at power-up | crosses with the analog rails, +0.09 ms | rises with VDDIO (pull-up) |
| P30/P32 at power-down | outlive VDDIO by 47/34 ms | fall with VDDIO |
| P21 before VDDIO | crosses threshold with the reference (notebook 2026-10-13) | Hi-Z, then low |
| 3.0 V → reference | 0.13 ms | 1 ms |
| reference source | 1–2 MΩ | buffer + 10 kΩ |
| bus cycle during init | 610–818 ns | 800 ns |
| init variant at cold boot | bootloader 146 writes | the same |
