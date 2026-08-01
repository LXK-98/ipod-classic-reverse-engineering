# Lab notebook

Running log. Newest entries at the bottom of each phase. Every entry: date, action,
result, interpretation, next step. **F** = verified fact, **H** = hypothesis,
**E** = collaborator estimate (not measured).

---

## Phase 0 — Environment

### 2026-07-26 — Session setup, open questions answered

**Action:** Collected the open questions from the project brief.

**Result:**
- Logic analyzers: **buffered gusmanb boards with TXU0104 level shifters** (F, reported).
- Rockbox: **already installed and booting** (F, reported).
- Interposer: in hand, **not yet installed**.
- Phase 6 target: undecided; plan for RP2040 PIO bridge as primary.
- Host: Fedora Linux 44, x86_64, Python 3.10.14 (pyenv). User is in `dialout`,
  so no udev work is needed for serial access.

**Interpretation:** The TXU0104 boards accept 1.6–5 V with an external VREF. This
substantially de-risks the Phase 1 decision gate: even if VDDIO is 1.8 V, we can probe
directly instead of building shifters. Direct-to-Pico probing is *not* on the table and
does not need to be, so rule 2 is satisfied by the shifter path.

**Next step:** Fetch Rockbox ground truth, stand up the capture toolchain.

---

### 2026-07-26 — Rockbox ground truth fetched and parsed

**Action:** Downloaded the two driver files plus two supporting headers into `refs/`,
and wrote `tools/rockbox_seq.py` to expand them into byte-exact bus transaction lists.

**Result:** `refs/sequences.json`. Bus-write counts per panel type:

| type | cmdset | init (bootloader) | sleep | awake (firmware) |
|-----:|-------:|------------------:|------:|-----------------:|
| 0 | 8-bit  | **9**   | 2  | 2   |
| 1 | 8-bit  | **150** | 2  | 2   |
| 2 | 16-bit | **146** | 18 | 152 |
| 3 | 16-bit | **146** | 18 | 152 |

**Interpretation — several findings that change the plan:**

1. **(F) Panel type is identifiable by edge-counting alone.** Init lengths of 9 / 150 / 146
   writes are so different that a raw /WR edge count over a boot separates type 0 from
   type 1 from type {2,3}, with no decoding and no known lane mapping. This is a Phase 2
   result, not a Phase 4 one. Types 2 and 3 are indistinguishable by sequence — Rockbox
   drives them identically — so the "which of four types" deliverable can only ever be
   narrowed to {2,3} if it is one of those.

2. **(F) Only the BOOTLOADER build runs an init sequence.** `lcd_init_device()` guards
   `lcd_run_seq(seq_init)` with `#ifdef BOOTLOADER`. A full panel init therefore appears
   only during a cold boot through the Rockbox bootloader. The main firmware never inits.

3. **(F) `HAVE_LCD_SLEEP` is `#ifndef BOOTLOADER`** (`config/ipod6g.h:95`). The bootloader
   and firmware expansions of the *same* `lcd_init_seq_23` array therefore differ: the
   firmware one is prefixed with 6× NOP + 1024 µs delay (release from deep standby),
   the bootloader one is not. 146 vs 152 writes. Do not treat them as one target.

4. **(F) Types 2/3 replay a full init on wake** — `seq_awake` *is* `lcd_init_seq_23`.
   Types 0/1 wake is only `0x11` + `0x29`. So on a 16-bit panel we can re-trigger a
   complete init on demand with a display-off/on cycle, no reboot needed. This is both a
   cheap discriminator and a huge convenience for Phase 3 (repeatable trigger).

5. **(F) `S5L_LCD_WITH_READID` is NOT defined for ipod6g** (`lcd-target.h`). Rockbox
   never issues a read transaction. **Correction to the project brief**, which assumed
   "Rockbox can read a display ID". Expect `/RD` to be idle for an entire Rockbox boot.
   Per the ground rules, /RD must therefore NOT be classified as NC from silence — it
   will be silent even when perfectly healthy. Apple firmware may still exercise it.

6. **(F) Pixel packing is documented in the driver, not just guessable.**
   `lcd-s5l8702.c` states frame mode on 6G is `LCD_MODE_P16` = 16-bit 8080,
   RGB565 in one transfer, `APB[15:0] -> D[17:10, 8:1]`.
   → **D9 and D0 are unused during pixel bursts.** Two lanes idle while 16 others toggle
   is a very strong fingerprint for lane identification.
   Command mode for the 8-bit command set is `LCD_MODE_P8`: `APB[7:0] -> D[8:1]`.
   → commands ride on **D8..D1 only**; D17..D9 and D0 idle. Independently corroborated by
   the read path doing `LCD_DBUFF >> 1` (an 8-bit field based at bit 1).
   Still (H) until confirmed by capture — the source comments mark it "TBC".

7. **(F) `LCD_PHTIME = 0x33` on 6G**, set in `lcd_init_device()`. A bus phase-timing
   register; gives Phase 5 a value to reconcile measured WR widths against.

