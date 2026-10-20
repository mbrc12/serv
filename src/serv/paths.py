"""Translate request URLs into filesystem paths.

These rules are the parity-critical part of the old script, so they are pure
functions here and covered by tests:

* a ``:line`` or ``:line:col`` suffix is stripped only when the target exists;
* a URL that still carries a home prefix (``/Users/me/x`` or ``/me/x``) is
  retried relative to the served root when the literal path does not exist;
* paths matching a configured glob are served verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path, PurePath
import posixpath
import re
import urllib.parse

import deal

LINE_REFERENCE = re.compile(r":(?P<line>\d+)(?::\d+)?$")


def home_prefixes() -> tuple[str, ...]:
    """Return the URL prefixes that can front a copied absolute path."""
    home = os.path.abspath(os.path.expanduser("~"))
    return tuple(
        dict.fromkeys(
            {
                home.replace(os.sep, "/").rstrip("/"),
                "/" + os.path.basename(home),
            }
        )
    )


def split_line_reference(url_path: str) -> int | None:
    """Return the line number in a ``…/file.py:29`` or ``…/file.py:29:5`` URL."""
    match = LINE_REFERENCE.search(url_path)
    return int(match.group("line")) if match else None


def strip_line_reference(url_path: str) -> str:
    """Return the URL without its line suffix, even when the target is missing."""
    return LINE_REFERENCE.sub("", url_path)


@deal.pre(lambda url_path, root: url_path.startswith("/"))
@deal.ensure(lambda url_path, root, result: result.is_absolute(), message="translated path must be absolute")
def translate(url_path: str, root: Path) -> Path:
    """Map one URL path onto the served root, mirroring http.server's rules.

    Query strings and fragments are dropped, the path is percent-decoded, and
    ``..`` segments are discarded rather than resolved, so a request can never
    escape the root.
    """
    path = urllib.parse.urlsplit(url_path).path
    try:
        path = urllib.parse.unquote(path, errors="surrogatepass")
    except UnicodeDecodeError:
        path = urllib.parse.unquote(path)
    normalised = posixpath.normpath(path)
    parts = [part for part in normalised.split("/") if part not in ("", ".", "..")]
    return Path(root, *parts)


@deal.ensure(
    lambda url_path, root, result: result.is_absolute(),
    message="resolved path must be absolute",
)
def resolve(url_path: str, root: Path) -> Path:
    """Resolve a request URL to a path, retrying home-prefixed and line forms.

    Returns the literal translation when nothing exists, so callers report 404
    for the path the browser actually asked for.
    """
    literal = translate(url_path, root)
    if literal.exists():
        return literal

    url_path = urllib.parse.urlsplit(url_path).path
    try:
        url_path = urllib.parse.unquote(url_path, errors="surrogatepass")
    except UnicodeDecodeError:
        url_path = urllib.parse.unquote(url_path)

    candidates = [url_path]
    without_line = strip_line_reference(url_path)
    if without_line != url_path:
        candidates.append(without_line)

    for candidate_url in candidates:
        candidate = translate(candidate_url, root)
        if candidate.exists():
            return candidate
        for prefix in home_prefixes():
            if candidate_url == prefix or candidate_url.startswith(prefix + "/"):
                relative = candidate_url[len(prefix) :] or "/"
                fallback = translate(relative, root)
                if fallback.exists():
                    return fallback
    return literal


@dataclass(frozen=True)
class NoProcessRules:
    """Glob patterns whose matching files bypass all processing."""

    patterns: tuple[str, ...] = ()

    @classmethod
    def from_patterns(cls, patterns: tuple[str, ...]) -> NoProcessRules:
        """Build the rule set, expanding ``~`` in each pattern."""
        return cls(tuple(os.path.expanduser(pattern) for pattern in patterns))

    @deal.pre(lambda self, path: isinstance(path, Path))
    def matches(self, path: Path) -> bool:
        """Return whether path has to be served verbatim."""
        if not self.patterns:
            return False
        absolute = PurePath(os.path.abspath(path))
        for pattern in self.patterns:
            if absolute.full_match(pattern):
                return True
            # A pattern written without a leading slash, e.g. "**/build/**",
            # behaves as if anchored at the served path's start.
            if not pattern.startswith("/") and absolute.full_match("**/" + pattern):
                return True
        return False


@lru_cache(maxsize=8)
def rules_for(patterns: tuple[str, ...]) -> NoProcessRules:
    """Return cached rules for a pattern tuple."""
    return NoProcessRules.from_patterns(patterns)
