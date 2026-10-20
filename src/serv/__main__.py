"""Command line entry point.

``serv`` serves the current directory. The LaunchAgent runs it from ``$HOME``,
so ``http://localhost:1002/…`` maps onto the home directory.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import threading

from . import ui, watch
from .config import ConfigError, load_config
from .server import build_server
from .tray import run_tray

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
        help="serve without the menu-bar status item",
    )
    parser.add_argument(
        "--app",
        action="store_true",
        help="start the server, show the menu-bar item and open the settings window",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="start the server and the menu-bar item without opening a window (login item)",
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
        ui.show_settings(config, standalone=True)
        return 0

    if args.ipython is not None:
        _delegate_ipython(args.ipython)
        return 0

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"serv: not a directory: {root}", file=sys.stderr)
        return 2

    try:
        server, state = build_server(config, root, args.port)
    except OSError as error:
        # The app is single-instance: a second launch shows the settings window
        # for the server that is already running (a file watcher applies them).
        if args.app:
            ui.show_settings(config, standalone=True)
            return 0
        print(f"serv: cannot listen on port {args.port}: {error}", file=sys.stderr)
        return 1

    url = f"http://localhost:{args.port}/"
    print(f"serving {root} at {url}", flush=True)

    watcher = watch.start(state, args.config)
    worker = threading.Thread(target=server.serve_forever, name="serv-http", daemon=True)
    worker.start()

    tray_ran = False
    if not args.no_tray:
        tray_ran = run_tray(state, url, server, show_settings=args.app and not args.agent)

    try:
        if tray_ran:
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