**Next step:** Stand up TerminalCapture and validate the pipeline end to end.

---

### 2026-07-26 — Capture toolchain

**Action:** Downloaded gusmanb release **v6.0.0.1** (`all-in-one_6.0.0.1-linux-x64`)
into `vendor/`. Inspected the shipped binaries and the upstream source.

**Result — deviation from the project brief:** the current release **no longer ships
`CLCapture`**. It is replaced by **`TerminalCapture`**, which is settings-file driven
rather than positional-argument driven:

    TerminalCapture capture <serial-port> <settings.tcs> <output.csv>

The brief's documented CLCapture syntax is therefore obsolete. Recovered the actual
interface from upstream source rather than guessing:

- `.tcs` is a JSON serialisation of `SharedDriver.CaptureSession`
  (`FileOperations.LoadSession`). Fields: `Frequency`, `PreTriggerSamples`,
  `PostTriggerSamples`, `LoopCount`, `MeasureBursts`, `CaptureChannels[]`,
  `TriggerType`, `TriggerChannel`, `TriggerInverted`, `TriggerBitCount`,
  `TriggerPattern`.
- `TriggerType` enum: `Edge=0, Complex=1, Fast=2, Blast=3`.
- `ChannelNumber` is **0-based** (`TextualChannelNumber` = `ChannelNumber + 1`).
- Burst count is expressed as `LoopCount`, where
  `TotalSamples = PostTriggerSamples * (LoopCount + 1) + PreTriggerSamples`.
  So `LoopCount = bursts - 1`.
- **CSV format** (`FileOperations.SaveCSV`): one header row of channel names, then one
  row per sample with a `0`/`1` per channel, comma separated. **There is no timestamp
  column** — time is implicit at `1/Frequency`. Parsers must not expect one.
  (F from source; to be re-verified against a real file in the dry run, per the brief's
  instruction not to assume the format.)

Binaries are self-contained .NET; no `dotnet` runtime install was needed.

Wrote `tools/capture.py` with presets `dryrun` / `survey` / `init-burst` / `blit-timing`,
port autodetection, sidecar JSON, and a hard sample-budget guard (131071 / 65535 / 32767
for ≤8 / ≤16 / ≤24 channels). Verified the guard rejects an over-budget request and that
the `init-burst` preset fits: 20 channels, 64 pre + 512 × 50 bursts = 25664 ≤ 32767.

**Next step:** Plug in one analyzer and validate capture → CSV → parse on a known signal.

---

### 2026-07-26 — Analyzer hardware, header pinout, and the VREF path

**Action:** Identified the analyzer board header silkscreen from the upstream KiCad
render, and read the TXU0104 datasheet (SCES937B) for real threshold numbers.

**Result — header silkscreen** (analyzer board; wiki states the shifter board header is
identical, *except* the `5v` pin becomes external VREF when the reference jumper is
removed):

```
top row:     CH1  CH2  CH3  CH4  CH5  CH6  CH7  CH8  CH9 CH10 CH11 CH12  GND  EXT  EXT
bottom row: CH24 CH23 CH22 CH21 CH20 CH19 CH18 CH17 CH16 CH15 CH14 CH13  GND  3v3   5v
```

**(F) Silkscreen `CHn` = software `ChannelNumber n-1`.** Silkscreen is 1-based, `.tcs`
is 0-based. Every channel index in this repo's tooling is the 0-based software number.

**(F) TXU0104 is unidirectional, A→B, A = input.** "Ax pins are referenced to VCCA
logic level ... Bx pins are referenced to VCCB." On the shifter board the probed signal
enters the A side referenced to the jumper-selected VREF; the B side drives the Pico.

**(F) TXU0104 Schmitt thresholds, referenced to the input-side supply VCCI:**

| VCCI | 1.1 V | 1.65 V | 2.3 V | 3 V | 4.5 V | 5.5 V |
|---|---|---|---|---|---|---|
| VT+ max | 0.88 | 1.13 | 1.56 | 1.92 | 2.74 | 3.33 |
| VT− min | 0.17 | 0.35 | 0.56 | 0.89 | 1.51 | 1.88 |

A port accepts 1.1–5.5 V input regardless of VCCA.

**Interpretation:**
1. The 3.3 V dry-run signal is valid into the default 5 V-referenced input: VT+ max at
   5 V nominal is ~3.0 V by interpolation, below the 3.3 V logic high. **No jumper
   change needed for phase 0.**
2. **Revises the brief's phase 1 decision gate.** The brief says to stop if
   VDDIO < ~2.3 V and plan level shifting. With these boards that is unnecessary: at
   VCCI = 1.65 V the thresholds are 1.13 / 0.35 V, so a 1.8 V panel translates cleanly
   *provided the 5 V reference jumper is removed and the panel's own VDDIO is fed to the
   `5v` pin as external VREF*. The gate becomes a configuration step, not a blocker.
   Still must not probe before VDDIO is measured (safety rule 2 unchanged).
