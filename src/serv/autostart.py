"""Start-at-login, per platform.

One small API for all three systems:

    is_installed() -> bool
    install(working_directory=None) -> Path        # where the definition lives
    uninstall() -> None
    restart() -> None                              # reload after an update

macOS uses a LaunchAgent, Linux a systemd user unit (falling back to an XDG
autostart entry when systemd is unavailable), and Windows the per-user Run key.

The definition builders are pure functions so their content can be tested on any
platform.
"""

from __future__ import annotations

import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import time

import deal

from .locations import log_paths as platform_log_paths

APP_NAME = "serv"
MACOS_LABEL = "local.serv"
SYSTEMD_UNIT = "serv.service"
DESKTOP_FILE = "serv.desktop"
WINDOWS_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

AGENT_FLAG = "--no-gui"


# ------------------------------------------------------------------- commands


def base_command() -> list[str]:
    """Return the program that starts the server without a window.

    Inside the macOS app bundle the launcher exports its own path, so the login
    item runs the same bundle the user launched. From a checkout or a Windows
    install it runs the module with the current interpreter.
    """
    launcher = os.environ.get("SERV_APP_LAUNCHER")
    if launcher:
        return [launcher]
    executable = Path(sys.executable)
    if getattr(sys, "frozen", False):
        return [str(executable)]
    if sys.platform == "win32":
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
    return [str(executable), "-m", "serv"]


def agent_command() -> list[str]:
    """Return the full command line for the login item."""
    return [*base_command(), AGENT_FLAG]


# --------------------------------------------------------------------- macOS


def launch_agent_path() -> Path:
    """Return ~/Library/LaunchAgents/local.serv.plist."""
    return Path("~/Library/LaunchAgents").expanduser() / f"{MACOS_LABEL}.plist"


def launch_agent_target() -> str:
    """Return the launchd service target, e.g. gui/501/local.serv."""
    return f"gui/{os.getuid()}/{MACOS_LABEL}"


def log_paths() -> tuple[Path, Path]:
    """Return the stdout and stderr log paths used by the macOS agent."""
    return platform_log_paths()


def plist_contents(working_directory: Path | None = None) -> bytes:
    """Return the LaunchAgent payload for the current installation."""
    stdout, stderr = log_paths()
    payload = {
        "Label": MACOS_LABEL,
        "ProgramArguments": agent_command(),
        "WorkingDirectory": str(working_directory or Path.home()),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"},
        "RunAtLoad": True,
        # No KeepAlive: quitting the tray must not be undone by launchd.
        "KeepAlive": False,
        "StandardOutPath": str(stdout),
        "StandardErrorPath": str(stderr),
        "ProcessType": "Interactive",
    }
    return plistlib.dumps(payload)


# --------------------------------------------------------------------- Linux


def systemd_unit_path() -> Path:
    """Return ~/.config/systemd/user/serv.service."""
    return Path("~/.config/systemd/user").expanduser() / SYSTEMD_UNIT


def desktop_entry_path() -> Path:
    """Return ~/.config/autostart/serv.desktop."""
    return Path("~/.config/autostart").expanduser() / DESKTOP_FILE


def systemd_available() -> bool:
    """Return whether this session can manage user services."""
    return shutil.which("systemctl") is not None


def systemd_unit(working_directory: Path | None = None) -> str:
    """Return the systemd user unit that starts serv at login."""
    command = " ".join(shlex.quote(part) for part in agent_command())
    return f"""[Unit]
Description=serv local file server
Documentation=https://localhost:1002/
After=default.target

[Service]
Type=simple
WorkingDirectory={working_directory or Path.home()}
ExecStart={command}
Restart=on-failure
RestartSec=2

[Install]
WantedBy=default.target
"""


def desktop_entry() -> str:
    """Return an XDG autostart entry, used when systemd is unavailable."""
    command = " ".join(shlex.quote(part) for part in agent_command())
    return f"""[Desktop Entry]
Type=Application
Name=serv
Comment=Local file server with rendered Markdown
Exec={command}
Terminal=false
X-GNOME-Autostart-enabled=true
"""


# ------------------------------------------------------------------- Windows


def windows_run_value() -> str:
    """Return the command line written to the per-user Run key."""
    return subprocess.list2cmdline(agent_command())


def _windows_registry():
    import winreg

    return winreg


# ------------------------------------------------------------------- helpers


def _run(*arguments: str, timeout: int = 20) -> subprocess.CompletedProcess:
    """Run a command, never raising on a non-zero exit."""
    return subprocess.run(list(arguments), capture_output=True, text=True, timeout=timeout)


def _wait_for(predicate, attempts: int = 20, interval: float = 0.1) -> bool:
    """Poll a predicate for up to attempts * interval."""
    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(interval)
    return False


