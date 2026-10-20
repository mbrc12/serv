"""Command line entry point.

``serv`` serves the current directory and shows a tray icon. The settings window
is a separate process (``--settings``), because Tk and the tray both need the
main thread of their own process; the running server applies saved changes
through its config watcher.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from .config import ConfigError, load_config
from .locations import user_config_path
from .server import ServerRunner, ServerState
from . import watch

IPYTHON_VIEWER = Path("~/.local/share/ipython-html/serv.py")
IPYTHON_PORT = 8765


def _parser(default_port: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="serv",
        description=(
            "Serve the current directory: Markdown is rendered in process, source files "
            "are highlighted, and the page styling comes from ~/.config/serv/serv.toml."
        ),
        epilog=(
            f"default port: {default_port} for the static server, {IPYTHON_PORT} for "
            "--ipython; `serv --settings` opens the settings window"
        ),
    )
    parser.add_argument(
        "--port", type=int, default=default_port, help=f"port to listen on (default: {default_port})"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.cwd(),
        help="directory to serve (default: the current directory)",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="configuration file to read instead of ~/.config/serv/serv.toml",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="serve without a tray icon",
    )
    parser.add_argument(
        "--app",
        action="store_true",
        help="open the settings window when starting",
    )
    parser.add_argument(
        "--no-gui",
        "--agent",
        dest="no_gui",
        action="store_true",
        help="start the tray without opening a window (used by the login item)",
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help="open the settings window and exit",
    )
    parser.add_argument(
        "--ipython",
        type=int,
        nargs="?",
        const=IPYTHON_PORT,
        metavar="PORT",
        help=f"serve the ipython .save() HTML viewer instead (default port: {IPYTHON_PORT})",
    )
    return parser


def _python_interpreter() -> str:
    """Return an interpreter that can run the ipython viewer script."""
    if not getattr(sys, "frozen", False):
        return sys.executable
    for candidate in ("python3", "python"):
        found = shutil.which(candidate)
        if found:
            return found
    raise RuntimeError("no Python interpreter found to run the ipython viewer")


def _delegate_ipython(port: int) -> None:
    """Replace this process with the ipython HTML viewer."""
    viewer = IPYTHON_VIEWER.expanduser()
    if not viewer.is_file():
        raise SystemExit(f"ipython viewer not found: {viewer}")
    interpreter = _python_interpreter()
    print(f"starting the ipython viewer at http://127.0.0.1:{port}/", flush=True)
    os.execv(interpreter, [interpreter, str(viewer), "--port", str(port)])


def _open_settings_window(config) -> None:
    """Run the settings window in this process, asking the first-run question."""
    from . import ui  # imported late: needs tkinter

    if not user_config_path().is_file():
        ui.ask_start_at_login_if_needed(config)
    ui.show_settings(config)


def _spawn_settings() -> None:
    """Open the settings window as a separate process."""
    from . import autostart

    subprocess.Popen([*autostart.base_command(), "--settings"], close_fds=True)


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, start the server, and keep it running."""
    preliminary = _parser(1002).parse_args(argv)
    try:
        config = load_config(preliminary.config)
    except ConfigError as error:
        print(f"serv: configuration error: {error}", file=sys.stderr)
        return 2

    args = _parser(config.server.port).parse_args(argv)

    if args.settings:
        _open_settings_window(config)
        return 0

    if args.ipython is not None:
        _delegate_ipython(args.ipython)
        return 0

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"serv: not a directory: {root}", file=sys.stderr)
        return 2

    state = ServerState.create(config, root, args.port)
    runner = ServerRunner(state)
    try:
        runner.start()
    except OSError:
        # One process owns the tray and the server. If the port is taken, this
        # launch cannot become that process, so it says why and exits.
        message = (
            f"serv cannot start: port {args.port} is already in use.\n\n"
            "Another copy is probably running. Quit it from the menu-bar icon "
            "(Quit serv) and start again."
        )
        print(f"serv: {message}", file=sys.stderr)
        if not args.no_tray:
            try:
                from . import ui

                ui.show_error("serv cannot start", message)
            except Exception:  # noqa: BLE001 - no display; the message above stands
                pass
        return 1

    print(f"serving {root} at {runner.url}", flush=True)

    watcher = watch.start(state, args.config)

    try:
        if args.no_tray:
            if runner.worker is not None:
                runner.worker.join()
        else:
            from . import tray  # imported late: needs pystray and Pillow

            # The bundle launcher always adds --app; --no-gui (the login item)
            # wins so no window appears at login.
            if args.app and not args.no_gui:
                _spawn_settings()
            tray.run_tray(runner)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        watcher.stop()
        runner.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
