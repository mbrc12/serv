"""Language detection for source files.

The extension map decides which files are shown as highlighted pages instead of
downloaded, and which Prism language class the page gets. Every language named
here is present in the vendored Prism bundle (see tools/vendor_assets.py).
"""

from __future__ import annotations

from pathlib import Path

# Extensions served as highlighted source pages, mapped to a Prism language.
CODE_EXTENSIONS: dict[str, str] = {
    ".asm": "nasm",
    ".bash": "bash",
    ".c": "c",
    ".cc": "cpp",
    ".cjs": "javascript",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".dockerfile": "docker",
    ".ex": "elixir",
    ".exs": "elixir",
    ".fish": "bash",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".hs": "haskell",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsonl": "json",
    ".json5": "json5",
    ".jsx": "jsx",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".lua": "lua",
    ".mjs": "javascript",
    ".odin": "odin",
    ".php": "php",
    ".pl": "perl",
    ".pm": "perl",
    ".py": "python",
    ".pyi": "python",
    ".r": "r",
    ".rb": "ruby",
    ".rs": "rust",
    ".scala": "scala",
    ".sh": "bash",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".txt": "plain",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".vue": "markup",
    ".xml": "markup",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".zsh": "bash",
}

# Extensions that must be delivered as text/plain instead of being downloaded,
# because the browser would otherwise offer to save them.
RAW_TEXT_EXTENSIONS: dict[str, str] = {
    ".odin": "text/plain; charset=utf-8",
}


def language_for(path: Path) -> str | None:
    """Return the Prism language for a file, or None when it is not source."""
    return CODE_EXTENSIONS.get(path.suffix.lower())
