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

## Phase 1 — DMM triage

*(not started — blocked on interposer installation and pin-1 convention)*

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