3. Backlight rails remain absolutely out of bounds regardless of VREF (safety rule 1) —
   the A port is rated to 5.5 V max and a boost-driven LED anode can exceed that.

**Next step:** Wire the Pico reference signal to CH1/CH2 and run the dry-run capture.

---

### 2026-07-26 — ModemManager wedges both instruments (root cause)

**Action:** First dry-run capture armed but never triggered (timed out). Investigated.

**Result:** **(F) Fedora's ModemManager probes both bench instruments.** udev tagged
both with `ID_MM_CANDIDATE=1`:

```
/dev/ttyACM0  1209:3020  Dr. Gusman LogicAnalyzer
/dev/ttyACM1  2e8a:0005  MicroPython Board
```

ModemManager opens such ports and fires AT commands at them to probe for a modem.
On a Pico-class CDC stack this wedges the port: the device stays enumerated and the
USB descriptor still reads correctly, but the data path goes deaf in both directions.
Symptom sequence matched exactly — the REPL worked immediately after flashing, then
became permanently unresponsive after the device re-enumerated and was probed. A USB
unplug/replug did not recover it.

**Fix:** `docs/99-bench-instruments.rules` sets `ID_MM_DEVICE_IGNORE=1` for vendor
`2e8a` (any RP2040 firmware, incl. BOOTSEL `2e8a:0003`) and for `1209:3020`.
Installed to `/etc/udev/rules.d/`, rules reloaded, ModemManager restarted. Verified
`ID_MM_DEVICE_IGNORE=1` now present on both ports. REPL recovered immediately.

Note `ID_MM_CANDIDATE=1` legitimately *remains* set — it is applied by MM's own
`77-mm-*` rules, which sort before ours. The property that matters is
`ID_MM_DEVICE_IGNORE`. Checking the wrong one gives a false alarm.

**Interpretation — this was worth catching before touching the iPod.** The hazard was
never Pico-specific: the **logic analyzer carries the same flag**, so an AT-command
probe landing mid-capture could have stalled or corrupted a boot capture. Had this
first appeared as garbled data on an unknown 33-pin flex, the obvious suspects would
have been bad probe contact or undersampling, and we would have chased the iPod for
a host-side fault. Anyone reproducing this work on a systemd distro needs this rule.

**Second bug, ours:** `picogen.py` originally created `PWM` objects in a REPL scope
and kept only result tuples alive. MicroPython finalises a garbage-collected `PWM` by
deinitialising the pin, so the signal died as soon as the block returned — leaving the
analyzer armed on an edge that never came. Fixed by deploying a `main.py` that holds
module-level references, which also makes the signal survive resets and replugs.

---

### 2026-07-26 — Phase 0 acceptance: PASSED

**Action:** Captured the known Pico signal and checked it against ground truth with
`tools/classify.py --expect`.

**Result — 1 MS/s, 10 kHz reference:**

| channel | freq | err | duty | err |
|---|---|---|---|---|
| SIG_50 | 10000.00 Hz | 0.000 % | 50.00 % | 0.00 pp |
| SIG_25 | 10000.00 Hz | 0.000 % | 25.00 % | 0.00 pp |

**Result — 100 MS/s, 1 MHz reference** (validates the top-speed path Phase 5 needs):
both channels 1000000.00 Hz, 0.000 % error; 121024 rows, exactly as predicted.
Median pulse widths 510/490 ns and 250/750 ns against nominal 504/496 and 252/748.

**(F) CSV format confirmed empirically**, matching what was derived from source:
header row of channel names, one row per sample, `0`/`1` per channel, **no timestamp
column**. Row count equals `Post*(Loop+1)+Pre` exactly.

**(F) The pre-trigger buffer is zero-filled if the trigger fires before it fills.**
In the 10 kHz capture, samples 0–510 were all zero with the first edge exactly at
sample 511 (= the 512-sample pre-trigger boundary). A free-running 10 kHz signal must
show ~5 periods in a 511 µs window, so those samples were never sampled from the wire.
**Consequence for phases 2–5: pre-trigger data is not trustworthy unless the device
was demonstrably armed before the event.** `classify.py` detects this
(`pretrigger_unfilled`) and measures duty over whole cycles instead.

**(F) Boundary runs must be excluded from pulse-width stats.** The first and last runs
in a capture are truncated by the window; including them reported a 40 ns minimum high
time on a 1 MHz 50 % signal. `classify.py` now drops both and reports median alongside
min, since ~3 samples of jitter exist at 100 MS/s.

**Acceptance criterion from the brief — "a scripted capture produces a CSV whose
contents match the known signal" — is met.** Phase 0 complete.

**Next step:** Phase 1. Install the interposer (power off) and fix the pin-numbering
convention from a photo before any measurement is recorded.

---

## Phase 1 — DMM triage

### 2026-07-26 — Interposer installed early; ATA error decoded

