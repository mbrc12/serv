"""Path resolution rules copied from the old script."""

from __future__ import annotations

from pathlib import Path

import pytest

from serv.paths import (
    NoProcessRules,
    home_prefixes,
    resolve,
    split_line_reference,
    strip_line_reference,
    translate,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "notes.md").write_text("# notes\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')\n")
    return tmp_path


def test_translate_keeps_requests_inside_root(root: Path) -> None:
    assert translate("/notes.md", root) == root / "notes.md"
    assert translate("/../../etc/passwd", root) == root / "etc" / "passwd"
    assert translate("/a/../b", root) == root / "b"


def test_translate_decodes_percent_escapes(root: Path) -> None:
    assert translate("/my%20notes.md", root) == root / "my notes.md"


def test_resolve_literal_path(root: Path) -> None:
    assert resolve("/notes.md", root) == root / "notes.md"


def test_resolve_strips_line_suffix_when_target_exists(root: Path) -> None:
    assert resolve("/src/main.py:29", root) == root / "src" / "main.py"
    assert resolve("/src/main.py:29:5", root) == root / "src" / "main.py"


def test_resolve_keeps_missing_path_literal(root: Path) -> None:
    assert resolve("/missing.py", root) == root / "missing.py"
    assert resolve("/missing.py:29", root) == root / "missing.py:29"


def test_resolve_retries_home_prefixed_urls(root: Path) -> None:
    absolute, short = home_prefixes()
    assert resolve(f"{absolute}/notes.md", root) == root / "notes.md"
    assert resolve(f"{short}/notes.md", root) == root / "notes.md"


def test_split_and_strip_line_reference() -> None:
    assert split_line_reference("/a/b.py:29") == 29
    assert split_line_reference("/a/b.py:29:5") == 29
    assert split_line_reference("/a/b.py") is None
    assert strip_line_reference("/a/b.py:29:5") == "/a/b.py"


def test_no_process_rules_match_build_output(tmp_path: Path) -> None:
    rules = NoProcessRules.from_patterns((str(tmp_path / "game" / "**" / "build" / "**"),))
    build_file = tmp_path / "game" / "x" / "build" / "out.css"
    source_file = tmp_path / "game" / "x" / "src" / "out.css"
    assert rules.matches(build_file)
    assert not rules.matches(source_file)
    assert not NoProcessRules().matches(build_file)


def test_no_process_rules_accept_relative_patterns(tmp_path: Path) -> None:
    rules = NoProcessRules.from_patterns(("**/vendor/**",))
    assert rules.matches(tmp_path / "a" / "vendor" / "b.js")
    assert not rules.matches(tmp_path / "a" / "b.js")
