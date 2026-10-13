# SPDX-License-Identifier: MIT
"""Breadboard RP2040 driver for the iPod Classic panel (MicroPython).

Spec: docs/DRIVING.md. Wiring: docs/BREADBOARD.md. Host side: tools/drv.py.

Importing this module does one thing: force every rail OFF in the safe order
(VDDIO, then the reference, then 3.0 V), whatever state the pins were left in.
Nothing is powered until power_up() is called. ASCII only: copied verbatim.
"""
import time
import machine
import rp2
from array import array
from machine import Pin

import bus

machine.freq(125_000_000)       # the PIO timing below assumes it

# Pin map -- must match docs/BREADBOARD.md. GP0..GP17 = D0..D17, GP18 = D/C.
GP_WR = 19      # PIO side-set
GP_CS = 20      # CPU-driven, framing each burst
GP_EN30 = 21    # ME6211C30 CE   -> 3.0 V panel supply, flex pin 33
GP_REF = 22     # TLV9061 input hold; released = reference on, flex pin 34
GP_EN18 = 26    # AP2112K-1.8 EN -> VDDIO, flex pin 26
GP_TE = 27      # TE in, through the SN74LVC1T45

# Sequencing. The ORDER is the hard requirement (DRIVING.md section 1). Every
# delay is a knob, defaulted to the original board's where that costs nothing.
REF_LEAD_US = 1000  # 3.0 V -> reference. Original 130 us; the ME6211 datasheet
                    # gives no start-up time, so let the rail settle first.
GAP_MS = 218        # reference -> VDDIO. Original 218.3 ms. Believed unnecessary.
WAIT_MS = 400       # VDDIO -> first command. Original 397 ms. Bisect down later.
DOWN_REF_MS = 33    # VDDIO off -> reference off. Original 32.9 ms.
DOWN_30_MS = 13     # reference off -> 3.0 V off. Original 13.6 ms.


class _Sink:
    """Sinks a pin to 0 V or floats it, and cannot drive it high.

    It holds the TLV9061 input. Driving that above an unpowered 3.0 V rail would
    push current through the op-amp's input clamp into the panel supply, so the
    high state is made impossible here rather than merely avoided.
    """

    def __init__(self, n):
        self.n = n
        self.hold()

    def hold(self):
        self.p = Pin(self.n, Pin.OUT, value=0)
        self.on = False

    def release(self):
        self.p = Pin(self.n, Pin.IN, None)
        self.on = True


# --- force a safe state, in order, before anything else ----------------------
cs = Pin(GP_CS, Pin.OUT, value=1)
en18 = Pin(GP_EN18, Pin.OUT, value=0)
time.sleep_ms(DOWN_REF_MS)
ref = _Sink(GP_REF)
time.sleep_ms(DOWN_30_MS)
en30 = Pin(GP_EN30, Pin.OUT, value=0)
te = Pin(GP_TE, Pin.IN, Pin.PULL_DOWN)   # the 1T45 is Hi-Z while VDDIO is off
try:
    led = Pin("LED", Pin.OUT, value=0)  # Pico and Pico W both accept "LED"
except (TypeError, ValueError):
    led = Pin(25, Pin.OUT, value=0)

_state = "off"
_inited = False
_t_vddio = 0
_sm = None
_cache = {}


# --- the 8080 write strobe ----------------------------------------------------
# 25 MHz state-machine clock = 40 ns per cycle, 20 cycles = 800 ns per write,
# close to the SoC's 818 ns slow regime. Every figure beats DRIVING.md section 3's
# measured known-good minimum: /WR low 120 ns (>= 80), data and D/C stable 520 ns
# before the latch (>= 60 and >= 380), held 280 ns after it (>= 270).
# With the FIFO empty the SM stalls on `out`, and its side-set keeps /WR high:
# "If an instruction stalls, the side-set still takes effect immediately"
# (RP2040 datasheet, PIO side-set).
@rp2.asm_pio(out_init=(rp2.PIO.OUT_LOW,) * 19, sideset_init=rp2.PIO.OUT_HIGH,
             out_shiftdir=rp2.PIO.SHIFT_RIGHT, autopull=True, pull_thresh=19,
             fifo_join=rp2.PIO.JOIN_TX)
def _wr8080():
    out(pins, 19)       .side(1)    [9]     # data + D/C change, /WR high
    nop()               .side(0)    [2]     # /WR low
    nop()               .side(1)    [6]     # /WR rises: the panel latches here


def _bus_start():
    global _sm
    _sm = rp2.StateMachine(0, _wr8080, freq=25_000_000,
                           out_base=Pin(0), sideset_base=Pin(GP_WR))
    _sm.active(1)


def _require_up():
    if _state != "up":
        raise RuntimeError("rails are not up: call power_up() first")


def _drain():
    while _sm.tx_fifo():
        pass
    time.sleep_us(2)    # the word already in the OSR has up to 800 ns left


def _burst(chunks):
    """One /CS-framed transfer. chunks: iterable of array('I') PIO words."""
    _require_up()
    cs.value(0)
    try:
        for c in chunks:
            _sm.put(c)
        _drain()
    finally:
        cs.value(1)


