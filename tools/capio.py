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
