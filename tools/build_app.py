#!/usr/bin/env python3
"""Build ``dist/serv.app``: a macOS application bundle with readable sources.

The bundle is deliberately inspectable. It contains no compiled Python archive:

    serv.app/
      Contents/
        Info.plist                 LSUIElement, so there is no Dock icon
        MacOS/serv                 native launcher with embedded Python
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
import platform
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
    "site-packages/pip",
    "site-packages/pip-*",
    "site-packages/setuptools",
    "site-packages/pkg_resources",
    "tkinter",
    "lib-dynload/_tkinter*",
)

#: Qt replaces Tcl/Tk for settings; keep only runtime libraries the app needs.
PYTHON_LIBRARY_EXCLUDES = (
    "pkgconfig",
    "tcl9",
    "tcl9.0",
    "tk9.0",
    "thread3.0.6",
    "itcl4.3.8",
    "libtcl9.0.dylib",
    "libtcl9tk9.0.dylib",
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


def write_launcher(version: str) -> None:
    """Compile a native bundle executable that embeds the bundled Python.

    Finder and ControlCenter must see one stable app process. Calling Python's
    main function in-process keeps the executable identified as this app; a
    shell script that execs Python loses that identity on recent macOS.
    """
    base = managed_python()
    path = MACOS / APP_NAME
    library_name = f"libpython{version}.dylib"
    source_library = base / "lib" / library_name
    bundled_library = PYTHON / "lib" / library_name
    launcher_source = ROOT / "tools" / "app_launcher.c"
    run(
        [
            "clang",
            "-O2",
            f"-I{base / 'include' / f'python{version}'}",
            f"-L{base / 'lib'}",
            str(launcher_source),
            f"-lpython{version}",
            "-Wl,-headerpad_max_install_names",
            "-o",
            str(path),
        ]
    )

    old_id = run(["otool", "-D", str(source_library)], capture_output=True).stdout.splitlines()[1]
    relative_id = f"@rpath/{library_name}"
    run(["install_name_tool", "-id", relative_id, str(bundled_library)])
    run(["install_name_tool", "-change", old_id, relative_id, str(path)])
    run(["install_name_tool", "-add_rpath", "@executable_path/../Resources/python/lib", str(path)])


def sign() -> None:
    """Ad-hoc sign the bundle so macOS keeps its identity between launches."""
    result = subprocess.run(
        ["codesign", "--force", "--deep", "--sign", "-", str(APP)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"codesign failed: {result.stderr.strip()}")
    verification = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(APP)],
        capture_output=True,
        text=True,
    )
    if verification.returncode != 0:
        raise SystemExit(f"bundle signature is invalid: {verification.stderr.strip()}")


def smoke_test(version: str) -> None:
    """Prove the bundled interpreter imports serv and the dependencies."""
    script = (
        "import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets;"
        "import pystray, PIL, PIL.Image, markdown_it, mdit_py_plugins, deal;"
        "import serv, serv.server, serv.ui, serv.tray, serv.autostart;"
        "from serv.config import load_config;"
        "from serv.ui import SettingsWindow;"
        "window = SettingsWindow(load_config());"
        "assert any(label.pixmap() is not None and not label.pixmap().isNull() "
        "for label in window.root.findChildren(PySide6.QtWidgets.QLabel));"
        "window.root.close();"
        "print('imports and settings UI ok, Qt', PySide6.QtCore.qVersion())"
    )
    result = run(
        [str(PYTHON / "bin" / "python3"), "-c", script],
        capture_output=True,
        env={
            "PYTHONPATH": str(PYSRC),
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": str(Path.home()),
            "PYTHONDONTWRITEBYTECODE": "1",
            "QT_QPA_PLATFORM": "offscreen",
            "QT_STYLE_OVERRIDE": "Fusion",
        },
    )
    log(result.stdout.strip())

    launcher_result = run([str(MACOS / APP_NAME), "--help"], capture_output=True)
    if "usage: serv" not in launcher_result.stdout:
        raise SystemExit("native app launcher smoke test did not print serv help")
    log("native launcher and embedded Python ok")
    log(f"python {version} bundled")


def remove_path(path: Path) -> None:
    """Remove a file, symlink, or directory without following symlinks."""
    if path.is_symlink() or path.is_file():
        path.unlink(missing_ok=True)
    elif path.is_dir():
        shutil.rmtree(path, ignore_errors=True)


def trim_site_packages() -> None:
    """Remove Qt build assets and modules that the settings UI does not use."""
    python_root = RESOURCES / "python"
    for pattern in ("PyObjCTest", "pyobjc_framework_cocoa-*/tests"):
        for path in python_root.rglob(pattern):
            remove_path(path)
    free = python_root / "lib" / "python3.14" / "site-packages" / "bin"
    remove_path(free)

    site = python_root / "lib" / "python3.14" / "site-packages"
    pyside = site / "PySide6"
    qt = pyside / "Qt"
    if not qt.is_dir():
        raise SystemExit(f"PySide6 Qt runtime not found: {qt}")

    keep_modules = {"QtCore.abi3.so", "QtDBus.abi3.so", "QtGui.abi3.so", "QtWidgets.abi3.so"}
    for path in pyside.iterdir():
        if path.is_file() and path.name.endswith(".pyi"):
            remove_path(path)
        elif path.is_file() and path.name.startswith("Qt") and path.suffix == ".so":
            if path.name not in keep_modules:
                remove_path(path)

    for name in (
        "Assistant.app",
        "Designer.app",
        "Linguist.app",
        "doc",
        "glue",
        "include",
        "lib",
        "scripts",
        "typesystems",
    ):
        remove_path(pyside / name)
    remove_path(pyside / "libpyside6qml.abi3.6.11.dylib")

    qt_lib = qt / "lib"
    keep_frameworks = {"QtCore.framework", "QtDBus.framework", "QtGui.framework", "QtWidgets.framework"}
    for path in qt_lib.iterdir():
        if path.name not in keep_frameworks:
            remove_path(path)

    for name in ("libexec", "metatypes", "qml", "translations"):
        remove_path(qt / name)

    plugins = qt / "plugins"
    for path in plugins.iterdir():
        if path.name != "platforms":
            remove_path(path)
    platforms = plugins / "platforms"
    keep_platforms = {"libqcocoa.dylib", "libqoffscreen.dylib"}
    for path in platforms.iterdir():
        if path.name not in keep_platforms:
            remove_path(path)

    for path in pyside.rglob("*.pyi"):
        remove_path(path)
    for path in python_root.rglob("__pycache__"):
        remove_path(path)


def thin_python_binaries(version: str) -> None:
    """Keep only the architecture used by the bundled Python interpreter."""
    python_binary = PYTHON / "bin" / f"python{version}"
    architectures = run(["lipo", "-archs", str(python_binary)], capture_output=True).stdout.split()
    architecture = architectures[0] if len(architectures) == 1 else platform.machine()
    if architecture not in architectures:
        raise SystemExit(f"Python architecture {architecture} is unavailable: {architectures}")

    candidates = set(PYTHON.rglob("*.so")) | set(PYTHON.rglob("*.dylib"))
    candidates.add(python_binary)
    qt_lib = PYTHON / "lib" / f"python{version}" / "site-packages" / "PySide6" / "Qt" / "lib"
    for framework in qt_lib.glob("*.framework"):
        candidates.add(framework / "Versions" / "A" / framework.stem)

    thinned = 0
    for path in sorted(candidates):
        if path.is_symlink() or not path.is_file():
            continue
        result = subprocess.run(["lipo", "-archs", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            continue
        binary_architectures = result.stdout.split()
        if architecture not in binary_architectures:
            raise SystemExit(f"{path} lacks bundled Python architecture {architecture}: {binary_architectures}")
        if len(binary_architectures) == 1:
            continue

        temporary = path.with_name(f".{path.name}.thin")
        try:
            run(["lipo", "-thin", architecture, str(path), "-output", str(temporary)])
            shutil.copymode(path, temporary)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        thinned += 1

    log(f"thinned {thinned} universal binaries to {architecture}")


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
    thin_python_binaries(version)
    write_info_plist()
    write_launcher(version)
    smoke_test(version)
    sign()

    total = sum(path.stat().st_size for path in APP.rglob("*") if path.is_file())
    log(f"bundle size: {total / (1024 * 1024):.0f} MiB")
    if args.install:
        install()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
