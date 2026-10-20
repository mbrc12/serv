"""Load, validate and write the TOML configuration.

Precedence: ``--config PATH``, then ``$SERV_CONFIG``, then the user file
``~/.config/serv/serv.toml``, then the copy bundled beside the package. When no
user file exists the bundled defaults are used in memory, so serv runs without
ever writing anything.

Colors are validated at startup so a typo fails loudly instead of producing a
page with one invisible element.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from functools import lru_cache
import os
from pathlib import Path
import re
import sys
import tomllib

import deal

from .locations import user_config_path

CONFIG_ENV = "SERV_CONFIG"

CONFIG_NAME = Path("config") / "serv.toml"

# Accepted color syntaxes: #rgb, #rrggbb, #rrggbbaa, rgb()/rgba()/hsl(), and
# the CSS-wide keywords. Everything else is a typo.
_COLOR = re.compile(
    r"""^(?:
        \#[0-9a-fA-F]{3,8}
      | (?:rgb|rgba|hsl|hsla)\([^()]*\)
      | transparent
      | currentColor
    )$""",
    re.VERBOSE,
)
CSS_LENGTH = re.compile(r"^(?:\d+(?:\.\d+)?)(?:px|rem|em|ch|%)$")
FONT_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9 \-]*$")
NUMBER = re.compile(r"^\d+(?:\.\d+)?$")
FONT_WEIGHTS = re.compile(r"^(?:[a-z]+(?:,[a-z]+)*@[0-9;,]+)?$")


class ConfigError(ValueError):
    """Raised when the configuration file is present but invalid."""


@dataclass(frozen=True)
class ServerSection:
    port: int = 1002
    # File paths matching any of these globs are served verbatim: no Markdown
    # rendering and no syntax highlighting. `**` crosses directory separators.
    no_process: tuple[str, ...] = ("~/dev/game/**/build/**",)
    # Files larger than this are served as plain text instead of being rendered
    # or highlighted, so one huge file cannot stall the server.
    max_render_bytes: int = 1_048_576


@dataclass(frozen=True)
class CacheSection:
    entries: int = 64


@dataclass(frozen=True)
class Palette:
    bg: str
    text: str
    muted: str
    border: str
    hover: str
    selected: str
    #: Text that sits on a selected surface, e.g. a table header.
    selected_text: str
    zebra: str
    red: str
    orange: str
    green: str
    blue: str
    teal: str
    purple: str

    def as_dict(self) -> dict[str, str]:
        return dict(vars(self))


@dataclass(frozen=True)
class Accents:
    markdown: str
    listing: str
    directory: str


@dataclass(frozen=True)
class CodePalette:
    base: str
    comment: str
    keyword: str
    operator: str
    string: str
    function: str
    number: str
    tag: str
    highlight: str
    #: Surface behind a code block on a Markdown page, and its border.
    block_bg: str
    block_border: str


@dataclass(frozen=True)
class Typography:
    reading: str
    mono: str
    # Google Fonts axis query for each family. Empty means "a font installed on
    # this Mac": the stylesheet then uses the family name without an import.
    reading_weights: str = "ital,wght@0,400;0,600;1,400"
    mono_weights: str = "wght@400;600"
    md_size: str = "1.2rem"
    md_table: str = "1.1rem"
    code_size: str = "12px"
    #: Multiple of the font size, e.g. "1.65".
    line_height: str = "1.65"
    underline_links: bool = True


@dataclass(frozen=True)
class Layout:
    md_width: str
    md_gutter: str
    listing_width: str


@dataclass(frozen=True)
class Config:
    server: ServerSection
    cache: CacheSection
    palette: Palette
    accents: Accents
    code: CodePalette
    type: Typography
    layout: Layout
    source: Path | None = None

    def page_context(self) -> dict[str, dict[str, str]]:
        """Return the section mapping the stylesheet template substitutes into."""
        return {
            "palette": self.palette.as_dict(),
            "accents": vars(self.accents),
            "code": vars(self.code),
            "type": vars(self.type),
            "layout": vars(self.layout),
        }


@lru_cache(maxsize=1)
def default_config_path() -> Path | None:
    """Return the config file that ships with this installation, if any.

    Covers all three layouts: the frozen binary (``config/`` next to the
    unpacked data), a checkout (``config/`` beside ``src/``), and a wheel
    install under ``sys.prefix``.
    """
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / CONFIG_NAME)
    candidates.extend(parent / CONFIG_NAME for parent in Path(__file__).resolve().parents)
    candidates.append(Path(sys.prefix) / "share" / "serv" / CONFIG_NAME)
    return next((path for path in candidates if path.is_file()), None)


def resolve_config_path(explicit: str | None) -> Path | None:
    """Pick the configuration file to read, or None to use embedded defaults."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        return path
    from_environment = os.environ.get(CONFIG_ENV)
    if from_environment:
        path = Path(from_environment).expanduser()
        if not path.is_file():
            raise ConfigError(f"{CONFIG_ENV} points at a missing file: {path}")
        return path
    user = user_config_path()
    if user.is_file():
        return user
    return default_config_path()


