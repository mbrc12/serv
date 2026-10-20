"""Configuration loading and validation."""

from __future__ import annotations

from pathlib import Path
import tomllib

import pytest

from serv.config import ConfigError, load_config, parse_config


@pytest.fixture
def raw() -> dict:
    with open("config/serv.toml", "rb") as handle:
        return tomllib.load(handle)


def test_defaults_load_from_the_shipped_config() -> None:
    config = load_config()
    assert config.server.port == 1002
    assert config.palette.bg == "#e1e2e7"
    assert config.type.reading == "Crimson Pro"
    assert config.server.no_process == (str(Path("~/dev/game/**/build/**").expanduser()),)


def test_invalid_colour_is_rejected(raw: dict) -> None:
    raw["palette"]["bg"] = "not-a-colour"
    with pytest.raises(ConfigError, match="palette.bg"):
        parse_config(raw)


def test_rgba_and_transparent_are_accepted(raw: dict) -> None:
    raw["palette"]["zebra"] = "rgba(0, 0, 0, 0.04)"
    config = parse_config(raw)
    assert config.palette.zebra.startswith("rgba(")


def test_no_process_must_be_a_list_of_patterns(raw: dict) -> None:
    raw["server"]["no_process"] = "~/dev/game/**/build/**"
    with pytest.raises(ConfigError, match="no_process"):
        parse_config(raw)


def test_no_process_expands_home(raw: dict) -> None:
    raw["server"]["no_process"] = ["~/tmp/build/**"]
    config = parse_config(raw)
    assert not config.server.no_process[0].startswith("~")


def test_invalid_length_is_rejected(raw: dict) -> None:
    raw["layout"]["md_width"] = "46"
    with pytest.raises(ConfigError, match="layout.md_width"):
        parse_config(raw)


def test_invalid_font_name_is_rejected(raw: dict) -> None:
    raw["type"]["mono"] = "../../etc/passwd;"
    with pytest.raises(ConfigError, match="type.mono"):
        parse_config(raw)


def test_missing_config_file_fails_loudly() -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config("/nonexistent/serv.toml")
