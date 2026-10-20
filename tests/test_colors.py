"""CSS color parsing shared by the settings window and the tests."""

from __future__ import annotations

import pytest

from serv.colors import css_color, hex_for_picker, parse_css_color


def test_hex_colors_parse_to_channels() -> None:
    assert parse_css_color("#ffffff") == (1.0, 1.0, 1.0, 1.0)
    assert parse_css_color("#000") == (0.0, 0.0, 0.0, 1.0)


def test_alpha_hex_is_understood() -> None:
    red, green, blue, alpha = parse_css_color("#00000080")
    assert (red, green, blue) == (0.0, 0.0, 0.0)
    assert alpha == pytest.approx(128 / 255)


def test_rgba_and_transparent() -> None:
    assert parse_css_color("rgba(0, 0, 0, 0)") == (0.0, 0.0, 0.0, 0.0)
    red, green, blue, alpha = parse_css_color("rgba(113, 70, 166, 0.16)")
    assert alpha == pytest.approx(0.16)
    assert round(red * 255) == 113
    assert parse_css_color("transparent")[3] == 0.0


def test_formatting_round_trips() -> None:
    assert css_color(0.443, 0.275, 0.651) == "#7146a6"
    assert css_color(0, 0, 0, 0) == "transparent"
    assert css_color(0.5, 0.5, 0.5, 0.5).startswith("rgba(128, 128, 128")


def test_picker_hex_composites_transparency_on_white() -> None:
    assert hex_for_picker("transparent") == "#ffffff"
    assert hex_for_picker("rgba(0, 0, 0, 0.5)") == "#808080"


def test_invalid_colors_raise() -> None:
    with pytest.raises(ValueError):
        parse_css_color("nonsense")
    with pytest.raises(ValueError):
        parse_css_color("#12")