def _require_mapping(section: object, name: str) -> dict:
    if not isinstance(section, dict):
        raise ConfigError(f"[{name}] must be a table")
    return section


@lru_cache(maxsize=1)
def bundled_section(section: str) -> dict:
    """Return one section of the shipped defaults, unvalidated.

    New colour keys appear from time to time; a config file written by an older
    version simply lacks them. Falling back to the bundled value keeps those
    files working, while a present-but-invalid value still fails loudly.
    """
    path = default_config_path()
    if path is None:
        return {}
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError:
        return {}
    table = data.get(section)
    return table if isinstance(table, dict) else {}


def _raw(section: dict, key: str, where: str):
    """Return a configured value, falling back to the bundled default.

    Keys added in later versions are simply absent from older config files;
    taking the shipped default keeps those files working.
    """
    if key in section:
        return section[key]
    return bundled_section(where).get(key)


def _color(section: dict, key: str, where: str) -> str:
    value = _raw(section, key, where)
    if not isinstance(value, str) or not _COLOR.match(value):
        raise ConfigError(f"{where}.{key} is not a CSS color: {value!r}")
    return value


def _length(section: dict, key: str, where: str) -> str:
    value = _raw(section, key, where)
    if not isinstance(value, str) or not CSS_LENGTH.match(value):
        raise ConfigError(f"{where}.{key} is not a CSS length: {value!r}")
    return value


def _font(section: dict, key: str, where: str) -> str:
    value = _raw(section, key, where)
    if not isinstance(value, str) or not FONT_NAME.match(value):
        raise ConfigError(f"{where}.{key} is not a font family name: {value!r}")
    return value


