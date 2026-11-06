"""Prebuilt color schemes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from serv import schemes
from serv.config import load_config


def test_bundled_schemes_are_valid_and_complete() -> None:
    bundled = schemes.load_schemes()
    assert len(bundled) >= 6
    for scheme in bundled:
        assert scheme.key and scheme.label
        assert scheme.palette.bg.startswith("#")
        assert len(scheme.colors()) == 28


def contrast(first: str, second: str) -> float:
    """Return the WCAG contrast ratio between two #rrggbb colors."""

    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.mark.parametrize("scheme", schemes.load_schemes(), ids=lambda scheme: scheme.key)
def test_every_scheme_keeps_body_text_readable(scheme: schemes.Scheme) -> None:
    """Body text must clear WCAG AA against its own page, at 4.5:1."""
    assert contrast(scheme.palette.text, scheme.palette.bg) >= 4.5


def test_default_config_matches_the_first_scheme() -> None:
    first = schemes.load_schemes()[0]
    assert schemes.name_for(load_config()) == first.key


def test_applying_a_scheme_replaces_only_colors() -> None:
    config = load_config()
    dark = next(scheme for scheme in schemes.load_schemes() if scheme.key == "tokyo-night")
    applied = schemes.apply(config, dark)
    assert applied.palette.bg == "#1a1b26"
    assert applied.type == config.type
    assert applied.layout == config.layout
    assert applied.server == config.server
    assert applied.palette.bg != config.palette.bg


def test_an_edited_palette_is_reported_as_custom() -> None:
    config = load_config()
    edited = replace(config, palette=replace(config.palette, bg="#123456"))
    assert schemes.name_for(edited) == schemes.CUSTOM


def test_values_round_trip_through_a_scheme() -> None:
    values = {"palette.bg": "#ffffff"}
    scheme = schemes.load_schemes()[1]
    schemes.apply_to_values(values, scheme)
    assert schemes.name_for_values(values) == scheme.key


@pytest.mark.parametrize("key", ["tokyo-night-day", "nord-light", "solarized-dark"])
def test_every_scheme_labels_are_unique(key: str) -> None:
    labels = [scheme.label for scheme in schemes.load_schemes()]
    assert len(labels) == len(set(labels))
    assert schemes.label_for(key) != key
