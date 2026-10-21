"""Human labels for colour keys.

The labels are data in ``config/labels.toml`` so the settings page never shows
a raw identifier such as ``zebra``. Every key must have a label; a missing one
is reported at startup instead of silently falling back to the key name.
"""

from __future__ import annotations

from functools import lru_cache
import tomllib

import deal

from .config import Accents, CodePalette, ConfigError, Palette
from .resources import config_file

LABELS_FILE = "labels.toml"

SECTIONS = (
    ("palette", Palette),
    ("accents", Accents),
    ("code", CodePalette),
)


@lru_cache(maxsize=1)
@deal.raises(ConfigError)
@deal.ensure(lambda result: set(result) == {"palette", "accents", "code"})
def load_labels() -> dict[str, dict[str, str]]:
    """Return the label table, validated against the colour dataclasses."""
    path = config_file(LABELS_FILE)
    if path is None:
        raise ConfigError(f"{LABELS_FILE} is missing from the configuration directory")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error

    labels: dict[str, dict[str, str]] = {}
    for section, dataclass in SECTIONS:
        table = data.get(section)
        if not isinstance(table, dict):
            raise ConfigError(f"{path}: missing [{section}]")
        section_labels: dict[str, str] = {}
        for key in dataclass.__dataclass_fields__:
            value = table.get(key)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{path}: [{section}] has no label for {key}")
            section_labels[key] = value.strip()
        labels[section] = section_labels
    return labels


def label_for(section: str, key: str) -> str:
    """Return the label for one colour key."""
    return load_labels().get(section, {}).get(key, key.replace("_", " ").capitalize())