def platform_name() -> str:
    """Return which implementation this process will use."""
    if sys.platform == "darwin":
        return "launchd"
    if sys.platform.startswith("win"):
        return "registry"
    return "systemd" if systemd_available() else "desktop"


# ---------------------------------------------------------------------- macOS


def _macos_installed() -> bool:
    return launch_agent_path().is_file()


def _macos_running() -> bool:
    return _run("launchctl", "print", launch_agent_target(), timeout=10).returncode == 0


@deal.raises(RuntimeError)
def _macos_install(working_directory: Path | None) -> Path:
    target = launch_agent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plist_contents(working_directory))
    if _macos_running():
        _run("launchctl", "bootout", launch_agent_target())
        _wait_for(lambda: not _macos_running())
    _run("launchctl", "enable", launch_agent_target())

    error = ""
    for attempt in range(2):
        result = _run("launchctl", "bootstrap", f"gui/{os.getuid()}", str(target))
        if result.returncode == 0:
            break
        error = (result.stderr or result.stdout).strip()
        if _run("launchctl", "load", "-w", str(target)).returncode == 0:
            error = ""
            break
        time.sleep(0.2 * (attempt + 1))
    if not _wait_for(_macos_running):
        raise RuntimeError(error or "launchd did not start the service")
    return target


def _macos_uninstall() -> None:
    _run("launchctl", "bootout", launch_agent_target())
    _wait_for(lambda: not _macos_running(), attempts=10)
    _run("launchctl", "disable", launch_agent_target())
    launch_agent_path().unlink(missing_ok=True)


def _macos_restart() -> None:
    _run("launchctl", "kickstart", "-k", launch_agent_target())


# ---------------------------------------------------------------------- Linux


def _linux_installed() -> bool:
    return systemd_unit_path().is_file() or desktop_entry_path().is_file()


def _linux_install(working_directory: Path | None) -> Path:
    if systemd_available():
        path = systemd_unit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(systemd_unit(working_directory))
        _run("systemctl", "--user", "daemon-reload")
        _run("systemctl", "--user", "enable", "--now", SYSTEMD_UNIT)
        return path
    path = desktop_entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(desktop_entry())
    path.chmod(0o755)
    return path


def _linux_uninstall() -> None:
    if systemd_unit_path().is_file():
        _run("systemctl", "--user", "disable", "--now", SYSTEMD_UNIT)
        systemd_unit_path().unlink(missing_ok=True)
        _run("systemctl", "--user", "daemon-reload")
    desktop_entry_path().unlink(missing_ok=True)


def _linux_restart() -> None:
    if systemd_available() and systemd_unit_path().is_file():
        _run("systemctl", "--user", "restart", SYSTEMD_UNIT)


# -------------------------------------------------------------------- Windows


def _windows_installed() -> bool:
    if sys.platform != "win32":
        return False
    winreg = _windows_registry()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(value)
    except FileNotFoundError:
        return False


def _windows_install(working_directory: Path | None) -> Path:
    winreg = _windows_registry()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, windows_run_value())
    # The "path" is registry location, shown as-is in the settings window.
    return Path(f"HKCU\\{WINDOWS_RUN_KEY}\\{APP_NAME}")


def _windows_uninstall() -> None:
    if sys.platform != "win32":
        return
    winreg = _windows_registry()
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, WINDOWS_RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, APP_NAME)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- public API


def is_installed() -> bool:
    """Return whether serv starts at login on this system."""
    if sys.platform == "darwin":
        return _macos_installed()
    if sys.platform.startswith("win"):
        return _windows_installed()
    return _linux_installed()


@deal.raises(RuntimeError)
def install(working_directory: Path | None = None) -> Path:
    """Install the login item and return where its definition lives."""
    if sys.platform == "darwin":
        return _macos_install(working_directory)
    if sys.platform.startswith("win"):
        return _windows_install(working_directory)
    return _linux_install(working_directory)


def uninstall() -> None:
    """Remove the login item."""
    if sys.platform == "darwin":
        _macos_uninstall()
    elif sys.platform.startswith("win"):
        _windows_uninstall()
    else:
        _linux_uninstall()


def restart() -> None:
    """Restart the login item, picking up new code or settings."""
    if sys.platform == "darwin":
        _macos_restart()
    elif sys.platform.startswith("win"):
        return
    else:
        _linux_restart()


def definition_path() -> Path | None:
    """Return where the login item is defined on this system, if it is."""
    if sys.platform == "darwin":
        return launch_agent_path()
    if sys.platform.startswith("win"):
        return Path(f"HKCU\\{WINDOWS_RUN_KEY}\\{APP_NAME}")
    return systemd_unit_path() if systemd_available() else desktop_entry_path()
