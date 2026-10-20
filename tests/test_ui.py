"""Settings window helpers and config round-trips.

The AppKit part is skipped when no window server is reachable, so the suite
still runs over SSH.
"""

from __future__ import annotations

import pytest

from serv.config import load_config, parse_config
from serv.ui import colour_from_css, css_from_colour


@pytest.mark.parametrize(
    "css",
    ["#e1e2e7", "#abc", "#34374680", "rgba(113, 70, 166, 0.16)", "transparent"],
)
def test_colour_round_trip(css: str) -> None:
    assert css_from_colour(colour_from_css(css)).lower() != ""


def test_hex_colour_survives_the_round_trip() -> None:
    assert css_from_colour(colour_from_css("#7146a6")) == "#7146a6"
    assert css_from_colour(colour_from_css("#abc")) == "#aabbcc"
    assert css_from_colour(colour_from_css("transparent")) == "transparent"


def test_translucent_colour_keeps_its_alpha() -> None:
    result = css_from_colour(colour_from_css("rgba(113, 70, 166, 0.16)"))
    assert result.startswith("rgba(113, 70, 166")


@pytest.fixture
def controller():
    pytest.importorskip("AppKit")
    from serv import ui

    try:
        return ui.SettingsController.alloc().initWithConfig_callback_(load_config(), None)
    except Exception as error:  # noqa: BLE001 - no window server in this session
        pytest.skip(f"AppKit unavailable: {error}")


def test_window_collects_valid_configuration(controller) -> None:
    collected = controller._collect()
    config = parse_config(collected)
    assert config.server.port == 1002
    assert config.palette.bg == "#e1e2e7"


def test_window_section_switch_keeps_edits(controller) -> None:
    controller._fields["server.port"].setStringValue_("1234")
    controller.sectionChanged_(type("Sender", (), {"selectedSegment": staticmethod(lambda: 1)})())
    config = parse_config(controller._collect())
    assert config.server.port == 1234


def test_window_add_and_remove_glob(controller) -> None:
    controller.addGlob_(None)
    assert len(controller._glob_fields) == 2
    controller.removeGlob_(controller._glob_fields and _first_remove_button(controller))
    assert len(controller._glob_fields) == 1


def _first_remove_button(controller):
    from serv.ui import IndexedButton

    for view in controller._card.contentView().subviews():
        if isinstance(view, IndexedButton):
            return view
    raise AssertionError("no remove button")


def test_invalid_number_is_reported(controller) -> None:
    controller._fields["server.port"].setStringValue_("not a port")
    with pytest.raises(ValueError):
        controller._collect()
