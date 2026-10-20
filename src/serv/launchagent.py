"""Start-at-login support: a per-user LaunchAgent.

The agent uses the same label as the existing installation (``local.serv``), so
enabling start-at-login replaces any hand-written plist rather than adding a
second copy of the server.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path

import deal

from .locations import LAUNCH_AGENT_LABEL, launch_agent_path, launch_agent_target, log_paths

# launchd starts agents with a minimal PATH; keep the Homebrew prefix so the
# noise-filter and any helper binaries stay reachable.
AGENT_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def executable_path() -> Path:
    """Return the program launchd should run.

    In the frozen build this is the serv binary itself; from a checkout it is
    the ``serv`` entry point of the current interpreter.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return Path(sys.executable)


def service_command() -> list[str]:
    """Return the ProgramArguments written into the plist.

    Inside the app bundle the launcher exports its own path, so the login item
    runs the same bundle the user is looking at. From a checkout it runs the
    module entry point, so the agent follows the code rather than whatever
    ``serv`` happens to be on PATH.
    """
    launcher = os.environ.get("SERV_APP_LAUNCHER")
    if launcher:
        return [launcher, "--agent"]
    if getattr(sys, "frozen", False):
        return [str(executable_path()), "--agent"]
    return [str(executable_path()), "-m", "serv", "--agent"]


def plist_contents(working_directory: Path | None = None) -> bytes:
    """Return the plist payload for the current installation."""
    stdout, stderr = log_paths()
    payload = {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": service_command(),
        "WorkingDirectory": str(working_directory or Path.home()),
        "EnvironmentVariables": {"PATH": AGENT_PATH},
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(stdout),
        "StandardErrorPath": str(stderr),
        "ProcessType": "Interactive",
    }
    return plistlib.dumps(payload)


def _launchctl(*arguments: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run launchctl and return the completed process (never raises on failure)."""
    return subprocess.run(
        ["launchctl", *arguments],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _wait_for(predicate, attempts: int = 20, interval: float = 0.1) -> bool:
    """Poll a predicate for up to attempts/interval."""
    for _ in range(attempts):
        if predicate():
            return True
        time.sleep(interval)
    return False


def is_installed() -> bool:
    """Return whether the LaunchAgent plist exists."""
    return launch_agent_path().is_file()


def is_running() -> bool:
    """Return whether launchd currently has the agent loaded."""
    return _launchctl("print", launch_agent_target(), timeout=10).returncode == 0


@deal.raises(RuntimeError)
def install(working_directory: Path | None = None) -> Path:
    """Write the plist and load it, replacing any previous version.

    Raises RuntimeError with launchctl's own message when the service does not
    come up, so the settings window can show something useful instead of
    claiming success.
    """
    target = launch_agent_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plist_contents(working_directory))

    # Unload the previous definition, and wait until the label is really gone:
    # bootstrapping while the old job is still registered fails with a plain
    # "Bad request".
    if is_running():
        _launchctl("bootout", launch_agent_target())
        _wait_for(lambda: not is_running())
    _launchctl("enable", launch_agent_target())

    last_error = ""
    for attempt in range(2):
        result = _launchctl("bootstrap", f"gui/{os.getuid()}", str(target))
        if result.returncode == 0:
            break
        last_error = (result.stderr or result.stdout).strip()
        # The older spelling still works on systems without bootstrap.
        fallback = _launchctl("load", "-w", str(target))
        if fallback.returncode == 0:
            last_error = ""
            break
        time.sleep(0.2 * (attempt + 1))

    if not _wait_for(is_running):
        raise RuntimeError(last_error or "launchd did not start the service")
    return target


def uninstall() -> None:
    """Unload the agent, disable it, and delete its plist."""
    _launchctl("bootout", launch_agent_target())
    _wait_for(lambda: not is_running(), attempts=10)
    _launchctl("disable", launch_agent_target())
    path = launch_agent_path()
    if path.is_file():
        path.unlink()


def restart() -> None:
    """Restart the loaded agent, picking up new code or settings."""
    _launchctl("kickstart", "-k", launch_agent_target())
