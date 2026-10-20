"""Menu-bar status item.

The HTTP server runs on a worker thread; ``NSApplication`` must own the main
thread, so ``Tray.run()`` blocks there. Every value the menu shows comes from
``ServerState.snapshot()``, so the tray never touches handler internals.

The item shows the icon alone — no port number in the menu bar — and the menu
carries the address, counters and the settings window.
"""

from __future__ import annotations

from pathlib import Path as FilePath
import threading
import time
import webbrowser

import rumps
from AppKit import NSBitmapImageRep, NSData, NSImage

from . import launchagent, ui
from .config import Config
from .resources import TRAY_ICON, data_path
from .server import ServerState, Snapshot

REFRESH_SECONDS = 2.0

#: Menu-bar height is about 22 points; 18 leaves the icon on its own baseline.
ICON_POINTS = 18

#: Rasterised sizes, one per display scale, so the icon is never upscaled.
ICON_FILES = (
    (1, "servTemplate.png"),
    (2, "servTemplate@2x.png"),
    (3, "servTemplate@3x.png"),
    (4, "servTemplate@4x.png"),
)


def status_image() -> NSImage:
    """Build the status image from every rasterised scale.

    Assigning each representation the same point size lets macOS pick the
    pixels that match the display, which is what keeps the glyph sharp instead
    of upscaling the 1x bitmap.
    """
    image = NSImage.alloc().initWithSize_((ICON_POINTS, ICON_POINTS))
    for _, name in ICON_FILES:
        path = data_path(TRAY_ICON.parent / name)
        if not path.is_file():
            continue
        data = NSData.dataWithContentsOfFile_(str(path))
        if data is None:
            continue
        representation = NSBitmapImageRep.imageRepWithData_(data)
        if representation is None:
            continue
        representation.setSize_((ICON_POINTS, ICON_POINTS))
        image.addRepresentation_(representation)
    image.setTemplate_(True)
    return image


def _copy_to_clipboard(text: str) -> None:
    """Put text on the system pasteboard."""
    from AppKit import NSPasteboard, NSPasteboardTypeString

    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    pasteboard.setString_forType_(text, NSPasteboardTypeString)


def _error_line(snapshot: Snapshot) -> str:
    if not snapshot.last_error:
        return "No errors"
    when = time.strftime("%H:%M", time.localtime(snapshot.last_error_time or 0))
    message = snapshot.last_error
    return f"{when} · {message[:60]}"


class Tray:
    """A rumps status item that reflects and controls one server."""

    def __init__(self, state: ServerState, url: str, server, show_settings: bool = False) -> None:
        self.state = state
        self.url = url
        self.server = server
        self.app = rumps.App(
            "serv",
            title=None,
            icon=str(data_path(TRAY_ICON)),
            template=True,
            quit_button=None,
        )
        # Replace rumps' single-bitmap image with the multi-scale one.
        self.app._icon_nsimage = status_image()

        self.status_item = rumps.MenuItem("Starting…", callback=None)
        self.pause_item = rumps.MenuItem("Pause", callback=self._toggle_pause)
        self.cache_item = rumps.MenuItem("", callback=None)
        self.error_item = rumps.MenuItem("", callback=None)
        self.login_item = rumps.MenuItem(
            "Start at login", callback=self._toggle_login
        )
        self.login_item.state = launchagent.is_installed()
        self.app.menu = [
            self.status_item,
            None,
            rumps.MenuItem("Open in Browser", callback=self._open),
            rumps.MenuItem("Copy URL", callback=self._copy),
            self.pause_item,
            self.login_item,
            None,
            self.cache_item,
            self.error_item,
            None,
            rumps.MenuItem("Settings…", callback=self._open_settings),
            None,
            rumps.MenuItem("Quit serv", callback=self._quit),
        ]
        self.settings_window = None
        self.timer = rumps.Timer(self._refresh, REFRESH_SECONDS)
        self.timer.start()
        if show_settings:
            # The window is opened once the run loop is up, so AppKit is ready.
            self.launch_timer = rumps.Timer(self._open_on_launch, 0.4)
            self.launch_timer.start()
        self._refresh(None)

    def _open_on_launch(self, timer) -> None:
        timer.stop()
        self._open_settings(None)
        ui.ask_start_at_login_if_needed()

    # ------------------------------------------------------------- actions

    def _open(self, _sender) -> None:
        webbrowser.open(self.url)

    def _copy(self, _sender) -> None:
        _copy_to_clipboard(self.url)

    def _toggle_pause(self, _sender) -> None:
        self.state.toggle_paused()
        self._refresh(None)

    def _toggle_login(self, _sender) -> None:
        try:
            if launchagent.is_installed():
                launchagent.uninstall()
            else:
                launchagent.install(FilePath.home())
        except Exception as error:  # noqa: BLE001 - report, never crash the server
            rumps.alert("Could not update the login item", str(error))
        self.login_item.state = launchagent.is_installed()
        self._refresh(None)

    def _open_settings(self, _sender) -> None:
        self.settings_window = ui.show_settings(self.state.config, self._apply_config)

    def _apply_config(self, config: Config) -> None:
        self.state.apply_config(config)

    def _quit(self, _sender) -> None:
        self.timer.stop()
        threading.Thread(target=self.server.shutdown, daemon=True).start()
        rumps.quit_application()

    # ------------------------------------------------------------ refresh

    def _refresh(self, _timer) -> None:
        snapshot = self.state.snapshot()
        state_word = "paused" if snapshot.paused else "serving"
        self.status_item.title = f"{state_word} · {self.url} · {snapshot.requests} requests"
        self.pause_item.title = "Resume" if snapshot.paused else "Pause"
        self.login_item.state = launchagent.is_installed()
        self.cache_item.title = (
            f"{snapshot.cached_pages} pages cached · "
            f"{snapshot.cache_hits} hits / {snapshot.cache_misses} misses"
        )
        self.error_item.title = _error_line(snapshot)

    def run(self) -> None:
        """Block on the main thread until the user quits."""
        self.app.run()


def run_tray(state: ServerState, url: str, server, show_settings: bool = False) -> bool:
    """Show the status item, returning False when the environment has no GUI.

    A launchd-started agent can lack a window server connection; in that case
    rumps raises before any item appears and the caller falls back to serving
    without a tray.
    """
    try:
        Tray(state, url, server, show_settings).run()
    except Exception as error:  # noqa: BLE001 - GUI absence is not fatal
        print(
            f"tray unavailable ({type(error).__name__}: {error}); serving without it",
            flush=True,
        )
        return False
    return True
