"""Where serv keeps its user-level files.

The configuration lives in the platform's usual place for application settings:
``~/.config`` (or ``$XDG_CONFIG_HOME``) on macOS and Linux, ``%APPDATA%`` on
Windows. Nothing is written unless the user saves settings or asks for
start-at-login.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys

APP_NAME = "serv"


def config_home() -> Path:
    """Return the base directory for user configuration on this platform."""
    if sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        return Path(appdata).expanduser() if appdata else Path("~/AppData/Roaming").expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base).expanduser() if base else Path("~/.config").expanduser()


def user_config_path() -> Path:
    """Return the per-user configuration file."""
    return config_home() / APP_NAME / "serv.toml"


def log_paths() -> tuple[Path, Path]:
    """Return the stdout and stderr log paths used by the login item on macOS."""
    logs = Path("~/Library/Logs").expanduser()
    return logs / "serv.log", logs / "serv.err.log"
