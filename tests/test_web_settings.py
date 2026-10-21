"""Tests for the loopback browser settings server and immediate persistence."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from serv import autostart, schemes, web_settings
from serv.config import load_config, save_config as persist_config
from serv.server import ServerState


@pytest.fixture
def server(tmp_path, monkeypatch):
    state = ServerState.create(load_config(), tmp_path, 1002)
    config_path = tmp_path / "serv.toml"
    monkeypatch.setattr(web_settings, "_save_path", lambda _config: config_path)
    settings = web_settings.SettingsWebServer(
        state, restart_root=lambda root: setattr(state, "root", root)
    )
    settings.start()
    try:
        yield settings, state, config_path
    finally:
        settings.stop()


def api_url(settings, path="/api/settings"):
    return f"http://127.0.0.1:{settings.port}{path}"


def get_json(settings, path="/api/settings", *, token=None, origin=None):
    headers = {}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if origin is not None:
        headers["Origin"] = origin
    request = Request(api_url(settings, path), headers=headers)
    with urlopen(request) as response:
        return json.load(response)


def post_json(settings, key, value, *, path="/api/settings", origin=None):
    headers = {
        "Authorization": f"Bearer {settings.token}",
        "Content-Type": "application/json",
    }
    if origin is not None:
        headers["Origin"] = origin
    request = Request(
        api_url(settings, path),
        data=json.dumps({"key": key, "value": value}).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(request) as response:
        return json.load(response)


def test_settings_server_uses_a_separate_loopback_ephemeral_port(server):
    settings, state, _ = server

    assert settings.port != state.port
    assert settings.httpd.server_address[0] == "127.0.0.1"
    assert settings.url.endswith(f"#token={settings.token}")
    assert "token=" not in settings.url.split("#", 1)[0]


def test_open_settings_sends_fragment_token_to_the_browser(server, monkeypatch):
    settings, _, _ = server
    opened = []
    monkeypatch.setattr(web_settings.webbrowser, "open", lambda url, new: opened.append((url, new)) or True)

    assert web_settings.open_settings(settings) is True
    assert opened == [(settings.url, 2)]


def test_section_navigation_preserves_token_and_handles_repeated_clicks():
    root = Path(__file__).resolve().parents[1]
    script = (root / "data" / "settings" / "settings.js").read_text()

    assert "new URLSearchParams({ token, section: link.dataset.section })" in script
    assert "link.addEventListener('click'" in script
    assert "target.scrollIntoView();" in script
    assert "history.pushState(null, '', link.hash)" in script


def test_page_assets_and_api_require_token(server):
    settings, state, _ = server
    base = settings.url.split("#", 1)[0]

    with urlopen(base) as response:
        page = response.read().decode()
        policy = response.headers["Content-Security-Policy"]
        assert "cdn.jsdelivr.net" in policy
        assert "connect-src 'self' data:" in policy
        assert "fonts.googleapis.com" in policy
        assert "fonts.gstatic.com" in policy
    assert "settings" in page.lower()
    assert 'id="save-status"' in page
    assert "changes are saved automatically" not in page.lower()
    assert "on disk" not in page.lower()

    assets = {}
    for asset, content_type in (("settings.css", "text/css"), ("settings.js", "text/javascript")):
        with urlopen(base + asset) as response:
            assert response.status == 200
            assert content_type in response.headers["Content-Type"]
            assets[asset] = response.read().decode()
    assert "All changes saved" in assets["settings.js"]
    assert "Unsaved" in assets["settings.js"]
    assert '.status[data-state="saved"]' in assets["settings.css"]
    assert '.status[data-state="editing"]' in assets["settings.css"]

    with pytest.raises(HTTPError) as error:
        urlopen(api_url(settings))
    assert error.value.code == 401

    payload = get_json(settings, token=settings.token)
    assert payload["active_port"] == state.port
    assert payload["root"] == str(state.root)
    assert "config_path" not in payload
    assert payload["config"]["server"]["port"] == state.config.server.port
    assert payload["fonts"]["reading"]
    assert payload["schemes"]


def test_api_rejects_untrusted_origins(server):
    settings, _, _ = server
    with pytest.raises(HTTPError) as error:
        post_json(settings, "cache.entries", 12, origin="https://example.com")
    assert error.value.code == 401


def test_each_valid_change_is_saved_and_applied_immediately(server, monkeypatch):
    settings, state, config_path = server
    lock_state = []

    def save_while_locked(config, target):
        acquired = state.config_lock.acquire(blocking=False)
        lock_state.append(acquired)
        if acquired:
            state.config_lock.release()
        persist_config(config, target)

    monkeypatch.setattr(web_settings, "save_config", save_while_locked)
    payload = post_json(settings, "cache.entries", 23)

    assert config_path.is_file()
    assert "entries = 23" in config_path.read_text()
    assert state.config.cache.entries == 23
    assert payload["config"]["cache"]["entries"] == 23
    assert lock_state == [False]


def test_server_port_change_is_persisted_but_requires_restart(server):
    settings, state, config_path = server
    new_port = state.port + 1

    payload = post_json(settings, "server.port", new_port)

    assert state.config.server.port == new_port
    assert state.port != new_port
    assert payload["restart_required"] is True
    assert config_path.is_file()


def test_root_change_is_saved_and_restarts_the_file_server(server, tmp_path, monkeypatch):
    settings, state, config_path = server
    new_root = tmp_path / "served"
    new_root.mkdir()
    restarted = []

    def restart_root(root):
        restarted.append(root)
        state.root = root

    monkeypatch.setattr(settings, "_restart_root", restart_root)
    payload = post_json(settings, "server.root", str(new_root))

    assert state.root == new_root
    assert state.config.server.root == str(new_root)
    assert payload["root"] == str(new_root)
    assert restarted == [new_root]
    assert f'root = "{new_root}"' in config_path.read_text()


def test_invalid_root_does_not_persist_or_restart(server, tmp_path, monkeypatch):
    settings, state, config_path = server
    old_root = state.root
    restarted = []
    monkeypatch.setattr(settings, "_restart_root", restarted.append)

    with pytest.raises(HTTPError) as error:
        post_json(settings, "server.root", str(tmp_path / "missing"))

    assert error.value.code == 400
    assert state.root == old_root
    assert restarted == []
    assert not config_path.exists()


def test_failed_root_restart_restores_the_previous_config(server, tmp_path, monkeypatch):
    settings, state, config_path = server
    old_root = state.root
    new_root = tmp_path / "served"
    new_root.mkdir()

    def fail_restart(_root):
        raise OSError("port could not be rebound")

    monkeypatch.setattr(settings, "_restart_root", fail_restart)
    with pytest.raises(HTTPError) as error:
        post_json(settings, "server.root", str(new_root))

    assert error.value.code == 400
    assert state.root == old_root
    assert state.config.server.root is None
    assert 'root = ' not in config_path.read_text()


def test_pattern_list_is_persisted_as_a_list(server):
    settings, state, config_path = server
    patterns = ["~/private/**", "*.secret"]

    post_json(settings, "server.no_process", patterns)

    assert state.config.server.no_process == tuple(
        str(Path(pattern).expanduser()) for pattern in patterns
    )
    assert "~/private/**" in config_path.read_text()


def test_invalid_update_does_not_overwrite_or_apply(server):
    settings, state, config_path = server
    original = state.config
    with pytest.raises(HTTPError) as error:
        post_json(settings, "palette.bg", "not a color")

    assert error.value.code == 400
    assert state.config == original
    assert not config_path.exists()


def test_preset_updates_all_colors_in_one_write(server):
    settings, state, config_path = server
    scheme = schemes.load_schemes()[0]

    payload = post_json(settings, "scheme", scheme.key)

    assert schemes.name_for(state.config) == scheme.key
    assert payload["scheme"] == scheme.key
    assert config_path.is_file()
    for key, value in scheme.colors().items():
        section, field = key.split(".", 1)
        assert getattr(getattr(state.config, section), field) == value


def test_font_change_updates_its_webfont_weights(server):
    settings, state, _ = server

    post_json(settings, "type.reading", "Inter")

    assert state.config.type.reading == "Inter"
    assert state.config.type.reading_weights == "ital,wght@0,400;0,600;1,400"


def test_autostart_is_updated_without_rewriting_settings(server, monkeypatch):
    settings, _, config_path = server
    installed = False

    def is_installed():
        return installed

    def install(_path):
        nonlocal installed
        installed = True

    monkeypatch.setattr(autostart, "is_installed", is_installed)
    monkeypatch.setattr(autostart, "install", install)
    request = Request(
        api_url(settings, "/api/autostart"),
        data=b'{"enabled":true}',
        headers={
            "Authorization": f"Bearer {settings.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request) as response:
        assert json.load(response) == {"autostart": True}
    assert config_path.exists() is False


def test_reveal_creates_config_before_opening_it(server, monkeypatch):
    settings, state, config_path = server
    revealed = []
    lock_state = []

    def save_while_locked(config, target):
        acquired = state.config_lock.acquire(blocking=False)
        lock_state.append(acquired)
        if acquired:
            state.config_lock.release()
        persist_config(config, target)

    monkeypatch.setattr(web_settings, "save_config", save_while_locked)
    monkeypatch.setattr(web_settings, "_reveal_config", revealed.append)
    request = Request(
        api_url(settings, "/api/reveal"),
        data=b"{}",
        headers={
            "Authorization": f"Bearer {settings.token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    with urlopen(request) as response:
        assert json.load(response) == {"ok": True}
    assert config_path.exists()
    assert revealed == [config_path]
    assert lock_state == [False]
    assert state.config is not None