**Action:** Collaborator installed the interposer board and booted the iPod ahead of the
planned sequence. Screen works. Rockbox shows `ATA error: -2147483605`.

**Result 1 — (F) the interposer is electrically sound.** The panel initialises and
displays normally through it, and the boot reached `apps/main.c`. So the Rockbox
*bootloader* ran a complete LCD init through the interposer, and read enough of the
drive to load and launch `rockbox.ipod`. This de-risks phase 3 considerably.

**Result 2 — the ATA error decoded from source.** `-2147483605` = `0x8000002B`.
Error codes here are a nested call trace, built by macros in
`firmware/target/arm/s5l8702/ipod6g/mmcdefs-target.h`:

```c
#define ERR_RC(val)               (BIT(31) | (val))
#define PASS_RC(expr, bits, val)  ... return ERR_RC((rc << (bits)) | (val))
```

Each layer shifts the inner code left and ORs its own tag, so reading from the LSB
upward walks outward-to-inward. `0x2B` = `0b101011`:

| bits | val | site |
|---|---|---|
| `[2:0]` = 3 | 3 | `ata_power_up()`, **non-CE-ATA branch**, `PASS_RC(ata_identify(...), 3, 3)` |
| `[3]` = 1 | 1 | `ata_identify()`, `PASS_RC(ata_wait_for_start_of_transfer(...), 1, 1)` |
| `[5:4]` = 2 | 2 | `ata_wait_for_start_of_transfer()`, `RET_ERR(2)` |

Reconstruction check: `ERR_RC(2)=0x80000002` → `(<<1)|1 = 5` → `(<<3)|3 = 0x2B`. ✓

**Interpretation:** the drive did not respond to IDENTIFY within the 10 s timeout.
`RET_ERR(2)` is the timeout path, *not* `RET_ERR(1)` which is "drive asserted ERR" — so
the drive is not reporting a fault, it is not answering at all. Printed from
`apps/main.c:598`, i.e. the **main firmware**, whose `storage_init()` re-initialises and
re-powers the drive from scratch after the bootloader had already read from it
successfully. A device that reads once and then fails a cold re-init points at a
marginal connection or a drive that will not spin up again, rather than at corruption.

Most likely cause, cheapest first: **the drive's ZIF ribbon was disturbed during the
interposer installation.** Other candidates: failing/stiction-prone HDD, low battery
failing under spin-up load.

**Result 3 — (F) a free route to deliverable #4 (panel type).** The error screen offers
"Press button to debug", which calls `dbg_ports()`
(`firmware/target/arm/s5l8702/debug-s5l8702.c:213`). That dumps every GPIO port
including **`GPIO 6`**, and `lcd_target_get_info()` selects the panel from
`(PDAT6 & 0x30) >> 4`. So the panel type can be read straight off the screen with no
capture at all. The same dump shows **`GPIO 11`**, and `ata_init()` sets
`ceata = PDAT(11) & BIT(1)` — which diagnoses why the driver took the parallel-ATA
branch. `dbg_hw_info()` at the same file prints `"LCD type: %d"` directly, but is
reachable only from a fully booted Rockbox.

**Next step:** read GPIO 6 and GPIO 11 off the debug screen before touching the drive.

---

### 2026-07-26 — ATA fault resolved; **panel type identified: TYPE 2**

**Action:** Collaborator found the HDD ZIF connector was inserted rotated 180°.
Corrected; Rockbox now boots fully. Read the debug menu.

**Result — (F) `LCD type: 2`.** Verified two independent ways:

| source | reading | derivation |
|---|---|---|
| `View HW info` | `LCD type: 2` | `dbg_hw_info()` prints `lcd_type` directly |
| `View I/O ports` | `GPIO 6: 0000006b` | `(0x6b & 0x30) >> 4 = 2` per `lcd-6g.c:264` |

The two agree exactly. **Deliverable #4 is complete** — and it resolves the ambiguity
that bus traffic never could, since Rockbox drives types 2 and 3 identically.

The flipped connector also explains the error signature precisely: a drive that is not
electrically present cannot answer IDENTIFY at all, which is the timeout path
(`RET_ERR(2)`) rather than the drive-reports-error path (`RET_ERR(1)`). The
"connection, not dead drive" reading held.

**Consequences — this reshapes phases 3–5:**

1. **16-bit register command set** (ILI9320/ILI9326-like). Command mode is
   `LCD_MODE_P18`, frame mode `LCD_MODE_P16`. Target sequences are
   `lcd_init_seq_23` / `lcd_deepstandby_seq_23`.
2. **(F) A repeatable init trigger exists without rebooting.** For type 2,
   `seq_awake == lcd_init_seq_23`, so an LCD sleep/wake cycle replays a full init.
   `HAVE_LCD_SLEEP_SETTING` is defined for this target, so the sleep timeout is
   settable from the Rockbox UI. Phase 3 no longer needs repeated cold boots.
