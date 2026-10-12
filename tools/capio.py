# SPDX-License-Identifier: MIT
"""Shared capture I/O.

Captures are stored gzipped: they are one-bit-per-channel CSV text and compress
about 110:1, which keeps the whole evidence set under a megabyte instead of tens
of megabytes. Every tool loads through here so `.csv` and `.csv.gz` are
interchangeable and no analysis has to care which is on disk.
"""
from __future__ import annotations

import gzip
import io
import json
from pathlib import Path

import numpy as np


def resolve(path: Path) -> Path:
    """Accept either form; prefer whichever exists."""
    path = Path(path)
    if path.exists():
        return path
    alt = Path(str(path) + ".gz") if path.suffix != ".gz" else path.with_suffix("")
    if alt.exists():
        return alt
    raise SystemExit(f"capture not found: {path} (nor {alt})")


def _open(path: Path):
    return gzip.open(path, "rt") if path.suffix == ".gz" else path.open()


def load(path: Path) -> tuple[list[str], np.ndarray]:
    """Return (channel names, samples[n_samples, n_channels] uint8)."""
    path = resolve(path)
    with _open(path) as f:
        names = f.readline().strip().split(",")
        data = np.loadtxt(io.StringIO(f.read()), delimiter=",", dtype=np.uint8, ndmin=2)
    if data.shape[1] != len(names):
        raise SystemExit(f"{path.name}: header has {len(names)} names, rows have {data.shape[1]}")
    return names, data


def sidecar(path: Path) -> dict:
    """Load the JSON sidecar recording settings, probe map and notes."""
    p = resolve(path)
    base = str(p)
    for suf in (".csv.gz", ".csv"):
        if base.endswith(suf):
            base = base[: -len(suf)]
            break
    j = Path(base + ".json")
    return json.loads(j.read_text()) if j.exists() else {}


def sample_rate(path: Path) -> int | None:
    sc = sidecar(path)
    if sc:
        return sc.get("session", {}).get("Frequency")
    return None


def invalid_reason(path: Path) -> str | None:
    """Why this capture must not be analysed, or None if it is sound.

    Some captures completed successfully and contain plausible-looking data that
    is nonetheless wrong -- the known case is VREF on the 3v3 switch position,
    which silently puts the shifter threshold above a 1.8 V logic high. Such a
    capture reports success, so nothing stops a content sweep from including it.

    ANY sweep over captures/*.csv.gz must skip captures where this returns a
    reason. Omitting the check is not hypothetical: on 2026-10-12 a sweep for
    replicated colour-lane pairs picked up 29 spurious splits from one such file.
    """
    sc = sidecar(path)
    return sc.get("invalid_reason") if sc.get("invalid") else None
