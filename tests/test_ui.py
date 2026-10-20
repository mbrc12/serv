"""The Tk settings window.

The window is built for real (Tk is available wherever this suite runs), which
catches widget wiring mistakes that a pure-logic test would miss. Saving is
exercised through ``save_config`` with a temporary path so a test run can never
rewrite the developer's own settings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from serv.config import load_config, parse_config, save_config
from serv.schemes import CUSTOM, label_for, load_schemes

tk = pytest.importorskip("tkinter")


@pytest.fixture(scope="module")
def window():
    pytest.importorskip("serv.ui")
    from serv.ui import SettingsWindow

    try:
        instance = SettingsWindow(load_config())
    except tk.TclError as error:  # no display in this session
        pytest.skip(f"Tk unavailable: {error}")
    instance.root.update_idletasks()
    yield instance
    instance.root.destroy()


def test_window_has_three_sections(window) -> None:
    tabs = [window.notebook.tab(tab, "text") for tab in window.notebook.tabs()]
    assert tabs == ["General", "Colors", "Type & Layout"]


def test_every_color_has_a_swatch(window) -> None:
    assert len(window.swatches) == 25
    assert "palette.zebra" in window.swatches
    assert "code.highlight" in window.swatches


def test_collected_values_form_a_valid_config(window) -> None:
    config = parse_config(window._collect())
    assert config.server.port == 1002
    assert config.palette.bg == "#e1e2e7"


def test_glob_rows_can_be_added_and_removed(window) -> None:
    before = len(window.glob_entries)
    window._add_glob()
    window.root.update_idletasks()
    assert len(window.glob_entries) == before + 1
    window._remove_glob(0)
    window.root.update_idletasks()
    assert len(window.glob_entries) == before


def test_scheme_selection_replaces_colors(window) -> None:
    dark = next(scheme for scheme in load_schemes() if scheme.key == "tokyo-night")
    window.scheme_var.set(dark.label)
    window._scheme_changed()
    assert window.values["palette.bg"] == dark.palette.bg
    assert window.scheme_var.get() == dark.label


def test_editing_a_color_marks_the_scheme_custom(window) -> None:
    window.values["palette.bg"] = "#123456"
    window._refresh_swatches()
    assert window.scheme_var.get() == label_for(CUSTOM)


def test_slider_values_reach_the_config(window) -> None:
    variable = window.slider_vars["type.md_size"]
    variable.set(1.33)
    window._slider_moved("type.md_size")
    assert window.slider_labels["type.md_size"].get() == "1.35rem"
    assert parse_config(window._collect()).type.md_size == "1.35rem"


def test_rebuilding_the_type_tab_keeps_general_edits(window) -> None:
    window.text_vars["server.port"].set("1234")
    window._rebuild_typography()
    window.root.update_idletasks()
    assert parse_config(window._collect()).server.port == 1234


def test_largest_file_is_edited_in_megabytes(window) -> None:
    assert window.megabyte_var.get() == "1"
    assert window._collect()["server"]["max_render_bytes"] == 1048576

    window.megabyte_var.set("2.5")
    assert window._collect()["server"]["max_render_bytes"] == int(2.5 * 1024 * 1024)


@pytest.mark.parametrize("text", ["", "big", "0", "-1"])
def test_bad_megabyte_values_are_rejected(text: str) -> None:
    from serv.ui import SettingsWindow

    with pytest.raises(ValueError):
        SettingsWindow._megabytes_as_bytes(text)


def test_font_dropdown_offers_the_catalogue_then_installed_fonts(window) -> None:
    from serv import fonts
    from serv.ui import SYSTEM_FONT_ITEM

    window.notebook.select(2)
    window.root.update_idletasks()
    catalogue = [choice.name for choice in fonts.choices_for("reading")]
    assert window.values["type.reading"] in catalogue

    window.font_vars["reading"].set(SYSTEM_FONT_ITEM)
    window._font_choice_changed("reading")
    window.root.update_idletasks()
    assert window.local_font["reading"] is True
    assert window.values["type.reading_weights"] == ""
    assert window.values["type.reading"]  # an installed family was chosen
    assert "reading" in window.system_font_vars

    window.font_vars["reading"].set("Literata")
    window._font_choice_changed("reading")
    window.root.update_idletasks()
    assert window.local_font["reading"] is False
    assert window.values["type.reading_weights"].startswith("ital,wght@")
    assert "reading" not in window.system_font_vars


def test_save_config_writes_a_temporary_file(window, tmp_path: Path) -> None:
    target = tmp_path / "serv.toml"
    config = parse_config(window._collect())
    save_config(config, target)
    assert target.is_file()
    assert "Page background" not in target.read_text()  # labels stay in the UI