3. **(F) The two boot paths are distinguishable at a glance.** Cold init (bootloader)
   opens `CMD 0x0008, DATA 0x0808`. Wake replay (firmware) opens with 6× `CMD 0x0000`
   spaced 1.28 ms apart — an unmistakable capture signature. 146 vs 152 bus writes.
4. **(F) LANE-SOLVER LIMITATION, found in advance from ground truth.** Across all 146
   (or 152) init writes, **bit columns 14 and 15 never toggle** — every value in
   `lcd_init_seq_23` is < `0x4000`. Column-matching therefore identifies only 14 of the
   16 data lanes from the init; the two lanes carrying bits 14/15 are stuck at 0 and
   mutually indistinguishable. All other columns are unique, there are no exact-inverse
   pairs, and the D/C column matches no data column (so D/C is unambiguous).
   **Mitigation:** frame-mode pixel data uses the full RGB565 range, and bits 15/14 are
   the red MSBs. A solid red or white fill exercises them. **Phase 5's colour fills are
   therefore load-bearing for the pinout, not merely confirmatory** — phase 4 cannot
   complete the lane map without them.

**Next step:** Phase 1 proper — fix the pin-numbering convention from a photo, then DMM
triage starting with the backlight (safety rule 1).

## Phase 2 — Survey capture

*(not started)*

## Phase 3 — Protocol capture

*(not started)*

## Phase 4 — Decode and solve

*(not started)*

## Phase 5 — Verification and timing

*(not started)*

## Phase 6 — Drive it

*(not started)*

---

### 2026-08-01 — Interposer design read; pin convention FIXED (flex is 34-pin, not 33)

**Action:** Collaborator supplied the interposer KiCad project (`display-analyzer-board/`,
their own design, v0.1b) plus a photo of the disassembled setup. Parsed the PCB netlist
and pad geometry directly rather than inferring from the photo.

**Result — (F) board topology, from the netlist:**

| ref | part | role |
|---|---|---|
| J2 | 35-pos 0.3 mm FPC | Logic board side |
| J3 | 35-pos 0.3 mm FPC | Display side |
| J1 | 2x17 header, SMD | probe header |
| J4 | 2x17 header, TH | alternate, identical nets |

```
J1/J4 pin p <-> net /(p+1)      p = 1..34
J2 pad q    <-> net /q          q = 2..35   (pad 1 unconnected by design)
J3 pad r    <-> net /(36-r)     r = 1..34   (pad 35 unconnected by design)
```

J3's pad order is mirrored relative to J2 — correct and intended, since the connectors
face opposite board edges. Both unconnected pads sit at the **top** in the photo
orientation. The interposer is confirmed **passive and 1:1**: no series parts, no lifted
pins, so DMM readings reflect the panel, not the board.

**(F) CORRECTION TO THE PROJECT BRIEF: the iPod LCD flex has 34 conductors, not 33.**
Confirmed by the collaborator. This reconciles everything: the connectors are 35-position
and were described as having "one more pin than the iPod" (35 vs 34), and the interposer's
own flex is built with all positions wired and the topmost conductor cut so it fits.
All 34 routed nets `/2`…`/35` are therefore **live**. `pinout.json` rebuilt for 34 pins.

An earlier intermediate reading — that header pin 1 was electrically dead — was a
consequence of the brief's 33-pin figure and is **withdrawn**. It was never measured.
Asking for the connector position count rather than assuming is what caught it; had we
guessed, every recorded pin index would have been silently offset by one.

**(F) Numbering convention, now authoritative** (see
`probe_maps/v1-interposer-convention.md`):

```
FLEX pin N = probe-header pin N = net /(N+1)      N = 1..34
```

Header pin 1 is **TOP-LEFT** with the board oriented as in the photo (title readable
top-left, Logic board/J2 left, Display/J3 right). Odd pins = LEFT column, even = RIGHT,
17 rows, increasing downward. FLEX 1 is the topmost live conductor. Internal convention
anchored to geometry; not claimed to match Apple's own pin 1.

**Sanity check:** 34 conductors fits the expected signal set — 18 data + WR/RD/CS/DC/
RESET/TE = 24, leaving ~10 for rails, grounds and backlight. Essentially no slack.

**(H) Panel module marking:** `LS025Q7UX05A S20 1227 003256 Z20 A1 RC`, read off the
panel in the photo. `LS025` indicates a Sharp 2.5" LCD module. No datasheet located for
this exact part; a sibling `LS025Q7UX01` is indexed by panel-spec sites but the host was
unreachable. Recorded as a lead only — Phase 1 will measure this unit directly, which is
better evidence than a sibling part's datasheet.

**Next step:** Phase 1 DMM triage, backlight first per safety rule 1.

---

### 2026-08-01 — Ground reference established; two distinct grounds found

**Action:** Needed a trustworthy ground reference before any voltage measurement.
Battery **disconnected** for this pass (the PMU keeps standby rails alive whenever the
battery is attached, so "powered off" is not unpowered; and a probe slip across 2.54 mm
pins is harmless only on a dead board).

