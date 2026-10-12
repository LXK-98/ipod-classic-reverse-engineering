# Lab notebook

Full chronological log of the investigation, **including the wrong turns** — several
findings only make sense alongside the hypotheses they replaced.

For the distilled results see [FINDINGS.md](FINDINGS.md), [PROTOCOL.md](PROTOCOL.md) and
[../PINOUT.md](../PINOUT.md). For what is still unresolved see
[OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

**Notation:** **F** = verified fact · **H** = hypothesis · **E** = estimate, not measured.

> Note: entries dated 2026-07-26 were written during setup; bench work is dated
> 2026-08-01. Some early conclusions are corrected by later entries — corrections are
> marked in place rather than edited out.

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

### 2026-08-01 — Cold-boot capture fails by construction: VREF dies with the target

**Action:** Armed a 24-channel capture with the iPod powered OFF, intending to catch the
bootloader init on power-up.

**Result:** all 24 channels read **flat 0 for the entire 32767-sample capture**, and the
trigger fired immediately rather than on a real write.

**(F) Root cause — a setup error, not a hardware fault.** The shifter's `VRF` reference
is wired to header pin 26, which is *the iPod's own 1.8 V rail*. With the iPod off:

1. VCCA collapses to 0 V.
2. The TXU0104 `Ioff-float` feature (datasheet: "if either VCC input is <100 mV or
   disconnected, all outputs are disabled and become high-impedance") forces every
   output high-Z, so all channels read 0.
3. That collapse looks like a falling edge on /WR and satisfies the trigger immediately.

**The reference cannot be derived from the device being powered up.** Arming before a
cold boot is incompatible with referencing VREF to the target's rail. Note the failure
was at least *loud*: 24 identically dead channels is unmistakable, not plausible-looking
wrong data — which is the property we wanted from the `EXT`-VREF arrangement.

**(F) Fix: use the sleep/wake trigger instead of a cold boot.** Rockbox has
`lcd_sleep_after_backlight_off` (`apps/settings_list.c:2075`, guarded by
`HAVE_LCD_SLEEP_SETTING`, which ipod6g defines), surfaced in the UI as
"Sleep (After Backlight Off)". With the LCD asleep and the iPod still running, the rails
stay up and VREF stays valid; waking the display replays a **full init** because type 2
sets `seq_awake = lcd_init_seq_23`. Target is then the *firmware* variant: **152 writes**
including the leading 6× `CMD 0x0000` + 1.28 ms delays, which is itself an unmistakable
capture signature.

**Residual risk:** if the panel's 1.8 V rail also drops during LCD sleep, VREF collapses
again and we get the same all-zero symptom. Cheap pre-check: measure pin 26 with the DMM
while the display is asleep. **Fallback if it does drop:** derive VREF from the analyzer's
own 3v3 through a divider (~12 k / 10 k gives 1.8 V; VCCA draws only microamps), making
the reference independent of the iPod entirely.

### 2026-08-01 — **LANE MAP SOLVED** from the wake init; wiring faults isolated

**Action:** Captured the LCD wake sequence with 7 bursts and matched the result against
`lcd_init_seq_23` (firmware variant) from `refs/sequences.json`.

**Result — the burst structure came out exactly as designed:** bursts 1–6 contained
**one write each** (the six NOPs, 1.28 ms apart) and burst 7 contained **69 consecutive
writes** (the register block). This proves the capture began at the true first
instruction of `seq_awake`, so the alignment anchor is sound.

**(F) Ten data lanes, D/C and /WR matched EXACTLY over 69 writes.** A false match at
that length has probability 2^-69, so these are certain:

| bit | pin | bit | pin | signal | pin |
|---|---|---|---|---|---|
| 0 | 25 | 9 | 15 | **/WR** | **27** |
| 1 | 24 | 10 | 14 | **D/C** | **28** |
| 2 | 23 | 11 | 13 | | |
| 7 | 18 | 12 | 12 | | |
| 8 | 16 | 13 | 11 | | |

**(F) D/C polarity: 0 = command, 1 = data** (standard 8080 convention).

**(F) P15 degeneracy resolved — it is genuinely bit 9.** The register block writes data
values ≥ 0x200 (`0x0808`, `0x2402`, `0x1c04`), and P15 followed them on data cycles. Had
it been an inverted D/C it would have stayed low on every data write. The ambiguity
flagged in the previous entry is closed.

**(F) The lane map follows a simple monotonic rule.** Every confirmed assignment fits:

```
pin  25 24 23 [22 21 20 19] 18 (17=GND) 16 15 14 13 12 11 [10  9]
bit   0  1  2 [ 3  4  5  6]  7           8  9 10 11 12 13 [14 15]
```

flex pin -> APB bit descends monotonically, **skipping the GND pins (17 and 8)**. Ten of
ten confirmed lanes obey it. The bracketed pins are exactly those reading constant 0.

**(F) TWO WIRING FAULTS, not measurement problems:**

1. **P09 and P14 are byte-identical across all 69 writes.** Two probes are reading the
   same header pin. The model says pin 14 = bit 10 and pin 9 = bit 15, so CH4 (pin 9) has
   almost certainly landed on pin 14. Pin 9 is therefore unprobed.
2. **Pins 20, 21, 22 read constant 0 but must toggle** — they carry bits 5, 4 and 3,
   which have 1, 22 and 14 ones respectively in this sequence. Their probes are not
   making contact.

Pins 19 and 10 (bits 6 and 14) are **unverifiable from this capture** because bits 6, 14
and 15 are constant zero throughout `lcd_init_seq_23` — the limitation predicted from
ground truth before any hardware was touched. Colour fills remain required for those.

**(H) P02 reads 2 ones in 69 writes and matches nothing** — most likely a marginal
contact on one of the two unused lanes (D0/D9 are idle in `LCD_MODE_P16`), or an
intermittent probe. Low priority.

**Next step:** reseat the probes on pins 9, 19, 20, 21, 22 (channels CH4, CH13–CH16) and
re-capture the wake sequence to confirm bits 3, 4, 5 and 15.

### 2026-08-01 — Reseat changes nothing: fault is in the probe path, not the interposer

**Action:** Re-captured the wake sequence after the collaborator pressed the probe wires
home (no wires were moved).

**Result: bit-identical outcome.** Burst structure again `[1,1,1,1,1,1,68]`, the same 10
lanes matched exactly, P09 still byte-identical to P14, and pins 20/21/22 still constant
zero. Fully reproducible, which rules out intermittent contact.

**(F) The signals ARE present at the header.** The powered DMM sweep of 2026-08-01
recorded pins 19, 20, 21, 22 as "~2 V spikes every 1 s" — i.e. live, toggling signals.
The interposer therefore delivers them correctly and the break lies **between the header
and the analyzer**: probe wire, shifter channel, or analyzer input.

**(H) Strong structural hypothesis: one dead TXU0104.** The TXU0104 is a **4-bit**
translator and the shifter board carries **six** of them for 24 channels, so channels are
almost certainly grouped CH1–4, CH5–8, CH9–12, **CH13–16**, CH17–20, CH21–24.
The four failing channels are **CH13, CH14, CH15, CH16 — exactly one group**. A single
device with an unsoldered VCCA, VCCB or GND pin gives precisely this signature, and the
`Ioff-float` behaviour (outputs high-Z when a VCC is missing) explains why they read a
clean constant 0 rather than noise.

Note CH13 (pin 19, bit 6) cannot be distinguished from a working channel here, since bit
6 is constant zero throughout the sequence — but it is in the same group and presumed
equally affected.

**Channels proven good** (exact ground-truth matches): CH6–CH12, CH17–CH21. That covers
the CH5–8, CH9–12 and CH17–20 groups plus CH21.

**(H) P09 ≡ P14 remains unexplained and does NOT fit the dead-group theory** (CH4 is in
the CH1–4 group, and a dead channel would read constant, not mirror another channel's
68-bit history). Two candidate explanations remain: the CH4 wire physically terminates on
header pin 14, or header pins 9 and 14 are shorted. A short between the two *nets* is
argued against by the data: pin 14 carries bit 10, which toggles heavily, and it matches
ground truth **exactly** — bus contention with another driver would corrupt it.

**Next step:** two cheap discriminating tests — a channel-swap to localise the CH13–16
fault, and a DMM continuity check between header pins 9 and 14.

### 2026-08-01 — Swap test: **dead TXU0104 confirmed**, predicted lane map validated

**Action:** Moved the pin-21 probe from `CH15` to `CH17` (a channel already proven good,
previously carrying pin 23 / bit 2 — safe to borrow since bit 2 is confirmed).

**Result — unambiguous:**

| observation | value |
|---|---|
| pin 21 on CH17 vs expected bit 4 | **exact match, 21/68 ones** |
| `NC15` (deliberately unconnected) | **0/68 ones** |
| regression: P24/P25/P28 | still bit 1 / bit 0 / D/C ✓ |

**(F) One TXU0104 on the shifter board is dead.** Pin 21 carries a perfectly good signal;
it simply does not reach the analyzer through `CH15`. Combined with CH13/14/16 failing
identically, and the TXU0104 being a 4-bit part with CH13–16 forming exactly one group,
the fault is a single translator — most likely an unsoldered VCCA/VCCB/GND pin. The
`Ioff-float` behaviour explains the clean constant 0.

**(F) pin 21 = APB bit 4, CONFIRMED.** This was a *prediction* from the monotonic
pin→bit rule, and it verified exactly. The rule now has 11 confirmed instances and zero
exceptions, which materially strengthens the remaining predictions (pins 22, 20, 19, 10,
9 → bits 3, 5, 6, 14, 15).

**(F) A floating channel reads constant 0, it does not mirror a neighbour.** The
accidentally-unconnected `CH15` provided a free control: 0 ones in 68 writes. This
**eliminates crosstalk/floating-input as the explanation for P09 ≡ P14** — CH4 is
genuinely receiving pin 14's signal, so either the wire terminates there or the two
header pins are shorted. DMM continuity between pins 9 and 14 remains the test.

**Method note worth keeping:** borrowing an already-confirmed channel to test a suspect
pin is cheap and non-destructive, and it cleanly separates "signal missing at the pin"
from "channel not reading". No rework was needed to localise a hardware fault.

### 2026-08-01 — LA-B: bits 3 and 5 confirmed; **both analyzers have a dead TXU0104**

**Action:** Swapped to LA-B (serial `5033592712586E1F`), full 24-channel wiring restored,
VREF switch on `EXT`, re-ran the wake-init capture.

**Result 1 — (F) bits 3 and 5 confirmed.** P22 = bit 3 and P20 = bit 5 matched exactly.
Together with pin 21 = bit 4 this closes the set: **every bit the init sequence is capable
of exercising (0,1,2,3,4,5,7,8,9,10,11,12,13) is now confirmed**, and the dead-CH13-16
diagnosis for LA-A is fully vindicated.

**Result 2 — (F) LA-B has its own dead group: CH21-CH24.** P28 (D/C) now reads constant
0, as do P29, P30 and P32. Decisive detail: P30 and P32 read constant **1** on LA-A and
constant **0** here — a dead channel, not a changed signal.

| board | serial | dead group | good channels |
|---|---|---|---|
| LA-A | `5033592792565F9F` | CH13-16 | CH1-12, CH17-24 |
| LA-B | `5033592712586E1F` | CH21-24 | **CH1-20** |

Each board has exactly one bad 4-bit translator, in different positions. Neither loss is
blocking: 20 good channels on either board covers 18 data + /WR + D/C.

No information was lost by D/C dropping out — it was already confirmed on LA-A, and the
sequence alignment comes from the burst structure (6 single-write bursts = the NOP
prefix), not from D/C.

**(F) P09 ≡ P14 PERSISTS on a different analyzer with independently re-run wiring.** Two
separate wirings on two boards producing byte-identical 68-write histories makes a
one-off probe misplacement unlikely, though not impossible if the same counting error was
repeated. Still unexplained, still not blocking. The DMM continuity check between header
pins 9 and 14 remains the decisive test.

**Remaining for the lane map:** bits **6, 14, 15** (predicted pins 19, 10, 9). These are
constant zero throughout `lcd_init_seq_23` and can never be resolved by init capture —
exactly as predicted from the Rockbox source before any hardware was connected. Solid
colour fills are the only route.

### 2026-08-01 — Analyzer repaired: OE cold joint, no chip replacement needed

**Action:** Traced the dead 4-channel groups to a specific pin rather than replacing parts.

**Diagnostic chain:**
1. Supplies measured good — 3.3 V across every decoupling cap on both boards — which
   ruled out the initial "unsoldered VCC" theory. (The apparent polarity flip between
   each cap pair is layout mirroring: one decouples VCCA, the other VCCB.)
2. **A single pin can disable all four channels at once: `OE`.** TXU0104 is active-high
   output-enable; floating or grounded OE puts all four outputs in high-Z, which reads as
   a clean constant 0. That is exactly the observed signature.
3. Netlist showed each TXU0104 touches only 11 distinct nets, so **OE is tied to a supply
   rail** (`POWER_3v3`) — a cold joint there leaves it floating.
4. Datasheet pinout (PW/TSSOP-14): **OE = pin 8, adjacent to GND = pin 7**, both at the
   same end of the package — the corner a drag-solder pass most easily skimps.
5. PCB geometry: all six devices rotated -90 deg, so **pin 8 is the top-left corner pin**
   (header side, upper), and it shares net `POWER_3v3` with pin 14 at bottom-left —
   giving a trivial continuity test between two pins on the same edge.

**(F) Reflowing fixed it.** Post-reflow capture of ordinary screen activity:
P28 (D/C) 160 edges, P29 173 edges — both alive. P30 and P32 now read **constant 1**,
matching what LA-A reported for those same pins when its CH21-24 group was healthy. A
dead channel floats to 0; constant 1 is their genuine idle state. **LA-B now has all 24
channels working.**

**(F) Chip-to-channel map for LogicAnalyzer V2** (from
`Electronics/LogicAnalyzer/LogicAnalyzerV2/designs/jitx-design/kicad`), physical order
**top to bottom** — note it is NOT sequential, so identifying a chip by eye would mislead:

| position | ref | channels | flanking caps |
|---|---|---|---|
| 1 | U1 | CH1-4 | C1, C7 |
| 2 | **U4** | **CH21-24** | C4, C10 |
| 3 | U6 | CH5-8 | C6, C12 |
| 4 | U5 | CH17-20 | C5, C11 |
| 5 | U3 | CH9-12 | C3, C9 |
| 6 | **U2** | **CH13-16** | C2, C8 |

LA-A's fault is U2 (bottom), LA-B's was U4 (2nd from top). Board A remains unrepaired
and still has CH13-16 dead; the same reflow should fix it.

**Method note:** the "dead group of exactly 4 contiguous channels" signature is worth
remembering — it points at a whole translator, and because OE gates all four outputs, a
single joint explains it. Supplies reading correct does *not* exonerate the device.

### 2026-08-01 — Colour fills: bits 6 confirmed, **bit 10 anomaly is real**

**Action:** Used Rockbox's `lamp` plugin (solid-colour flashlight) for known fills. Its
palette is hard-coded in `apps/plugins/lamp.c`, so expected bus words are exact.

**Result — the window-setup commands decode byte-perfectly on every fill:**
`0x210/0x0000, 0x211/0x013F, 0x212/0x0000, 0x213/0x00EF, 0x200/0x0000, 0x201/0x0000,
0x202` — a full-screen 320x240 window, exactly as `displaylcd_setup()` should emit.

**(F) bit 6 = pin 19 CONFIRMED.** `0x00EF` (= 239 = vertical end for a 240-row panel) has
bit 6 set and decoded exactly. Re-running with `--no-predicted` yields `0x00AF`, the wrong
value — so including pin 19 as bit 6 is precisely what makes the known parameter correct.

**(F) Pixel fills:**

| fill | expected | observed | delta |
|---|---|---|---|
| blue | `0x001F` | `0x001F` | **exact** |
| red | `0xF800` | `0xFC00` | bit 10 only |
| green | `0x07E0` | `0x03E0` | bit 10 only |

**(F) The bit-10 error is real, not a mis-set colour.** No lamp palette entry produces
`0xFC00` or `0x03E0`. Both errors are a single bit, the same bit, in opposite directions
(red: reads 1, should be 0; green: reads 0, should be 1).

**(F) Pin 14 takes pin 9's value.** In every capture P09 == P14 byte-for-byte. Red has
bit15=1/bit10=0 and both read 1; green has bit15=0/bit10=1 and both read 0. Note that
**red and green are the ONLY two colours in the lamp palette where bit 15 and bit 10
differ** — white/yellow/orange/violet have both set, blue/indigo/black both clear. The
two discriminating cases both fail the same way.

**CONTRADICTION that remains unexplained.** A simple short between pins 9 and 14, with
bit 15 winning contention, fits both fills — but it cannot fit the init capture, where
bit 15 is constant 0 while bit 10 varies, and P09/P14 tracked **bit 10** exactly across 68
writes. A short cannot win contention in frame mode and lose it in command mode.

One structural difference between the two modes is documented in `lcd-s5l8702.c` and may
be relevant: command mode uses `LCD_MODE_P18` while frame mode uses `LCD_MODE_P16` with
`APB[15:0] -> D[17:10, 8:1]`, i.e. **two physical lanes (D9, D0) are unused during pixel
writes**. Whether the APB-bit-to-physical-lane mapping differs between the modes is
explicitly marked "TBC" in the Rockbox source. Simple relabelling models were tried
against the blue fill and do not fit, so this is not yet an explanation - only a lead.

**Status of the lane map:** bits 0-9 and 11-13 are confirmed against three independent
stimuli (init sequence, window-setup commands, colour fills). Bit 6 confirmed. **Bits 10,
14 and 15 are NOT settled** and must not be treated as final.

**Outstanding test, never yet performed:** DMM continuity between header pins 9 and 14
with the iPod powered off.

### 2026-08-01 — **The bus is RGB666, not RGB565.** Bit-10 "anomaly" was my error

**Action:** Pins 9 and 14 measured **6.66 MOhm** apart (open, not shorted) and the
collaborator confirmed CH4->pin 9 and CH9->pin 14 are wired correctly. That eliminated
every hardware explanation, so the frame-mode mapping was solved empirically from the
three known lamp fills instead of assumed.

**(F) The data bus carries RGB666 - 18 lanes, 6 bits per colour channel.** Red, green and
blue fills partition the lanes into three disjoint groups of **six**:

| field | pins |
|---|---|
| RED | 9, 10, 11, 12, 13, 14 |
| GREEN | 1, 15, 16, 18, 19, 20 |
| BLUE | 2, 21, 22, 23, 24, 25 |

Six per channel, not 5/6/5. A saturated channel drives all six of its lanes high.

**CORRECTION — the "bit 10 anomaly" was my analysis error, not a fault.** I had assumed
the bus carried raw RGB565 on 16 lanes and decoded pixels with the command-mode bit map.
It does not: Rockbox's RGB565 framebuffer is **expanded by the SoC into RGB666** before
reaching the flex. Decoding pixel writes with a 16-bit command-mode map is simply the
wrong model, and it manufactured a one-bit discrepancy in exactly the two fills
(red, green) where the fields disagree. No hardware is faulty.

**(F) P09 == P14 is explained and expected.** Expanding a 5-bit RGB565 channel to 6 lanes
requires replicating one bit onto two lanes, so two lanes of that channel are permanently
identical. Verified against the prediction:

| field | expansion needed | duplicate pair predicted | found |
|---|---|---|---|
| RED (5-bit in 565) | yes | 1 | **(P09, P14)** ✓ |
| GREEN (already 6-bit) | no | 0 | **none** ✓ |
| BLUE (5-bit in 565) | yes | 1 | **none** ✗ |

Red and green match the model exactly. **Blue does not**, so the expansion is not
symmetric between red and blue and the model is incomplete.

**This bears on deliverable #6 and partially contradicts the Rockbox source.**
`lcd-s5l8702.c` documents frame mode as `APB[15:0] -> D[17:10, 8:1]` and marks it "TBC" -
that mapping would leave D9 and D0 undriven and give 5/6/5-shaped behaviour. What we
measure is 6/6/6 with all lanes driven, so the real hardware does a genuine 5->6
expansion rather than a bit-shuffle. This is the "TBC" the Rockbox authors left open.

**Still open:** why blue lacks a duplicate pair, and P02's role (blue-field in the fills
but only 2 ones across the 69-write init).

**Note on the command-mode map:** the pin->APB-bit assignments confirmed from the init
sequence remain valid **for 16-bit register/command writes**. They are simply not the
right model for pixel writes.

### 2026-08-01 — White fill closes the 18-lane inventory

**Action:** White (`0xFFFF`) fill via the lamp plugin.

**Result — (F) all 18 data lanes driven high, 6/6/6:**

```
RED   : 9 10 11 12 13 14   -> 6/6 high
GREEN : 1 15 16 18 19 20   -> 6/6 high
BLUE  : 2 21 22 23 24 25   -> 6/6 high
```

P02 included, which resolves the pin flagged as doubtful (blue-field in the fills but
almost inert during the init). **The RGB666 lane inventory is now confirmed in both
states** - every lane observed high on white and low on black/other fills.

**(F) The four non-data pins did not follow the pixel data**: `P07=0, P29=0, P30=1,
P32=1`, identical across every fill. They are not part of the data bus.

**Pin accounting - 32 of 34 assigned:**

| function | pins | n |
|---|---|---|
| GND | 3, 6, 8, 17, 31 | 5 |
| Backlight | 4 (BL+), 5 (BL-) | 2 |
| Data bus (RGB666) | 1, 2, 9-16, 18-25 | 18 |
| /WR | 27 | 1 |
| D/C | 28 | 1 |
| rails / control (ambiguous) | 26, 30, 32, 33 | 4 |
| analog | 34 | 1 |
| **unassigned** | **7, 29** | **2** |

**(H) The "rails" classification for pins 30 and 32 is probably wrong.** Four control
signals remain to place (/CS, /RD, /RESET, TE) but only two unassigned pins. An
**idle-high control line reads a steady 1.8 V on a DMM and is indistinguishable from a
supply rail** - which is exactly how pins 30 and 32 were classified. Pins 26 (VDDIO,
currently feeding VREF) and 33 (3.0 V) remain genuine rail candidates.

**(H) Pin 7 = TE.** The original powered DMM sweep recorded pin 7 as "~2 V spikes every
~15 ms" = ~66 Hz, which is a panel refresh rate, not bus traffic. TE is the only expected
signal at that frequency. Pin 29, constant low throughout every write burst, fits **/CS**
held asserted for the duration of a transfer.

**Why these are invisible in the current captures:** every capture so far is a ~325 us
window taken *inside* a write burst. /CS stays asserted for the whole burst, /RESET and
/RD never move during normal operation, and TE at 66 Hz has a 15 ms period - all four are
constant on that timescale by construction.

**Next step:** a slow, wide capture (~100-200 kS/s over 150-300 ms) to see the /CS
envelope between bursts and resolve TE's period. Aliasing of /WR is irrelevant there
since only the slow signals matter - but the lesson from the 1 MS/s trap applies: do not
read any fast-signal statistics off that capture.

### 2026-08-01 — **PINOUT COMPLETE.** TE and /CS identified; all 34 pins assigned

**Action:** Slow wide capture, 200 kS/s over 163.8 ms, to expose signals that are
constant by construction inside a ~325 us burst window.

**(F) Pin 7 = TE (tearing effect).** 60 us pulse every **14.72 ms = 67.9 Hz** — one
narrow pulse per frame at the panel refresh rate. This also retro-explains the very first
powered DMM sweep, which recorded pin 7 as "~2 V spikes every ~15 ms".

**(F) Pin 29 = /CS.** Idles high (85.7 % duty over the window), pulled low in long
envelopes that frame the write bursts.

**(F) Pins 30 and 32 = /RD and /RESET** (which is which undetermined), by elimination:

```
34 = 5 GND + 2 backlight + 18 data + /WR + D/C + TE + /CS
     + 1.8 V rail (26) + 3.0 V rail (33) + analog (34) + [30, 32]
```

Pin 26 is a genuine rail (it fed the shifter VREF stably all session) and pin 33 is 3.0 V,
outside the 1.8 V logic domain. Neither 30 nor 32 ever toggles, which is *expected*:
Rockbox never issues a read (`S5L_LCD_WITH_READID` undefined for ipod6g) and /RESET moves
only at power-on. Separating them needs a cold-boot capture, which in turn needs VREF
derived independently of the iPod (see the earlier divider note).

**As predicted, /WR aliased to a meaningless "18 kHz" at 200 kS/s** and was ignored. The
constraint was written into the capture's sidecar note before the capture ran.

**Deliverable #1 complete: all 34 pins assigned.** 28 high confidence, 5 medium, 1 low.
`PINOUT.md` is generated from `pinout.json` by `tools/report.py` and must not be
hand-edited.

**Remaining low-confidence item:** pin 34, ~1.5 V with ~100 mV ripple at ~80 us
(12.5 kHz) — a switching or bias node rather than logic, still unidentified.

### 2026-08-01 — Frame reconstruction validates the protocol end to end

**Action:** Wrote `tools/frame2png.py`, which recovers the update rectangle from the
window-setup commands (`0x210`-`0x213`), decodes pixel writes as RGB666, and renders a
PNG with the stdlib only.

**(F) The decoder reproduces the lamp plugin's colours exactly:**

| fill | decoded RGB666 | RGB888 | expected |
|---|---|---|---|
| red | (63,0,0) | (255,0,0) | (255,0,0) |
| green | (0,63,0) | (0,255,0) | (0,255,0) |
| blue | (0,0,63) | (0,0,255) | (0,0,255) |
| white | (63,63,63) | (255,255,255) | (255,255,255) |

Byte-exact on all four. This validates, in one step, the pin assignment, the RGB666 field
mapping, the /WR rising-edge latch and the D/C polarity — by reconstruction rather than
by pattern matching, so it is an independent check of the whole chain.

**(F) A full frame cannot be captured with this hardware.** 76800 px x 610 ns = 46.9 ms;
catching a 70-80 ns /WR low needs >= 20 MS/s (a pulse longer than the sample period
guarantees at least one sample inside it), so ~940k samples are required against a
131,071-sample maximum. **Short by roughly 7x.** Partial capture is unaffected: the
window commands give the true rectangle, and the renderer lays down as many rows as were
captured.

Practical options:
- 24 ch @ 20 MS/s, 32767 samples -> ~2700 px = ~8 rows of 320, full 18-bit colour, no rewiring.
- 8 ch (/WR + 7 lanes on CH1-8) @ 20 MS/s, 131071 samples -> ~10700 px = ~33 rows, ~2 bits/colour.

### 2026-08-01 — **P09==P14 SOLVED.** Bit order within fields; 5->6 expansion rule

**Trigger for the correction:** collaborator reported the top of the screen is **grey**,
but our reconstruction decoded it as green RGB(48,145,24). Saturated fills cannot detect a
wrong bit order *within* a colour field — every lane is high, so any ordering agrees. The
ordering had been **assumed** (pin order = MSB..LSB), never measured.

**Action:** captured the lamp plugin's **indigo** (75,0,130), whose channels are
deliberately non-saturated: R5=9=`01001`, G6=0, B5=16=`10000`.

**(F) Both non-green channels showed one MORE high lane than the 5-bit source has.**
That is the RGB565->RGB666 expansion **replicating the MSB into the LSB**:

```
6bit = (5bit << 1) | (5bit >> 4)
```

**(F) Field orderings, MSB -> LSB:**

| field | order | note |
|---|---|---|
| RED | P09 P10 P11 P12 P13 **P14** | **P14 is a hardware replica of P09** |
| BLUE | P21 P22 P23 P24 P25 **P02** | **P02 is a hardware replica of P21** |
| GREEN | P01 P15 P16 P18 P19 P20 | order still **unverified** |

**(F) THIS RESOLVES P09 == P14.** The two pins are byte-identical in every capture, sit
6.66 MOhm apart, and are correctly wired — because **P14 carries a hardware copy of P09**,
the replicated red MSB. It was never a short, never a probe error, and never a bus fault.
Every earlier hypothesis (solder bridge, miswire, crosstalk, contention) was wrong.

It also explains the contradiction that blocked progress for hours: in **command** mode
P14 carries APB bit 10, while in **frame** mode it carries the replicated red MSB. Same
pin, two different signals depending on the SoC's output mode - which is exactly why it
matched bit 10 across 68 init writes yet tracked the red MSB in the colour fills.

And it explains why blue appeared to lack a duplicate pair: the partner is **P02**, which
had been mis-filed as the blue MSB rather than the replicated LSB.

**Verified against every capture:** red 63/63, green 0/0, blue 63/63, white 63/63,
indigo R 18/18 and B 33/33, and the grey menu top giving R == B == 12 as grey requires.
Indigo is the load-bearing case - its asymmetric patterns would have exposed a wrong order.

**Still open:** the GREEN field's internal order. Green needs no expansion (already 6-bit),
so no replica identifies it. The lamp's **violet** (238,130,238) has G6=32=`100000` -
exactly one green lane high - which identifies the green MSB with no inference.

### 2026-08-01 — **PIXEL PATH COMPLETE.** All three field orderings measured

**Action:** Resolved the last two green lanes using colours chosen to isolate single bits.
Rockbox's colour picker works in **RGB565 units directly** (R 0-31, G 0-63, B 0-31), so a
target value can be dialled in without conversion.

**(F) GREEN field order, MSB -> LSB: P15 P16 P01 P18 P19 P20**

| position | pin | evidence |
|---|---|---|
| 5 (MSB) | P15 | violet, G6=32=`100000` - only P15 high |
| 4 | P16 | custom R0 G16 B0, G6=16=`010000` - only P16 high |
| 3 | P01 | orange, G6=41=`101001` - P15/P01/P20 high |
| 2 | P18 | grey status bar, G6=12=`001100` - P01/P18 high |
| 1 | P19 | by elimination |
| 0 (LSB) | P20 | orange, same capture |

**(F) Complete pixel path, verified against nine captures:**

```
RED   = P09 P10 P11 P12 P13 P14      P14 = hardware replica of P09
GREEN = P15 P16 P01 P18 P19 P20      no replica (already 6-bit)
BLUE  = P21 P22 P23 P24 P25 P02      P02 = hardware replica of P21
        6bit = (5bit << 1) | (5bit >> 4)
```

red 63/63, green 63/63, blue 63/63, white OK, **indigo 18/18 & 33/33**, **violet 59/59 &
32/32 & 59/59**, **orange 63/63 & 41/41**, G=16 16/16 - and the grey status bar decodes to
**R = G = B = 12 = RGB888(48,48,48)**, neutral grey, matching what is physically on screen.
The three asymmetric colours are load-bearing: a wrong ordering would light the wrong lanes.

**Method note that cost several hours:** saturated fills **cannot** validate bit order
within a colour field - every lane is high, so any permutation agrees. Only non-saturated
values discriminate. The error surfaced solely because the collaborator compared the
rendered image against the actual screen and said "it's grey, not green". **Reconstruction
checked against reality caught what nine byte-exact protocol matches could not.**

**Also useful:** row 0 is the status bar, which keeps its own colour independent of the
theme background - and burst mode always starts at the first pixel of a frame, so every
burst capture lands there. That is why background-colour changes never appeared until the
status bar itself was recoloured.

### 2026-08-01 — Backlight fully characterised

**Action:** Read pin 5 (BL-) across the 25.6 Ohm sense resistor at both brightness extremes.

| brightness | pin 5 | current | note |
|---|---|---|---|
| 63 (max) | **500 mV, flat** | **19.53 mA** | no ripple => 100% duty, so this is the true DC LED current |
| 7 | 27.1 mV | 1.06 mA avg | ~5.4% duty; same peak current |

**(F) Dimming is PWM at constant peak current (~19.5 mA).** The "flat" reading at maximum
confirms 100% duty there, which retro-validates the earlier PWM hypothesis: the 1.06 mA
was a duty-cycle average, not a lower drive current. Colour temperature is therefore
constant across the brightness range.

**(F) The brightness curve is non-linear.** Setting 7 of 63 gives ~5.4% duty where a
linear map would give 11.1% - roughly a gamma of 1.3, i.e. perceptual scaling.

**(F) LED string: approximately 3 white LEDs in series.** 10.7 V at the anode less the
0.5 V developed across the 25.6 Ohm sense resistor leaves ~10.2 V across the string; white
LEDs drop ~3.2-3.4 V each.

**Phase 6 driver spec:** constant-current boost, **~20 mA** into a **~10.2 V** string
(allow >= 11 V compliance), with PWM dimming. Deliverable #3 is now complete in the detail
a driver design actually needs.

**Minor open item:** the 10.7 V anode figure was taken at low brightness. Forward voltage
rises slightly with current, so at 19.5 mA the anode may sit a few hundred mV higher -
worth a re-read at brightness 63 before finalising the boost converter's headroom.

### 2026-08-01 — Backlight anode re-read at full brightness: **4 LEDs, not 3**

**Action:** Re-read pin 4 at brightness 63, the open item flagged in the previous entry.

**Result: 12.76 V** (against 10.7 V at brightness 7).

**(F) CORRECTION - the string is 4 white LEDs, not 3.** At 19.5 mA:
12.76 V - 0.50 V across the sense resistor = **12.26 V across the LEDs**.

| string | V per LED | verdict |
|---|---|---|
| 3 LEDs | 4.09 V | out of range for white LEDs |
| **4 LEDs** | **3.07 V** | textbook Vf at 20 mA |

The earlier 3-LED estimate used the 10.7 V figure taken at brightness 7, where the string
runs at ~5 % duty and the boost converter is far more lightly loaded. **Deriving a
component count from a measurement taken at the wrong operating point produced a wrong
answer** - the re-read was flagged as an open item for exactly this reason and was worth
doing.

**(F) The PWM switches the low side.** At ~5 % duty the anode still sits at 10.7 V rather
than collapsing toward zero, so dimming is done by the cathode-side current sink while the
boost rail stays up between pulses.

**Corrected phase 6 driver spec:** constant-current boost, **~20 mA** into a **4-LED
string**, output reaching **12.8 V under load** - design for **>= 14 V compliance** with
headroom. PWM the low side for dimming.

**Safety note updated:** pin 4 reaches **12.76 V**, not 10.7 V. Still far above the
TXU0104's 5.5 V A-side maximum; the prohibition is unchanged but the margin is worse.

### 2026-08-02 — Pin 34 resolved; /RESET not asserted on a warm reboot

**Pin 34 — (F) an analog reference INPUT to the panel, ~1.54 V, supplied by the logic
board.** With the display flex disconnected the board still holds it at ~1.54 V, so the
panel receives it rather than generating it. A replacement driver must supply it.

**(F) CORRECTION — all previously reported activity on pin 34 was charger noise.** The
"~80 us square wave", the "~12.5 kHz ripple", a 125 Hz frequency readout and bursts of
ringing all vanish on battery power and return when the USB charger is connected. The pin
carries no signal. The tell, missed at the time: **the apparent period changed with the
timebase it was viewed at** - 80 us, then ~13 ms, then ~8 ms. A real signal does not do
that. Lesson: take analog measurements on battery.

**(F) Neither pin 30 nor pin 32 pulses during a Menu+Select soft reset.** Both were armed
on a falling edge across a 32.7 ms window with 8 ms pre-trigger, and neither triggered.

Interpretation: **the panel's reset line is not asserted on a warm reboot.** The SoC
restarts and the bootloader re-runs the LCD init, but the reset GPIO is evidently left
high throughout - reset is asserted only at cold power-on, most likely by the PMU during
rail sequencing.

This is useful in its own right: **a replacement driver cannot rely on a warm reset to
initialise the panel and must drive the reset line itself at power-up.**

It also means separating /RD from /RESET still requires a genuine cold boot, and therefore
a VREF source independent of the target.

**(F) A resistive divider will NOT work as that VREF source.** Attempting one gave
**0.60 V** - a silicon junction drop, not a divider ratio - with ~270 uA flowing through a
single 10k from 3v3. With the iPod powered down, the TXU0104 A-side inputs are clamped to
a dead board and the chips' internal ESD structures present roughly a 2.9 kOhm load on
VCCA. The load appears in precisely the condition the divider is needed for. A **stiff**
source is required: an LDO, or a shunt reference (series diodes / a red LED) that can
actually sink current.

### 2026-08-02 — VREF at 3v3 fails, and fails QUIETLY

**Action:** Tested whether the shifter could run with its reference switch on `3v3`
(independent of the iPod, which would solve the cold-boot VREF problem) by capturing
known bus traffic with the iPod running.

**Result — (F) it does not work.** 18 of 24 channels read **constant 0 with zero edges**;
the entire data bus is unreadable. Only /WR, D/C, /CS and pins 30/32 registered at all.

This confirms the datasheet margin in practice: at VCCI = 3.3 V the TXU0104's V(T+)
maximum is **1.92 V**, above a 1.8 V logic high. The data lanes never cross it.

**The important part is the failure mode.** The capture reported success, returned 190
writes and two plausible-looking data values (`0x0000`, `0x0010`), and produced no error
of any kind. Against unknown data it would have been accepted as real. It was caught only
because the test used traffic whose correct decoding was already known - the window-setup
commands were simply absent.

**Consequence:** the cold-boot capture needs a **stiff ~1.8 V source**, since a divider is
also ruled out (the ~2.9 kOhm ESD clamp load when the iPod is powered down). Options:
3x 1N4148 in series from 3v3 through ~1 kOhm (~1.95 V, ~60 Ohm dynamic impedance), a red
LED in the same arrangement (~1.8-2.0 V), or a 1.8 V LDO.

### 2026-08-02 — /RD vs /RESET parked after five attempts

Five cold/warm boot captures failed to trigger: P30 falling, P32 falling, P30 rising,
/CS falling, and /CS falling again after validating the rig.

**Design error, attempts 1-3.** With the iPod off both lines sit at 0 V and rise at
power-on; **a falling-edge trigger could never have fired**. Reset is asserted by the rail
being down and released by the line rising, not by the SoC pulling it low. Two cold boots
were spent on a test that was incapable of succeeding.

**Wrong diagnosis, attempt 4.** When /CS also failed to trigger I concluded the VREF
switch must still be on `3v3` and withdrew the earlier negative results. Validation showed
the opposite: at VREF = 1.6 V from the 1k/1k divider the window-setup commands decode
**byte-exactly**. The reference was never the problem, and the withdrawal was wrong.

**Still unexplained.** /CS visibly frames every write burst when the iPod is running, yet a
/CS falling-edge trigger does not fire during a cold boot - reproduced after the rig was
validated. Candidates not tested: VREF sagging during the target's power-up transient, or
analyzer edge detection behaving differently when an input is indeterminate at arm time.

**Parked.** The distinction has a trivial workaround (hold both high; identify reset later
by pulling one pin on live hardware) and nothing in Phase 6 depends on it.

### 2026-08-02 — **VISUAL CONFIRMATION AGAINST THE PHYSICAL PANEL**

Reconstructed rows 0-3 of a live Rockbox screen from a raw bus capture and compared the
result against the actual display. **Collaborator confirms it is recognisable, is the top
of the status bar, and the colours are correct.**

This is the strongest verification in the project, and categorically different from the
others. Every previous check compared captured data against values we *predicted* - the
init sequence, the window-setup commands, known colour fills. Those are strong, but they
share a failure mode: an error that is consistent between prediction and decode passes
unnoticed. That is exactly how the within-field bit-order bug survived nine byte-exact
protocol matches.

An image has no such failure mode. It either resembles the screen or it does not.

It simultaneously confirms the 34-pin map, the RGB666 field assignment **and bit order
within each field**, the /WR rising-edge latch, the D/C polarity, and the window-setup
geometry decode - since an error in any one of them would visibly scramble, shear or
mis-colour the result.

**Rule worth carrying forward: validate against the physical system, not only against
your own predictions.**

### 2026-08-03 — **INIT SEQUENCE CAPTURED END TO END.** 151 of 152 writes, byte-exact

**Action:** Re-ran the wake-init capture with two parameters changed from the 2026-08-01
attempt: **100 → 20 MS/s** and **7 → 10 bursts** (`--post 3270 --loops 9`, 24 channels,
trigger /WR falling on ch19). Same probe map, same wiring, no rehandling of the rig.
Capture `20260803_203836_init-burst`.

**(F) The 69-write ceiling was never a capture failure — it was arithmetic.** The
2026-08-01 run used `post 4670 @ 100 MS/s` = **46.7 µs per burst**, and 69 writes is
simply what fits in 46.7 µs at the ~690 ns/write the bus actually runs. The 140-write
register block needs ~98 µs. Halving the rate quadrupled the window to 163.5 µs and the
whole block landed in one contiguous burst.

Worth stating plainly because it was mis-filed for two days: the documented failures
(VREF collapse, the NOP prefix, the wrong-trigger accident) are all about the **cold
boot**. None of them was blocking the init writes. That gap was open because nobody
re-did the burst-sizing sum after the lane map was solved.

**(F) Burst structure came out `[1,1,1,1,1,1,140,2,2,8]`** against the sleep structure
of `seq_awake`, which is `[1,1,1,1,1,1,140,2,2,2]`. Bursts 1–6 holding exactly one write
each is the alignment anchor: it proves the capture began at the true first instruction
of the sequence rather than somewhere convenient.

**(F) 151 of 152 writes match `configs.firmware.types.2.sequences.awake` byte-exactly.**
Previous best was 75 of 152 (six NOPs plus 69 of the register block).

| | 2026-08-01 | 2026-08-03 |
|---|---|---|
| NOP prefix | 6 / 6 | 6 / 6 |
| register block | 69 / 140 | **140 / 140** |
| tail pairs | 0 / 6 | 5 / 6 |
| **total** | **75 / 152** | **151 / 152** |

**(F) The one lost write carries no information.** Expected #150 `CMD 0x0007` was dropped
in the re-arm gap at the burst 9→10 boundary — burst 10 opened with D/C already low and
/WR already back high, i.e. mid-cycle, after that pulse had passed. This is exactly the
"one write per boundary" cost the burst-sizing tradeoff predicts, and it landed on the
one boundary preceded by the longest sleep (150 ms). It is **byte-identical to #148
`CMD 0x0007`**, captured intact two writes earlier, and its data word `DATA 0x0173` was
captured. Every distinct value in `lcd_init_seq_23` has now been observed on the bus.

**(F) Since `firmware/awake` minus its six NOPs is byte-identical to `bootloader/init`,
this also verifies the cold-boot init's write content.** Confirmed programmatically
against `refs/sequences.json`, not assumed from the shared array name. **A cold boot is
no longer needed for any question about the init writes** — only for rail sequencing and
reset.

**(F) 20 MS/s is sound for this bus, measured rather than argued.** 158 falling edges and
158 rising edges — every pulse complete, none clipped or merged. /WR low measured 50–100 ns
(1–2 samples), consistent with the documented 70–80 ns. Had a pulse been missed the edge
counts would not balance.

> **CORRECTED later the same day — the last sentence is wrong.** A pulse shorter than the
> sample interval takes *both* its edges with it, so balanced counts prove nothing about
> completeness; they only rule out clipping at a window boundary. 20 MS/s *is* sound for
> the init, which is entirely slow-regime, and the 140-write block independently passes the
> D/C cross-check. But six writes elsewhere in this same capture were missed. See the
> 2026-08-03 entry below.

**(F) Register-block timing, now over the full 140 writes.** The block spans **97.5 µs**
of the 163.5 µs window (68 % headroom). Write-to-write spacing 600–1400 ns, mean **701 ns**,
with 55 intervals at 600 ns and 44 at 650 ns — the 610–1110 ns range measured earlier from
69 writes holds over the full block, with a few outliers to 1400 ns.

**Wrote `tools/seqmatch.py`.** `decode8080.py` answers "what is on the bus"; nothing
answered "is this the sequence we expected, in order, with nothing missing". It segments
by burst against the sidecar's geometry, compares the per-burst counts to the sequence's
run/sleep structure, and diffs with `difflib` rather than a fixed offset — so a write
dropped in a re-arm gap reports as one deletion at a known index instead of shifting
everything after it into a wall of false mismatches.

**Unexpected dividend: it retro-flags a known-bad capture.** Run against
`20260801_200739_dryrun` (the LA-B trial) it reports every DATA write decoding as CMD.
Checking edges per channel: **channels 20–23 (silkscreen CH21–24 = P28, P29, P30, P32)
have exactly zero edges** — the U4 group, captured *before* the reflow repair. D/C was
dead for that entire capture. The lane map was solved from the three LA-A captures, which
have D/C healthy (34 DATA / 40 CMD), so nothing downstream is affected — but it is a
reminder that a capture can be structurally convincing and still have a dead quarter.

### 2026-08-03 — Six window-setup writes absent from the post-wake redraw

**Observation, not yet explained.** Burst 10 caught seven writes after the init ended —
the panel had woken and Rockbox redrew. They decode as recognisable window-setup
registers and terminate correctly:

```
CMD 0x0210  DATA 0x0000  DATA 0x0000  CMD 0x0213  CMD 0x0201  DATA 0x0000  CMD 0x0202
```

followed by ~97 µs of silence, consistent with the documented >1.6 ms memcpy gap after
`0x202`. But `displaylcd_setup()` emits **13** writes and only **7** are present:
`0x211`, `0x212`, `0x200` and their data words are missing.

**It is not undersampling.** Falling and rising edge counts balance across the whole
capture, and the region 29740–29830 contains exactly seven /WR pulses for seven decoded
writes. The gaps between them are 1400 ns — about two write cycles — but carry no pulses
at all. There is no burst boundary anywhere near: all seven sit inside burst 10.

So the bus genuinely carried seven writes where the source says thirteen. Recorded as an
open question; it does not touch the init result, and the 13-write structure itself was
confirmed byte-exactly in earlier captures.

### 2026-08-03 — **The "missing" window-setup writes were undersampling.** Two write regimes on this bus

**Action:** Investigated the 7-vs-13 anomaly logged an hour earlier, entirely from existing
captures — no hardware, the parts for the bench rig have not arrived.

**(F) All 13 writes happened. Six /WR pulses were never sampled.** D/C is the witness: over
the region it makes **13 transitions in the pattern `0,1,0,1,…,0`** — one run per write,
starting and ending on a command, which is exactly the shape of `displaylcd_setup()`. Only
7 /WR pulses appear. The missing six map precisely onto the runs with no pulse:
`CMD 0x211`, `DATA 0x013F`, `CMD 0x212`, `DATA 0x00EF`, `CMD 0x200`, `DATA 0x0000`.

**(F) CORRECTION — "balanced edge counts prove nothing was missed" is wrong,** and it was
the reasoning used to dismiss undersampling in the entry above. A pulse that falls entirely
between two samples removes its falling *and* rising edge, so the counts stay balanced and
the write vanishes silently. Balanced counts only rule out a pulse **clipped at a window
boundary**. The sound check is `writes ≥ D/C transitions + 1` within a burst.

**(F) The bus has two command-write regimes.** Measured on 100 MS/s captures of the
identical 13-write block, so this is a property of the traffic and not of the capture:

| regime | write cycle | /WR low | min sample rate |
|---|---|---|---|
| slow | **818 ns** | **60–80 ns** | 16.7 MS/s |
| fast | **309 ns** | **30–40 ns** | **33.3 MS/s** |

Across the capture set both appear; 100 MS/s captures resolve either. Every previous
20 MS/s capture that returned a clean 13/13 happened to land on a **slow** redraw. This one
landed on a fast one, and at 20 MS/s a 30 ns pulse is *shorter than the 50 ns sample
interval* — it can miss entirely. Six of thirteen did.

**What selects the regime is not understood.** Both occur with the same command values and
the same panel state as far as anything captured shows.

**(F) The init result is unaffected.** Burst 7 has **140 /WR pulses against 139 D/C
transitions** — exactly the expected relationship for 140 strictly-alternating writes — and
it matched 140/140 byte-exactly against the source. The init runs entirely in the slow
regime (600–1400 ns, mean 701 ns). Nothing from the previous entry needs revisiting except
the reasoning quoted above.

**Phase 6 dividend, and the more valuable half of this.** The panel demonstrably accepts a
**309 ns write cycle with a 30–40 ns /WR low** — the SoC does it routinely. That is 2.6×
faster than the 610 ns "known-good" point `DRIVING.md` was written around, and it partly
pre-answers the planned write-rate sweep. A full frame at 309 ns is **23.7 ms** against
46.9 ms at 610 ns; tear-free at the panel's 67.9 Hz still needs ~192 ns, so the sweep is
still worth running, but it starts from a much better-informed position.

**`tools/seqmatch.py` now cross-checks /WR against D/C per burst** and reports how many
writes were missed. Run against this capture it flags burst 10 with "at least 6 writes
missed"; it stays quiet on the slow-regime captures. Verified against
`20260802_131348_dryrun` (20 MS/s, slow regime, clean).

**Method note.** This came out of asking why 15 earlier captures all showed 7/7
window-setup commands and one showed 4/7 — a comparison across the whole evidence set
rather than a closer look at the odd one. The capture index and per-capture sidecars are
what made that sweep a five-minute job.

### 2026-08-03 — **The init was already captured on 2026-08-01.** 152/152 across two captures

**Action:** Ran the new `seqmatch.py` over the whole capture set as a regression check.

**(F) `20260801_212943_dryrun` contains 151 of the 152 wake-init writes** and has done
since it was taken. Its sidecar note reads *"Post-reflow check: burst capture of ordinary
screen activity. D/C (P28, CH21) must toggle if the CH21-24 group is alive."* It was armed
for an unrelated purpose while the display happened to wake, and swept up the entire
sequence across its 64 small bursts.

The match is contiguous, not a scattered-subsequence artefact:

```
equal   exp[0:105]    got[0:105]      105 writes
delete  exp[105:106]                  one write lost at a burst boundary
equal   exp[106:152]  got[105:151]     46 writes
insert                got[151:759]    608 writes of subsequent screen activity
```

Burst structure opens `[1,1,1,1,1,1,7,8,6,8,…]` — the six single-write NOP bursts are
present, so the alignment anchor holds there too.

**(F) Together the two captures cover the whole sequence: 152/152.** They lose *different*
writes — `20260801_212943` is missing expected #105 (`DATA 0x0300`), `20260803_203836` is
missing #150 (`CMD 0x0007`). **Every write of `lcd_init_seq_23` has now been observed on
the bus**, not merely every distinct value.

**This is the uncomfortable part.** The project spent two days believing it had 69 of 140
writes and treating the rest as blocked. A capture taken **40 minutes later on the same
evening** already held 151 of 152. Nothing was missing but a tool that compared captures
against the expected sequence — `decode8080.py` answers "what is on the bus", and nobody
had asked "is this the sequence we expected". The evidence set was searched by *intent
recorded in a note*, never by *content*.

**Rule worth carrying forward: when you build a new analysis, run it over the whole
existing evidence set before collecting more.** It cost five minutes here and would have
saved a bench session.

**(F) Burst boundaries lose writes far less often than assumed.** That capture chops the
140-write register block across roughly twenty boundaries and loses **one** write in total,
not twenty. The existing guidance — "many small bursts: one dropped write per boundary" —
is an upper bound and a pessimistic one; the observed rate here is nearer 5 % per boundary.
The design rule (put boundaries in known sleeps) still holds, because *which* write is lost
is not predictable.

**What today's capture still contributes.** It is not redundant: the 140-write block sits
in **one contiguous burst**, which is what makes the block-level timing measurable
(97.5 µs end to end, spacing histogram, mean 701 ns). In `20260801_212943` the block is
twenty fragments, so only per-fragment spacing survives. It is also a deliberate,
reproducible plan whose burst structure self-validates, rather than a lucky accident.

### 2026-10-12 — The five cold-boot "failures" were operator aborts. The rig is fine

**Action:** Resumed Phase 6 at gap 1 (rail power-up sequencing). Swept the capture set by
content for existing rail evidence first, then tried to establish what an armed capture
actually looks like before spending any boots.

**(F) No capture has ever recorded a rail.** All 41 captures taken before today use the
bus/control channel set; pins **26, 33 and 34 have never been assigned to a channel**.
Gap 1 is genuinely unmeasured, not merely unanalysed.

**(F) The five 2026-08-02 cold-boot attempts were aborted, not negative results.** Every
one of `20260802_125222`, `_125453`, `_125835`, `_130138` and `_130459` records
`returncode: -2` — **SIGINT**. They were killed from the keyboard while still armed. The
code is meaningful, not noise: `20260801_213713` records `rc=1`, a genuine tool-reported
failure, and a deliberate SIGTERM today recorded `rc=143`.

So **"the analyzer does not fire during a cold boot" was never established.** The
"unexplained" /CS result in OPEN-QUESTIONS §1 rested entirely on it, and parking /RD vs
/RESET was premature.

**Why this was easy to get wrong.** `capture.py` runs `subprocess.run` with **no timeout**,
and TerminalCapture's entire output while armed is `Capture started, press Ctrl+C to stop.`
— the same line whether it is waiting for a trigger, downloading, or refusing the
configuration outright. The tool invites the Ctrl+C that destroys the capture and shows no
progress either way.

**(F) `/proc/<pid>/io` distinguishes the states.** `rchar` static = still armed; `rchar`
climbing = triggered and transferring. This is the progress signal the tool does not give.

**Four attempts, and the pair that matters is a controlled comparison.**

| # | capture | config | result |
|---|---|---|---|
| 1 | `154402` | 8 ch, pre **65536**, trigger ch0 rising, manual jumper edge | no fire |
| 2 | — | same capture still armed, GND-then-VREF touch on ch0 | no fire |
| 3 | `161426` | 8 ch, pre **65536**, trigger ch2 = TE, ~20 s scrolling, 128 s armed | no fire |
| 4 | `161634` | 8 ch, pre **1024** / post 130047, trigger ch2 = TE | **fired, rc=0, 131071 rows** |
| 5 | `161748` | 24 ch, pre 512 / post 32255 @ 20 MS/s, trigger ch19 = /WR falling | fired, 32767 rows |

**(3) and (4) differ in exactly one parameter.** Same 8 channels, same total of 131071,
same trigger channel, same 1 MS/s, same rig, same session — only the pre-trigger changed,
65536 → 1024. (3) sat armed for 128 s with TE demonstrably pulsing and never fired.
(4) completed. That is a single-variable result.

**A caution about how (4) was nearly misread.** It was recorded as "no fire" during the
session on the strength of a static `rchar` at +6 s and +9 s. The panel had gone back to
sleep, so TE had stopped; it woke later and the capture completed before the kill landed.
The sidecar — `rc=0`, 131071 rows — was only noticed when the index was regenerated.
**A live `rchar` check is a snapshot, not a verdict; the sidecar is the record.**

**(F) The rig is healthy and the 1k/1k divider reference works.** `20261012_161748` decodes
coherently: **2 writes, both `CMD 0x0000`**, /WR low **50–100 ns**, /CS low **600–650 ns**
framing each write, all 18 data lanes constant 0 — which is exactly correct for `0x0000`,
not the dead-bus signature it superficially resembles. P30/P32 constant high, as documented.

On its own that was only a **partial** validation — two isolated NOPs, well short of the
window-setup gold standard. Capture (4)'s nine clean TE periods (below) supersede it.

**An aside worth recording:** the two NOPs are **1.0004 ms** apart, not the 1.28 ms of the
documented wake prefix. Suspiciously exactly 1 ms, so probably a periodic write rather than
a standby release. Unexplained, not chased.

**(F) An oversized pre-trigger prevents arming, silently. This is the cause.** Confirmed
by the (3)–(4) comparison above, and consistent with the whole history. Across all 44
sidecars: **every one of the 35 successes used pre ∈ {64, 512, 1024}**, and **no capture
with pre > 1024 has ever produced data (0 of 7: 8000 ×3, 30000 ×2, 65536 ×2)**. The two
remaining failures sit below the ceiling and are independently explained —
`20260801_213713` (`rc=1`, a genuine tool error, the USB drop-out) and `20260801_222235`
(aborted, with a degenerate pre=1). The true ceiling lies somewhere in **(1024, 8000]** and
has not been bisected; 1024 is simply the largest value ever observed to work.

**Two candidate explanations are now dead:**

- **8-channel mode works.** Capture (4) is the first 8-channel capture in the project's
  history and it returned the full 131071 samples cleanly.
- **A 131071-sample total is legal.** (3) and (4) both requested it; only (4) armed.

**(F) This explains the five 2026-08-02 cold-boot attempts outright.** They used pre = 8000
(×3) and 30000 (×2), both above the ceiling. They would never have armed no matter how long
anyone waited. The SIGINT in each sidecar records an operator correctly observing nothing
happen — but the root cause was a tooling bug, not impatience and not the hardware. The
"unexplained" /CS anomaly in OPEN-QUESTIONS §1 was an artefact of it.

**(F) TE independently reconfirmed, and measured over a long window for the first time.**
From capture (4)'s 131 ms: **9 pulses, mean period 14.7227 ms = 67.92 Hz, width 57–58 µs,
duty 0.39 %**, with ±1 µs jitter across 8 consecutive periods. Documented values were
67.9 Hz / 14.73 ms / ~60 µs from much shorter windows. This is also the strongest rig
validation of the day — far better than capture (5)'s two isolated NOPs.

`capture.py` validated only the *total* against the channel-count tier and never `pre` on
its own, so it emitted configs the device refuses without complaint. Now capped at 1024.

**(F) TRG is a trigger OUTPUT, not an input.** `SharedDriver.dll`'s TriggerType enum holds
only `Edge`, `Complex`, `Fast`, `blast` — no external member, and no external-trigger field
in the session schema. Upstream documents the complex/fast trigger GPIOs as "exposed
through a diode, so that signal can be used to trigger other devices like an
oscilloscope", at 20 ns (fast) / 35 ns (complex) delay. Cascading uses the **separate 3-pin
connector pair**, not TRG. **This matters for Stage 3:** the VC-1008 is single-channel, so
each rail must be measured on its own boot, and TRG gives those boots a common hardware
trigger. It only asserts on `complex`/`fast`; every preset here uses `edge`.

**Method note.** The pre-trigger correlation came from tabulating pre/post/channels against
csv-present across all 41 sidecars — the same content sweep that found the init (finding
13), and it cost one query.

The detour afterwards is the instructive part. On seeing one more failure I abandoned the
correlation, declared 8-channel mode the suspect, and went off to replicate a 24-channel
config — while the capture that actually confirmed the original hypothesis had already
succeeded on disk, unnoticed. Two lessons: **a single apparent counter-example is not
grounds to abandon a hypothesis the entire capture history supports**, and **check the
sidecar before concluding anything from a live process probe.**

### 2026-10-12 (later) — **GAP 1 ANSWERED.** The analog domain leads the logic domain by 218 ms

**Action:** Rewired the rails onto silkscreen CH2/CH9/CH19 (pins 26/33/34), displacing P02,
P14 and P25 — the two MSB replicas and one blue lane, none load-bearing. Validated, then
captured two cold starts. **First capture of these three pins in the project's history.**

**(F) Pre-flight passed on every channel** (`20261012_165816`, iPod running): all three rail
channels constant 1 — including `VREF_P34`, whose 1.54 V against a ~1.1 V threshold is the
thinnest margin of the three and the main open risk — TE 22 pulses at **67.89 Hz**, width
50–60 µs, all 15 remaining data lanes active, P30/P32 idle high.

**(F) The rail sequence, reproduced to one sample.** Threshold crossings at ~1.1 V relative
to the 3.0 V rail:

| signal | `170354` (battery reconnect) | `171537` (hold switch) | delta |
|---|---|---|---|
| 3.0 V `V30_P33` | 0.000 ms | 0.000 ms | — (trigger) |
| `P32` | +0.100 ms | +0.090 ms | −10 µs |
| 1.54 V `VREF_P34` | +0.130 ms | +0.130 ms | **0** |
| 1.8 V `V18_P26` | +218.300 ms | +218.310 ms | +10 µs |
| `P30` | +218.310 ms | +218.320 ms | +10 µs |
| `WR_P27`, `CS_P29` | +218.300 ms | +218.310 ms | +10 µs |

±10 µs is exactly one sample at 100 kS/s, so the runs agree to the limit of the method.
All transitions are **single and monotonic** — no glitching, no brown-out, no rail that
rises and falls.

**(F) The 218.3 ms gap is deterministic.** It reproduced to 0.005 % across two boots
started by *different mechanisms* — battery reconnect and hold-switch release. That rules
out software jitter: it is a programmed delay in the SoC's boot path, measured from the
3.0 V rail. Phase 1 is the analog domain (3.0 V, then the reference 130 µs later); phase 2,
218 ms on, is the logic domain. /WR and /CS rise *with* VDDIO because they are referenced
to it and cannot lead it.

**Driver consequence that bites hardest:** the 1.54 V reference leads VDDIO by 218 ms, so
the **TLV9061 buffering it cannot be powered from VDDIO** — it must run from the 3.0 V
domain or its own earlier rail. That was a hypothesis raised at the start of the day and is
now a hardware constraint. Written into `DRIVING.md` §1.

**(F) P30 and P32 behave differently at power-up — the first measurement that separates
them.** P32 crosses with the analog rails (+0.09 ms); P30 crosses 10 µs *after* VDDIO.
Five cold boots in August never distinguished these two pins. It does not yet say which is
/RD and which is /RESET.

> ⚠️ **Do not over-read P32.** A threshold detector cannot tell 1.8 V logic from 3.0 V from
> ~1.2 V of leakage. P32 reading high 218 ms *before* VDDIO exists is odd for a
> VDDIO-referenced line, so that early crossing needs a DMM or scope confirmation of the
> actual voltage before anyone concludes anything from it.

**(F) No reset pulse exists in the window.** Both P30 and P32 show exactly one 0→1 edge and
never return low across 322 ms. Direct support for the August hypothesis that reset is
asserted by the rail being down and released by the line rising, not by the SoC pulling the
line low.

**(F) No init traffic within 322 ms of the 3.0 V rail.** /WR has exactly one edge — its
rise with VDDIO — and zero aliasing hits, against 488 aliased edges when the bus was
active in the pre-flight. The bus was genuinely idle. Gap 2 (rail to first command) lies
beyond this window.

**(F) A cold start can abort, leaving the 3.0 V rail high for 3.700 ms before collapsing**
with nothing else following (`20261012_171110`). The panel tolerates it. Recorded in
`DRIVING.md` as a condition a driver should survive.

**Method: the hold switch beats battery reconnect.** Battery out → **hold switch locked**
→ battery in (firmly seated) → iPod stays off with all three rails confirmed at 0 V by DMM
→ arm → unlock hold to boot. Reconnecting the battery by hand bounces, and a bounce burns
the capture: `171110` triggered on a false start and spent its whole window on it. The hold
switch is a clean mechanical action that touches nothing electrical. **The collaborator's
method, and it is the one to use.**

It also answers a standing question: with the battery seated and hold locked, pins 26, 33
and 34 all read **0 V**, so the panel rails are *not* part of the PMU standby domain. The
earlier warning that "powered off is not unpowered" does not apply to these three.

**Method note.** The reproducibility check earned its keep in an unexpected way. It did not
catch a wrong number — it caught an unreliable *method*. Had the first capture gone
straight into the record as fact, the number would have been right and the procedure behind
it would have been one that works roughly half the time.
