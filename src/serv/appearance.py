"""Light or dark UI, as reported by the operating system.

The tray needs to know which glyph to draw: a black one on a light menu bar and
a white one on a dark one. Both choices are crisp; a two-tone glyph that tries to
work on both turns to mush at 22 pixels.

``SERV_TRAY_ICON=light|dark`` overrides detection, which is handy on Linux
panels that do not expose their theme.
"""

from __future__ import annotations

import os
import subprocess
import sys


def override() -> bool | None:
    """Return a forced value when SERV_TRAY_ICON asks for one."""
    value = os.environ.get("SERV_TRAY_ICON", "").strip().lower()
    if value in {"light", "dark"}:
        return value == "dark"
    return None


def is_dark() -> bool:
    """Return whether the desktop is using its dark appearance."""
    forced = override()
    if forced is not None:
        return forced
    if sys.platform == "darwin":
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip().lower() == "dark"
    if sys.platform.startswith("win"):
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                light, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
            return not light
        except (OSError, ImportError):
            return True
    return False
