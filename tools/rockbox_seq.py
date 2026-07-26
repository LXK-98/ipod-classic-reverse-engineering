#!/usr/bin/env python3
"""Parse Rockbox lcd-6g.c into machine-readable LCD bus sequence tables.

Ground truth for the whole project. Emits, for each panel type (0..3) and each
build config (bootloader vs main firmware), the exact ordered list of bus
transactions the S5L8702 issues.

Opcode semantics come from firmware/target/arm/s5l8702/lcd-s5l8702.h:
    CMD=0, SLEEP=1, MREG=2, DELAY=3, END=0xff
    MREG16(len) = MREG | (len<<8)
    SLEEP16(t)  = SLEEP | (t<<8)
    DELAY16(t)  = DELAY | (t<<8)
    CMD16       = CMD
SLEEP is in Rockbox ticks (HZ=100 -> 10 ms each); DELAY is in units of 64 us.

Interpretation follows s5l_lcd_run_seq8() / s5l_lcd_run_seq16() in
lcd-s5l8702.c, so the emitted stream is what actually appears on the bus.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# Opcodes, from lcd-s5l8702.h
CMD, SLEEP, MREG, DELAY, END = 0, 1, 2, 3, 0xFF

HZ = 100  # Rockbox tick rate -> SLEEP unit is 10 ms


# --------------------------------------------------------------------------
# Minimal C preprocessor: enough for the #ifdef structure in lcd-6g.c
# --------------------------------------------------------------------------
def preprocess(text: str, defines: set[str]) -> str:
    """Strip comments and resolve #if/#ifdef/#ifndef/#else/#endif."""
    # Comments first, so commented-out directives never reach the evaluator.
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)

    def evaluate(expr: str) -> bool:
        expr = expr.strip()
        if expr == "0":
            return False
        if expr == "1":
            return True
        expr = re.sub(r"defined\s*\(\s*(\w+)\s*\)", lambda m: str(m.group(1) in defines), expr)
        expr = re.sub(r"defined\s+(\w+)", lambda m: str(m.group(1) in defines), expr)
        expr = expr.replace("||", " or ").replace("&&", " and ").replace("!", " not ")
        # Any bare identifier left is an undefined macro -> 0
        expr = re.sub(r"\b(?!True\b|False\b|or\b|and\b|not\b)[A-Za-z_]\w*\b", "False", expr)
        try:
            return bool(eval(expr, {"__builtins__": {}}, {}))
        except Exception:
            return False

    out: list[str] = []
    # stack entries: [currently_emitting, any_branch_taken_yet]
    stack: list[list[bool]] = []
    for line in text.splitlines():
        s = line.strip()
        m = re.match(r"#\s*(ifdef|ifndef|if|elif|else|endif)\b(.*)", s)
        if not m:
            out.append(line if all(f[0] for f in stack) else "")
            continue
        directive, rest = m.group(1), m.group(2)
        active = all(f[0] for f in stack)  # state of the *enclosing* scope

        if directive in ("ifdef", "ifndef", "if"):
            if directive == "ifdef":
                cond = rest.strip() in defines
            elif directive == "ifndef":
                cond = rest.strip() not in defines
            else:
                cond = evaluate(rest)
            stack.append([active and cond, cond])
        elif directive == "elif":
            if not stack:
                raise SyntaxError("#elif without #if")
            taken = stack[-1][1]
            cond = (not taken) and evaluate(rest)
            outer = all(f[0] for f in stack[:-1])
            stack[-1] = [outer and cond, taken or cond]
        elif directive == "else":
            if not stack:
                raise SyntaxError("#else without #if")
            taken = stack[-1][1]
            outer = all(f[0] for f in stack[:-1])
            stack[-1] = [outer and (not taken), True]
        elif directive == "endif":
            if not stack:
                raise SyntaxError("#endif without #if")
            stack.pop()
        out.append("")  # keep line numbering stable
    if stack:
        raise SyntaxError("unterminated #if block")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Array extraction and token evaluation
# --------------------------------------------------------------------------
ARRAY_RE = re.compile(
    r"static\s+const\s+(uint8_t|uint16_t)\s+(\w+)\s*\[\s*\]\s*=\s*\{(.*?)\}\s*;",
    re.S,
)


def eval_token(tok: str) -> int:
    """Evaluate one initializer token to its integer value."""
    tok = tok.strip()
    if not tok:
        raise ValueError("empty token")
    for name, op in (("MREG16", MREG), ("SLEEP16", SLEEP), ("DELAY16", DELAY)):
        m = re.fullmatch(rf"{name}\s*\(\s*(\w+)\s*\)", tok)
        if m:
            return op | (int(m.group(1), 0) << 8)
    if tok == "CMD16":
        return CMD
    if tok in ("CMD", "SLEEP", "MREG", "DELAY", "END"):
        return {"CMD": CMD, "SLEEP": SLEEP, "MREG": MREG, "DELAY": DELAY, "END": END}[tok]
    return int(tok, 0)


def extract_arrays(src: str) -> dict[str, dict]:
    arrays = {}
    for width, name, body in ARRAY_RE.findall(src):
        toks = [t.strip() for t in body.split(",")]
        toks = [t for t in toks if t]
        arrays[name] = {
            "width": 8 if width == "uint8_t" else 16,
            "values": [eval_token(t) for t in toks],
        }
    return arrays


