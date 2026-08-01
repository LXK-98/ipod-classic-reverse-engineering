# Probe map v1 — interposer pin convention

**STATUS: CONFIRMED 2026-08-01.** The iPod LCD flex has **34** conductors (the
project brief's "33-pin" is wrong). All 34 routed nets are live.

Derived from the collaborator's own KiCad design at `display-analyzer-board/`
(`display-analyzer-board.kicad_pcb`, read 2026-08-01), not from a photo.

## Board identity

Silkscreen: `iPod Classic 6 Gen display signal interceptor board v0.1b — Alex Karlin`,
fab ID `6507911A_Y9_250207`.

| ref | part | role |
|---|---|---|
| J2 | `046293635005829+`, 35-pos 0.3 mm FPC | **Logic board** side |
| J3 | `046293635005829+`, 35-pos 0.3 mm FPC | **Display** side |
| J1 | `PinHeader_2x17_P2.54mm_Vertical_SMD` | probe header (34 pins) |
| J4 | `PinHeader_2x17_P2.54mm_Vertical` (TH) | alternate probe header, same nets |

J1 and J4 occupy the same board position and carry **identical** net assignments, so the
pin numbering below is valid regardless of which is populated.

## Orientation reference

The photo taken 2026-08-01 matches the KiCad layout orientation exactly:
silkscreen title readable at top-left, `Logic board`/J2 at **left**, `Display`/J3 at
**right**, header vertical in the middle. KiCad +Y is down, so "top of photo" =
"low Y" = the J1 pin-1 end.

## Header geometry (as seen in the photo orientation)

- 17 rows of 2 pins, 2.54 mm pitch, spanning Y 79.36 → 120.00 mm.
- **Pin 1 is TOP-LEFT.**
- **Odd pins (1,3,5…33) = LEFT column. Even pins (2,4,6…34) = RIGHT column.**
- Pin numbers increase downward, two per row: row 1 = pins 1,2 … row 17 = pins 33,34.

## Net mapping (authoritative, from the PCB netlist)

```
J1/J4 pin p   <->  net /(p+1)          p = 1..34
J2 pad q      <->  net /q              q = 2..35   (pad 1 = unconnected by design)
J3 pad r      <->  net /(36-r)         r = 1..34   (pad 35 = unconnected by design)
```

J3's numbering runs opposite to J2's. That is correct and intended: the two FPC
connectors face opposite board edges, so mirroring keeps a given physical conductor
aligned end to end.

Both deliberately-unconnected pads (J2 pad 1, J3 pad 35) sit at the **top** in the
photo orientation, matching the collaborator's description of the topmost position
being the unused one.

## Live-signal set (confirmed)

The iPod LCD flex has **34 conductors**. The FPC connectors have **35 positions**, i.e.
"one more pin than the iPod" as the collaborator described. The single surplus position
is the **topmost** on both connectors and is unused by design (J2 pad 1, J3 pad 35).

- **Live nets: `/2` … `/35` = 34 signals — ALL routed nets are live.**
- **Live header pins: 1 … 34. No dead pins.**

The earlier reading that header pin 1 was dead was based on the brief's incorrect 33-pin
figure and is **withdrawn**.

## Numbering convention (authoritative)

```
FLEX pin N  =  header pin N  =  net /(N+1)        N = 1..34
```

**FLEX pin 1 = header pin 1 = TOP-LEFT** = the topmost live conductor.
**FLEX pin 34 = header pin 34 = BOTTOM-RIGHT.**

Odd flex pins are on the header's LEFT column, even flex pins on the RIGHT column.

This is an internal convention anchored to physical geometry. It is **not** claimed to
match Apple's own pin-1 designation, which remains unknown and does not matter provided
we stay consistent. `PINOUT.md` will state the physical anchor so it can be re-derived
at the bench without this document.

## Physical probing crib

| header row | left pin | right pin |
|---|---|---|
| 1 (top) | 1 | 2 |
| 2 | 3 | 4 |
| ... | ... | ... |
| 17 (bottom) | 33 | 34 |

`left_pin = 2*row - 1`, `right_pin = 2*row`, `row = ceil(N/2)`.

## Sanity check on the count

34 conductors is consistent with the expected signal set: 18 data lanes + WR + RD + CS +
D/C + RESET + TE = 24 signals, leaving ~10 for power rails, grounds and the backlight
string. No spare capacity for surprises, which is itself useful to know.
