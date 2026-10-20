"""Font catalog and the weights query used for Google Fonts."""

from __future__ import annotations

from dataclasses import replace

import pytest

from serv import fonts
from serv.config import ConfigError, load_config, parse_config
from serv.theme import stylesheet


def test_catalog_has_both_roles() -> None:
    catalog = fonts.load_fonts()
    assert set(catalog) == {"reading", "mono"}
    for role in ("reading", "mono"):
        assert len(catalog[role]) >= 5
        assert all(choice.name and choice.weights for choice in catalog[role])


def test_weights_lookup_is_case_insensitive() -> None:
    assert fonts.weights_for("mono", "fira code") == "wght@400;600"
    assert fonts.weights_for("reading", "Helvetica Neue") is None


def test_stylesheet_imports_google_fonts() -> None:
    css = stylesheet(load_config())
    assert "family=Crimson+Pro:ital,wght@0,400;0,600;1,400" in css
    assert "family=Fira+Code:wght@400;600" in css
    assert "text-decoration-line: underline;" in css


def test_link_underline_setting_changes_the_stylesheet() -> None:
    config = load_config()
    assert "text-decoration-line: underline;" in stylesheet(config)
    no_underlines = replace(config, type=replace(config.type, underline_links=False))
    assert "text-decoration-line: none;" in stylesheet(no_underlines)


def test_local_font_skips_its_import() -> None:
    config = load_config()
    local = replace(
        config,
        type=replace(
            config.type, reading="Helvetica Neue", reading_weights=""
        ),
    )
    css = stylesheet(local)
    assert "Crimson+Pro" not in css
    assert "Fira+Code" in css
    assert "font-family: 'Helvetica Neue', Georgia" in css


def test_missing_weights_are_derived_from_the_catalog() -> None:
    config = load_config()
    raw = {
        "server": {},
        "cache": {},
        "palette": vars(config.palette),
        "accents": vars(config.accents),
        "code": vars(config.code),
        "type": {
            "reading": "Literata",
            "mono": "Menlo",
            "md_size": "1.2rem",
            "md_table": "1.1rem",
            "code_size": "12px",
        },
        "layout": vars(config.layout),
    }
    parsed = parse_config(raw)
    assert parsed.type.reading_weights == "ital,wght@0,400;0,600;1,400"
    assert parsed.type.mono_weights == ""


def test_invalid_weights_query_is_rejected() -> None:
    config = load_config()
    raw = {
        "server": {},
        "cache": {},
        "palette": vars(config.palette),
        "accents": vars(config.accents),
        "code": vars(config.code),
        "type": {
            "reading": "Lora",
            "mono": "Fira Code",
            "reading_weights": "nonsense!!",
            "md_size": "1.2rem",
            "md_table": "1.1rem",
            "code_size": "12px",
        },
        "layout": vars(config.layout),
    }
    with pytest.raises(ConfigError, match="reading_weights"):
        parse_config(raw)
