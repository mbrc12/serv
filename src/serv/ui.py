"""Qt settings, run separately from the server and tray.

The server's config watcher picks up saved changes. Validation uses the same
parser as the server, so mistakes can be reported before writing the file.
"""

from __future__ import annotations

from dataclasses import fields
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import appearance, autostart, fonts, labels, schemes
from .colors import css_color, hex_for_picker
from .config import Config, ConfigError, load_config, parse_config, save_config
from .locations import user_config_path
from .resources import TRAY_GLYPH_DARK, TRAY_GLYPH_LIGHT, data_path
from .units import format_length, slider_for, snap

WINDOW_WIDTH = 700
MIN_WINDOW_HEIGHT = 420
SWATCH_COLUMNS = 3
SYSTEM_FONT_ITEM = "System font…"
SLIDER_SCALE = 100

#: Called with the saved config so an in-process server can apply it.
SaveCallback = Callable[[Config], None]

# Keep a Python reference: Qt does not own the application wrapper.
_application: QApplication | None = None


def _get_application() -> QApplication:
    """Reuse one application for settings and standalone dialogs."""
    global _application
    # This also forces QFileDialog to use Qt's built-in dialog, not the OS one.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs, True)
    application = QApplication.instance()
    if application is None:
        application = QApplication([sys.argv[0]])
        application.setApplicationName("serv")
        application.setQuitOnLastWindowClosed(False)
    if not isinstance(application, QApplication):
        raise RuntimeError("serv settings need a QApplication")
    application.setStyle("Fusion")
    _application = application
    return application


def _reveal(path: Path) -> None:
    """Show a file in the platform's file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def _clear_layout(layout: QLayout) -> None:
    """Remove old controls before rebuilding a section."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        child_layout = item.layout()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif child_layout is not None:
            _clear_layout(child_layout)
            child_layout.deleteLater()


def _draw_swatch(button: QPushButton, color: str) -> None:
    """Show a color on a standard, keyboard-accessible button."""
    patch = QPixmap(22, 22)
    patch.fill(QColor(color))
    button.setIcon(QIcon(patch))
    button.setIconSize(QSize(22, 22))
    button.setToolTip(color)


