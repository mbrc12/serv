"""Configuration watching and the LaunchAgent plist."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import threading

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


def test_watcher_holds_config_lock_while_loading(
    state: ServerState, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()
    lock_acquired_during_load = []

    def load_while_paused(_explicit: str | None = None):
        acquired = state.config_lock.acquire(blocking=False)
        lock_acquired_during_load.append(acquired)
        if acquired:
            state.config_lock.release()
        entered.set()
        assert release.wait(2)
        return state.config

    monkeypatch.setattr(watch, "load_config", load_while_paused)
    watcher = watch.ConfigWatcher(state)
    thread = threading.Thread(target=watcher.reload)
    thread.start()
    try:
        assert entered.wait(2)
    finally:
        release.set()
        thread.join(2)

    assert not thread.is_alive()
    assert lock_acquired_during_load == [False]


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
