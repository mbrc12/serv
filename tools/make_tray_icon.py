#!/usr/bin/env python3
"""Rasterise data/tray/serv.svg into the tray and app icons.

Files written:

* ``servTemplate*.png`` — black artwork on transparency, used as the window
  glyph and as the macOS template image.
* ``servTray-dark.png`` — white glyph for dark menu bars and taskbars.
* ``servTray-light.png`` — black glyph for light ones. The tray picks between
  them from the system appearance, which keeps the strokes sharp; an outlined
  two-tone glyph turns to mush at 22 pixels.

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


#: Tray images are drawn at twice the icon size so Retina panels stay sharp.
TRAY_SIZE = 44
TRAY_VARIANTS = (("servTray-light.png", "#000000"), ("servTray-dark.png", "#ffffff"))


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

    markup = SOURCE.read_text()
    for name, color in TRAY_VARIANTS:
        target = SOURCE.parent / name
        cairosvg.svg2png(
            bytestring=markup.replace("#000000", color).encode(),
            write_to=str(target),
            output_width=TRAY_SIZE,
            output_height=TRAY_SIZE,
        )
        print(f"{target.relative_to(ROOT)}  {TRAY_SIZE}x{TRAY_SIZE} ({color})")


if __name__ == "__main__":
    main()