# --- power ---------------------------------------------------------------------
def power_up(ref_lead_us=REF_LEAD_US, gap_ms=GAP_MS):
    """3.0 V -> reference -> VDDIO.

    The bus is put at idle (/WR and /CS high, data low) BEFORE any rail, so those
    lines rise with VDDIO through the shifters exactly as on the original, and
    the shifters hold them Hi-Z until VDDIO exists.
    """
    global _state, _inited, _t_vddio
    if _state != "off":
        raise RuntimeError("already up: power_down() first")
    try:
        cs.value(1)
        _bus_start()
        en30.value(1)
        time.sleep_us(ref_lead_us)
        ref.release()
        time.sleep_ms(gap_ms)
        en18.value(1)
        _t_vddio = time.ticks_ms()
        _inited = False
        _state = "up"
        led.value(1)
    except BaseException:
        power_down(standby=False)
        raise


def power_down(standby=None, down_ref_ms=DOWN_REF_MS, down_30_ms=DOWN_30_MS):
    """VDDIO -> reference -> 3.0 V, the mirror of power-up. Safe from any state.

    If the panel was initialised, its sleep sequence goes first: the original
    stops TE before cutting power, so it quiesces by command. WHICH command it
    sends was never captured -- firmware.types.2.sleep is an inference.
    """
    global _state, _inited
    if standby is None:
        standby = _state == "up" and _inited
    if standby:
        try:
            _send_seq("sleep")
        except Exception as e:  # never let it block the power-down itself
            print("standby sequence failed:", e)
    cs.value(1)
    en18.value(0)           # the AP2112 discharges VDDIO through ~60 ohm
    time.sleep_ms(down_ref_ms)
    ref.hold()
    time.sleep_ms(down_30_ms)
    en30.value(0)
    if _sm is not None:
        _sm.active(0)
    _state = "off"
    _inited = False
    led.value(0)


def cycle(hold_ms=30):
    """Milestone 1: up, hold, down in one call. At the default hold the whole
    thing takes ~295 ms, so up AND down fit one 322 ms power-seq capture."""
    power_up()
    time.sleep_ms(hold_ms)
    power_down(standby=False)


# --- panel -----------------------------------------------------------------------
def _runs(name):
    if name not in _cache:
        import initseq
        _cache[name] = [(array("I", w), us) for w, us in bus.runs(initseq.SEQ[name])]
    return _cache[name]


def _send_seq(name):
    for words, us in _runs(name):
        if len(words):
            _burst((words,))
        if us:
            time.sleep_us(us)


def init(variant="init", wait_ms=WAIT_MS):
    """Send the panel init, no earlier than wait_ms after VDDIO came up.

    'init'  = bootloader.types.2.init, 146 writes: what the original sends at
              cold boot.
    'awake' = firmware.types.2.awake, 152 writes: the same, preceded by six
              CMD 0x0000 that release deep standby.
    """
    global _inited
    _require_up()
    left = wait_ms - time.ticks_diff(time.ticks_ms(), _t_vddio)
    if left > 0:
        time.sleep_ms(left)
    _send_seq(variant)
    _inited = True


def _frame(rows):
    """Full-screen window, then H rows, rows(y) -> array of W words."""
    def gen():
        yield array("I", bus.window(0, bus.W - 1, 0, bus.H - 1))
        for y in range(bus.H):
            yield rows(y)
    _burst(gen())


def fill(r, g, b):
    """Solid colour, 6-bit channel values."""
    row = array("I", [bus.pixel(r, g, b)] * bus.W)
    _frame(lambda y: row)


def ramp(which="rgb", band=5):
    """The pair test. 'rgb' stacks red, green and blue ramps in thirds, so the
    green control sits between the two channels under test in one photo."""
    rows = {c: array("I", bus.ramp_row(c, band)) for c in "rgb"}
    if which == "rgb":
        third = bus.H // 3
        _frame(lambda y: rows["rgb"[min(y // third, 2)]])
    else:
        row = rows[which]
        _frame(lambda y: row)


def te_rate(ms=1000):
    """Count TE rising edges for ms. Returns (edges, Hz or None).

    On the original TE starts 12.5 ms after init at 67.9 Hz, so a live TE is the
    panel's own confirmation that init took -- independent of any capture.
    """
    t = []
    te.irq(trigger=Pin.IRQ_RISING, handler=lambda p: t.append(time.ticks_us()))
    time.sleep_ms(ms)
    te.irq(handler=None)
    if len(t) < 2:
        return len(t), None
    return len(t), 1e6 * (len(t) - 1) / time.ticks_diff(t[-1], t[0])


def status():
    return {"state": _state, "inited": _inited,
            "ms_since_vddio": time.ticks_diff(time.ticks_ms(), _t_vddio) if _state == "up" else None,
            "en30": en30.value(), "ref_on": ref.on, "en18": en18.value(),
            "cs": cs.value(), "te": te.value()}
