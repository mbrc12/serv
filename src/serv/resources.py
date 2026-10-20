"""Locate the files serv ships with itself.

Only application data lives here: the stylesheet template, the tray icon and
the default configuration. Every third-party library (Prism, KaTeX, fonts,
RDKit.js, Mermaid) is loaded from a CDN, so nothing else has to be found on
disk.

Three layouts are supported: running from a checkout, running from an
installed wheel, and the frozen binary.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import sys

import deal

DATA_DIR = "data"
CONFIG_NAME = Path("config") / "serv.toml"
SCHEMES_NAME = Path("config") / "schemes.toml"
STYLE_TEMPLATE = Path("style") / "serv.css"
TRAY_ICON = Path("tray") / "servTemplate.png"


@lru_cache(maxsize=1)
def data_dir() -> Path:
    """Return the directory holding the stylesheet template and tray icon."""
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / DATA_DIR)
    candidates.extend(parent / DATA_DIR for parent in Path(__file__).resolve().parents)
    candidates.append(Path(sys.prefix) / "share" / "serv" / DATA_DIR)
    for candidate in candidates:
        if (candidate / STYLE_TEMPLATE).is_file():
            return candidate
    searched = "\n  ".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(f"no serv data directory found in:\n  {searched}")


@deal.ensure(lambda relative, result=None: ".." not in Path(relative).parts, message="data path escapes the data directory")
def data_path(relative: str | Path) -> Path:
    """Return an absolute path to one file inside the data directory."""
    return data_dir() / Path(relative)


@lru_cache(maxsize=4)
def config_file(name: str) -> Path | None:
    """Return a bundled config file, e.g. "serv.toml" or "schemes.toml"."""
    relative = Path("config") / name
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(getattr(sys, "_MEIPASS", "")) / relative)
    candidates.extend(parent / relative for parent in Path(__file__).resolve().parents)
    candidates.append(Path(sys.prefix) / "share" / "serv" / relative)
    return next((path for path in candidates if path.is_file()), None)


def read_text(relative: str | Path) -> str:
    """Read one data file as text."""
    return data_path(relative).read_text()