def _glob_list(value: object, where: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ConfigError(f"{where} must be a list of glob patterns, got {value!r}")
    patterns: list[str] = []
    for pattern in value:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ConfigError(f"{where} contains an empty or non-string pattern: {pattern!r}")
        patterns.append(os.path.expanduser(pattern.strip()))
    return tuple(patterns)


def _number(section: dict, key: str, where: str) -> str:
    value = _raw(section, key, where)
    if not isinstance(value, str) or not NUMBER.match(value.strip()):
        raise ConfigError(f"{where}.{key} is not a number: {value!r}")
    return value.strip()


def _boolean(section: dict, key: str, where: str, default: bool) -> bool:
    value = section.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be true or false, got {value!r}")
    return value


def _weights(section: dict, key: str, where: str) -> str | None:
    """Read a weights query; None means the key is absent (derive it)."""
    if key not in section:
        return None
    value = section[key]
    if not isinstance(value, str) or not FONT_WEIGHTS.match(value):
        raise ConfigError(f"{where}.{key} is not a Google Fonts weights query: {value!r}")
    return value


def _integer(value: object, where: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{where} must be an integer, got {value!r}")
    if not minimum <= value <= maximum:
        raise ConfigError(f"{where} must be between {minimum} and {maximum}, got {value}")
    return value


@deal.raises(ConfigError)
@deal.ensure(lambda data, source=None, result=None: isinstance(result, Config))
def parse_config(data: dict, source: Path | None = None) -> Config:
    """Build a validated Config from parsed TOML."""
    server = _require_mapping(data.get("server", {}), "server")
    cache = _require_mapping(data.get("cache", {}), "cache")
    palette = _require_mapping(data.get("palette"), "palette")
    accents = _require_mapping(data.get("accents"), "accents")
    code = _require_mapping(data.get("code"), "code")
    typography = _require_mapping(data.get("type"), "type")
    layout = _require_mapping(data.get("layout"), "layout")

    reading = _font(typography, "reading", "type")
    mono = _font(typography, "mono", "type")
    reading_weights = _weights(typography, "reading_weights", "type")
    mono_weights = _weights(typography, "mono_weights", "type")
    if reading_weights is None or mono_weights is None:
        # Configs written before the weights keys existed: derive them from the
        # font catalog, so a known Google family still loads its webfont.
        from . import fonts as font_catalog

        if reading_weights is None:
            reading_weights = font_catalog.weights_for("reading", reading) or ""
        if mono_weights is None:
            mono_weights = font_catalog.weights_for("mono", mono) or ""

    return Config(
        server=ServerSection(
            port=_integer(server.get("port", 1002), "server.port", 1, 65535),
            no_process=_glob_list(server.get("no_process", ()), "server.no_process"),
            max_render_bytes=_integer(
                server.get("max_render_bytes", 1_048_576),
                "server.max_render_bytes",
                1024,
                1 << 32,
            ),
        ),
        cache=CacheSection(
            entries=_integer(cache.get("entries", 64), "cache.entries", 1, 4096)
        ),
        palette=Palette(**{key: _color(palette, key, "palette") for key in Palette.__annotations__}),
        accents=Accents(**{key: _color(accents, key, "accents") for key in Accents.__annotations__}),
        code=CodePalette(**{key: _color(code, key, "code") for key in CodePalette.__annotations__}),
        type=Typography(
            reading=reading,
            mono=mono,
            reading_weights=reading_weights,
            mono_weights=mono_weights,
            md_size=_length(typography, "md_size", "type"),
            md_table=_length(typography, "md_table", "type"),
            code_size=_length(typography, "code_size", "type"),
            line_height=_number(typography, "line_height", "type"),
            underline_links=_boolean(typography, "underline_links", "type", True),
        ),
        layout=Layout(
            md_width=_length(layout, "md_width", "layout"),
            md_gutter=_length(layout, "md_gutter", "layout"),
            listing_width=_length(layout, "listing_width", "layout"),
        ),
        source=source,
    )


def embedded_config_text() -> str:
    """Return the default configuration bundled with the binary."""
    path = default_config_path()
    if path is None:
        raise ConfigError("no bundled default configuration found")
    return path.read_text()


@deal.raises(ConfigError)
def load_config(explicit: str | None = None) -> Config:
    """Load the configuration, falling back to the bundled defaults."""
    path = resolve_config_path(explicit)
    try:
        if path is None:
            text = embedded_config_text()
            return parse_config(tomllib.loads(text), None)
        with path.open("rb") as handle:
            return parse_config(tomllib.load(handle), path)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path or '<embedded>'}: {error}") from error


# --------------------------------------------------------------------- writing

_HEADER = """\
# serv configuration. Every color the server emits lives here; the Python
# source only reads these keys. Saved by the settings window, safe to edit by
# hand: a bad value is reported at startup instead of failing silently.
"""


def _quote(value: str) -> str:
    """Return a TOML basic string for a value."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _abbreviate_home(path: str) -> str:
    """Show the home directory as ``~`` so patterns stay readable and portable."""
    home = str(Path.home())
    return "~" + path[len(home) :] if path.startswith(home) else path


def _color_block(name: str, comment: str, mapping: dict[str, str]) -> str:
    lines = [f"[{name}]", comment]
    width = max(len(key) for key in mapping)
    lines.extend(f"{key.ljust(width)} = {_quote(value)}" for key, value in mapping.items())
    return "\n".join(lines)


@deal.ensure(
    lambda config, result: replace(load_config_text(result), source=config.source) == config,
    message="serialized config must load back identically",
)
def dump_config(config: Config) -> str:
    """Serialise a Config as commented TOML that loads back identically."""
    patterns = [_abbreviate_home(pattern) for pattern in config.server.no_process]
    no_process = ", ".join(_quote(pattern) for pattern in patterns)
    sections = [
        _HEADER,
        "[server]",
        f"port = {config.server.port}",
        "# Absolute file paths matching any of these globs are served verbatim: no",
        "# Markdown rendering and no syntax highlighting. `**` crosses directories, and",
        "# a leading `~` means the home directory.",
        f"no_process = [{no_process}]",
        "# Files larger than this many bytes are served as plain text instead of",
        "# being rendered or highlighted.",
        f"max_render_bytes = {config.server.max_render_bytes}",
        "",
        "[cache]",
        "# Rendered-Markdown entries kept in memory; each entry is one page of HTML.",
        f"entries = {config.cache.entries}",
        "",
        _color_block("palette", "# Surfaces and the base syntax colors.", config.palette.as_dict()),
        "",
        _color_block("accents", "# One accent per surface.", vars(config.accents)),
        "",
        _color_block("code", "# Source-page tokens on the flat canvas.", vars(config.code)),
        "",
        "[type]",
        f"reading   = {_quote(config.type.reading)}",
        f"mono      = {_quote(config.type.mono)}",
        "# Google Fonts axis queries. Leave empty to use a font installed on this",
        "# Mac instead of downloading one.",
        f"reading_weights = {_quote(config.type.reading_weights)}",
        f"mono_weights    = {_quote(config.type.mono_weights)}",
        f"md_size   = {_quote(config.type.md_size)}",
        f"md_table  = {_quote(config.type.md_table)}",
        f"code_size = {_quote(config.type.code_size)}",
        f"line_height = {_quote(config.type.line_height)}",
        f"underline_links = {str(config.type.underline_links).lower()}",
        "",
        "[layout]",
        f"md_width      = {_quote(config.layout.md_width)}",
        f"md_gutter     = {_quote(config.layout.md_gutter)}",
        f"listing_width = {_quote(config.layout.listing_width)}",
    ]
    return "\n".join(sections) + "\n"


def load_config_text(text: str) -> Config:
    """Parse configuration text, raising ConfigError on any problem."""
    try:
        return parse_config(tomllib.loads(text), None)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(str(error)) from error


@deal.raises(ConfigError)
def save_config(config: Config, path: Path | None = None) -> Path:
    """Write the configuration to the user config file, creating directories.

    The text is validated by loading it back before it replaces the existing
    file, so a failed save cannot leave an unreadable configuration behind.
    """
    target = path or user_config_path()
    text = dump_config(config)
    load_config_text(text)  # round-trip check: never write something unloadable
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".toml.tmp")
    temporary.write_text(text)
    temporary.replace(target)
    return target