**Result:**

| measurement | reading |
|---|---|
| iPod rear shell → flex pins | no continuity |
| headphone jack casing → flex pins | no continuity |
| HDD case → flex pins | beeps on several pins |
| HDD case, two points on itself | ~0 Ω |
| dock connector shell, two points on itself | ~0 Ω |
| **HDD case ↔ dock connector shell** | **300 Ω** |
| **dock shell ↔ the beeping flex pins** | **300 Ω** |
| **beeping flex pins ↔ each other** | **~0 Ω (beep)** |

Contact resistance was the first hypothesis for the 300 Ω, and was **ruled out**: both
pieces of metal measure ~0 Ω across their own surface, so the probes are making good
contact and the 300 Ω lies in the circuit.

**Interpretation — (F) this unit has two distinct grounds:**

1. **Signal ground** — the HDD case together with a set of LCD flex pins, all mutually
   ~0 Ω. This is a genuine ground net; the mutual continuity between the pins proves it
   independently of what we call the reference.
2. **Chassis / shield ground** — the dock connector shell, the rear shell and the
   headphone jack casing, bonded to signal ground through **~300 Ω**.

A resistive chassis-to-signal-ground bond is a standard EMI/ESD measure (normally with a
parallel capacitor): it gives ESD a bleed path while avoiding ground loops. The rear
shell and headphone jack read open additionally because they are anodised/coated.

**(F) Consequence for safety rule 3 — analyzer grounding.** The rule says the analyzers
and iPod must share ground. This measurement shows *which* ground: **signal ground**.
Grounding the analyzer to the dock shell or the iPod case would insert 300 Ω into the
ground return, degrading every capture and risking common-mode artifacts that would
likely be misdiagnosed as bad probe contact. **In phase 2 the analyzer ground goes to a
GND pin on the interposer header itself** — same net, shortest loop, closest to the
signals being measured.

**Reference for all subsequent measurements: the HDD case.**

**Next step:** full 34-pin resistance sweep to ground; then reconnect the battery for the
powered sweep that identifies the backlight.

---

### 2026-08-01 — Ground sweep: clear structural clustering

**Action:** Resistance from every header pin to signal ground (HDD case), battery
disconnected, both flexes connected.

**Method note:** a first pass used the meter's **continuity/beeper** mode, which reports
"OL" above roughly 50 Ω and therefore hid every distinction above that. The
resistance-range pass superseded it and is the data of record. Lesson for later sweeps:
never take beeper output where structure is expected.

**Result — pins group sharply:**

| group | pins | n | reading |
|---|---|---|---|
| GND | 3, 6, 8, 17, 31 | 5 | 0.6–1.5 Ω |
| **BL− candidate** | **5** | 1 | **25.6 Ω** |
| mid-Z | 32, 33, 34 | 3 | 70 k, 266 k, 1 M |
| sub-megohm cluster | 21, 22, 23, 24, 25, 30 | 6 | 0.5–0.6 M |
| high-Z baseline | 1, 2, 9–16, 18, 19, 20, 26–29 | 17 | 3.7–3.8 M |
| high outliers | 4, 7 | 2 | 5.4 M, 13.5 M |

**Interpretation (all (H) until the powered sweep):**

1. **(F) GND = pins 3, 6, 8, 17, 31.** Five grounds distributed along the connector,
   consistent with return-current management on a fast parallel bus.
2. **(H) The 17-pin 3.7–3.8 MΩ group is the data bus.** Identical leakage implies
   identical silicon on the far end. 18 lanes are expected, so one more is likely hiding
   among the outliers (pins 4 or 7) or in the mid-Z group.
3. **(H) The 6-pin 0.5–0.6 MΩ cluster is the control set** — WR, RD, CS, D/C, RESET, TE
   is exactly six signals. The count match is striking but is not proof.
4. **(H) Pin 5 = backlight cathode (BL−).** 25.6 Ω is far too low for a logic pull-down
   and sits exactly where an LED driver's current-sense resistor would (0.6 V feedback
   at ~20 mA ⇒ 30 Ω).
5. Budget closes exactly: 18 data + 6 control + 5 GND + BL± + ~3 power = 34.

**CAVEAT recorded in the data file:** megohm-range values are leakage through
semiconductor structures on an unpowered board, with large parasitic capacitance. The
clustering is meaningful; the absolute values are not, and may drift with measurement
order. They must not be quoted as specifications.

**Still unresolved:** a 0.6–1.5 Ω pin could be true system ground *or* a pin the panel
ties low (an ID strap would look identical). Separable by re-measuring with the display
flex disconnected — deferred, since the powered sweep is the higher-value next step.

**Next step:** powered voltage sweep — identifies the backlight anode (safety rule 1)
and VDDIO (the phase 2 gate).

---

### 2026-08-01 — Powered sweep: **backlight found**, VDDIO ≈ 1.8 V

