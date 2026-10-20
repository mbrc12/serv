"""Settings window, built with Tk.

Tk runs everywhere, so this one window serves macOS, Linux and Windows. It is a
separate process from the server (``serv --settings``): both Tk and the tray want
the main thread, and splitting them also means the window can be closed without
stopping the server -- the running instance picks up the saved file through its
config watcher.

Layout mirrors the old AppKit window: a header, three sections, and a footer that
saves. Values are validated with the same ``parse_config`` the server uses, so a
mistake is reported here rather than at the next start.
"""

from __future__ import annotations

from dataclasses import fields
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import colorchooser, font as tkfont, messagebox, ttk
from typing import Callable

from . import appearance, autostart, fonts, labels, schemes
from .colors import css_color, hex_for_picker, parse_css_color
from .config import Config, ConfigError, load_config, parse_config, save_config
from .locations import user_config_path
from .resources import TRAY_GLYPH_DARK, TRAY_GLYPH_LIGHT, data_path
from .units import format_length, slider_for, snap

WINDOW_WIDTH = 700
MIN_WINDOW_HEIGHT = 420
SWATCH_COLUMNS = 3
LABEL_WIDTH = 150
SYSTEM_FONT_ITEM = "System font…"

#: Called with the saved config so an in-process server can apply it.
SaveCallback = Callable[[Config], None]


# ------------------------------------------------------------------- helpers


def _muted_color(root: tk.Misc) -> str:
    """Return a system-ish secondary text color, avoiding hardcoded grays."""
    for name in ("systemSecondaryLabelColor", "gray50"):
        try:
            root.winfo_rgb(name)
        except tk.TclError:
            continue
        return name
    return "gray"


def _bold(font: tkfont.Font, size: int | None = None) -> tkfont.Font:
    copy = font.copy()
    copy.configure(weight="bold")
    if size is not None:
        copy.configure(size=size)
    return copy


