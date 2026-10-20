"""Where serv keeps its user-level files.

The config lives in the XDG config home; the launch agent in the standard
LaunchAgents directory. Nothing is written unless the user saves settings or
asks for start-at-login.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Label of the LaunchAgent shared with the existing installation.
LAUNCH_AGENT_LABEL = "local.serv"

#: Bundle identifier used by launchd for the agent.
LAUNCH_AGENT_DOMAIN = "gui"

APP_NAME = "serv"


def config_home() -> Path:
    """Return the base directory for user configuration ($XDG_CONFIG_HOME)."""
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base).expanduser() if base else Path("~/.config").expanduser()


def user_config_path() -> Path:
    """Return ~/.config/serv/serv.toml."""
    return config_home() / APP_NAME / "serv.toml"


def launch_agent_path() -> Path:
    """Return ~/Library/LaunchAgents/local.serv.plist."""
    return Path("~/Library/LaunchAgents").expanduser() / f"{LAUNCH_AGENT_LABEL}.plist"


def log_paths() -> tuple[Path, Path]:
    """Return the stdout and stderr log paths used by the agent."""
    logs = Path("~/Library/Logs").expanduser()
    return logs / "serv.log", logs / "serv.err.log"


def launch_agent_target() -> str:
    """Return the launchd service target, e.g. gui/501/local.serv."""
    return f"{LAUNCH_AGENT_DOMAIN}/{os.getuid()}/{LAUNCH_AGENT_LABEL}"
