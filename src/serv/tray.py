"""Tray icon, via pystray, on every platform.

pystray gives one API over NSStatusBar on macOS, the Win32 notification area on
Windows and AppIndicator/XEmbed on Linux. The icon image is the white-with-outline
glyph, which stays legible on light and dark panels without asking the OS.

The settings window is a separate process (``serv --settings``) because both Tk
and the tray want the main thread; the server and this tray keep the main thread,
and the window exits on close while the tray stays.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
import time
import webbrowser

import pystray
from PIL import Image

from . import appearance, autostart
from .server import ServerRunner, Snapshot
from .resources import TRAY_GLYPH_DARK, TRAY_GLYPH_LIGHT, data_path

REFRESH_SECONDS = 2.0
APPEARANCE_SECONDS = 10.0


def _copy_to_clipboard(text: str) -> bool:
    """Copy text with whatever clipboard tool the platform provides."""
    commands: list[list[str]] = []
    if sys.platform == "darwin":
        commands = [["pbcopy"]]
    elif sys.platform.startswith("win"):
        commands = [["clip"]]
    else:
        for tool in ("wl-copy", "xclip", "xsel"):
            if shutil.which(tool) is None:
                continue
            if tool == "xclip":
                commands.append([tool, "-selection", "clipboard"])
            elif tool == "xsel":
                commands.append([tool, "--clipboard", "--input"])
            else:
                commands.append([tool])
    for command in commands:
        try:
            subprocess.run(command, input=text.encode(), check=True, timeout=10)
            return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _macos_template_image():
    """Return a sharp template NSImage for the macOS menu bar.

    pystray resizes whatever image it is given to the status bar thickness (22
    pixels), which is soft on a Retina display. This builds an 18-point image from
    the 2x and 4x glyphs and marks it as a template, so macOS draws the right
    number of pixels and inverts it for dark menu bars on its own.
    """
    from AppKit import NSBitmapImageRep, NSData, NSImage

    image = NSImage.alloc().initWithSize_((18, 18))
    for scale in (2, 4):
        path = data_path(f"tray/servTemplate@{scale}x.png")
        if not path.is_file():
            continue
        rep = NSBitmapImageRep.imageRepWithData_(
            NSData.dataWithContentsOfFile_(str(path))
        )
        if rep is None:
            continue
        rep.setSize_((18, 18))
        image.addRepresentation_(rep)
    image.setTemplate_(True)
    return image


def _apply_macos_template(icon, attempts: int = 50) -> None:
    """Replace pystray's scaled bitmap once the status item is on screen."""
    import time as clock

    for _ in range(attempts):
        button = getattr(getattr(icon, "_status_item", None), "button", lambda: None)()
        if button is not None and button.image() is not None:
            button.setImage_(_macos_template_image())
            return
        clock.sleep(0.1)


def tray_image() -> Image.Image:
    """Return the glyph that matches the current menu bar or taskbar."""
    path = data_path(TRAY_GLYPH_DARK if appearance.is_dark() else TRAY_GLYPH_LIGHT)
    return Image.open(path)


def _settings_command() -> list[str]:
    """Return the command that opens the settings window."""
    return [*autostart.base_command(), "--settings"]


def open_settings() -> None:
    """Open the settings window in its own process."""
    subprocess.Popen(_settings_command(), close_fds=True)


def _error_line(snapshot: Snapshot) -> str:
    if not snapshot.last_error:
        return "No errors"
    when = time.strftime("%H:%M", time.localtime(snapshot.last_error_time or 0))
    return f"{when} · {snapshot.last_error[:60]}"


