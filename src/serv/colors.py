"""CSS color parsing and formatting, independent of any toolkit.

The settings window needs to turn ``#7146a6`` into a color picker value and back
again. Keeping that arithmetic here means both the Tk window and the tests use
one implementation, with no GUI toolkit imported.
"""

from __future__ import annotations

import re

import deal

HexColor = str

_HEX = re.compile(r"^#([0-9a-fA-F]{3,8})$")
_FUNC = re.compile(r"^(rgba?|hsla?)\(([^)]*)\)$")


@deal.raises(ValueError)
def parse_css_color(value: str) -> tuple[float, float, float, float]:
    """Parse a CSS color into (red, green, blue, alpha), each from 0 to 1.

    Supports #rgb, #rrggbb, #rrggbbaa, rgb()/rgba() and the two keywords serv
    uses. ``transparent`` becomes fully transparent black.
    """
    text = value.strip()
    if text.lower() == "transparent":
        return (0.0, 0.0, 0.0, 0.0)

    match = _HEX.match(text)
    if match:
        digits = match.group(1)
        if len(digits) == 3:
            digits = "".join(character * 2 for character in digits)
        if len(digits) == 6:
            digits += "ff"
        if len(digits) != 8:
            raise ValueError(f"not a CSS hex color: {value!r}")
        return tuple(int(digits[index : index + 2], 16) / 255 for index in range(0, 8, 2))

    match = _FUNC.match(text)
    if match and match.group(1).startswith("rgb"):
        parts = [part.strip() for part in match.group(2).replace("/", ",").split(",")]
        if len(parts) not in (3, 4):
            raise ValueError(f"not a CSS rgb color: {value!r}")
        channels = [float(part.rstrip("%")) / 255 for part in parts[:3]]
        alpha = float(parts[3]) if len(parts) == 4 else 1.0
        if any(channel < 0 or channel > 1 for channel in channels):
            raise ValueError(f"channel out of range: {value!r}")
        return (channels[0], channels[1], channels[2], min(max(alpha, 0.0), 1.0))

    raise ValueError(f"not a CSS color: {value!r}")


def css_color(red: float, green: float, blue: float, alpha: float = 1.0) -> str:
    """Format channels as the shortest accurate CSS color."""
    if alpha <= 0.004:
        return "transparent"
    red, green, blue = (min(max(channel, 0.0), 1.0) for channel in (red, green, blue))
    if alpha >= 0.996:
        return f"#{round(red * 255):02x}{round(green * 255):02x}{round(blue * 255):02x}"
    return (
        f"rgba({round(red * 255)}, {round(green * 255)}, {round(blue * 255)}, "
        f"{round(alpha, 3)})"
    )


def hex_for_picker(value: str) -> str:
    """Return a #rrggbb color, compositing any transparency over white.

    Tk color pickers and canvas fills have no alpha channel, so a translucent
    config color is shown as it would look on a white page.
    """
    red, green, blue, alpha = parse_css_color(value)
    return css_color(
        red * alpha + (1 - alpha),
        green * alpha + (1 - alpha),
        blue * alpha + (1 - alpha),
        1.0,
    )