class SettingsWindow:
    """The settings dialog and its editable draft.

    Control dictionaries group Qt widgets by config key for reading and
    rebuilding the form.
    """

    def __init__(self, config: Config, callback: SaveCallback | None = None) -> None:
        self.application = _get_application()
        self.config = config
        self.callback = callback
        self.values = self._config_values(config)
        self.root = QDialog()
        self.root.setWindowTitle("serv settings")
        self.root.setMinimumSize(WINDOW_WIDTH, MIN_WINDOW_HEIGHT)
        self.root.setFixedWidth(WINDOW_WIDTH)
        self._centered = False
        self.text_vars: dict[str, QLineEdit] = {}
        self.slider_vars: dict[str, QSlider] = {}
        self.slider_labels: dict[str, QLabel] = {}
        self.boolean_vars: dict[str, QCheckBox] = {}
        self.swatches: dict[str, QPushButton] = {}
        self.font_vars: dict[str, QComboBox] = {}
        self.system_font_vars: dict[str, QComboBox] = {}
        self.local_font = {
            role: self.values[f"type.{role}"] not in self._catalogue_names(role)
            for role in ("reading", "mono")
        }
        self.megabyte_var: QLineEdit | None = None
        self.glob_entries: list[QLineEdit] = []
        self.login_var = QCheckBox("Start serv at login")
        self.login_var.setChecked(autostart.is_installed())
        self._build()
        self._resize_to_content()

    @staticmethod
    def _catalogue_names(role: str) -> list[str]:
        """Return the curated Google Fonts families for a role."""
        return [choice.name for choice in fonts.choices_for(role)]

    @staticmethod
    def _installed_families(_widget: QWidget | None = None) -> list[str]:
        """Return the font families installed on this machine."""
        return sorted(set(QFontDatabase.families()))

    def _resize_to_content(self, _index: int = 0) -> None:
        """Let the active tab determine the window's preferred height."""
        for index in range(self.notebook.count()):
            page = self.notebook.widget(index)
            policy = (
                QSizePolicy.Policy.Preferred
                if index == self.notebook.currentIndex()
                else QSizePolicy.Policy.Ignored
            )
            page.setSizePolicy(QSizePolicy.Policy.Preferred, policy)
        page = self.notebook.currentWidget()
        # The tab stack can keep an old size hint until the next layout pass.
        # Set a floor now so fixed-size swatch buttons cannot overlap.
        self.notebook.setMinimumHeight(
            page.minimumSizeHint().height() + self.notebook.tabBar().sizeHint().height() + 4
        )
        minimum_height = max(MIN_WINDOW_HEIGHT, self.layout.minimumSize().height())
        self.root.setMinimumHeight(minimum_height)
        self.root.resize(max(WINDOW_WIDTH, self.root.width()), minimum_height)

    @staticmethod
    def _config_values(config: Config) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {
            "server.port": str(config.server.port),
            "server.max_render_bytes": str(config.server.max_render_bytes),
            "cache.entries": str(config.cache.entries),
            "server.no_process": "\n".join(config.server.no_process),
        }
        for section, mapping in (
            ("palette", config.palette),
            ("accents", config.accents),
            ("code", config.code),
            ("type", config.type),
            ("layout", config.layout),
        ):
            for field in fields(mapping):
                values[f"{section}.{field.name}"] = getattr(mapping, field.name)
        return values

    # ------------------------------------------------------------- building

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label

    def _build(self) -> None:
        self.layout = QVBoxLayout(self.root)
        self.layout.setContentsMargins(18, 14, 18, 14)
        self.layout.setSpacing(12)
        self._build_header()
        self.notebook = QTabWidget()
        self.layout.addWidget(self.notebook)
        general, colors, typography = QWidget(), QWidget(), QWidget()
        for page, title in (
            (general, "General"), (colors, "Colors"), (typography, "Type & Layout")
        ):
            self.notebook.addTab(page, title.replace("&", "&&"))
        self._build_general(general)
        self._build_colors(colors)
        self._build_typography(typography)
        self._build_footer()
        self.notebook.currentChanged.connect(self._resize_to_content)

    def _build_header(self) -> None:
        header = QHBoxLayout()
        glyph = TRAY_GLYPH_DARK if appearance.is_dark() else TRAY_GLYPH_LIGHT
        image = QPixmap(str(data_path(glyph)))
        if not image.isNull():
            icon = QLabel()
            icon.setPixmap(image.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation))
            header.addWidget(icon)
        title = QVBoxLayout()
        title.addWidget(self._heading("serv"))
        title.addWidget(QLabel(f"Local file server · http://localhost:{self.config.server.port}/"))
        header.addLayout(title)
        header.addStretch()
        self.layout.addLayout(header)

    @staticmethod
    def _form(parent: QWidget) -> QFormLayout:
        form = QFormLayout(parent)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        return form

    def _build_general(self, parent: QWidget) -> None:
        form = self._form(parent)
        for key, caption, unit in (
            ("server.port", "Port", ""),
            ("server.max_render_bytes", "Largest rendered file", "MB"),
            ("cache.entries", "Cached pages", ""),
        ):
            entry = QLineEdit(self._display_value(key))
            entry.setAlignment(Qt.AlignmentFlag.AlignRight)
            entry.setMaximumWidth(110)
            holder = QHBoxLayout()
            holder.addStretch()
            holder.addWidget(entry)
            suffix = QLabel(unit)
            suffix.setMinimumWidth(30)
            holder.addWidget(suffix)
            label = QLabel(caption)
            label.setBuddy(entry)
            form.addRow(label, holder)
            if key == "server.max_render_bytes":
                self.megabyte_var = entry
            else:
                self.text_vars[key] = entry
        form.addRow(self._heading("Served verbatim"))
        explanation = QLabel("Matched files are sent as-is, without rendering")
        explanation.setWordWrap(True)
        form.addRow(explanation)
        self.glob_frame = QWidget()
        self.glob_layout = QGridLayout(self.glob_frame)
        self.glob_layout.setContentsMargins(0, 0, 0, 0)
        self.glob_layout.setColumnStretch(0, 1)
        form.addRow(self.glob_frame)
        self._render_globs()
        add = QPushButton("+ Add pattern")
        add.clicked.connect(self._add_glob)
        form.addRow(add)
        form.addRow(self.login_var)

    def _display_value(self, key: str) -> str:
        """Return a config value as it should appear in a text field."""
        if key == "server.max_render_bytes":
            megabytes = int(self.values[key]) / (1024 * 1024)
            return f"{round(megabytes, 2):g}"
        return str(self.values[key])

    def _render_globs(self) -> None:
        _clear_layout(self.glob_layout)
        self.glob_entries = []
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        for index, pattern in enumerate(patterns):
            entry = QLineEdit(pattern)
            entry.setAccessibleName(f"Verbatim pattern {index + 1}")
            self.glob_layout.addWidget(entry, index, 0)
            remove = QPushButton("−")
            remove.setAccessibleName(f"Remove pattern {index + 1}")
            remove.setFixedWidth(32)
            remove.clicked.connect(lambda _checked=False, position=index: self._remove_glob(position))
            self.glob_layout.addWidget(remove, index, 1)
            self.glob_entries.append(entry)
        self._resize_to_content()

    def _add_glob(self) -> None:
        self._stash_globs()
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        patterns.append("~/")
        self.values["server.no_process"] = "\n".join(patterns)
        self._render_globs()
        self.glob_entries[-1].setFocus()

    def _remove_glob(self, index: int) -> None:
        self._stash_globs()
        patterns = [line for line in self.values["server.no_process"].splitlines() if line.strip()]
        if 0 <= index < len(patterns):
            patterns.pop(index)
        self.values["server.no_process"] = "\n".join(patterns)
        self._render_globs()

    def _stash_globs(self) -> None:
        self.values["server.no_process"] = "\n".join(entry.text() for entry in self.glob_entries)

    def _build_colors(self, parent: QWidget) -> None:
        layout = QVBoxLayout(parent)
        layout.setContentsMargins(18, 16, 18, 16)
        self.scheme_labels = {scheme.label: scheme for scheme in schemes.load_schemes()}
        self.scheme_combo = QComboBox()
        self.scheme_var = self.scheme_combo
        self.scheme_combo.addItems([*self.scheme_labels, schemes.label_for(schemes.CUSTOM)])
        self.scheme_combo.setCurrentText(schemes.label_for(schemes.name_for_values(self.values)))
        self.scheme_combo.activated.connect(self._scheme_changed)
        form = QFormLayout()
        form.addRow("Scheme", self.scheme_combo)
        layout.addLayout(form)
        for title, section, mapping in (
            ("Interface", "palette", self.config.palette),
            ("Accents", "accents", self.config.accents),
            ("Source", "code", self.config.code),
        ):
            layout.addWidget(self._heading(title))
            grid = QGridLayout()
            layout.addLayout(grid)
            for index, field in enumerate(fields(mapping)):
                key = f"{section}.{field.name}"
                caption = labels.label_for(section, field.name)
                cell = QHBoxLayout()
                button = QPushButton()
                button.setFixedSize(32, 32)
                button.setAccessibleName(f"Choose {caption.lower()} color")
                _draw_swatch(button, hex_for_picker(self.values[key]))
                button.clicked.connect(lambda _checked=False, name=key: self._pick_color(name))
                cell.addWidget(button)
                label = QLabel(caption)
                label.setWordWrap(True)
                label.setBuddy(button)
                cell.addWidget(label, 1)
                grid.addLayout(cell, index // SWATCH_COLUMNS, index % SWATCH_COLUMNS)
                self.swatches[key] = button
        layout.addStretch()

    def _scheme_changed(self, _index: int = 0) -> None:
        """Apply the scheme picked in the dropdown."""
        scheme = self.scheme_labels.get(self.scheme_var.currentText())
        if scheme is not None:
            self._apply_scheme(scheme)

    def _apply_scheme(self, scheme: schemes.Scheme) -> None:
        """Copy a scheme's colors into the draft and repaint the swatches."""
        self.values.update(scheme.colors())
        self._refresh_swatches()

    def _pick_color(self, key: str) -> None:
        chosen = QColorDialog.getColor(
            QColor(hex_for_picker(self.values[key])),
            self.root,
            labels.label_for(*key.split(".", 1)),
            QColorDialog.ColorDialogOption.DontUseNativeDialog,
        )
        if chosen.isValid():
            self.values[key] = css_color(chosen.redF(), chosen.greenF(), chosen.blueF())
            self._refresh_swatches()

    def _refresh_swatches(self) -> None:
        for key, button in self.swatches.items():
            _draw_swatch(button, hex_for_picker(self.values[key]))
        self.scheme_var.setCurrentText(schemes.label_for(schemes.name_for_values(self.values)))

    def _build_typography(self, parent: QWidget) -> None:
        form = parent.layout() or self._form(parent)
        for role, caption in (("reading", "Reading font"), ("mono", "Monospace font")):
            combo = QComboBox()
            combo.addItems([*self._catalogue_names(role), SYSTEM_FONT_ITEM])
            combo.setCurrentText(SYSTEM_FONT_ITEM if self.local_font[role] else self.values[f"type.{role}"])
            combo.activated.connect(lambda _index, name=role: self._font_choice_changed(name))
            self.font_vars[role] = combo
            form.addRow(caption, combo)
            if self.local_font[role]:
                installed = self._installed_families(self.root)
                family = self.values[f"type.{role}"]
                if family not in installed:
                    installed.insert(0, family)
                system_combo = QComboBox()
                system_combo.addItems(installed)
                system_combo.setCurrentText(family)
                system_combo.activated.connect(lambda _index, name=role: self._system_font_changed(name))
                self.system_font_vars[role] = system_combo
                form.addRow("Installed", system_combo)
        for title, keys in (
            ("Text sizes", (("type.md_size", "Markdown"), ("type.md_table", "Tables"),
                            ("type.code_size", "Code"), ("type.line_height", "Line spacing"))),
            ("Layout", (("layout.md_width", "Reading column"), ("layout.md_gutter", "Side padding"),
                        ("layout.listing_width", "Listing width"))),
        ):
            form.addRow(self._heading(title))
            for key, caption in keys:
                self._add_slider(form, key, caption)
        self.underline_links_var = QCheckBox("Underline links")
        self.underline_links_var.setChecked(self.values["type.underline_links"])
        form.addRow("Markdown links", self.underline_links_var)
        self.boolean_vars["type.underline_links"] = self.underline_links_var

    def _add_slider(self, form: QFormLayout, key: str, caption: str) -> None:
        spec = slider_for(key, self.values.get(key, ""))
        if spec is None:
            entry = QLineEdit(self.values.get(key, ""))
            form.addRow(caption, entry)
            self.text_vars[key] = entry
            return
        minimum, maximum, step, unit, value = spec
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(round(minimum * SLIDER_SCALE), round(maximum * SLIDER_SCALE))
        slider.setSingleStep(round(step * SLIDER_SCALE))
        slider.setPageStep(round(step * SLIDER_SCALE))
        slider.setValue(round(value * SLIDER_SCALE))
        slider.setAccessibleName(caption)
        slider.setMinimumWidth(210)
        readout = QLabel(format_length(value, unit))
        readout.setMinimumWidth(70)
        readout.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        holder = QHBoxLayout()
        holder.addWidget(slider, 1)
        holder.addWidget(readout)
        form.addRow(caption, holder)
        self.slider_vars[key] = slider
        self.slider_labels[key] = readout
        slider.valueChanged.connect(lambda _value, name=key: self._slider_moved(name))

    def _slider_moved(self, key: str, _value: int | None = None) -> None:
        slider = self.slider_vars[key]
        _, _, step, unit, _ = slider_for(key, self.values[key]) or (0, 0, 1, "", 0)
        value = snap(slider.value() / SLIDER_SCALE, step)
        position = round(value * SLIDER_SCALE)
        if slider.value() != position:
            slider.setValue(position)
        self.slider_labels[key].setText(format_length(value, unit))

    def _font_choice_changed(self, role: str) -> None:
        """Apply a curated choice, or switch to installed fonts."""
        choice = self.font_vars[role].currentText()
        if choice == SYSTEM_FONT_ITEM:
            self.local_font[role] = True
            installed = self._installed_families(self.root)
            family = self.values[f"type.{role}"]
            if family not in installed and installed:
                family = installed[0]
            self.values[f"type.{role}"] = family
            self.values[f"type.{role}_weights"] = fonts.weights_for(role, family) or ""
        else:
            self.local_font[role] = False
            self.values[f"type.{role}"] = choice
            self.values[f"type.{role}_weights"] = fonts.weights_for(role, choice) or ""
        self._rebuild_typography()

    def _system_font_changed(self, role: str) -> None:
        """Apply a family chosen from the installed-font list."""
        family = self.system_font_vars[role].currentText()
        if not family:
            return
        self.local_font[role] = True
        self.values[f"type.{role}"] = family
        # Keep webfont weights when an installed family is also in the catalog.
        self.values[f"type.{role}_weights"] = fonts.weights_for(role, family) or ""
        self._rebuild_typography()

    def _typography_values(self) -> dict[str, str | bool]:
        values: dict[str, str | bool] = {
            key: widget.text() for key, widget in self.text_vars.items()
            if key.split(".")[0] in ("type", "layout")
        }
        for key, slider in self.slider_vars.items():
            _, _, step, unit, _ = slider_for(key, self.values[key]) or (0, 0, 1, "", 0)
            values[key] = format_length(snap(slider.value() / SLIDER_SCALE, step), unit)
        values.update({key: widget.isChecked() for key, widget in self.boolean_vars.items()})
        return values

    def _rebuild_typography(self) -> None:
        """Rebuild the Type tab without losing edits on any tab."""
        self.values.update(self._typography_values())
        frame = self.notebook.widget(2)
        _clear_layout(frame.layout())
        for key in list(self.text_vars):
            if key.split(".")[0] in ("type", "layout"):
                del self.text_vars[key]
        self.slider_vars.clear()
        self.slider_labels.clear()
        self.boolean_vars.clear()
        self.font_vars.clear()
        self.system_font_vars.clear()
        self._build_typography(frame)
        self._resize_to_content()

    def _build_footer(self) -> None:
        footer = QHBoxLayout()
        reveal = QPushButton("Show config file")
        reveal.clicked.connect(self._reveal_config)
        footer.addWidget(reveal)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self._close)
        footer.addWidget(buttons)
        self.layout.addLayout(footer)
        QShortcut(QKeySequence.StandardKey.Save, self.root, activated=self._save)

    # --------------------------------------------------------------- saving

    def _collect(self) -> dict:
        """Read every control into a TOML-shaped dict."""
        self._stash_globs()
        values = dict(self.values)
        values.update({key: widget.text() for key, widget in self.text_vars.items()})
        values.update(self._typography_values())
        values["server.no_process"] = [
            line.strip() for line in values["server.no_process"].splitlines() if line.strip()
        ]
        if self.megabyte_var is not None:
            values["server.max_render_bytes"] = self._megabytes_as_bytes(self.megabyte_var.text())
        data: dict[str, dict] = {}
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
        if not math.isfinite(megabytes) or megabytes <= 0:
            raise ValueError("Largest rendered file must be a finite number greater than zero")
        byte_count = megabytes * 1024 * 1024
        if not math.isfinite(byte_count):
            raise ValueError("Largest rendered file is too large")
        return str(int(round(byte_count)))

    def _save(self) -> None:
        try:
            config = parse_config(self._collect(), user_config_path())
        except ConfigError as error:
            QMessageBox.critical(self.root, "These settings cannot be saved", str(error))
            return
        except ValueError as error:
            QMessageBox.critical(self.root, "These settings cannot be saved", f"Not a number: {error}")
            return
        login_error = None
        try:
            installed = autostart.is_installed()
            if self.login_var.isChecked() and not installed:
                autostart.install(Path.home())
            elif not self.login_var.isChecked() and installed:
                autostart.uninstall()
        except Exception as error:  # noqa: BLE001 - show, do not crash
            login_error = f"Could not update the login item: {error}"
        try:
            save_config(config)
        except (ConfigError, OSError) as error:
            QMessageBox.critical(self.root, "Could not write the config file", str(error))
            return
        if self.callback is not None:
            self.callback(config)
        if login_error:
            QMessageBox.warning(self.root, "Settings saved, but the login item failed", login_error)
        elif config.server.port != self.config.server.port:
            QMessageBox.information(self.root, "Settings saved", "The new port takes effect after serv restarts.")
        self.config = config
        self._close()

    def _reveal_config(self) -> None:
        path = user_config_path()
        if not path.is_file():
            try:
                save_config(self.config)
            except (ConfigError, OSError) as error:
                QMessageBox.critical(self.root, "Could not write the config file", str(error))
                return
        _reveal(path)

    def _close(self) -> None:
        self.root.close()

    def show(self) -> None:
        """Show the dialog and block until it closes."""
        self.root.show()
        if not self._centered:
            screen = self.root.screen() or self.application.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                frame = self.root.frameGeometry()
                x = area.x() + max((area.width() - frame.width()) // 2, 0)
                y = area.y() + max((area.height() - frame.height()) // 3, 0)
                self.root.move(x, y)
            self._centered = True
        self.root.raise_()
        self.root.activateWindow()
        self.root.exec()


def show_settings(config: Config, callback: SaveCallback | None = None) -> None:
    """Open the settings window and block until it closes."""
    SettingsWindow(config, callback).show()


def show_error(title: str, detail: str) -> None:
    """Show a blocking error dialog, even without a settings window."""
    _get_application()
    dialog = QMessageBox(QMessageBox.Icon.Critical, title, detail, QMessageBox.StandardButton.Ok)
    dialog.setWindowModality(Qt.WindowModality.ApplicationModal)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.exec()


def ask_start_at_login_if_needed(config: Config | None = None) -> bool | None:
    """Ask once on first launch, then write a config to record the answer."""
    if user_config_path().is_file():
        return None
    _get_application()
    answer = QMessageBox.question(
        None,
        "Start serv at login?",
        "serv can start automatically and live in the tray, so "
        "http://localhost:1002/ always works.\n\n"
        "You can change this later in serv settings.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    wanted = answer == QMessageBox.StandardButton.Yes
    if wanted:
        try:
            autostart.install(Path.home())
        except Exception as error:  # noqa: BLE001 - never block the app
            print(f"serv: could not install the login item: {error}", flush=True)
    try:
        save_config(config or load_config())
    except (ConfigError, OSError) as error:
        print(f"serv: could not write {user_config_path()}: {error}", flush=True)
    return wanted
