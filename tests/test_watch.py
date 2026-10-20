"""Configuration watching and the LaunchAgent plist."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from serv import watch
from serv.config import load_config, save_config
from serv.server import ServerState


@pytest.fixture
def state(tmp_path: Path) -> ServerState:
    return ServerState.create(load_config(), tmp_path, 0)


def test_watcher_applies_an_external_edit(tmp_path: Path, state: ServerState) -> None:
    path = tmp_path / "serv.toml"
    save_config(state.config, path)
    watcher = watch.ConfigWatcher(state, str(path))

    changed = replace(
        state.config,
        layout=replace(state.config.layout, md_width="52rem"),
    )
    save_config(changed, path)
    watcher.reload()

    assert state.config.layout.md_width == "52rem"
    # The stylesheet is regenerated, so the served CSS carries the new width.
    assert "max-width: 52rem" in state.stylesheet


def test_watcher_reports_a_broken_file_and_keeps_serving(
    tmp_path: Path, state: ServerState
) -> None:
    path = tmp_path / "serv.toml"
    save_config(state.config, path)
    original = state.config
    watcher = watch.ConfigWatcher(state, str(path))

    path.write_text("[palette]\nbg = \"nonsense\"\n")
    watcher.reload()

    assert state.config == original
    assert state.snapshot().last_error is not None
