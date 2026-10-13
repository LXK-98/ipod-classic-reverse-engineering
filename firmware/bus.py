# SPDX-License-Identifier: MIT
"""Bus encoding for the breadboard driver.

Pure Python with no hardware imports, so it runs both on the Pico (MicroPython)
and on the host (CPython). tools/encoder_check.py therefore tests the exact code
the firmware executes, against the iPod's own captures.

Lane convention: GPIO n drives panel lane Dn, where D17..D0 is the pixel order
of docs/DRIVING.md section 4 -- R5..R0, G5..G0, B5..B0. GPIO 18 is D/C. So a
PIO word is simply bit n -> GPn, n = 0..18. ASCII only: this file is copied to
the Pico verbatim.
"""

# Dn -> flex pin, n = 0..17
FLEX = (2, 25, 24, 23, 22, 21, 20, 19, 18, 1, 16, 15, 14, 13, 12, 11, 10, 9)

CMD = 0
DATA = 1
SLEEP = 2          # in a sequence tuple, the value is microseconds
DC = 1 << 18       # D/C lane: 0 = command, 1 = data

W = 320
H = 240


def reg(kind, value):
    """One register-interface write, encoded exactly as the SoC drives it.

    Measured, not assumed: this reproduces all 151 aligned writes of the iPod's
    init capture pin for pin on all 18 lanes (tools/encoder_check.py). Value
    bits 15..8 go to D17..D10 and bits 7..0 to D8..D1; D9 and D0 stay low. On
    DATA writes the SoC also copies bit 10 onto D17 (P09) and bit 4 onto D0
    (P02) -- the RGB666 pair tie -- and that is reproduced as well, so during
    init the panel sees the pin levels it has always seen.
    """
    w = ((value & 0xFF00) << 2) | ((value & 0x00FF) << 1)
    if kind == DATA:
        w = (w & ~0x20001) | (((value >> 10) & 1) << 17) | ((value >> 4) & 1) | DC
    return w


def pixel(r, g, b):
    """One RGB666 pixel write: 6 bits per channel, all 18 lanes independent.

    Unlike reg(), nothing is replicated -- D12 (P14) and D0 (P02) carry the red
    and blue LSBs. That independence is exactly what the pair test probes.
    """
    return DC | ((r & 63) << 12) | ((g & 63) << 6) | (b & 63)


def runs(tx):
    """Split (kind, value) transactions into [(words, sleep_us), ...].

    One run per stretch between sleeps -- the same structure seqmatch.py
    compares burst captures against, and the unit the driver frames with /CS.
    """
    out, cur = [], []
    for kind, value in tx:
        if kind == SLEEP:
            out.append((cur, value))
            cur = []
        else:
            cur.append(reg(kind, value))
    if cur:
        out.append((cur, 0))
    return out


def window(x0, x1, y0, y1):
    """Window and GRAM address, then CMD 0x202 (DRIVING.md section 7)."""
    w = []
    for r, v in ((0x210, x0), (0x211, x1), (0x212, y0), (0x213, y1),
                 (0x200, x0), (0x201, y0)):
        w.append(reg(CMD, r))
        w.append(reg(DATA, v))
    w.append(reg(CMD, 0x202))
    return w


def ramp_row(channel, band=5):
    """One 320-px row stepping one channel 0..63, `band` px per step.

    At the default 5 px the 64 steps fill the row exactly. A channel whose LSB
    lane is honoured shows 64 bands; one whose LSB is ignored or tied shows 32
    double-width bands. Green is the control: it is natively 6-bit, so it must
    always show 64.
    """
    row = []
    for x in range(W):
        v = min(x // band, 63)
        row.append(pixel(v if channel == "r" else 0,
                         v if channel == "g" else 0,
                         v if channel == "b" else 0))
    return row
