"""Loopback-only browser settings served on a separate ephemeral port."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, fields, replace
import hmac
import http.server
import json
from pathlib import Path
import secrets
import threading
import urllib.parse
import webbrowser

import deal

from . import autostart, fonts, labels, schemes
from .config import Config, ConfigError, default_config_path, parse_config, save_config
from .locations import user_config_path
from .resources import data_path
from .server import ServerState

MAX_BODY_BYTES = 64 * 1024


def _save_path(config: Config) -> Path:
    """Write to the active config, or create a user file for bundled defaults."""
    source = config.source
    bundled = default_config_path()
    if source is None or (bundled is not None and source.resolve() == bundled.resolve()):
        return user_config_path()
    return source


def _config_data(config: Config) -> dict:
    data = asdict(config)
    data.pop("source", None)
    data["server"]["no_process"] = list(config.server.no_process)
    return data


@deal.raises(ConfigError, ValueError)
@deal.ensure(lambda config, key, value, result=None: isinstance(result, Config))
def update_config(config: Config, key: str, value: object) -> Config:
    """Validate and persist one setting, returning the saved configuration."""
    if key == "scheme":
        scheme = next((item for item in schemes.load_schemes() if item.key == value), None)
        if scheme is None:
            raise ValueError(f"Unknown color scheme: {value!r}")
        draft = schemes.apply(config, scheme)
    else:
        try:
            section_name, field_name = key.split(".", 1)
        except ValueError as error:
            raise ValueError(f"Unknown setting: {key!r}") from error
        if section_name not in {"server", "cache", "palette", "accents", "code", "type", "layout"}:
            raise ValueError(f"Unknown setting: {key!r}")
        section = getattr(config, section_name)
        known_fields = {field.name for field in fields(section)}
        if field_name not in known_fields:
            raise ValueError(f"Unknown setting: {key!r}")

        current = getattr(section, field_name)
        if field_name == "no_process" and section_name == "server":
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise ValueError("Verbatim patterns must be a list of strings")
            value = tuple(value)
        elif type(current) is bool:
            if type(value) is not bool:
                raise ValueError(f"{key} must be true or false")
        elif type(current) is int:
            if type(value) is not int:
                raise ValueError(f"{key} must be an integer")
        elif not isinstance(value, str):
            raise ValueError(f"{key} must be text")

        changes = {field_name: value}
        if section_name == "type" and field_name in {"reading", "mono"}:
            changes[f"{field_name}_weights"] = fonts.weights_for(field_name, value) or ""
        draft = replace(config, **{section_name: replace(section, **changes)})

    target = _save_path(config)
    validated = parse_config(_config_data(draft), source=target)
    save_config(validated, target)
    return validated


def _payload(state: ServerState) -> dict:
    config = state.config
    return {
        "config": _config_data(config),
        "root": str(state.root),
        "schemes": [{"key": item.key, "label": item.label} for item in schemes.load_schemes()],
        "scheme": schemes.name_for(config),
        "labels": labels.load_labels(),
        "fonts": {
            role: [asdict(choice) for choice in fonts.choices_for(role)]
            for role in fonts.ROLES
        },
        "autostart": autostart.is_installed(),
        "active_port": state.port,
        "restart_required": config.server.port != state.port,
    }


class SettingsWebServer:
    """Serve the settings page on an OS-assigned loopback port."""

    def __init__(
        self,
        state: ServerState,
        *,
        restart_root: Callable[[Path], None] | None = None,
    ) -> None:
        self.state = state
        self._restart_root = restart_root
        self.token = secrets.token_urlsafe(32)
        self._thread: threading.Thread | None = None
        owner = self

        class Handler(http.server.BaseHTTPRequestHandler):
            server_version = "serv-settings"

            def log_message(self, _format: str, *args: object) -> None:
                return

            def _host_ok(self) -> bool:
                return self.headers.get("Host", "").lower() == f"127.0.0.1:{owner.port}"

            def _authorized(self) -> bool:
                expected = f"Bearer {owner.token}"
                received = self.headers.get("Authorization", "")
                return hmac.compare_digest(received, expected)

            def _origin_ok(self) -> bool:
                origin = self.headers.get("Origin")
                return origin is None or origin == f"http://127.0.0.1:{owner.port}"

            def _send(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status: int, payload: dict) -> None:
                self._send(
                    status,
                    json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8",
                )

            def _deny(self, status: int = 403) -> None:
                self._json(status, {"error": "Request not allowed"})

            def _api_guard(self) -> bool:
                if not self._host_ok() or not self._origin_ok():
                    self._deny()
                    return False
                if not self._authorized():
                    self._deny(401)
                    return False
                return True

            def _read_json(self) -> dict:
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Expected an application/json request")
                length_text = self.headers.get("Content-Length", "0")
                try:
                    length = int(length_text)
                except ValueError as error:
                    raise ValueError("Invalid Content-Length") from error
                if not 0 <= length <= MAX_BODY_BYTES:
                    raise ValueError("Request body is too large")
                try:
                    payload = json.loads(self.rfile.read(length))
                except (json.JSONDecodeError, UnicodeDecodeError) as error:
                    raise ValueError("Invalid JSON") from error
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
                return payload

            def do_GET(self) -> None:  # noqa: N802
                if not self._host_ok():
                    self._deny()
                    return
                path = urllib.parse.urlsplit(self.path).path
                if path == "/":
                    self._send_html(data_path("settings/index.html").read_bytes())
                elif path == "/settings.css":
                    self._send(200, data_path("settings/settings.css").read_bytes(), "text/css; charset=utf-8")
                elif path == "/settings.js":
                    self._send(200, data_path("settings/settings.js").read_bytes(), "text/javascript; charset=utf-8")
                elif path == "/api/settings":
                    if self._api_guard():
                        self._json(200, _payload(owner.state))
                elif path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                else:
                    self._json(404, {"error": "Not found"})

            def _send_html(self, body: bytes) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", owner.content_security_policy)
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:  # noqa: N802
                if not self._host_ok() or not self._origin_ok() or not self._authorized():
                    self._deny(401)
                    return
                path = urllib.parse.urlsplit(self.path).path
                try:
                    payload = self._read_json()
                    if path == "/api/settings":
                        key = payload.get("key")
                        if not isinstance(key, str):
                            raise ValueError("Setting key must be text")
                        with owner.state.config_lock:
                            old_config = owner.state.config
                            target = _save_path(old_config)
                            restart_root = owner._restart_root
                            if key == "server.root" and restart_root is None:
                                raise ValueError("Root changes require a running server")
                            config = update_config(old_config, key, payload.get("value"))
                            if key == "server.root":
                                if config.server.root is None or restart_root is None:
                                    raise ValueError("Root cannot be empty")
                                try:
                                    restart_root(Path(config.server.root))
                                except Exception:
                                    try:
                                        save_config(old_config, target)
                                    except Exception as rollback_error:  # noqa: BLE001
                                        owner.state.note_error(
                                            f"settings root rollback failed: {rollback_error}"
                                        )
                                    raise
                            owner.state.apply_config(config)
                        response = _payload(owner.state)
                        response["saved_key"] = key
                        self._json(200, response)
                    elif path == "/api/autostart":
                        enabled = payload.get("enabled")
                        if type(enabled) is not bool:
                            raise ValueError("enabled must be true or false")
                        installed = autostart.is_installed()
                        if enabled and not installed:
                            autostart.install(Path.home())
                        elif not enabled and installed:
                            autostart.uninstall()
                        self._json(200, {"autostart": autostart.is_installed()})
                    elif path == "/api/reveal":
                        with owner.state.config_lock:
                            config = owner.state.config
                            target = _save_path(config)
                            if not target.is_file():
                                save_config(config, target)
                        _reveal_config(target)
                        self._json(200, {"ok": True})
                    else:
                        self._json(404, {"error": "Not found"})
                except (ConfigError, OSError, ValueError) as error:
                    self._json(400, {"error": str(error)})
                except Exception as error:  # noqa: BLE001 - keep the settings server alive
                    owner.state.note_error(f"settings: {type(error).__name__}: {error}")
                    self._json(500, {"error": "Settings update failed"})

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.httpd.block_on_close = False
        self.port = self.httpd.server_address[1]
        self.content_security_policy = (
            "default-src 'none'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net https://fonts.googleapis.com 'unsafe-inline'; "
            "connect-src 'self' data:; img-src 'self' data:; "
            "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
            "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        )

    @property
    def url(self) -> str:
        """Browser URL with the API token kept in the fragment, never sent to HTTP."""
        return f"http://127.0.0.1:{self.port}/#token={self.token}"

    def start(self) -> str:
        """Start serving in a daemon thread and return the settings URL."""
        if self._thread is None:
            self._thread = threading.Thread(
                target=self.httpd.serve_forever,
                kwargs={"poll_interval": 0.2},
                name="serv-settings-http",
                daemon=True,
            )
            self._thread.start()
        return self.url

    def stop(self) -> None:
        """Stop accepting requests and release the random port."""
        if self._thread is None:
            self.httpd.server_close()
            return
        self.httpd.shutdown()
        self.httpd.server_close()
        self._thread.join(timeout=2)
        self._thread = None


def _reveal_config(path: Path) -> None:
    """Open the config file in its platform file manager."""
    import subprocess
    import sys

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform.startswith("win"):
        import os

        os.startfile(str(path))  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path.parent)])


def open_settings(server: SettingsWebServer) -> bool:
    """Open the browser settings page; return whether the browser launched."""
    return webbrowser.open(server.start(), new=2)
