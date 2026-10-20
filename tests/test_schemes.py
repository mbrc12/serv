"""Prebuilt colour schemes."""

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
        assert len(scheme.colours()) == 25


def test_default_config_matches_the_first_scheme() -> None:
    first = schemes.load_schemes()[0]
    assert schemes.name_for(load_config()) == first.key


def test_applying_a_scheme_replaces_only_colours() -> None:
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


@pytest.mark.parametrize("key", ["tokyo-night-day", "nord", "solarized-dark"])
def test_every_scheme_labels_are_unique(key: str) -> None:
    labels = [scheme.label for scheme in schemes.load_schemes()]
    assert len(labels) == len(set(labels))
    assert schemes.label_for(key) != key
