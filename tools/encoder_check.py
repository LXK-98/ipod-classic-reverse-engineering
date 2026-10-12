#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check a candidate (kind, 16-bit value) -> 18-pin encoder against the iPod's own
init capture, pin for pin on all 18 lanes. Alignment reuses seqmatch's own decode
(14 confirmed lanes) and difflib, exactly as seqmatch does."""
import difflib, json, sys
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'tools'))
import capio, seqmatch
import numpy as np

cap = REPO / 'captures/20260803_203836_init-burst.csv.gz'
print('invalid?', capio.invalid_reason(cap))
lanes = seqmatch.load_lane_map(REPO / 'pinout.json')
got, rise, _ = seqmatch.decode(cap, lanes, 'P27', 'P28')
exp, _ = seqmatch.expected(REPO / 'refs/sequences.json', 'firmware', '2', 'awake')
names, data = capio.load(cap)
idx = {n: i for i, n in enumerate(names)}

# GPn = D_n, D17..D0 = R5..R0 G5..G0 B5..B0 (DRIVING.md section 4 pixel order)
GP_PIN = [2, 25, 24, 23, 22, 21, 20, 19, 18, 1, 16, 15, 14, 13, 12, 11, 10, 9]

def std(v):  # bits 7..0 -> GP8..GP1, bits 15..8 -> GP17..GP10, GP0 = GP9 = 0
    return ((v & 0xFF00) << 2) | ((v & 0x00FF) << 1)

def soc(kind, v):  # what the SoC does: DATA writes copy bit 10 to GP17 (P09), bit 4 to GP0 (P02)
    w = std(v)
    if kind == 1:
        w = (w & ~((1 << 17) | 1)) | (((v >> 10) & 1) << 17) | ((v >> 4) & 1)
    return w

sm = difflib.SequenceMatcher(a=exp, b=got, autojunk=False)
matched = bad_soc = bad_std = 0
first_bad = []
for op, a0, a1, b0, b1 in sm.get_opcodes():
    if op != 'equal':
        print('non-equal opcode', op, a0, a1, b0, b1)
        continue
    for k in range(a1 - a0):
        kind, v = exp[a0 + k]
        s = rise[b0 + k]
        pins = 0
        for g, p in enumerate(GP_PIN):
            pins |= int(data[s, idx[f'P{p:02d}']]) << g
        matched += 1
        if pins != soc(kind, v):
            bad_soc += 1
            if len(first_bad) < 5:
                first_bad.append((a0 + k, kind, hex(v), bin(pins), bin(soc(kind, v))))
        if pins != std(v):
            bad_std += 1
print(f'matched writes: {matched} of {len(exp)} expected, {len(got)} decoded')
print(f'pin-exact vs SoC encoder : {matched - bad_soc}/{matched}')
print(f'pin-exact vs std encoder : {matched - bad_std}/{matched}  (differs only on replicated pairs)')
for b in first_bad:
    print('  mismatch', b)

# Facts the encoder relies on, from the source sequence itself
init = json.load(open(REPO / 'refs/sequences.json'))['configs']['bootloader']['types']['2']['sequences']['init']['transactions']
vals = [(e['kind'], e['value']) for e in init if e['kind'] != 'sleep']
print('bootloader init writes:', len(vals),
      '| max cmd', hex(max(v for k, v in vals if k == 'cmd')),
      '| data with bit14/15:', sum(1 for k, v in vals if k != 'cmd' and v & 0xC000),
      '| data with bit10:', sum(1 for k, v in vals if k != 'cmd' and v & 0x400),
      '| data with bit4:', sum(1 for k, v in vals if k != 'cmd' and v & 0x10))
print('firmware awake minus 6 NOPs == bootloader init:', exp[6:] == [(0 if k == 'cmd' else 1, v) for k, v in vals])