**Action:** DC voltage on all 34 pins, iPod booted into Rockbox, idle on a static menu,
backlight on. Reference: HDD case.

**Result 1 — (F) SAFETY RULE 1 SATISFIED. Pin 4 = backlight anode (BL+), 10.7 V.**
The only pin anywhere near that voltage; everything else is ≤ ~3 V.
**Pin 4 must never be connected to an analyzer input** — the TXU0104 A-side absolute
maximum is 5.5 V, so 10.7 V would destroy the shifter, not merely misread.
10.7 V is consistent with a 3-LED white string plus driver headroom.

**Result 2 — (F) VDDIO ≈ 1.8 V.** Logic swings measured ~1.8–2.0 V (collaborator notes
the "2 V" readings are probably nearer 1.8 V), and three steady ~1.8 V rails are present
on pins 26, 30, 32. A separate steady ~3.0 V rail sits on pin 33.

**This trips the brief's phase 1 decision gate** ("if VDDIO < ~2.3 V, stop and plan level
shifting"). With these boards it is a configuration change rather than a blocker, **but
it is mandatory, not optional**:

| shifter VREF | TXU0104 VT+ max | 1.8 V logic high | verdict |
|---|---|---|---|
| `3v3` (current) | **1.92 V** @ VCCI=3 V | 1.8 V | **BELOW threshold — unreliable** |
| `EXT` @ 1.8 V | **~1.23 V** (interp.) | 1.8 V | 0.57 V margin — good |

So the switch **must** move from `3v3` to `EXT`, referenced to the panel's own 1.8 V.
Had we probed on `3v3`, a 1.8 V high would have sat below the guaranteed threshold and
produced intermittent, plausible-looking-but-wrong data.

**Result 3 — pin structure is now coherent and the budget closes:**

| group | pins | n |
|---|---|---|
| GND | 3, 6, 8, 17, 31 | 5 |
| BL+ | 4 | 1 |
| unresolved (BL− candidate) | 5 | 1 |
| rails ~1.8 V | 26, 30, 32 | 3 |
| rail ~3.0 V | 33 | 1 |
| analog/switching ~1.5 V, 80 µs ripple | 34 | 1 |
| **control, idle HIGH + pulse LOW** | 21, 27, 28, 29 | **4** |
| **bus, idle LOW + burst HIGH** | 1, 2, 10–16, 18–20, 22–25 | **16** |
| **fast cadence (~15 ms)** | 7, 9 | **2** |

16 + 2 = **18**, matching the expected 18-bit data bus. The four active-low pins are
strong candidates for /CS, /WR, /RD, /RESET (D/C would also idle in one state).
The 1 s burst cadence matches Rockbox redrawing its status bar once per second.

**(H) Pin 5 = BL−.** It is physically adjacent to pin 4 (BL+), which is how an LED
string is normally routed, and it showed 25.6 Ω to ground unpowered — right where a
current-sense resistor sits. But it read 0 V powered, where I·R across 25.6 Ω should be
visible. Needs a mV-resolution re-read with the backlight on and off; that also yields
the drive current (I = V / 25.6 Ω) for the phase 6 driver design.

**Open question:** the ~15 ms and ~80 µs cadences cannot be resolved by a multimeter.
Need to know how they were observed — an oscilloscope may be present, which would be
useful for phase 5 timing work.

**Next step:** move the shifter VREF to EXT at 1.8 V before any analyzer connection.

---

### 2026-08-01 — Shifter validated at 1.8 V; **pin 27 = /WR**; bus timing measured

**Action:** VREF switch moved to `EXT`, referenced from header pin 26 (1.8 V rail) via
the board's `VRF` pin; analyzer GND to header pin 3 (signal ground); single probe on
header pin 27. Captured at 1 MS/s, then 100 MS/s.

**Result 1 — (F) the 1.8 V probing path works.** The capture triggered and produced
clean logic. This validates the whole `EXT`-VREF arrangement before committing to 22
probe wires. Note the failure mode here is loud, not subtle: TXU0104 forces outputs
high-Z if VCCA is absent, so a bad VRF wire gives a dead channel rather than plausible
bad data.

**Result 2 — a sampling-rate trap, worth recording.** At 1 MS/s pin 27 appeared to be a
clean ~91 kHz signal: LOW runs *all* exactly 1 sample, HIGH runs *all* 10. That
regularity was used to argue the signal was **not** aliased — **which was wrong.** At
100 MS/s the true signal is **1.64 MHz**. The beat between 1.639 MHz and the 1 MS/s
sample clock re-aligns roughly every 11 samples, manufacturing the false regularity.

> **Lesson: run-length regularity is not evidence against aliasing.** Undersampling can
> produce output that looks *more* periodic than the real signal. Only a capture at a
> rate well above the suspected fundamental settles it. Applies directly to phase 2:
> the survey preset's 10 MS/s would have mis-measured this signal.

