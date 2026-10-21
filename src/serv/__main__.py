"""Command line entry point.

``serv`` serves the current directory and shows a tray icon. The tray starts a
loopback-only settings server on an ephemeral port when the user opens Settings.
Changes are saved as they are made and applied to the running server.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys

from .config import ConfigError, load_config
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
            "--ipython; settings open from the tray menu"
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
        "--no-gui",
        "--agent",
        dest="no_gui",
        action="store_true",
        help="start the tray without opening a window (used by the login item)",
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

    if args.ipython is not None:
        _delegate_ipython(args.ipython)
        return 0

    root = args.root.expanduser().resolve()
    if not root.is_dir():
        print(f"serv: not a directory: {root}", file=sys.stderr)
        return 2

    state = ServerState.create(config, root, args.port)
    runner = ServerRunner(state)
    watcher = watch.start(state, args.config)

    try:
        from . import tray  # imported late: needs pystray and Pillow

        # The tray confirms its native item from the AppKit event loop before
        # binding the server port. Settings are opened only from the tray menu.
        if not tray.run_tray(runner):
            detail = state.snapshot().last_error or "The tray could not be created."
            if not args.no_gui:
                print(f"serv: could not start: {detail}", file=sys.stderr)
            return 1
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        watcher.stop()
        runner.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
