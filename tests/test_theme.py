"""The stylesheet's custom properties must match the names the CSS uses."""

from __future__ import annotations

import re

from serv.config import load_config
from serv.theme import stylesheet


def _defined_variables(css: str) -> set[str]:
    return set(re.findall(r"^\s+(--[a-z0-9-]+)\s*:", css, re.MULTILINE))


def _used_variables(css: str) -> set[str]:
    return set(re.findall(r"var\((--[a-z0-9-]+)\)", css))


def test_every_referenced_variable_is_defined() -> None:
    css = stylesheet(load_config())
    missing = _used_variables(css) - _defined_variables(css)
    assert missing == set(), f"undefined custom properties: {sorted(missing)}"


def test_underscored_keys_become_hyphenated_variables() -> None:
    css = stylesheet(load_config())
    defined = _defined_variables(css)
    assert "--selected-text" in defined
    assert "--code-block-bg" in defined
    assert "--code-block-border" in defined
    assert not any("_" in name for name in defined)


def test_table_headers_use_the_configured_header_text_colour() -> None:
    config = load_config()
    css = stylesheet(config)
    assert f"--selected-text: {config.palette.selected_text};" in css
