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
import threading
import time

from .config import Config, ConfigError, load_config
from .locations import user_config_path
from .server import build_server, free_port
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
        help="start the server and tray, and open the settings window",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="start the server and tray without opening a window (login item)",
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


def _bind(config: Config, root: Path, port: int):
    """Bind the HTTP server, or explain why that is not possible."""
    return build_server(config, root, port)


def _wait_for_port(port: int, interval: float = 2.0) -> None:
    """Block until nothing is listening on the port."""
    while not free_port(port):
        time.sleep(interval)


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

    try:
        server, state = _bind(config, root, args.port)
    except OSError as error:
        if args.agent:
            # The login item waits for the port rather than exiting, so launchd
            # does not restart it in a loop while another copy is running.
            print(
                f"serv: port {args.port} is in use; waiting for it to become free",
                flush=True,
            )
            while True:
                _wait_for_port(args.port)
                try:
                    server, state = _bind(config, root, args.port)
                    break
                except OSError:
                    continue
        elif args.no_tray:
            # Terminal run: no dialogs, just a clear failure.
            print(f"serv: port {args.port} is already in use: {error}", file=sys.stderr)
            return 1
        else:
            # Only one server can own the port. Say so out loud, then attach to
            # the running instance by opening its settings window; the file
            # watcher there applies changes to the live server.
            message = (
                f"serv is already running on port {args.port}.\n\n"
                "This launch cannot start a second copy, so it will exit. Use the "
                "menu-bar icon to reach the running server, or quit it first "
                "(Quit serv) to start a new one from here."
            )
            print(f"serv: {message}", file=sys.stderr)
            try:
                from . import ui

                ui.show_error("serv is already running", message)
            except Exception:  # noqa: BLE001 - no display; the message above stands
                pass
            _spawn_settings()
            return 0

    url = f"http://localhost:{args.port}/"
    print(f"serving {root} at {url}", flush=True)

    watcher = watch.start(state, args.config)
    worker = threading.Thread(target=server.serve_forever, name="serv-http", daemon=True)
    worker.start()

    try:
        if args.no_tray:
            worker.join()
        else:
            from . import tray  # imported late: needs pystray and Pillow

            if args.app and not args.agent:
                _spawn_settings()
            if tray.run_tray(state, url, server):
                server.shutdown()
            worker.join()
    except KeyboardInterrupt:
        print("\nstopped")
        server.shutdown()
    finally:
        watcher.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
