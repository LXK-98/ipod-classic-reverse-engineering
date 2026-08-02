# Reference sources

Upstream files vendored here as the **ground truth** this project is validated against.
They are unmodified copies; `tools/rockbox_seq.py` parses them into
`refs/sequences.json`.

## Rockbox (GPL v2)

| file | upstream path |
|---|---|
| `lcd-6g.c` | `firmware/target/arm/s5l8702/ipod6g/lcd-6g.c` |
| `lcd-s5l8702.c` | `firmware/target/arm/s5l8702/lcd-s5l8702.c` |
| `lcd-s5l8702.h` | `firmware/target/arm/s5l8702/lcd-s5l8702.h` |
| `lcd-target.h` | `firmware/target/arm/s5l8702/ipod6g/lcd-target.h` |
| `ipod6g.h` | `firmware/export/config/ipod6g.h` |

Source: <https://github.com/Rockbox/rockbox>

A full copy of the GPL v2 is included here as [`COPYING`](COPYING), as that licence
requires when redistributing.

**These files are licensed GPL v2 by the Rockbox project** and are redistributed here
under those terms. Copyright remains with their respective authors (Dave Chapman,
Michael Sparmann and others). They are included so the analysis is reproducible without
a network fetch and so the exact revision used is pinned; see `SHA256SUMS`.

`sequences.json` is a derived work of these files and inherits the same licence.
