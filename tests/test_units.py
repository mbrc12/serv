"""CSS length handling for the size sliders."""

from __future__ import annotations

import pytest

from serv.units import SLIDERS, format_length, parse_length, slider_for, snap


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1.2rem", (1.2, "rem")), ("12px", (12.0, "px")), ("46rem", (46.0, "rem"))],
)
def test_parse_length(text: str, expected: tuple[float, str]) -> None:
    assert parse_length(text) == expected


def test_parse_length_rejects_junk() -> None:
    assert parse_length("wide") is None
    assert parse_length("") is None


def test_format_drops_trailing_zeros() -> None:
    assert format_length(1.2, "rem") == "1.2rem"
    assert format_length(12.0, "px") == "12px"


def test_snap_uses_the_step() -> None:
    assert snap(1.33, 0.05) == 1.35
    assert snap(11.2, 0.5) == 11.0


def test_slider_spec_matches_the_unit() -> None:
    assert slider_for("type.md_size", "1.2rem") is not None
    assert slider_for("type.md_size", "19px") is None  # unit mismatch
    assert slider_for("unknown", "1rem") is None


def test_all_slider_keys_have_sane_ranges() -> None:
    for key, (minimum, maximum, step, unit) in SLIDERS.items():
        assert minimum < maximum
        assert step > 0
        # An empty unit is a plain multiple, e.g. line height.
        assert unit in {"px", "rem", "em", "ch", "%", ""}, key
