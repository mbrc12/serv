#!/usr/bin/env python3
"""Rasterise data/tray/serv.svg into macOS template-image PNGs.

A template image is black artwork with alpha; the system tints it to match the
menu bar. Several pixel sizes are written — one per display scale — and the tray
adds each as a representation of one 18-point image, so the glyph is never
upscaled on a Retina display.

Run from the project root: uv run python tools/make_tray_icon.py
"""

from __future__ import annotations

from pathlib import Path

import cairosvg

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "data" / "tray" / "serv.svg"

#: One file per scale factor, at 18 points.
SCALES = ((1, "servTemplate.png"), (2, "servTemplate@2x.png"), (3, "servTemplate@3x.png"), (4, "servTemplate@4x.png"))
BASE_POINTS = 18


def main() -> None:
    source = SOURCE.read_bytes()
    for scale, name in SCALES:
        size = BASE_POINTS * scale
        target = SOURCE.parent / name
        cairosvg.svg2png(
            bytestring=source,
            write_to=str(target),
            output_width=size,
            output_height=size,
        )
        print(f"{target.relative_to(ROOT)}  {size}x{size} ({scale}x)")


if __name__ == "__main__":
    main()
