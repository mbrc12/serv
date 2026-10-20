"""Watch the configuration file and apply edits to a running server.

This is what makes external edits safe: a person or an agent can rewrite
``~/.config/serv/serv.toml`` and the running server picks it up within a couple
of seconds, without a restart and without the settings window.
"""

from __future__ import annotations

import threading

from .config import Config, ConfigError, load_config, resolve_config_path
from .server import ServerState

INTERVAL_SECONDS = 2.0


class ConfigWatcher(threading.Thread):
    """A daemon thread that reloads the config file when it changes."""

    def __init__(self, state: ServerState, explicit: str | None = None) -> None:
        super().__init__(name="serv-config-watch", daemon=True)
        self.state = state
        self.explicit = explicit
        self._stamp: tuple[str, int, int] | None = self._current_stamp()
        self._stop = threading.Event()

    def _current_stamp(self) -> tuple[str, int, int] | None:
        path = resolve_config_path(self.explicit)
        if path is None:
            return None
        try:
            stat = path.stat()
        except OSError:
            return None
        return (str(path), stat.st_mtime_ns, stat.st_size)

    def run(self) -> None:
        while not self._stop.wait(INTERVAL_SECONDS):
            stamp = self._current_stamp()
            if stamp is None or stamp == self._stamp:
                continue
            self._stamp = stamp
            self.reload()

    def reload(self) -> None:
        """Load the config file and apply it, reporting failures in the tray."""
        try:
            config: Config = load_config(self.explicit)
        except ConfigError as error:
            self.state.note_error(f"config: {error}")
            return
        if config == self.state.config:
            return
        self.state.apply_config(config)
        self.state.clear_error()

    def stop(self) -> None:
        self._stop.set()


def start(state: ServerState, explicit: str | None = None) -> ConfigWatcher:
    """Start watching; the caller keeps the thread object to stop it later."""
    watcher = ConfigWatcher(state, explicit)
    watcher.start()
    return watcher