def _reveal(path: Path) -> None:
    """Show a file in the platform's file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def _center(window: tk.Tk | tk.Toplevel, width: int, height: int) -> None:
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    window.geometry(f"{width}x{height}+{(screen_width - width) // 2}+{max((screen_height - height) // 3, 0)}")


#: Border of a color swatch: UI chrome, not part of the served palette.
SWATCH_BORDER = "gray60"


def _draw_swatch(canvas: tk.Canvas, color: str) -> None:
    """Paint a rounded color patch inside a small canvas."""
    canvas.delete("all")
    radius = 5
    width = int(canvas["width"])
    height = int(canvas["height"])
    points = [
        radius, 1, width - radius, 1, width - 1, 1, width - 1, radius,
        width - 1, height - radius, width - 1, height - 1, width - radius, height - 1,
        radius, height - 1, 1, height - 1, 1, height - radius, 1, radius, 1, 1,
    ]
    canvas.create_polygon(
        points, smooth=True, splinesteps=12, fill=color, outline=SWATCH_BORDER
    )


# -------------------------------------------------------------------- window


class SettingsWindow:
    """The settings window and everything it needs to build itself."""

    def __init__(self, config: Config, callback: SaveCallback | None = None) -> None:
        self.config = config
        self.callback = callback
        self.values = self._config_values(config)
        self.root = tk.Tk()
        self.root.title("serv settings")
        self.root.resizable(False, False)
        self._centered = False
        self._widgets: dict[str, ttk.Widget] = {}
        self.text_vars: dict[str, tk.StringVar] = {}
        self.slider_vars: dict[str, tk.DoubleVar] = {}
        self.slider_labels: dict[str, tk.StringVar] = {}
        self.swatches: dict[str, tk.Canvas] = {}
        self.font_vars: dict[str, tk.StringVar] = {}
        self.system_font_vars: dict[str, tk.StringVar] = {}
        #: True when a role uses a font installed on this machine.
        self.local_font: dict[str, bool] = {
            role: self.values[f"type.{role}"] not in self._catalogue_names(role)
            for role in ("reading", "mono")
        }
        self.megabyte_var: tk.StringVar | None = None
        self.glob_entries: list[tk.Entry] = []
        self.login_var = tk.IntVar(value=1 if autostart.is_installed() else 0)
        self.theme = ttk.Style()
        self.base_font = tkfont.nametofont("TkDefaultFont")
        self.muted = _muted_color(self.root)
        self._build()
        self._resize_to_content()

    @staticmethod
    def _catalogue_names(role: str) -> list[str]:
        """Return the curated Google Fonts families for a role."""
        return [choice.name for choice in fonts.choices_for(role)]

    @staticmethod
    def _installed_families(widget: tk.Misc) -> list[str]:
        """Return the font families installed on this machine."""
        return sorted(set(tkfont.families(widget)))

    def _resize_to_content(self, _event=None) -> None:
        """Size the window to the visible section, keeping a single width.

        A notebook normally keeps the height of its tallest page, which leaves a
        large blank area under the shorter ones. Fitting the pane per section
        keeps every tab tight, and the window grows or shrinks when tabs change.
        """
        self.root.update_idletasks()
        page = self.notebook.nametowidget(self.notebook.select())
        self.notebook.configure(height=page.winfo_reqheight())
        self.root.update_idletasks()
        height = max(self.root.winfo_reqheight(), MIN_WINDOW_HEIGHT)
        self.root.geometry(f"{WINDOW_WIDTH}x{height}")
        if self._centered:
            return
        self._centered = True
        _center(self.root, WINDOW_WIDTH, height)

    @staticmethod
    def _config_values(config: Config) -> dict[str, str]:
        values: dict[str, str] = {
            "server.port": str(config.server.port),
            "server.max_render_bytes": str(config.server.max_render_bytes),
            "cache.entries": str(config.cache.entries),
            "server.no_process": "\n".join(config.server.no_process),
        }
        for section, mapping in (
            ("palette", config.palette),
            ("accents", config.accents),
            ("code", config.code),
        ):
            for field in fields(mapping):
                values[f"{section}.{field.name}"] = getattr(mapping, field.name)
        for field in fields(config.type):
            values[f"type.{field.name}"] = getattr(config.type, field.name)
        for field in fields(config.layout):
            values[f"layout.{field.name}"] = getattr(config.layout, field.name)
        return values

    # ------------------------------------------------------------- building

    def _build(self) -> None:
        self._build_header()
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=16, pady=(2, 6))

        general = ttk.Frame(notebook, padding=(18, 16))
        colors = ttk.Frame(notebook, padding=(18, 16))
        typography = ttk.Frame(notebook, padding=(18, 16))
        notebook.add(general, text="General")
        notebook.add(colors, text="Colors")
        notebook.add(typography, text="Type & Layout")
        self.notebook = notebook
        notebook.bind("<<NotebookTabChanged>>", self._resize_to_content)

        self._build_general(general)
        self._build_colors(colors)
        self._build_typography(typography)
        self._build_footer()

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(18, 14, 18, 6))
        header.pack(fill="x")
        try:
            glyph = TRAY_GLYPH_DARK if appearance.is_dark() else TRAY_GLYPH_LIGHT
            # Drawn at its natural pixel size: 44 pixels fills a 22-point box on
            # a Retina display, so the glyph is never resampled.
            image = tk.PhotoImage(file=str(data_path(glyph)))
            self._icon = image  # keep a reference or Tk drops it
            ttk.Label(header, image=image).grid(row=0, column=0, rowspan=2, padx=(0, 12))
        except tk.TclError:
            pass
        ttk.Label(header, text="serv", font=_bold(self.base_font, 15)).grid(
            row=0, column=1, sticky="sw"
        )
        ttk.Label(
            header,
            text=f"Local file server · http://localhost:{self.config.server.port}/",
            foreground=self.muted,
        ).grid(row=1, column=1, sticky="nw")

    def _form_row(
        self,
        parent: ttk.Frame,
        row: int,
        caption: str,
        build: Callable[[ttk.Frame], tk.Widget],
        *,
        align: str = "w",
    ) -> tk.Widget:
        """Place a caption and its control on one row, on a shared center line.

        The control is created inside the row frame by `build`, so the caption
        and the control share one grid row and one vertical center.
        """
        line = ttk.Frame(parent)
        line.grid(row=row, column=0, sticky="ew", pady=4)
        parent.columnconfigure(0, weight=1)
        line.columnconfigure(0, minsize=LABEL_WIDTH)
        if align == "e":
            line.columnconfigure(1, weight=1)
        ttk.Label(line, text=caption).grid(row=0, column=0, sticky="w")
        control = build(line)
        control.grid(row=0, column=1, sticky=align)
        return control

    def _build_general(self, parent: ttk.Frame) -> None:
        rows = (
            ("server.port", "Port", ""),
            ("server.max_render_bytes", "Largest rendered file", "MB"),
            ("cache.entries", "Cached pages", ""),
        )
        for index, (key, caption, unit) in enumerate(rows):
            variable = tk.StringVar(value=self._display_value(key))

            def build(line, variable=variable, unit=unit):
                holder = ttk.Frame(line)
                entry = ttk.Entry(holder, textvariable=variable, width=10, justify="right")
                entry.pack(side="left")
                if unit:
                    ttk.Label(holder, text=unit, foreground=self.muted).pack(
                        side="left", padx=(6, 0)
                    )
                return holder

            self._form_row(parent, index, caption, build)
            if key == "server.max_render_bytes":
                self.megabyte_var = variable
            else:
                self.text_vars[key] = variable

        heading_row = len(rows)
        ttk.Label(parent, text="Served verbatim", font=_bold(self.base_font)).grid(
            row=heading_row, column=0, sticky="w", pady=(18, 0)
        )
        ttk.Label(
            parent,
            text="matched files are sent as-is, without rendering",
            foreground=self.muted,
        ).grid(row=heading_row + 1, column=0, sticky="w", pady=(0, 2))

        self.glob_frame = ttk.Frame(parent)
        self.glob_frame.grid(row=heading_row + 2, column=0, sticky="ew", pady=(6, 0))
        self.glob_frame.columnconfigure(0, weight=1)
        self._render_globs()

        ttk.Button(parent, text="+ Add pattern", command=self._add_glob, width=16).grid(
            row=heading_row + 3, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Checkbutton(
            parent, text="Start serv at login", variable=self.login_var
        ).grid(row=heading_row + 4, column=0, sticky="w", pady=(18, 0))

    def _display_value(self, key: str) -> str:
        """Return a config value as it should appear in a text field."""
        if key == "server.max_render_bytes":
            megabytes = int(self.values[key]) / (1024 * 1024)
            return f"{round(megabytes, 2):g}"
        return self.values[key]

    def _render_globs(self) -> None:
        for child in self.glob_frame.winfo_children():
            child.destroy()
        self.glob_entries = []
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        for index, pattern in enumerate(patterns):
            entry = ttk.Entry(self.glob_frame)
            entry.insert(0, pattern)
            entry.grid(row=index, column=0, sticky="ew", pady=2)
            ttk.Button(
                self.glob_frame,
                text="−",
                width=3,
                command=lambda position=index: self._remove_glob(position),
            ).grid(row=index, column=1, padx=(6, 0), pady=2)
            self.glob_entries.append(entry)

    def _add_glob(self) -> None:
        self._stash_globs()
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        patterns.append("~/")
        self.values["server.no_process"] = "\n".join(patterns)
        self._render_globs()

    def _remove_glob(self, index: int) -> None:
        self._stash_globs()
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        if 0 <= index < len(patterns):
            patterns.pop(index)
        self.values["server.no_process"] = "\n".join(patterns)
        self._render_globs()

    def _stash_globs(self) -> None:
        if self.glob_entries:
            self.values["server.no_process"] = "\n".join(
                entry.get() for entry in self.glob_entries
            )

    def _build_colors(self, parent: ttk.Frame) -> None:
        current = schemes.name_for_values(self.values)
        self.scheme_labels = {scheme.label: scheme for scheme in schemes.load_schemes()}
        self.scheme_var = tk.StringVar(value=schemes.label_for(current))

        def build_scheme(line):
            combo = ttk.Combobox(
                line,
                textvariable=self.scheme_var,
                values=[*self.scheme_labels, schemes.label_for(schemes.CUSTOM)],
                state="readonly",
                width=24,
            )
            combo.bind("<<ComboboxSelected>>", self._scheme_changed)
            self.scheme_combo = combo
            return combo

        self._form_row(parent, 0, "Scheme", build_scheme)
        # A focused combobox paints a blue indicator on macOS; let the group
        # heading take the initial focus instead.
        parent.after_idle(self.notebook.focus_set)

        row = 1
        for title, section, mapping in (
            ("Interface", "palette", self.config.palette),
            ("Accents", "accents", self.config.accents),
            ("Source", "code", self.config.code),
        ):
            ttk.Label(parent, text=title, font=_bold(self.base_font)).grid(
                row=row, column=0, sticky="w", pady=(16, 6)
            )
            row += 1
            grid = ttk.Frame(parent)
            grid.grid(row=row, column=0, sticky="w")
            row += 1
            for index, field in enumerate(fields(mapping)):
                key = f"{section}.{field.name}"
                cell = ttk.Frame(grid)
                cell.grid(
                    row=index // SWATCH_COLUMNS,
                    column=index % SWATCH_COLUMNS,
                    sticky="w",
                    padx=(0, 20),
                    pady=3,
                )
                swatch = tk.Canvas(
                    cell, width=26, height=26, highlightthickness=0, cursor="hand2"
                )
                swatch.pack(side="left", padx=(0, 8))
                _draw_swatch(swatch, hex_for_picker(self.values[key]))
                swatch.bind("<Button-1>", lambda _event, name=key: self._pick_color(name))
                ttk.Label(cell, text=labels.label_for(section, field.name)).pack(
                    side="left"
                )
                self.swatches[key] = swatch
            for column in range(SWATCH_COLUMNS):
                grid.columnconfigure(column, minsize=208)

    def _scheme_changed(self, _event=None) -> None:
        """Apply the scheme picked in the dropdown."""
        scheme = self.scheme_labels.get(self.scheme_var.get())
        if scheme is not None:
            self._apply_scheme(scheme)

    def _apply_scheme(self, scheme: schemes.Scheme) -> None:
        """Copy a scheme's colors into the draft and repaint the swatches."""
        self.values.update(scheme.colors())
        self._refresh_swatches()

    def _pick_color(self, key: str) -> None:
        current = hex_for_picker(self.values.get(key, "#000000"))
        _, chosen = colorchooser.askcolor(
            color=current,
            parent=self.root,
            title=labels.label_for(key.split(".")[0], key.split(".")[1]),
        )
        if not chosen:
            return
        red, green, blue, _ = parse_css_color(chosen)
        self.values[key] = css_color(red, green, blue)
        self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        for key, canvas in self.swatches.items():
            _draw_swatch(canvas, hex_for_picker(self.values[key]))
        self.scheme_var.set(schemes.label_for(schemes.name_for_values(self.values)))

    def _build_typography(self, parent: ttk.Frame) -> None:
        row = 0
        for role, caption in (("reading", "Reading font"), ("mono", "Monospace font")):
            options = [*self._catalogue_names(role), SYSTEM_FONT_ITEM]
            current = (
                SYSTEM_FONT_ITEM if self.local_font[role] else self.values[f"type.{role}"]
            )
            variable = tk.StringVar(value=current)

            def build(line, role=role, options=options, variable=variable):
                combo = ttk.Combobox(
                    line, textvariable=variable, values=options, state="readonly", width=30
                )
                combo.bind(
                    "<<ComboboxSelected>>",
                    lambda _event, name=role: self._font_choice_changed(name),
                )
                return combo

            self._form_row(parent, row, caption, build, align="e")
            self.font_vars[role] = variable
            row += 1

            if self.local_font[role]:
                # Only the families actually installed here, so the long list
                # appears solely for someone who asked for a system font.
                installed = self._installed_families(self.root)
                family = self.values[f"type.{role}"]
                if family not in installed:
                    installed.insert(0, family)
                system_variable = tk.StringVar(value=family)

                def build_system(line, role=role, installed=installed, system_variable=system_variable):
                    combo = ttk.Combobox(
                        line,
                        textvariable=system_variable,
                        values=installed,
                        state="readonly",
                        width=30,
                    )
                    combo.bind(
                        "<<ComboboxSelected>>",
                        lambda _event, name=role: self._system_font_changed(name),
                    )
                    return combo

                self._form_row(parent, row, "Installed", build_system, align="e")
                self.system_font_vars[role] = system_variable
                row += 1

        for title, keys in (
            (
                "Text sizes",
                (
                    ("type.md_size", "Markdown"),
                    ("type.md_table", "Tables"),
                    ("type.code_size", "Code"),
                ),
            ),
            (
                "Layout",
                (
                    ("layout.md_width", "Reading column"),
                    ("layout.md_gutter", "Side padding"),
                    ("layout.listing_width", "Listing width"),
                ),
            ),
        ):
            ttk.Label(parent, text=title, font=_bold(self.base_font)).grid(
                row=row, column=0, sticky="w", pady=(18, 4)
            )
            row += 1
            for key, caption in keys:
                row = self._add_slider(parent, key, row, caption)

    def _add_slider(self, parent: ttk.Frame, key: str, row: int, caption: str) -> int:
        spec = slider_for(key, self.values.get(key, ""))
        if spec is None:
            variable = tk.StringVar(value=self.values.get(key, ""))
            self._form_row(
                parent,
                row,
                caption,
                lambda line: ttk.Entry(
                    line, textvariable=variable, width=14, justify="right"
                ),
                align="e",
            )
            self.text_vars[key] = variable
            return row + 1

        minimum, maximum, step, unit, value = spec
        variable = tk.DoubleVar(value=value)
        readout = tk.StringVar(value=format_length(value, unit))

        def build(line):
            holder = ttk.Frame(line)
            scale = ttk.Scale(
                holder,
                from_=minimum,
                to=maximum,
                variable=variable,
                length=210,
                command=lambda new_value, k=key: self._slider_moved(k, new_value),
            )
            scale.pack(side="left")
            ttk.Label(
                holder, textvariable=readout, width=7, anchor="e", foreground=self.muted
            ).pack(side="left", padx=(10, 0))
            return holder

        self._form_row(parent, row, caption, build, align="e")
        self.slider_vars[key] = variable
        self.slider_labels[key] = readout
        return row + 1

    def _slider_moved(self, key: str, _value=None) -> None:
        variable = self.slider_vars[key]
        _, _, step, unit, _ = slider_for(key, self.values[key]) or (0, 0, 1, "", 0)
        value = snap(variable.get(), step)
        if abs(variable.get() - value) > 1e-9:
            variable.set(value)
        self.slider_labels[key].set(format_length(value, unit))

    def _font_choice_changed(self, role: str) -> None:
        """Apply a choice from the curated list, or switch to installed fonts."""
        choice = self.font_vars[role].get()
        if choice == SYSTEM_FONT_ITEM:
            self.local_font[role] = True
            installed = self._installed_families(self.root)
            family = self.values[f"type.{role}"]
            if family not in installed and installed:
                family = installed[0]
            self.values[f"type.{role}"] = family
            self.values[f"type.{role}_weights"] = fonts.weights_for(role, family) or ""
            self._rebuild_typography()
            return
        self.local_font[role] = False
        self.values[f"type.{role}"] = choice
        self.values[f"type.{role}_weights"] = fonts.weights_for(role, choice) or ""
        self._rebuild_typography()

    def _system_font_changed(self, role: str) -> None:
        """Apply a family chosen from the installed-font list."""
        family = self.system_font_vars[role].get()
        if not family:
            return
        self.local_font[role] = True
        self.values[f"type.{role}"] = family
        # An installed family may also be a Google font; keep its webfont then.
        self.values[f"type.{role}_weights"] = fonts.weights_for(role, family) or ""
        self._rebuild_typography()

    def _rebuild_typography(self) -> None:
        """Rebuild the Type tab, e.g. after choosing a font."""
        frame = self.notebook.nametowidget(self.notebook.tabs()[2])
        for child in frame.winfo_children():
            child.destroy()
        # Only this tab's controls are being rebuilt; the General tab's entries
        # must keep their variables or an edit there would be lost.
        for key in [key for key in self.text_vars if key.split(".")[0] in ("type", "layout")]:
            del self.text_vars[key]
        self.slider_vars.clear()
        self.slider_labels.clear()
        self.font_vars.clear()
        self.system_font_vars.clear()
        self._build_typography(frame)
        self._resize_to_content()

    def _build_footer(self) -> None:
        footer = ttk.Frame(self.root, padding=(18, 8, 18, 14))
        footer.pack(fill="x")
        ttk.Button(footer, text="Show config file", command=self._reveal_config).pack(side="left")
        ttk.Button(footer, text="Save", command=self._save, width=9).pack(side="right")
        ttk.Button(footer, text="Cancel", command=self._close, width=9).pack(
            side="right", padx=(0, 8)
        )
        self.root.bind("<Escape>", lambda _event: self._close())
        self.root.bind("<Command-s>", lambda _event: self._save())
        self.root.bind("<Control-s>", lambda _event: self._save())

    # --------------------------------------------------------------- saving

    def _collect(self) -> dict:
        """Read every control into a TOML-shaped dict."""
        values = dict(self.values)
        for key, variable in self.text_vars.items():
            values[key] = variable.get()
        for key, variable in self.slider_vars.items():
            _, _, step, unit, _ = slider_for(key, self.values[key]) or (0, 0, 1, "", 0)
            values[key] = format_length(snap(variable.get(), step), unit)
        self._stash_globs()
        values["server.no_process"] = [
            line.strip() for line in values["server.no_process"].splitlines() if line.strip()
        ]

        data: dict[str, dict] = {}
        if self.megabyte_var is not None:
            values["server.max_render_bytes"] = self._megabytes_as_bytes(
                self.megabyte_var.get()
            )

        for key, value in values.items():
            section, name = key.split(".", 1)
            data.setdefault(section, {})[name] = value
        for key in ("server.port", "cache.entries", "server.max_render_bytes"):
            section, name = key.split(".", 1)
            data[section][name] = int(values[key])
        return data

    @staticmethod
    def _megabytes_as_bytes(text: str) -> str:
        """Convert the MB field to the byte count the config stores."""
        try:
            megabytes = float(text.strip())
        except ValueError as error:
            raise ValueError("Largest rendered file must be a number of megabytes") from error
        if megabytes <= 0:
            raise ValueError("Largest rendered file must be greater than zero")
        return str(int(round(megabytes * 1024 * 1024)))

    def _save(self) -> None:
        try:
            config = parse_config(self._collect(), user_config_path())
        except ConfigError as error:
            messagebox.showerror("These settings cannot be saved", str(error), parent=self.root)
            return
        except ValueError as error:
            messagebox.showerror("These settings cannot be saved", f"Not a number: {error}", parent=self.root)
            return

        login_error = None
        try:
            if self.login_var.get() and not autostart.is_installed():
                autostart.install(Path.home())
            elif not self.login_var.get() and autostart.is_installed():
                autostart.uninstall()
        except Exception as error:  # noqa: BLE001 - show, do not crash
            login_error = f"Could not update the login item: {error}"

        try:
            save_config(config)
        except (ConfigError, OSError) as error:
            messagebox.showerror("Could not write the config file", str(error), parent=self.root)
            return

        if self.callback is not None:
            self.callback(config)
        if login_error:
            messagebox.showwarning("Settings saved, but the login item failed", login_error, parent=self.root)
        elif config.server.port != self.config.server.port:
            messagebox.showinfo(
                "Settings saved", "The new port takes effect after serv restarts.", parent=self.root
            )
        self.config = config
        self._close()

    def _reveal_config(self) -> None:
        path = user_config_path()
        if not path.is_file():
            try:
                save_config(self.config)
            except (ConfigError, OSError) as error:
                messagebox.showerror("Could not write the config file", str(error), parent=self.root)
                return
        _reveal(path)

    def _close(self) -> None:
        self.root.destroy()

    # ---------------------------------------------------------------- run

    def show(self) -> None:
        """Show the window and run its event loop until it closes."""
        self.root.mainloop()


# ---------------------------------------------------------------- entry points


def show_settings(config: Config, callback: SaveCallback | None = None) -> None:
    """Open the settings window and block until it closes."""
    SettingsWindow(config, callback).show()


def ask_start_at_login_if_needed(config: Config | None = None) -> bool | None:
    """Ask the start-at-login question once, on the very first launch.

    Returns None when a user config already exists, so the question appears
    exactly once. Answering writes the config file, which both pins the answer
    and marks the question as asked.
    """
    if user_config_path().is_file():
        return None

    root = tk.Tk()
    root.withdraw()
    try:
        wanted = messagebox.askyesno(
            "Start serv at login?",
            "serv can start automatically and live in the tray, so "
            "http://localhost:1002/ always works.\n\n"
            "You can change this later in serv settings.",
            parent=root,
        )
        if wanted:
            try:
                autostart.install(Path.home())
            except Exception as error:  # noqa: BLE001 - never block the app
                print(f"serv: could not install the login item: {error}", flush=True)
        try:
            save_config(config or load_config())
        except (ConfigError, OSError) as error:
            print(f"serv: could not write {user_config_path()}: {error}", flush=True)
    finally:
        root.destroy()
    return wanted
