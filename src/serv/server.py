"""The HTTP server: routing, listings, code pages and rendered Markdown.

The handler is intentionally thin. Path resolution lives in paths.py, page
building in page.py and markdown.py, so this module only decides which of those
to call and what to send back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import http.server
import io
from pathlib import Path
import socket
import threading
import time
import urllib.parse

from .cache import RenderCache, file_digest
from .config import Config
from .constants import CSS_URL, JS_URL
from .highlight import RAW_TEXT_EXTENSIONS, language_for
from .markdown import MarkdownRenderer
from .page import code_page, listing_page, read_chemistry_js
from .paths import NoProcessRules, resolve, rules_for, split_line_reference, strip_line_reference
from .theme import stylesheet_cached


@dataclass(frozen=True)
class Snapshot:
    """The state the tray menu displays."""

    port: int
    root: Path
    requests: int
    cached_pages: int
    cache_hits: int
    cache_misses: int
    paused: bool
    last_error: str | None
    last_error_time: float | None
    started_at: float


@dataclass
class ServerState:
    """Shared, thread-safe server state (the HTTP server runs off the main thread)."""

    config: Config
    root: Path
    port: int
    rules: NoProcessRules
    renderer: MarkdownRenderer
    stylesheet: str
    chemistry_js: str
    cache: RenderCache = field(default_factory=lambda: RenderCache(64))
    requests: int = 0
    paused: bool = False
    last_error: str | None = None
    last_error_time: float | None = None
    started_at: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def create(cls, config: Config, root: Path, port: int) -> ServerState:
        """Build the shared state, rendering the stylesheet once."""
        return cls(
            config=config,
            root=root,
            port=port,
            rules=rules_for(config.server.no_process),
            renderer=MarkdownRenderer(config),
            stylesheet=stylesheet_cached(config),
            chemistry_js=read_chemistry_js(),
            cache=RenderCache(config.cache.entries),
        )

    def note_request(self) -> None:
        """Count one served request."""
        with self._lock:
            self.requests += 1

    def clear_error(self) -> None:
        """Forget the last error, e.g. after the config is valid again."""
        with self._lock:
            self.last_error = None
            self.last_error_time = None

    def note_error(self, message: str) -> None:
        """Remember the most recent error for the tray menu."""
        with self._lock:
            self.last_error = message
            self.last_error_time = time.time()

    def apply_config(self, config: Config) -> None:
        """Swap in a new configuration, e.g. after the settings window saved.

        The renderer, stylesheet and no-process rules are rebuilt and the render
        cache is dropped, because cached pages carry the old colors. The
        listening port cannot change here; it is bound at startup.
        """
        renderer = MarkdownRenderer(config)
        styles = stylesheet_cached(config)
        rules = rules_for(config.server.no_process)
        cache = RenderCache(config.cache.entries)
        with self._lock:
            self.config = config
            self.renderer = renderer
            self.stylesheet = styles
            self.rules = rules
            self.cache = cache

    def set_paused(self, paused: bool) -> None:
        """Stop or resume answering requests."""
        with self._lock:
            self.paused = paused

    def toggle_paused(self) -> bool:
        """Flip the pause flag and return the new value."""
        with self._lock:
            self.paused = not self.paused
            return self.paused

    def snapshot(self) -> Snapshot:
        """Return a consistent copy of the counters."""
        stats = self.cache.stats()
        with self._lock:
            return Snapshot(
                port=self.port,
                root=self.root,
                requests=self.requests,
                cached_pages=stats.entries,
                cache_hits=stats.hits,
                cache_misses=stats.misses,
                paused=self.paused,
                last_error=self.last_error,
                last_error_time=self.last_error_time,
                started_at=self.started_at,
            )


class Handler(http.server.SimpleHTTPRequestHandler):
    """One request. All knowledge of paths, pages and caches lives in ServerState."""

    state: ServerState
    server_version = "serv/0.2"

    # ------------------------------------------------------------- routing

    def guess_type(self, path: str) -> str:
        """Serve plain-text source types as text instead of as downloads."""
        extension = Path(path).suffix.lower()
        return RAW_TEXT_EXTENSIONS.get(extension, super().guess_type(path))

    def translate_path(self, path: str) -> str:
        """Resolve the request path with home-prefix and :line retries."""
        return str(resolve(path, self.state.root))

    def do_GET(self) -> None:  # noqa: N802 - http.server naming
        """Route one GET request."""
        self.state.note_request()
        try:
            if self.state.paused:
                self._send_text(503, "serv is paused\n")
                return
            clean_path = self.path.split("?", 1)[0]
            if clean_path == CSS_URL:
                self._serve_stylesheet()
                return
            if clean_path == JS_URL:
                self._serve_chemistry_js()
                return

            url_path = urllib.parse.urlsplit(clean_path).path
            highlight_line = split_line_reference(urllib.parse.unquote(url_path))
            path = self.translate_path(clean_path)

            if self.state.rules.matches(Path(path)):
                # Files matching a no_process glob are served verbatim: no
                # Markdown rendering and no syntax highlighting.
                super().do_GET()
                return
            file_path = Path(path)
            renderable = file_path.is_file() and (
                file_path.suffix.lower() == ".md" or language_for(file_path) is not None
            )
            if renderable and self._too_large(file_path):
                # One huge file must not stall the server; show it as it is.
                self._serve_verbatim(file_path)
                return
            if path.lower().endswith(".md") and file_path.is_file():
                self._serve_markdown(file_path, url_path)
                return
            if language_for(file_path) and file_path.is_file():
                self._serve_code(file_path, highlight_line)
                return
            super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            # The browser navigated away mid-response; nothing to report.
            pass
        except Exception as error:  # noqa: BLE001 - a server must not die per request
            self.state.note_error(f"{type(error).__name__}: {error}")
            try:
                self._send_text(500, f"serv error: {type(error).__name__}: {error}\n")
            except (BrokenPipeError, ConnectionResetError):
                pass

    # ------------------------------------------------------- in-memory pages

    def _serve_stylesheet(self) -> None:
        body = self.state.stylesheet.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/css; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")  # always re-fetch
        self.end_headers()
        self.wfile.write(body)

    def _serve_chemistry_js(self) -> None:
        body = self.state.chemistry_js.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/javascript; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html_text: str) -> None:
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _too_large(self, path: Path) -> bool:
        """Return whether the file is too big to render."""
        try:
            return path.stat().st_size > self.state.config.server.max_render_bytes
        except OSError:
            return False

    def _serve_verbatim(self, path: Path) -> None:
        """Send a file as plain text, without rendering or highlighting it."""
        try:
            body = path.read_bytes()
        except OSError as error:
            self.state.note_error(f"read {path}: {error}")
            self.send_error(500, f"could not read file: {error}")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------- markdown

    def _serve_markdown(self, path: Path, url_path: str) -> None:
        try:
            digest = file_digest(path)
        except OSError as error:
            self.state.note_error(f"read {path}: {error}")
            self.send_error(404, "Markdown file not found")
            return

        parent = url_path.rsplit("/", 1)[0] + "/" if "/" in url_path else "/"
        key = (str(path), digest)

        def render() -> str:
            source = path.read_text(encoding="utf-8", errors="replace")
            return self.state.renderer.render_document(source, path.name, parent)

        try:
            page = self.state.cache.render(key, render)
        except Exception as error:  # noqa: BLE001 - report why rendering failed
            self.state.note_error(f"render {path.name}: {error}")
            self.send_error(500, f"could not render Markdown: {error}")
            return
        self._send_html(page)

    # ---------------------------------------------------------- code pages

    def _serve_code(self, path: Path, highlight_line: int | None) -> None:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            self.state.note_error(f"read {path}: {error}")
            self.send_error(500, f"could not read source file: {error}")
            return
        self._send_html(code_page(source, path, self.state.root, highlight_line))

    # ------------------------------------------------------------- listings

    def list_directory(self, path: str):  # noqa: N802 - http.server naming
        """Serve an aligned listing with an up-arrow row and hidden-file switch."""
        try:
            page = listing_page(Path(path), self.path)
        except PermissionError:
            self.send_error(404, "No permission to list directory")
            return None
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        return io.BytesIO(body)


def _handler_class(state: ServerState) -> type[Handler]:
    """Return a Handler subclass bound to this state."""
    return type("BoundHandler", (Handler,), {"state": state})


def build_server(config: Config, root: Path, port: int) -> tuple[http.server.ThreadingHTTPServer, ServerState]:
    """Create the HTTP server (bound, not yet serving) and its shared state."""
    state = ServerState.create(config, root, port)
    server = http.server.ThreadingHTTPServer(("", port), _handler_class(state))
    server.daemon_threads = True
    return server, state


def serve_forever(config: Config, root: Path, port: int) -> None:
    """Serve the current directory until interrupted."""
    server, _ = build_server(config, root, port)
    print(f"serving {root} at http://localhost:{port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()


def free_port(port: int) -> bool:
    """Return whether nothing is listening on the port already."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("", port))
        except OSError:
            return False
    return True


__all__ = [
    "Handler",
    "ServerState",
    "Snapshot",
    "build_server",
    "free_port",
    "serve_forever",
    "strip_line_reference",
]
