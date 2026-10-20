#!/usr/bin/env python3
"""Build ``dist/serv.app``: a macOS application bundle with readable sources.

The bundle is deliberately inspectable. It contains no compiled Python archive:

    serv.app/
      Contents/
        Info.plist                 LSUIElement, so there is no Dock icon
        MacOS/serv                 small shell launcher
        Resources/
          pysrc/serv/*.py          the server, as plain source files
          data/                    stylesheet template, icons, chemistry JS
          config/serv.toml         the internal defaults
          python/                  a standalone CPython with dependencies
          serv.icns                application icon

Edit ``Contents/Resources/pysrc/serv`` and restart the app; nothing needs
rebuilding. Run this script again to refresh the bundle from the checkout.

Usage: uv run python tools/build_app.py [--install]
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import tomllib

import cairosvg

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
APP = DIST / "serv.app"
CONTENTS = APP / "Contents"
MACOS = CONTENTS / "MacOS"
RESOURCES = CONTENTS / "Resources"
PYSRC = RESOURCES / "pysrc"
PYTHON = RESOURCES / "python"

APP_NAME = "serv"
BUNDLE_ID = "local.serv"
VERSION = "0.3.0"
INSTALL_DIR = Path("~/Applications").expanduser()

#: Dropped from the copied interpreter; none of it is needed at runtime and it
#: is the bulk of the download.
PYTHON_EXCLUDES = (
    "test",
    "tests",
    "idlelib",
    "idle_test",
    "ensurepip",
    "turtledemo",
    "tkinter",
    "site-packages/pip",
    "site-packages/pip-*",
    "site-packages/setuptools",
    "site-packages/pkg_resources",
)

#: Tcl/Tk and its shared libraries: serv draws with AppKit, never with Tk.
PYTHON_LIBRARY_EXCLUDES = (
    "tcl*",
    "tk*",
    "itcl*",
    "thread*",
    "libtcl*",
    "libtk*",
    "pkgconfig",
)


def log(message: str) -> None:
    print(f"  {message}", flush=True)


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, text=True, **kwargs)


def clean_environment() -> dict[str, str]:
    """Return os.environ without the venv markers uv run exports.

    Otherwise `uv python find` answers with the project virtualenv instead of a
    managed standalone interpreter.
    """
    ignored = {"VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "CONDA_PREFIX", "PYTHONHOME"}
    return {key: value for key, value in os.environ.items() if key not in ignored}


def managed_python() -> Path:
    """Return a uv-managed standalone CPython 3.14 interpreter."""
    result = run(
        [
            "uv",
            "python",
            "find",
            "--no-project",
            "--python-preference",
            "only-managed",
            "3.14",
        ],
        capture_output=True,
        env=clean_environment(),
    )
    base = Path(result.stdout.strip()).parent.parent
    if "uv/python" not in str(base):
        raise SystemExit(f"not a uv-managed interpreter: {base}")
    return base


def copy_python() -> str:
    """Copy and trim the standalone interpreter; return its version string."""
    base = managed_python()
    version = run(
        [str(base / "bin" / "python3"), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
        capture_output=True,
    ).stdout.strip()

    PYTHON.mkdir(parents=True)
    shutil.copytree(base / "bin", PYTHON / "bin", symlinks=True)
    shutil.copytree(base / "lib", PYTHON / "lib", symlinks=True)
    (PYTHON / "BUILD").write_text((base / "BUILD").read_text() if (base / "BUILD").is_file() else "")

    library = PYTHON / "lib" / f"python{version}"
    for pattern in PYTHON_EXCLUDES:
        for path in library.glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    for pattern in ("python*/config-*", "python*/__pycache__"):
        for path in (PYTHON / "lib").glob(pattern):
            shutil.rmtree(path, ignore_errors=True)
    for pattern in PYTHON_LIBRARY_EXCLUDES:
        for path in (PYTHON / "lib").glob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
    # Strip caches and static metadata that only matter for building C modules.
    for cache in PYTHON.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--target",
            str(library / "site-packages"),
            "--python",
            str(PYTHON / "bin" / "python3"),
            *dependencies(),
        ],
        capture_output=True,
    )
    return version


def dependencies() -> list[str]:
    """Read runtime dependencies from pyproject.toml, so there is one source."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    return list(project["dependencies"])


