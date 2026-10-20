"""Turn the configured palette into CSS.

Nothing in this module names a color: every value comes from the Config, and
the structural rules live in ``data/style/serv.css`` with ``${name}``
placeholders for the type and layout settings.

Fonts are loaded from Google Fonts, like the old stylesheet did, so the page
carries no font binaries of its own.
"""

from __future__ import annotations

from functools import lru_cache
from string import Template

import deal

from .config import Config
from .resources import STYLE_TEMPLATE, read_text

# Custom properties emitted in :root, in the order the stylesheet expects.
# Declared here so a new palette key cannot be silently forgotten.
VARIABLE_SECTIONS = (
    ("palette", "bg"),
    ("palette", "text"),
    ("palette", "muted"),
    ("palette", "border"),
    ("palette", "hover"),
    ("palette", "selected"),
    ("palette", "zebra"),
    ("palette", "red"),
    ("palette", "orange"),
    ("palette", "green"),
    ("palette", "blue"),
    ("palette", "teal"),
    ("palette", "purple"),
    ("accents", "markdown"),
    ("accents", "listing"),
    ("accents", "directory"),
    ("code", "base"),
    ("code", "comment"),
    ("code", "keyword"),
    ("code", "operator"),
    ("code", "string"),
    ("code", "function"),
    ("code", "number"),
    ("code", "tag"),
    ("code", "highlight"),
)

GOOGLE_FONTS = "https://fonts.googleapis.com/css2"


def _variable_name(section: str, key: str) -> str:
    """Map a config section and key onto the custom property the CSS expects."""
    if section == "palette":
        return f"--{key}"
    if section == "accents":
        return f"--accent-{key}"
    return f"--{section}-{key}"


def _import_line(name: str, weights: str) -> str | None:
    """Return one @import for a Google family, or None for a local font."""
    family = name.replace(" ", "+")
    if not weights:
        return None
    return f"@import url('{GOOGLE_FONTS}?family={family}:{weights}&display=swap');"


def font_imports(config: Config) -> str:
    """Return the @import lines for the two configured families.

    A family with no weights query is an installed font, so nothing is
    downloaded; the stylesheet's font-family declaration finds it locally.
    """
    lines = [
        line
        for line in (
            _import_line(config.type.reading, config.type.reading_weights),
            _import_line(config.type.mono, config.type.mono_weights),
        )
        if line
    ]
    return "\n".join(lines) if lines else "/* no web fonts configured */"


@deal.ensure(lambda config, result: result.startswith(("@import url(", "/* no web fonts")), message="stylesheet must start with the font rules")
@deal.ensure(lambda config, result: config.palette.bg in result, message="stylesheet must use the configured background")
def stylesheet(config: Config) -> str:
    """Return the complete stylesheet for this configuration."""
    context = config.page_context()
    lines = [":root {"]
    for section, key in VARIABLE_SECTIONS:
        lines.append(f"  {_variable_name(section, key)}: {context[section][key]};")
    lines.append("}")

    body = Template(read_text(STYLE_TEMPLATE)).substitute(
        reading=config.type.reading,
        mono=config.type.mono,
        md_size=config.type.md_size,
        md_table=config.type.md_table,
        code_size=config.type.code_size,
        md_width=config.layout.md_width,
        md_gutter=config.layout.md_gutter,
        listing_width=config.layout.listing_width,
    )
    return f"{font_imports(config)}\n\n" + "\n".join(lines) + "\n\n" + body


@lru_cache(maxsize=8)
def stylesheet_cached(config: Config) -> str:
    """Return the stylesheet, reusing the last result for an unchanged config."""
    return stylesheet(config)
