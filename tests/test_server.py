"""End-to-end requests against a real server on an ephemeral port."""

from __future__ import annotations

from dataclasses import replace
import threading
import urllib.error
import urllib.request

import pytest

from serv.config import ServerSection, load_config
from serv.server import build_server


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory):
    root = tmp_path_factory.mktemp("site")
    (root / "notes.md").write_text("# Notes\n\n## Part\n\nSome $x^2$ math.\n")
    (root / "src").mkdir()
    (root / "src" / "main.py").write_text("def main():\n    return 1\n")
    (root / "build").mkdir()
    (root / "build" / "notes.md").write_text("# Raw, not rendered\n")
    (root / "build" / "out.odin").write_text("package out\n")
    (root / "empty").mkdir()
    (root / "huge.md").write_text("# Huge\n\n" + "text " * 2000 + "\n")
    (root / "huge.py").write_text("x = 1\n" * 2000)

    config = replace(
        load_config(),
        server=ServerSection(
            port=0, no_process=(str(root / "build" / "**"),), max_render_bytes=4096
        ),
    )
    server, state = build_server(config, root, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", state, root
    server.shutdown()
    server.server_close()


def fetch(url: str) -> tuple[int, str, dict[str, str]]:
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            headers = {key.lower(): value for key, value in response.headers.items()}
            return response.status, response.read().decode("utf-8", "replace"), headers
    except urllib.error.HTTPError as error:
        headers = {key.lower(): value for key, value in error.headers.items()}
        return error.code, error.read().decode("utf-8", "replace"), headers


def test_stylesheet_is_generated_from_the_config(site) -> None:
    base, _, _ = site
    status, body, headers = fetch(f"{base}/__serv__/style.css")
    assert status == 200
    assert headers["content-type"].startswith("text/css")
    assert headers["cache-control"] == "no-cache"
    assert ":root {" in body
    assert "--bg: #e1e2e7;" in body
    assert "fonts.googleapis.com" in body


def test_markdown_page_renders_with_toc_and_parent_link(site) -> None:
    base, _, _ = site
    status, body, _ = fetch(f"{base}/notes.md")
    assert status == 200
    assert '<body class="markdown-page">' in body
    assert '<h1 id="notes">' in body
    assert '<nav id="TOC"' in body
    assert 'class="markdown-parent"' in body
    assert 'href="/"' in body  # parent folder of /notes.md
    assert "math inline" in body


def test_markdown_is_cached_by_content_digest(site) -> None:
    base, state, root = site
    before = state.snapshot()
    fetch(f"{base}/notes.md")
    after = state.snapshot()
    assert after.cache_hits == before.cache_hits + 1

    (root / "notes.md").write_text("# Notes\n\nEdited.\n")
    fetch(f"{base}/notes.md")
    edited = state.snapshot()
    assert edited.cache_misses > after.cache_misses


def test_source_file_becomes_a_highlighted_page(site) -> None:
    base, _, _ = site
    status, body, _ = fetch(f"{base}/src/main.py")
    assert status == 200
    assert '<body class="code-page">' in body
    assert 'class="line-numbers language-python"' in body
    assert "return 1" in body
    assert "prismjs@1.29.0/components/prism-python.min.js" in body


def test_line_reference_highlights_the_line(site) -> None:
    base, _, _ = site
    status, body, _ = fetch(f"{base}/src/main.py:2")
    assert status == 200
    assert 'data-line="2"' in body
    assert "scrollIntoView" in body


def test_directory_listing_has_up_arrow_and_hidden_toggle(site) -> None:
    base, _, _ = site
    status, body, _ = fetch(f"{base}/empty/")
    assert status == 200
    assert 'class="parent-row"' in body
    assert 'id="show-hidden"' in body
    assert 'href="../"' in body


def test_no_process_glob_serves_files_verbatim(site) -> None:
    base, _, _ = site
    status, body, _ = fetch(f"{base}/build/notes.md")
    assert status == 200
    assert "<h1" not in body
    assert body.strip() == "# Raw, not rendered"


def test_raw_area_keeps_text_plain_for_odin(site) -> None:
    base, _, _ = site
    status, body, headers = fetch(f"{base}/build/out.odin")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert "package out" in body


def test_large_markdown_is_served_verbatim(site) -> None:
    base, _, _ = site
    status, body, headers = fetch(f"{base}/huge.md")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert "<h1" not in body
    assert body.startswith("# Huge")


def test_large_source_file_is_served_verbatim(site) -> None:
    base, _, _ = site
    status, body, headers = fetch(f"{base}/huge.py")
    assert status == 200
    assert headers["content-type"].startswith("text/plain")
    assert "line-numbers" not in body
    assert body.startswith("x = 1")


def test_missing_markdown_is_a_404(site) -> None:
    base, _, _ = site
    status, _, _ = fetch(f"{base}/nowhere.md")
    assert status == 404


def test_chemistry_renderer_is_served(site) -> None:
    base, _, _ = site
    status, body, headers = fetch(f"{base}/__serv__/js/chemistry.js")
    assert status == 200
    assert headers["content-type"].startswith("text/javascript")
    assert "SERV_RDKIT_URL" in body


def test_paused_server_refuses_requests(site) -> None:
    base, state, _ = site
    state.set_paused(True)
    try:
        status, body, _ = fetch(f"{base}/notes.md")
        assert status == 503
        assert "paused" in body
    finally:
        state.set_paused(False)
