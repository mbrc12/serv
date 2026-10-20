"""Start-at-login definitions for each platform."""

from __future__ import annotations

import plistlib
from pathlib import Path

from serv import autostart


def test_agent_command_ends_with_the_agent_flag() -> None:
    assert autostart.agent_command()[-1] == "--no-gui"


def test_launch_agent_plist_points_at_the_installation() -> None:
    payload = plistlib.loads(autostart.plist_contents(Path.home()))
    assert payload["Label"] == "local.serv"
    assert payload["RunAtLoad"] is True
    assert payload["KeepAlive"] is False
    assert payload["WorkingDirectory"] == str(Path.home())
    assert payload["ProgramArguments"][-1] == "--no-gui"
    assert "serv" in payload["ProgramArguments"][0]


def test_systemd_unit_starts_the_server() -> None:
    unit = autostart.systemd_unit(Path("/home/someone"))
    assert "ExecStart=" in unit
    assert "--no-gui" in unit
    assert "WorkingDirectory=/home/someone" in unit
    assert "WantedBy=default.target" in unit


def test_desktop_entry_is_an_application() -> None:
    entry = autostart.desktop_entry()
    assert entry.startswith("[Desktop Entry]")
    assert "Type=Application" in entry
    assert "Exec=" in entry and "--no-gui" in entry
    assert "Terminal=false" in entry


def test_windows_run_value_quotes_a_path_with_spaces() -> None:
    value = autostart.windows_run_value()
    assert "--no-gui" in value


def test_platform_name_is_known() -> None:
    assert autostart.platform_name() in {"launchd", "registry", "systemd", "desktop"}


def test_definition_path_is_absolute_or_registry_key() -> None:
    path = autostart.definition_path()
    assert path is not None
    assert str(path).startswith(("/", "HKCU\\"))
