#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Host-side test of firmware/lcddrv.py against mock machine/rp2/time modules.

The Pico cannot be in CI, but the properties that protect the panel are pure
logic and can be checked here: rail ORDER up and down, the bus idling before
VDDIO, the wait before the first command, /CS framing, the init's run
structure, and that the reference-hold pin is never driven high.

What this cannot check is anything electrical or PIO timing -- the analyzer
does that at milestones 1 and 2 (docs/BREADBOARD.md).

    python3 firmware/test_host.py
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))

# --- mocks ------------------------------------------------------------------------
clock = [0]          # microseconds
events = []          # (t_us, kind, detail)


def log(kind, detail):
    events.append((clock[0], kind, detail))


class Pin:
    OUT, IN, PULL_DOWN, IRQ_RISING = "OUT", "IN", "PULL_DOWN", "IRQ_RISING"
    state: dict = {}

    def __init__(self, n, mode=None, pull=None, value=None):
        self.n = n
        if mode is not None:
            if mode == Pin.OUT and value is not None:
                Pin.state[n] = value
            log("pin", (n, mode, value))

    def value(self, v=None):
        if v is None:
            return Pin.state.get(self.n, 0)
        Pin.state[self.n] = v
        log("pin", (self.n, "OUT", v))

    def irq(self, trigger=None, handler=None):
        pass


class StateMachine:
    def __init__(self, sm_id, prog, freq=None, out_base=None, sideset_base=None):
        self.freq = freq
        log("sm", ("init", freq, out_base.n, sideset_base.n))

    def active(self, x):
        log("sm", ("active", x))

    def put(self, words):
        log("put", list(words))

    def tx_fifo(self):
        return 0


def sleep_us(us):
    clock[0] += int(us)


def sleep_ms(ms):
    clock[0] += int(ms) * 1000


machine = types.ModuleType("machine")
machine.Pin = Pin
machine.freq = lambda f=None: None
rp2 = types.ModuleType("rp2")
rp2.PIO = types.SimpleNamespace(OUT_LOW=0, OUT_HIGH=1, SHIFT_RIGHT=1, JOIN_TX=1)
rp2.asm_pio = lambda **kw: (lambda f: ("pio-program", kw))
rp2.StateMachine = StateMachine
mtime = types.ModuleType("time")
mtime.sleep_us, mtime.sleep_ms = sleep_us, sleep_ms
mtime.ticks_us = lambda: clock[0]
mtime.ticks_ms = lambda: clock[0] // 1000
mtime.ticks_diff = lambda a, b: a - b

import drv  # noqa: E402  (initseq generator only; no serial needed)

initseq = types.ModuleType("initseq")
exec(drv.initseq_source(), initseq.__dict__)
sys.modules.update(machine=machine, rp2=rp2, initseq=initseq)
_real_time = sys.modules["time"]
sys.modules["time"] = mtime
try:
    import bus  # noqa: E402
    import lcddrv as d  # noqa: E402
finally:
    sys.modules["time"] = _real_time

EN30, REF, EN18, CS, WR = d.GP_EN30, d.GP_REF, d.GP_EN18, d.GP_CS, d.GP_WR


# --- helpers ------------------------------------------------------------------------
def first(pred, after=0):
    for i, e in enumerate(events[after:], after):
        if pred(e):
            return i, e
    raise AssertionError("expected event not found")


def pin_set(n, v):
    return lambda e: e[1] == "pin" and e[2][0] == n and e[2][1] == "OUT" and e[2][2] == v


def pin_mode(n, mode):
    return lambda e: e[1] == "pin" and e[2][0] == n and e[2][1] == mode


def frames(after):
    """/CS-framed bursts after event index `after`: list of word counts."""
    out, cur, inside = [], 0, False
    for _, k, det in events[after:]:
        if k == "pin" and det[0] == CS and det[1] == "OUT":
            if det[2] == 0:
                inside, cur = True, 0
            elif inside:
                out.append(cur)
                inside = False
        elif k == "put":
            assert inside, "bus write outside a /CS frame"
            cur += len(det)
    return out


checks = 0


def check(cond, msg):
    global checks
    assert cond, msg
    checks += 1


# --- import: ordered safe state -------------------------------------------------------
i18, e18 = first(pin_set(EN18, 0))
ir, er = first(pin_mode(REF, "OUT"))
i30, e30 = first(pin_set(EN30, 0))
check(i18 < ir < i30, "import must force VDDIO off, then the reference, then 3.0 V")
check(er[0] - e18[0] >= 33_000 and e30[0] - er[0] >= 13_000, "import shutdown keeps the gaps")

# --- nothing may touch the bus before power_up ----------------------------------------
try:
    d.init()
    raise AssertionError("init() ran with the rails down")
except RuntimeError:
    check(True, "")