# --------------------------------------------------------------------------
# Sequence interpreters (mirror s5l_lcd_run_seq8 / run_seq16)
# --------------------------------------------------------------------------
def run_seq8(vals: list[int]) -> list[dict]:
    """8-bit command set. Bus carries 8-bit words on D[8:1] (LCD_MODE_P8)."""
    out, i = [], 0
    while i < len(vals):
        op = vals[i]
        i += 1
        if op == CMD:
            cmd, n = vals[i], vals[i + 1]
            i += 2
            out.append({"kind": "cmd", "value": cmd, "width": 8})
            for _ in range(n):
                out.append({"kind": "data", "value": vals[i], "width": 8})
                i += 1
        elif op == SLEEP:
            out.append({"kind": "sleep", "ms": vals[i] * 1000 // HZ})
            i += 1
        else:  # END or anything unrecognised -> stop, as the C does
            break
    return out


def run_seq16(vals: list[int]) -> list[dict]:
    """16-bit register command set. Bus carries 16-bit words (LCD_MODE_P18)."""
    out, i = [], 0
    while i < len(vals):
        word = vals[i]
        i += 1
        action, param = word & 0xFF, word >> 8
        if action == CMD:
            out.append({"kind": "cmd", "value": vals[i], "width": 16})
            i += 1
        elif action == MREG:
            reg = vals[i]
            i += 1
            for _ in range(param):
                out.append({"kind": "cmd", "value": reg, "width": 16})
                out.append({"kind": "data", "value": vals[i], "width": 16})
                reg += 1
                i += 1
        elif action == SLEEP:
            out.append({"kind": "sleep", "ms": param * 1000 // HZ})
        elif action == DELAY:
            out.append({"kind": "sleep", "ms": (param << 6) / 1000.0})
        else:  # END
            break
    return out


# --------------------------------------------------------------------------
def build(src_path: Path) -> dict:
    raw = src_path.read_text()

    # Two build configs matter. Per firmware/export/config/ipod6g.h:
    #   HAVE_LCD_SLEEP is "#ifndef BOOTLOADER", so the two are mutually exclusive.
    # Only the BOOTLOADER build runs seq_init (see lcd_init_device()).
    configs = {
        "bootloader": {"BOOTLOADER", "HAVE_LCD_SHUTDOWN", "S5L_LCD_WITH_CMDSET16"},
        "firmware": {"HAVE_LCD_SLEEP", "HAVE_LCD_SHUTDOWN", "HAVE_LCD_ENABLE",
                     "S5L_LCD_WITH_CMDSET16"},
    }

    # Which array backs which role, per panel type (from lcd_info_list[]).
    roles = {
        0: {"init": "lcd_init_seq_0", "sleep": "lcd_sleep_seq_01", "awake": "lcd_awake_seq_01"},
        1: {"init": "lcd_init_seq_1", "sleep": "lcd_sleep_seq_01", "awake": "lcd_awake_seq_01"},
        2: {"init": "lcd_init_seq_23", "sleep": "lcd_deepstandby_seq_23", "awake": "lcd_init_seq_23"},
        3: {"init": "lcd_init_seq_23", "sleep": "lcd_deepstandby_seq_23", "awake": "lcd_init_seq_23"},
    }
    cmdset = {0: 8, 1: 8, 2: 16, 3: 16}

    result = {
        "source": str(src_path.relative_to(REPO)),
        "notes": [
            "Only the BOOTLOADER build calls lcd_run_seq(seq_init) (lcd_init_device()).",
            "HAVE_LCD_SLEEP is #ifndef BOOTLOADER, so bootloader and firmware expansions "
            "of lcd_init_seq_23 differ: the firmware one is prefixed with 6x NOP+DELAY "
            "(release from deep standby), the bootloader one is not.",
            "Types 2/3 seq_awake IS lcd_init_seq_23, so a firmware sleep/wake cycle "
            "replays a full init. Types 0/1 wake is only 0x11 + 0x29.",
            "S5L_LCD_WITH_READID is not defined for ipod6g, so Rockbox never issues a "
            "read transaction; /RD is expected idle for an entire Rockbox boot.",
        ],
        "configs": {},
    }

    for cfg_name, defines in configs.items():
        arrays = extract_arrays(preprocess(raw, defines))
        entry = {"available_arrays": sorted(arrays), "types": {}}
        for t, r in roles.items():
            runner = run_seq8 if cmdset[t] == 8 else run_seq16
            seqs = {}
            for role, arr_name in r.items():
                if role == "init" and cfg_name != "bootloader":
                    continue  # firmware never runs seq_init
                if arr_name not in arrays:
                    continue
                tx = runner(arrays[arr_name]["values"])
                seqs[role] = {
                    "array": arr_name,
                    "transactions": tx,
                    "n_cmd": sum(1 for x in tx if x["kind"] == "cmd"),
                    "n_data": sum(1 for x in tx if x["kind"] == "data"),
                    "n_bus_writes": sum(1 for x in tx if x["kind"] in ("cmd", "data")),
                    "total_sleep_ms": sum(x.get("ms", 0) for x in tx if x["kind"] == "sleep"),
                }
            entry["types"][str(t)] = {"cmdset_bits": cmdset[t], "sequences": seqs}
        result["configs"][cfg_name] = entry
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=REPO / "refs" / "lcd-6g.c")
    ap.add_argument("--out", type=Path, default=REPO / "refs" / "sequences.json")
    ap.add_argument("--summary", action="store_true", help="print a human summary")
    args = ap.parse_args()

    data = build(args.src)
    args.out.write_text(json.dumps(data, indent=2))
    print(f"wrote {args.out.relative_to(REPO)}")

    if args.summary:
        for cfg, c in data["configs"].items():
            print(f"\n=== build: {cfg} ===")
            for t, ti in c["types"].items():
                for role, s in ti["sequences"].items():
                    print(f"  type {t} ({ti['cmdset_bits']}-bit) {role:6s}: "
                          f"{s['n_bus_writes']:4d} bus writes "
                          f"({s['n_cmd']} cmd / {s['n_data']} data), "
                          f"{s['total_sleep_ms']:.1f} ms sleep  [{s['array']}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