class Tray:
    """A pystray icon that reflects and controls one running server."""

    def __init__(self, runner: ServerRunner) -> None:
        self.runner = runner
        self.state = runner.state
        self.url = runner.url
        self._stop_refresh = threading.Event()
        self._dark = appearance.is_dark()
        self.icon = pystray.Icon(
            "serv",
            icon=tray_image(),
            title="serv",
            menu=pystray.Menu(
                pystray.MenuItem(self._status_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Open in Browser", self._open, default=True),
                pystray.MenuItem("Copy URL", self._copy),
                pystray.MenuItem(
                    lambda _item: "Resume" if self.state.snapshot().paused else "Pause",
                    self._toggle_pause,
                ),
                pystray.MenuItem(
                    "Start at login",
                    self._toggle_login,
                    checked=lambda _item: autostart.is_installed(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(self._cache_text, None, enabled=False),
                pystray.MenuItem(self._error_text, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Settings…", self._open_settings),
                pystray.MenuItem("Quit serv", self._quit),
            ),
        )

    # ------------------------------------------------------------- labels

    def _status_text(self, _item=None) -> str:
        snapshot = self.state.snapshot()
        state_word = "paused" if snapshot.paused else "serving"
        return f"{state_word} · {self.url} · {snapshot.requests} requests"

    def _cache_text(self, _item=None) -> str:
        snapshot = self.state.snapshot()
        return (
            f"{snapshot.cached_pages} pages cached · "
            f"{snapshot.cache_hits} hits / {snapshot.cache_misses} misses"
        )

    def _error_text(self, _item=None) -> str:
        return _error_line(self.state.snapshot())

    # ------------------------------------------------------------ actions

    def _open(self, _icon=None, _item=None) -> None:
        webbrowser.open(self.url)

    def _copy(self, _icon=None, _item=None) -> None:
        _copy_to_clipboard(self.url)

    def _toggle_pause(self, _icon=None, _item=None) -> None:
        # Pausing releases the port, so another program can take it while serv
        # is idle; resuming binds it again.
        self.runner.toggle()
        self._refresh()

    def _toggle_login(self, _icon=None, _item=None) -> None:
        try:
            if autostart.is_installed():
                autostart.uninstall()
            else:
                autostart.install()
        except Exception as error:  # noqa: BLE001 - report, never crash the server
            self.state.note_error(f"login item: {error}")
        self._refresh()

    def _open_settings(self, _icon=None, _item=None) -> None:
        open_settings()

    def _quit(self, _icon=None, _item=None) -> None:
        self._stop_refresh.set()
        self.icon.stop()
        threading.Thread(target=self.runner.shutdown, daemon=True).start()

    # ------------------------------------------------------------ refresh

    def _refresh(self) -> None:
        try:
            self.icon.update_menu()
        except Exception:  # noqa: BLE001 - the icon may already be gone
            pass

    def _refresh_loop(self) -> None:
        waited = 0.0
        while not self._stop_refresh.wait(REFRESH_SECONDS):
            self._refresh()
            waited += REFRESH_SECONDS
            if waited >= APPEARANCE_SECONDS:
                waited = 0.0
                self._follow_appearance()

    def _follow_appearance(self) -> None:
        """Swap the glyph when the system switches between light and dark."""
        if sys.platform == "darwin":
            return  # the template image already follows the menu bar
        dark = appearance.is_dark()
        if dark == self._dark:
            return
        self._dark = dark
        try:
            self.icon.icon = tray_image()
        except Exception:  # noqa: BLE001 - the icon may already be gone
            pass

    def run(self) -> None:
        """Run the tray on the main thread until it is quit."""
        refresh = threading.Thread(
            target=self._refresh_loop, name="serv-tray-refresh", daemon=True
        )
        refresh.start()
        if sys.platform == "darwin":
            threading.Thread(
                target=_apply_macos_template, args=(self.icon,), daemon=True
            ).start()
        self.icon.run()


def run_tray(runner: ServerRunner) -> bool:
    """Show the tray, returning False when this session cannot display one."""
    try:
        Tray(runner).run()
    except Exception as error:  # noqa: BLE001 - headless sessions have no tray
        print(f"tray unavailable ({type(error).__name__}: {error}); serving without it", flush=True)
        return False
    return True
