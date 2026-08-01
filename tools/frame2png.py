#!/usr/bin/env python3
"""Reconstruct a (partial) framebuffer image from an 8080-bus capture.

End-to-end protocol validation: if the pinout, the RGB666 field mapping, the /WR
latch edge and the D/C polarity are all correct, this produces a recognisable
image. If any of them is wrong the picture is visibly scrambled, sheared, or
colour-swapped -- which makes the failure mode diagnostic rather than silent.

Reads the update rectangle from the window-setup commands
(0x210/0x211 = x start/end, 0x212/0x213 = y start/end) so the geometry comes
from the capture itself and is never assumed.

    tools/frame2png.py captures/<id>.csv -o frame.png

PNG is written with the stdlib only (zlib) -- no external imaging library.
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import capio

REPO = Path(__file__).resolve().parent.parent

R_HORIZ_START, R_HORIZ_END = 0x210, 0x211
R_VERT_START, R_VERT_END = 0x212, 0x213
R_GRAM_WRITE = 0x202


def write_png(path: Path, rgb: np.ndarray) -> None:
    """rgb: (h, w, 3) uint8."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path.write_bytes(png)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=REPO / "frame.png")
    ap.add_argument("--wr", default="P27")
    ap.add_argument("--dc", default="P28")
    ap.add_argument("--pinout", type=Path, default=REPO / "pinout.json")
    ap.add_argument("--scale", type=int, default=1, help="nearest-neighbour upscale")
    args = ap.parse_args()

    names, data = capio.load(args.csv)
    for ch in (args.wr, args.dc):
        if ch not in names:
            raise SystemExit(f"channel {ch!r} missing from capture")

    doc = json.loads(args.pinout.read_text())
    fields = doc["pixel_format"]["fields"]          # RED/GREEN/BLUE -> [pin names]
    cmdbits = {int(k): v for k, v in doc["lane_map"]["confirmed"].items()}
    idx = {n: i for i, n in enumerate(names)}

    wr = idx[args.wr]
    rise = np.flatnonzero(np.diff(data[:, wr].astype(np.int8)) == 1) + 1
    if len(rise) == 0:
        raise SystemExit("no /WR strobes in capture")
    is_data = data[rise, idx[args.dc]] == 1

    # --- commands: recover the update window using the 16-bit command-mode map ---
    def cmd_word(rows):
        w = np.zeros(len(rows), dtype=np.uint32)
        for pin, bit in cmdbits.items():
            nm = f"P{pin:02d}"
            if nm in idx:
                w |= data[rows, idx[nm]].astype(np.uint32) << bit
        return w

    cmd_rows = rise[~is_data]
    cmds = cmd_word(cmd_rows)
    # data word following each command, in bus order
    order = np.argsort(rise)
    seq = [(int(rise[i]), bool(is_data[i])) for i in order]
    win: dict[int, int] = {}
    last_cmd = None
    gram_at = None
    for pos, (samp, isd) in enumerate(seq):
        if not isd:
            c = int(cmd_word(np.array([samp]))[0])
            last_cmd = c
            if c == R_GRAM_WRITE:
                gram_at = pos
        elif last_cmd in (R_HORIZ_START, R_HORIZ_END, R_VERT_START, R_VERT_END):
            win[last_cmd] = int(cmd_word(np.array([samp]))[0])

    x0 = win.get(R_HORIZ_START, 0); x1 = win.get(R_HORIZ_END, 319)
    y0 = win.get(R_VERT_START, 0);  y1 = win.get(R_VERT_END, 239)
    w_full, h_full = x1 - x0 + 1, y1 - y0 + 1
    print(f"window from capture: x {x0}..{x1}, y {y0}..{y1}  ({w_full} x {h_full})")
    if gram_at is None:
        print("WARNING: no 0x202 GRAM-write command seen; using all data writes")

    # --- pixels: RGB666, one transfer per pixel ---
    pix_rows = [samp for pos, (samp, isd) in enumerate(seq)
                if isd and (gram_at is None or pos > gram_at)]
    # drop the window parameters that precede the GRAM write
    pix = np.array(pix_rows, dtype=int)
    if len(pix) == 0:
        raise SystemExit("no pixel writes found after the GRAM-write command")

    def channel(field: str) -> np.ndarray:
        pins = fields[field]                       # MSB..LSB order as stored
        v = np.zeros(len(pix), dtype=np.uint16)
        for k, nm in enumerate(pins):
            v |= data[pix, idx[nm]].astype(np.uint16) << (len(pins) - 1 - k)
        return v

    # fields are stored MSB->LSB; red/blue LSB is a hardware replica of their MSB
    r6, g6, b6 = channel("RED"), channel("GREEN"), channel("BLUE")
    rgb = np.stack([(r6 * 255 // 63), (g6 * 255 // 63), (b6 * 255 // 63)], axis=1).astype(np.uint8)

    n = len(rgb)
    rows_got = n // w_full
    print(f"pixels decoded: {n}  ({n / (w_full * h_full) * 100:.2f}% of the window, "
          f"{rows_got} complete rows of {w_full})")

    h_out = max(1, min(h_full, -(-n // w_full)))
    img = np.zeros((h_out, w_full, 3), dtype=np.uint8)
    flat = img.reshape(-1, 3)
    flat[:min(n, len(flat))] = rgb[:min(n, len(flat))]

    if args.scale > 1:
        img = np.repeat(np.repeat(img, args.scale, axis=0), args.scale, axis=1)
    write_png(args.out, img)
    print(f"wrote {args.out} ({img.shape[1]}x{img.shape[0]})")

    uniq = len({tuple(c) for c in rgb[: min(n, 5000)]})
    print(f"distinct colours in the first {min(n,5000)} pixels: {uniq}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
