"""Font choices for the reading and monospace roles.

The catalog is data in ``config/fonts.toml``: each entry is a Google Fonts
family plus the axis query needed to load the weights serv uses. A family with an
empty weights string is treated as a font installed on the Mac, so no web
request is made for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import re

import tomllib

from .config import ConfigError
from .resources import config_file

FONTS_FILE = "fonts.toml"

#: A Google Fonts axis query such as "ital,wght@0,400;0,600;1,400".
WEIGHTS = re.compile(r"^[a-z]+(?:,[a-z]+)*@[0-9;,]+$")

ROLES = ("reading", "mono")


@dataclass(frozen=True)
class FontChoice:
    """One selectable family."""

    name: str
    weights: str


@lru_cache(maxsize=1)
def load_fonts() -> dict[str, tuple[FontChoice, ...]]:
    """Return the catalog per role, in file order."""
    path = config_file(FONTS_FILE)
    if path is None:
        return {role: () for role in ROLES}
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error

    catalog: dict[str, tuple[FontChoice, ...]] = {}
    for role in ROLES:
        table = data.get(role)
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: missing [{role}]")
        entries = table.get("fonts")
        if not isinstance(entries, list) or not entries:
            raise ConfigError(f"{path}: [{role}] needs at least one [[{role}.fonts]] entry")
        choices: list[FontChoice] = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ConfigError(f"{path}: [{role}.fonts] entries must be tables")
            name = entry.get("name")
            weights = entry.get("weights", "")
            if not isinstance(name, str) or not name.strip():
                raise ConfigError(f"{path}: a [{role}.fonts] entry has no name")
            if not isinstance(weights, str) or (weights and not WEIGHTS.match(weights)):
                raise ConfigError(f"{path}: {name} has an invalid weights query {weights!r}")
            choices.append(FontChoice(name=name, weights=weights))
        catalog[role] = tuple(choices)
    return catalog


def choices_for(role: str) -> tuple[FontChoice, ...]:
    """Return the families offered for a role."""
    if role not in ROLES:
        raise ValueError(f"unknown font role: {role}")
    return load_fonts()[role]


def weights_for(role: str, name: str) -> str | None:
    """Return the Google Fonts query for a known family, or None if it is local."""
    for choice in choices_for(role):
        if choice.name.lower() == name.strip().lower():
            return choice.weights
    return None