# --- power_up order --------------------------------------------------------------------
mark = len(events)
sys.modules["time"] = mtime
d.time = mtime
d.power_up()
ism, esm = first(lambda e: e[1] == "sm" and e[2][0] == "init", mark)
i30, e30 = first(pin_set(EN30, 1), mark)
ir, er = first(pin_mode(REF, "IN"), mark)
i18, e18 = first(pin_set(EN18, 1), mark)
check(esm[2][1] == 25_000_000 and esm[2][2] == 0 and esm[2][3] == WR, "PIO: 25 MHz, data at GP0, /WR side-set")
check(ism < i30, "bus must idle (/WR high, data low) before any rail")
check(i30 < ir < i18, "power-up order must be 3.0 V -> reference -> VDDIO")
check(er[0] - e30[0] >= 1000, "reference lags 3.0 V by >= 1 ms")
check(e18[0] - er[0] >= 218_000, "VDDIO lags the reference by >= 218 ms")
check(Pin.state.get(CS) == 1, "/CS idles high")
try:
    d.power_up()
    raise AssertionError("power_up() ran twice")
except RuntimeError:
    check(True, "")

# --- init: 400 ms wait, run structure, /CS framing ---------------------------------------
mark = len(events)
t_vddio = e18[0]
d.init()
iw, ew = first(lambda e: e[1] == "put", mark)
check(ew[0] - t_vddio >= 400_000, "first command >= 400 ms after VDDIO")
check(frames(mark) == [140, 2, 2, 2], f"init frames {frames(mark)} != [140, 2, 2, 2]")
sent = [w for _, k, det in events[mark:] if k == "put" for w in det]
expect = [bus.reg(k, v) for k, v in initseq.SEQ["init"] if k != bus.SLEEP]
check(sent == expect, "init words are the bootloader init, encoded by bus.reg")
puts = [e[0] for e in events[mark:] if e[1] == "put"]
gaps = sorted(b - a for a, b in zip(puts, puts[1:]))[-3:]
check(gaps[0] >= 30_000 and gaps[1] >= 60_000 and gaps[2] >= 150_000, "the 30/60/150 ms sleeps are honoured")

# --- pair-test frame -------------------------------------------------------------------
mark = len(events)
d.ramp("rgb")
check(frames(mark) == [13 + 240 * 320], "ramp is one /CS frame: window + 76 800 pixels")
px = [w for _, k, det in events[mark:] if k == "put" for w in det][13:]
row = lambda y: px[y * 320:(y + 1) * 320]
check(row(0)[5] == bus.pixel(1, 0, 0) and row(0)[319] == bus.pixel(63, 0, 0), "top third: red ramp")
check(row(80)[5] == bus.pixel(0, 1, 0) and row(239)[5] == bus.pixel(0, 0, 1), "then green, then blue")
check(bus.pixel(1, 0, 0) == bus.DC | 1 << 12 and bus.pixel(32, 0, 0) == bus.DC | 1 << 17,
      "red LSB on D12 (P14) alone, red MSB on D17 (P09) alone: the pair is split")
check(bus.FLEX[12] == 14 and bus.FLEX[17] == 9 and bus.FLEX[0] == 2 and bus.FLEX[5] == 21,
      "lane map: D12=P14, D17=P09, D0=P02, D5=P21")

# --- power_down: standby first, then the mirror order ----------------------------------------
mark = len(events)
d.power_down()
i18, e18 = first(pin_set(EN18, 0), mark)
ir, er = first(pin_mode(REF, "OUT"), mark)
i30, e30 = first(pin_set(EN30, 0), mark)
standby = [w for _, k, det in events[mark:i18] if k == "put" for w in det]
check(standby == [bus.reg(k, v) for k, v in initseq.SEQ["sleep"] if k != bus.SLEEP],
      "an initialised panel gets the sleep sequence before power goes")
check(i18 < ir < i30, "power-down order must be VDDIO -> reference -> 3.0 V")
check(er[0] - e18[0] >= 33_000 and e30[0] - er[0] >= 13_000, "power-down gaps")
check(d.status()["state"] == "off", "state off")

# --- an interrupted power_up still powers down in order ------------------------------------
mark = len(events)
real = mtime.sleep_ms


def boom(ms):
    if ms == d.GAP_MS:
        raise KeyboardInterrupt
    real(ms)


mtime.sleep_ms = boom
try:
    d.power_up()
    raise AssertionError("interrupt swallowed")
except KeyboardInterrupt:
    pass
mtime.sleep_ms = real
check(Pin.state[EN30] == 0 and Pin.state[EN18] == 0 and d.status()["state"] == "off",
      "an interrupt mid power-up leaves every rail off")
ir, _ = first(pin_mode(REF, "OUT"), mark)
i30, _ = first(pin_set(EN30, 0), mark)
check(ir < i30, "... with the reference dropped before 3.0 V")

# --- GP22 is never driven high, ever ---------------------------------------------------------
check(not any(k == "pin" and det[0] == REF and det[1] == "OUT" and det[2] == 1
              for _, k, det in events), "the reference-hold pin was driven high")

print(f"OK: {checks} checks passed")
