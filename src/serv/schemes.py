"""Prebuilt color schemes.

The schemes live in ``config/schemes.toml`` as data; this module only reads,
validates and applies them. Picking a scheme in the settings page copies its
colors into the served palette fields, so ``~/.config/serv/serv.toml`` stays the
single source of truth.

A scheme must define every color serv uses. A missing or malformed value is a
startup error rather than a half-themed page.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import tomllib

import deal

from .config import Accents, CodePalette, Config, ConfigError, Palette, _color
from .resources import config_file

SCHEMES_FILE = "schemes.toml"

#: Shown in the dropdown when the colors match no scheme.
CUSTOM = "custom"

SECTIONS = (
    ("palette", Palette),
    ("accents", Accents),
    ("code", CodePalette),
)


@dataclass(frozen=True)
class Scheme:
    """One prebuilt set of colors."""

    key: str
    label: str
    palette: Palette
    accents: Accents
    code: CodePalette

    def colors(self) -> dict[str, str]:
        """Return the values as ``section.key`` → CSS color."""
        values: dict[str, str] = {}
        for section, mapping in (
            ("palette", self.palette),
            ("accents", self.accents),
            ("code", self.code),
        ):
            for field in mapping.__dataclass_fields__:
                values[f"{section}.{field}"] = getattr(mapping, field)
        return values


@deal.raises(ConfigError)
def _parse_scheme(key: str, data: dict) -> Scheme:
    if not isinstance(data, dict):
        raise ConfigError(f"scheme {key} must be a table")
    label = data.get("label", key)
    if not isinstance(label, str) or not label.strip():
        raise ConfigError(f"scheme {key} needs a label")
    parsed = {}
    for section, section_type in SECTIONS:
        table = data.get(section)
        if not isinstance(table, dict):
            raise ConfigError(f"scheme {key} is missing [{section}]")
        values = {
            name: _color(table, name, f"schemes.{key}.{section}")
            for name in section_type.__dataclass_fields__
        }
        parsed[section] = section_type(**values)
    return Scheme(
        key=key,
        label=label,
        palette=parsed["palette"],
        accents=parsed["accents"],
        code=parsed["code"],
    )


@lru_cache(maxsize=1)
def load_schemes() -> tuple[Scheme, ...]:
    """Return every bundled scheme, in file order."""
    path = config_file(SCHEMES_FILE)
    if path is None:
        return ()
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    tables = data.get("schemes")
    if not isinstance(tables, dict) or not tables:
        raise ConfigError(f"{path}: no [schemes.*] tables")
    return tuple(_parse_scheme(key, table) for key, table in tables.items())


def apply(config: Config, scheme: Scheme) -> Config:
    """Return a copy of config with the scheme's colors."""
    return Config(
        server=config.server,
        cache=config.cache,
        palette=scheme.palette,
        accents=scheme.accents,
        code=scheme.code,
        type=config.type,
        layout=config.layout,
        source=config.source,
    )


def name_for_values(values: dict[str, str]) -> str:
    """Return the scheme key matching these color values, or 'custom'."""
    for scheme in load_schemes():
        colors = scheme.colors()
        if all(values.get(key, "").strip().lower() == value.lower() for key, value in colors.items()):
            return scheme.key
    return CUSTOM


def name_for(config: Config) -> str:
    """Return the scheme key matching this config, or 'custom'."""
    return name_for_values(
        {
            **{f"palette.{key}": value for key, value in config.palette.as_dict().items()},
            **{f"accents.{key}": value for key, value in vars(config.accents).items()},
            **{f"code.{key}": value for key, value in vars(config.code).items()},
        }
    )


def label_for(key: str) -> str:
    """Return the human label for a scheme key."""
    if key == CUSTOM:
        return "Custom"
    return next((scheme.label for scheme in load_schemes() if scheme.key == key), key)


def apply_to_values(values: dict[str, str], scheme: Scheme) -> None:
    """Copy a scheme's colors into a draft mapping (mutated in place)."""
    values.update(scheme.colors())