def copy_sources() -> None:
    """Copy the package as plain .py files, without caches or tests."""
    target = PYSRC / "serv"
    shutil.copytree(
        ROOT / "src" / "serv",
        target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    log(f"sources: {len(list(target.rglob('*.py')))} python files")


def copy_data() -> None:
    shutil.copytree(
        ROOT / "data",
        RESOURCES / "data",
        ignore=shutil.ignore_patterns("__pycache__", ".DS_Store"),
    )
    (RESOURCES / "config").mkdir(parents=True, exist_ok=True)
    for source in sorted((ROOT / "config").glob("*.toml")):
        shutil.copyfile(source, RESOURCES / "config" / source.name)


def build_icon() -> None:
    """Render the app icon into an .icns using iconutil."""
    source = (ROOT / "data" / "app" / "serv-icon.svg").read_bytes()
    with tempfile.TemporaryDirectory() as temporary:
        iconset = Path(temporary) / "serv.iconset"
        iconset.mkdir()
        for points in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = points * scale
                name = f"icon_{points}x{points}{'@2x' if scale == 2 else ''}.png"
                cairosvg.svg2png(
                    bytestring=source,
                    write_to=str(iconset / name),
                    output_width=pixels,
                    output_height=pixels,
                )
        run(["iconutil", "-c", "icns", str(iconset), "-o", str(RESOURCES / "serv.icns")])
    log("icon: serv.icns")


def write_info_plist() -> None:
    payload = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": "serv.icns",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": "13.0",
        # Menu-bar application: no Dock icon, no main menu, windows still open.
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,
    }
    (CONTENTS / "Info.plist").write_bytes(plistlib.dumps(payload))


LAUNCHER = """#!/bin/sh
# serv launcher: run the plain-Python sources in Resources/pysrc with the
# interpreter in Resources/python. Edit those sources and restart the app.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
RESOURCES="$HERE/../Resources"
export PYTHONPATH="$RESOURCES/pysrc"
export PYTHONDONTWRITEBYTECODE=
export SERV_APP_LAUNCHER="$HERE/serv"
unset PYTHONHOME
exec "$RESOURCES/python/bin/python3" -m serv --app "$@"
"""


def write_launcher() -> None:
    path = MACOS / APP_NAME
    path.write_text(LAUNCHER)
    path.chmod(0o755)


def sign() -> None:
    """Ad-hoc sign the bundle so macOS keeps its identity between launches."""
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(APP)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log(f"codesign skipped: {result.stderr.strip()[:120]}")


def smoke_test(version: str) -> None:
    """Prove the bundled interpreter imports serv and the dependencies."""
    script = (
        "import serv, serv.server, serv.ui, serv.tray, markdown_it, mdit_py_plugins, rumps, deal;"
        "print('imports ok')"
    )
    result = run(
        [str(PYTHON / "bin" / "python3"), "-c", script],
        capture_output=True,
        env={
            "PYTHONPATH": str(PYSRC),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
        },
    )
    log(result.stdout.strip())
    log(f"python {version} bundled")


def trim_site_packages() -> None:
    """Drop the PyObjC test bundle; it is the largest unused package."""
    for pattern in ("PyObjCTest", "pyobjc_framework_cocoa-*/tests"):
        for path in (RESOURCES / "python").rglob(pattern):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
    free = RESOURCES / "python" / "lib" / "python3.14" / "site-packages" / "bin"
    if free.is_dir():
        shutil.rmtree(free, ignore_errors=True)


def install() -> None:
    """Copy the bundle to ~/Applications, replacing any previous copy."""
    target = INSTALL_DIR / f"{APP_NAME}.app"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(APP, target, symlinks=True)
    log(f"installed {target}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dist/serv.app")
    parser.add_argument("--install", action="store_true", help="copy the bundle to ~/Applications")
    args = parser.parse_args()

    if APP.exists():
        shutil.rmtree(APP)
    MACOS.mkdir(parents=True)
    RESOURCES.mkdir(parents=True)

    print(f"building {APP.relative_to(ROOT)}")
    version = copy_python()
    copy_sources()
    copy_data()
    build_icon()
    trim_site_packages()
    write_info_plist()
    write_launcher()
    sign()
    smoke_test(version)

    total = sum(path.stat().st_size for path in APP.rglob("*") if path.is_file())
    log(f"bundle size: {total / (1024 * 1024):.0f} MiB")
    if args.install:
        install()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
