"""CSS lengths as slider values.

The Type & Layout sliders need a range and a step per setting, and the config
stores them as strings such as ``1.2rem``. This module owns both conversions so
the UI stays a thin shell.
"""

from __future__ import annotations

import re

import deal

LENGTH = re.compile(r"^(?P<value>\d+(?:\.\d+)?)(?P<unit>px|rem|em|ch|%)$")

#: key -> (minimum, maximum, step, unit) for the Type & Layout sliders.
SLIDERS: dict[str, tuple[float, float, float, str]] = {
    "type.md_size": (0.9, 1.6, 0.05, "rem"),
    "type.md_table": (0.8, 1.4, 0.05, "rem"),
    "type.code_size": (10.0, 18.0, 0.5, "px"),
    "layout.md_width": (32.0, 72.0, 2.0, "rem"),
    "layout.md_gutter": (1.0, 6.0, 0.5, "rem"),
    "layout.listing_width": (32.0, 72.0, 2.0, "rem"),
}


def parse_length(text: str) -> tuple[float, str] | None:
    """Split a CSS length such as ``1.2rem`` into its number and unit."""
    match = LENGTH.match(text.strip())
    if match is None:
        return None
    return float(match.group("value")), match.group("unit")


@deal.pre(lambda value, step: step > 0)
def snap(value: float, step: float) -> float:
    """Round a slider value to its step, avoiding binary float noise."""
    return round(round(value / step) * step, 4)


def format_length(value: float, unit: str) -> str:
    """Format a slider value as the CSS length string the config stores."""
    return f"{round(value, 2):g}{unit}"


def slider_for(key: str, text: str) -> tuple[float, float, float, str, float] | None:
    """Return (min, max, step, unit, value) when a slider can represent the value.

    Returns None when the key has no slider or the stored unit is not the
    slider's unit, so the caller can fall back to a text field rather than
    silently converting and rewriting the user's value.
    """
    spec = SLIDERS.get(key)
    parsed = parse_length(text)
    if spec is None or parsed is None:
        return None
    minimum, maximum, step, unit = spec
    value, stored_unit = parsed
    if unit != stored_unit:
        return None
    return minimum, maximum, step, unit, min(max(value, minimum), maximum)
