"""Exercise real Qt controls without touching the user's settings or login item."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

# Real widgets work on headless CI too. No pytest-qt dependency is needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QPushButton,
    QTabWidget,
)

from serv import ui
from serv.config import ConfigError, load_config, parse_config, save_config
from serv.schemes import CUSTOM, label_for, load_schemes


@pytest.fixture(scope="session")
def application():
    return ui._get_application()


@pytest.fixture(autouse=True)
def safe_io(monkeypatch, tmp_path: Path):
    target = tmp_path / "serv.toml"
    monkeypatch.setattr(ui, "user_config_path", lambda: target)
    monkeypatch.setattr(ui, "save_config", lambda config: save_config(config, target))
    monkeypatch.setattr(ui.autostart, "is_installed", lambda: False)
    monkeypatch.setattr(ui.autostart, "install", Mock())
    monkeypatch.setattr(ui.autostart, "uninstall", Mock())
    monkeypatch.setattr(ui, "_reveal", Mock())
    for method in ("critical", "warning", "information"):
        monkeypatch.setattr(QMessageBox, method, Mock())
    monkeypatch.setattr(QMessageBox, "question", Mock(return_value=QMessageBox.StandardButton.No))
    return target


@pytest.fixture
def window(application):
    instance = ui.SettingsWindow(load_config())
    application.processEvents()
    yield instance
    instance.root.close()
    instance.root.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_window_has_three_sections(window) -> None:
    assert isinstance(window.root, QDialog)
    assert isinstance(window.notebook, QTabWidget)
    assert [window.notebook.tabText(index).replace("&&", "&") for index in range(window.notebook.count())] == [
        "General", "Colors", "Type & Layout"
    ]


def test_tabs_have_room_for_their_controls(window, application) -> None:
    window.root.show()
    for index in (1, 2, 0):
        window.notebook.setCurrentIndex(index)
        application.processEvents()
        assert window.root.height() >= window.layout.minimumSize().height()
        assert window.notebook.currentWidget().height() >= window.notebook.currentWidget().minimumSizeHint().height()


def test_application_is_reused_and_fusion_is_forced(application, window) -> None:
    application.setStyle("Windows")
    assert ui._get_application() is application
    assert window.application is application
    assert application.style().objectName().lower() == "fusion"
    assert ui._application is application


def test_native_file_and_color_dialogs_are_disabled(application) -> None:
    assert application.testAttribute(Qt.ApplicationAttribute.AA_DontUseNativeDialogs)


def test_every_color_has_a_standard_button_swatch(window) -> None:
    assert len(window.swatches) == 28
    assert "palette.zebra" in window.swatches
    assert "code.highlight" in window.swatches
    assert all(isinstance(button, QPushButton) for button in window.swatches.values())
    assert all(not button.icon().isNull() for button in window.swatches.values())
    assert all(button.accessibleName() for button in window.swatches.values())


def test_collected_values_form_a_valid_config(window) -> None:
    config = parse_config(window._collect())
    assert config.server.port == 1002
    assert config.palette.bg == "#e1e2e7"


def test_glob_rows_can_be_added_edited_and_removed(window) -> None:
    before = len(window.glob_entries)
    window._add_glob()
    assert len(window.glob_entries) == before + 1
    window.glob_entries[-1].setText("  *.raw  ")
    assert window._collect()["server"]["no_process"][-1] == "*.raw"
    window._remove_glob(0)
    assert len(window.glob_entries) == before
    while window.glob_entries:
        window._remove_glob(0)
    assert window._collect()["server"]["no_process"] == []


def test_blank_glob_rows_are_not_saved(window) -> None:
    window._add_glob()
    window.glob_entries[-1].clear()
    assert "" not in window._collect()["server"]["no_process"]


def test_scheme_selection_replaces_colors(window) -> None:
    dark = next(scheme for scheme in load_schemes() if scheme.key == "tokyo-night")
    window.scheme_combo.setCurrentText(dark.label)
    window.scheme_combo.activated.emit(window.scheme_combo.currentIndex())
    assert window.values["palette.bg"] == dark.palette.bg
    assert window.scheme_var.currentText() == dark.label


def test_editing_a_color_marks_the_scheme_custom(window) -> None:
    window.values["palette.bg"] = "#123456"
    window._refresh_swatches()
    assert window.scheme_var.currentText() == label_for(CUSTOM)


def test_color_dialog_is_non_native_and_updates_the_swatch(window, monkeypatch) -> None:
    picker = Mock(return_value=QColor("#123456"))
    monkeypatch.setattr(QColorDialog, "getColor", picker)
    window.swatches["palette.bg"].click()
    assert picker.call_args.args[3] & QColorDialog.ColorDialogOption.DontUseNativeDialog
    assert picker.call_args.args[1] is window.root
    assert window.values["palette.bg"] == "#123456"
    assert window.swatches["palette.bg"].toolTip() == "#123456"
    assert window.scheme_var.currentText() == label_for(CUSTOM)


def test_cancelling_color_selection_preserves_the_value(window, monkeypatch) -> None:
    before = dict(window.values)
    monkeypatch.setattr(QColorDialog, "getColor", lambda *args: QColor())
    window._pick_color("palette.bg")
    assert window.values == before


def test_slider_values_are_rounded_and_reach_the_config(window) -> None:
    window.slider_vars["type.md_size"].setValue(133)
    assert window.slider_vars["type.md_size"].value() == 135
    assert window.slider_labels["type.md_size"].text() == "1.35rem"
    assert parse_config(window._collect()).type.md_size == "1.35rem"


def test_sliders_cover_lengths_and_unitless_line_spacing(window) -> None:
    for key, position, expected in (
        ("type.code_size", 1260, "12.5px"),
        ("type.line_height", 173, "1.75"),
        ("layout.md_width", 5100, "52rem"),
    ):
        window.slider_vars[key].setValue(position)
        assert window.slider_labels[key].text() == expected
        section, name = key.split(".")
        assert window._collect()[section][name] == expected


def test_rebuilding_the_type_tab_keeps_all_edits(window) -> None:
    window.text_vars["server.port"].setText("1234")
    window.megabyte_var.setText("2.5")
    window.glob_entries[0].setText("*.raw")
    window.slider_vars["type.md_size"].setValue(135)
    window.underline_links_var.setChecked(False)
    window._rebuild_typography()
    config = parse_config(window._collect())
    assert config.server.port == 1234
    assert config.server.max_render_bytes == 2621440
    assert config.server.no_process[0] == "*.raw"
    assert config.type.md_size == "1.35rem"
    assert config.type.underline_links is False


def test_unusual_units_remain_editable_as_text(window) -> None:
    window.values["type.md_size"] = "18px"
    window.slider_vars.pop("type.md_size")
    window._rebuild_typography()
    assert "type.md_size" not in window.slider_vars
    window.text_vars["type.md_size"].setText("20px")
    window._rebuild_typography()
    assert parse_config(window._collect()).type.md_size == "20px"


def test_underline_checkbox_reaches_config(window) -> None:
    window.underline_links_var.setChecked(False)
    assert parse_config(window._collect()).type.underline_links is False
    window.underline_links_var.setChecked(True)
    assert parse_config(window._collect()).type.underline_links is True


def test_largest_file_is_edited_in_megabytes(window) -> None:
    assert window.megabyte_var.text() == "1"
    assert window._collect()["server"]["max_render_bytes"] == 1048576
    window.megabyte_var.setText("2.5")
    assert window._collect()["server"]["max_render_bytes"] == 2621440


@pytest.mark.parametrize("text", ["", "big", "0", "-1", "nan", "inf", "1e308"])
def test_bad_megabyte_values_are_rejected(text: str) -> None:
    with pytest.raises(ValueError):
        ui.SettingsWindow._megabytes_as_bytes(text)


def test_font_dropdown_offers_catalogue_then_installed_fonts(window, monkeypatch) -> None:
    from serv import fonts

    monkeypatch.setattr(window, "_installed_families", lambda *_: ["Local Reading", "Local Mono"])
    window.notebook.setCurrentIndex(2)
    combo = window.font_vars["reading"]
    assert isinstance(combo, QComboBox)
    assert [combo.itemText(index) for index in range(combo.count())] == [
        *[choice.name for choice in fonts.choices_for("reading")], ui.SYSTEM_FONT_ITEM
    ]
    window.slider_vars["type.md_size"].setValue(135)
    combo.setCurrentText(ui.SYSTEM_FONT_ITEM)
    combo.activated.emit(combo.currentIndex())
    assert window.local_font["reading"] is True
    assert window.values["type.reading_weights"] == ""
    assert window.values["type.reading"] == "Local Reading"
    assert "reading" in window.system_font_vars
    assert window.slider_labels["type.md_size"].text() == "1.35rem"
    combo = window.font_vars["reading"]
    combo.setCurrentText("Literata")
    combo.activated.emit(combo.currentIndex())
    assert window.local_font["reading"] is False
    assert window.values["type.reading_weights"].startswith("ital,wght@")
    assert "reading" not in window.system_font_vars


def test_installed_font_change_preserves_catalogue_weights(window, monkeypatch) -> None:
    monkeypatch.setattr(window, "_installed_families", lambda *_: ["Local Reading", "Literata"])
    window.font_vars["reading"].setCurrentText(ui.SYSTEM_FONT_ITEM)
    window._font_choice_changed("reading")
    combo = window.system_font_vars["reading"]
    combo.setCurrentText("Literata")
    combo.activated.emit(combo.currentIndex())
    assert window.local_font["reading"] is True
    assert window.values["type.reading"] == "Literata"
    assert window.values["type.reading_weights"].startswith("ital,wght@")


def test_unknown_installed_font_is_kept_in_the_list(window, monkeypatch) -> None:
    monkeypatch.setattr(window, "_installed_families", lambda *_: ["Other family"])
    window.values["type.mono"] = "Missing family"
    window.local_font["mono"] = True
    window._rebuild_typography()
    assert window.system_font_vars["mono"].currentText() == "Missing family"
    assert window._collect()["type"]["mono"] == "Missing family"


def test_installed_families_use_qt_font_database(application) -> None:
    assert ui.SettingsWindow._installed_families() == sorted(set(QFontDatabase.families()))


def test_save_writes_config_calls_callback_and_closes(window, safe_io, monkeypatch) -> None:
    callback = Mock()
    window.callback = callback
    closed = Mock()
    monkeypatch.setattr(window, "_close", closed)
    window._save()
    assert safe_io.is_file()
    assert "Page background" not in safe_io.read_text()
    callback.assert_called_once_with(window.config)
    closed.assert_called_once()


@pytest.mark.parametrize("key, value", [("server.port", "bad"), ("server.port", "99999"), ("cache.entries", "-1")])
def test_invalid_settings_show_error_and_do_not_save(window, safe_io, key, value) -> None:
    window.text_vars[key].setText(value)
    window._save()
    QMessageBox.critical.assert_called_once()
    assert not safe_io.exists()
    ui.autostart.install.assert_not_called()


def test_write_failure_keeps_dialog_open(window, monkeypatch) -> None:
    monkeypatch.setattr(ui, "save_config", Mock(side_effect=OSError("Read-only file")))
    close = Mock()
    monkeypatch.setattr(window, "_close", close)
    window.callback = Mock()
    window._save()
    QMessageBox.critical.assert_called_once()
    close.assert_not_called()
    window.callback.assert_not_called()


@pytest.mark.parametrize("installed,wanted,method", [(False, True, "install"), (True, False, "uninstall")])
def test_save_updates_login_item(window, monkeypatch, installed, wanted, method) -> None:
    monkeypatch.setattr(ui.autostart, "is_installed", lambda: installed)
    window.login_var.setChecked(wanted)
    window._save()
    getattr(ui.autostart, method).assert_called_once()


def test_login_failure_warns_but_settings_are_saved(window, safe_io, monkeypatch) -> None:
    window.login_var.setChecked(True)
    monkeypatch.setattr(ui.autostart, "install", Mock(side_effect=OSError("No permission")))
    window._save()
    assert safe_io.is_file()
    QMessageBox.warning.assert_called_once()


def test_port_change_explains_restart(window) -> None:
    window.text_vars["server.port"].setText("1234")
    window._save()
    QMessageBox.information.assert_called_once()
    assert window.config.server.port == 1234


def test_reveal_config_creates_file_before_showing_it(window, safe_io) -> None:
    window._reveal_config()
    assert safe_io.is_file()
    ui._reveal.assert_called_once_with(safe_io)


def test_reveal_failure_shows_error(window, monkeypatch) -> None:
    monkeypatch.setattr(ui, "save_config", Mock(side_effect=ConfigError("Cannot save")))
    window._reveal_config()
    QMessageBox.critical.assert_called_once()
    ui._reveal.assert_not_called()


def test_cancel_does_not_save(window, safe_io) -> None:
    buttons = window.root.findChild(QDialogButtonBox)
    buttons.button(QDialogButtonBox.StandardButton.Cancel).click()
    assert not safe_io.exists()
    ui.autostart.install.assert_not_called()


def test_save_button_is_connected(window, safe_io) -> None:
    buttons = window.root.findChild(QDialogButtonBox)
    buttons.button(QDialogButtonBox.StandardButton.Save).click()
    assert safe_io.is_file()


def test_show_settings_and_error_reuse_application(application) -> None:
    def close_dialog():
        for widget in application.topLevelWidgets():
            if isinstance(widget, QDialog) and widget.isVisible():
                widget.reject()

    for _ in range(2):
        QTimer.singleShot(0, close_dialog)
        ui.show_settings(load_config())
        QTimer.singleShot(0, close_dialog)
        ui.show_error("Problem", "Details")
        assert QApplication.instance() is application
        assert ui._application is application


@pytest.mark.parametrize("wanted", [True, False])
def test_first_launch_asks_and_records_answer(application, safe_io, wanted) -> None:
    QMessageBox.question.return_value = QMessageBox.StandardButton.Yes if wanted else QMessageBox.StandardButton.No
    assert ui.ask_start_at_login_if_needed(load_config()) is wanted
    assert safe_io.is_file()
    assert ui.autostart.install.call_count == int(wanted)
    assert ui.ask_start_at_login_if_needed() is None
    QMessageBox.question.assert_called_once()


def test_first_launch_login_failure_still_records_answer(application, safe_io, monkeypatch, capsys) -> None:
    QMessageBox.question.return_value = QMessageBox.StandardButton.Yes
    monkeypatch.setattr(ui.autostart, "install", Mock(side_effect=OSError("No permission")))
    assert ui.ask_start_at_login_if_needed() is True
    assert safe_io.is_file()
    assert "could not install the login item" in capsys.readouterr().out


def test_first_launch_write_failure_is_reported(application, safe_io, monkeypatch, capsys) -> None:
    monkeypatch.setattr(ui, "save_config", Mock(side_effect=OSError("Read-only file")))
    assert ui.ask_start_at_login_if_needed() is False
    assert not safe_io.exists()
    assert "could not write" in capsys.readouterr().out