**Result 3 — (F) pin 27 = /WR, active low.** Measured at 100 MS/s:

| parameter | value |
|---|---|
| WR low width | **70–80 ns** |
| WR high width | **530–540 ns** |
| WR cycle | **610 ns** |
| write rate | **1.64 MHz** |

**Result 4 — (F) one transfer per pixel, confirmed empirically.** The 1 s burst spans
**46.92 ms**. A full frame is 320×240 = 76800 pixels; 76800 × 610 ns = **46.85 ms** — a
0.1 % match. So each 1 s burst is one complete framebuffer update, and each pixel costs
exactly **one** bus write, not two. This independently confirms the `LCD_MODE_P16`
"RGB565 / 1-transfer" claim in `lcd-s5l8702.c`, which the source itself marks "TBC", and
it retires part of deliverable #6 without any decoding.

**Result 5 — instrument inventory.** Collaborator's scope is a **Voltcraft VC-1008**
(handheld DMM with a single-channel scope). Adequate for rails, ripple and slow signals;
the logic analyzer remains primary for bus timing, and a 1.64 MHz strobe with 70 ns
pulses is at or beyond the VC-1008's comfortable range.

**Backlight (updated):** pin 5 reads 27.1 mV backlight-on / 0 mV off across 25.6 Ω ⇒
**1.06 mA average** at partial brightness. Far too low for a real backlight, so the
string is PWM-dimmed and the meter reads the duty average. A max-brightness reading is
still wanted for the phase 6 driver spec.

**Next step:** wire all 22 signal pins to LA-A and run the phase 2 survey.

---

## Phase 2/3 — first real bus decode

### 2026-08-01 — Accidental capture of `displaylcd_setup()`; 3 lanes + D/C identified

**Action:** Armed a contiguous 100 MS/s capture intending to catch the bootloader init on
a reboot. The iPod was **not** reset (no confirmation received); the capture instead
triggered on ordinary screen activity.

**Result — what we caught is better than nothing: exactly 13 writes, spanning 9.8 µs,
followed by 318 µs of silence.** 13 is the signature of `displaylcd_setup()` for a
16-bit command-set panel:

```
0x210,x  0x211,xe  0x212,y  0x213,ye  0x200,x  0x201,y  0x202
= 6 register+data pairs + 1 bare command = 13 writes
```

The 318 µs of silence afterwards is the `memcpy` of the 153 KB framebuffer into the DMA
buffer before the pixel burst begins.

**(F) Two lanes alternate perfectly and are exact complements: P15 = `1010101010101`,
P28 = `0101010101010`.** Since the sequence has 7 commands and 6 data words, the
7-count group (writes 0,2,4,…,12) must be the commands.

**(F) P28 = D/C, with 0 = command, 1 = data** (the standard 8080 convention).

**(F) Lane identification from the 7 command words**, whose values are known exactly
regardless of which screen rect was being updated:

| APB bit | signature over the 7 commands | pin |
|---|---|---|
| bit 9 | `1111111` | **P15** |
| bit 0 | `0101010` | **P25** |
| bit 1 | `0011001` | **P24** |
| bit 4 | `1111000` | **NOT FOUND** |

**(H) DEGENERACY WARNING — P15 could be bit 9 *or* an inverted D/C.** In this sequence
every command is `0x2xx` (bit 9 set) and every data word is a screen coordinate < 0x200
(bit 9 clear), so "bit 9" and "inverted D/C" have identical histories here.
**This resolves itself in the init sequence**, where data values such as `0x0808`,
`0x17b0` and `0x03ff` exceed 0x200 and therefore set bit 9 on *data* writes, breaking
the tie. Do not treat P15 as settled until then.

**(F) ANOMALY: the bit-4 lane is not in the probe set.** Bit 4 is 1 for `0x210`–`0x213`
and 0 for `0x200`–`0x202`, so a lane carrying it must show `1111000` across the command
writes. No probed pin does; every other probed pin reads 0 throughout the commands,
which is *correct* for bits 2,3,5–8,10–15 (all zero in these seven words), so the other
silent lanes are legitimately silent. Exactly one lane is unaccounted for.

**Leading hypothesis:** one of pins **26, 30, 32** — classified as "steady ~1.8 V rails"
from the DMM sweep — is actually a **data lane that is high most of the time**. Write
bursts occupy only ~4.7 % of wall time (46.9 ms per 1 s), so a mostly-high data lane
averages ≈1.7–1.8 V on a multimeter and is indistinguishable from a rail. Pin 33 reads
3.0 V and is too high for 1.8 V logic, so it remains a genuine rail.

**Complication:** pin 26 is currently feeding the shifter's `VRF` reference. If pin 26 is
the missing lane, the threshold reference is a toggling signal. Captures look clean,
which argues against it, but it cannot be ruled out without testing.

**Next step:** two spare analyzer channels are available (22 of 24 used). Probe pins 30
and 32 and re-capture; look for the `1111000` command signature.
