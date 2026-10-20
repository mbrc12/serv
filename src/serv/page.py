"""HTML shell, code pages and directory listings.

Everything here is a pure function of its arguments, so the pages can be tested
without a socket. The palette never appears in Python: pages link to
``/__serv__/style.css``, which theme.py generates from the config.
"""

from __future__ import annotations

import html
from pathlib import Path
import time

from .constants import CSS_URL
from .highlight import language_for
from .resources import data_path

PRISM_VERSION = "1.29.0"
PRISM_BASE = f"https://cdn.jsdelivr.net/npm/prismjs@{PRISM_VERSION}"

# Components Prism's default bundle does not include, in dependency order.
PRISM_COMPONENTS: dict[str, tuple[str, ...]] = {
    "bash": ("bash",),
    "c": ("c",),
    "cpp": ("c", "cpp"),
    "csharp": ("csharp",),
    "docker": ("docker",),
    "elixir": ("elixir",),
    "go": ("go",),
    "haskell": ("haskell",),
    "java": ("java",),
    "json": ("json",),
    "json5": ("json", "json5"),
    "jsx": ("jsx",),
    "kotlin": ("kotlin",),
    "lua": ("lua",),
    "nasm": ("nasm",),
    "odin": ("odin",),
    "perl": ("perl",),
    "php": ("markup-templating", "php"),
    "plain": (),
    "python": ("python",),
    "r": ("r",),
    "ruby": ("ruby",),
    "rust": ("rust",),
    "scala": ("scala",),
    "sql": ("sql",),
    "swift": ("swift",),
    "toml": ("toml",),
    "tsx": ("jsx", "typescript", "tsx"),
    "typescript": ("typescript",),
    "yaml": ("yaml",),
}

#: Icons are inline SVG so they inherit the text color and need no requests.
FOLDER_ICON = (
    '<svg class="icon folder-icon" viewBox="0 0 16 16" width="16" height="16" '
    'aria-hidden="true" focusable="false">'
    '<path d="M1.9 4.4a1 1 0 0 1 1-1h3.05a1 1 0 0 1 .71.3l1.1 1.1h5.35a1 1 0 0 1 1 1v5.9a1 1 0 0 1-1 1H2.9a1 1 0 0 1-1-1z" '
    'fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg>'
)

FILE_ICON = (
    '<svg class="icon file-icon" viewBox="0 0 16 16" width="16" height="16" '
    'aria-hidden="true" focusable="false">'
    '<path d="M9.4 1.9H4.3a1 1 0 0 0-1 1v10.2a1 1 0 0 0 1 1h7.4a1 1 0 0 0 1-1V5z" '
    'fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>'
    '<path d="M9.4 1.9V5h3.3" fill="none" stroke="currentColor" stroke-width="1.4" '
    'stroke-linejoin="round"/></svg>'
)

UP_ARROW = (
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">'
    '<path d="M8 13V3M4 7l4-4 4 4" fill="none" stroke="currentColor" '
    'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

LISTING_SCRIPT = """<script>
(function () {
  var toggle = document.getElementById('show-hidden');
  if (!toggle) return;
  var KEY = 'serv.showHidden';
  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* private mode */ }
  toggle.checked = saved === '1';
  document.body.classList.toggle('show-hidden', toggle.checked);
  toggle.addEventListener('change', function () {
    document.body.classList.toggle('show-hidden', toggle.checked);
    try { localStorage.setItem(KEY, toggle.checked ? '1' : '0'); } catch (e) { /* ignore */ }
  });
})();
</script>"""


def prism_components(languages: set[str]) -> tuple[str, ...]:
    """Return the Prism component files a set of languages needs, in order."""
    ordered: list[str] = []
    for language in sorted(languages):
        for component in PRISM_COMPONENTS.get(language, ()):
            if component not in ordered:
                ordered.append(component)
    return tuple(ordered)


def prism_scripts(languages: set[str]) -> str:
    """Return Prism and its language files, ready to run after the page body.

    Fenced blocks in Markdown carry ``language-*`` classes, so the same bundle the
    source pages use highlights them; nothing is loaded for a page with no code.
    """
    if not languages:
        return ""
    sources = [f"{PRISM_BASE}/prism.min.js"]
    sources.extend(
        f"{PRISM_BASE}/components/prism-{component}.min.js"
        for component in prism_components(languages)
    )
    tags = "\n".join(f'  <script src="{source}"></script>' for source in sources)
    return f"\n{tags}\n  <script>Prism.highlightAll();</script>"


def document(
    title: str,
    body: str,
    *,
    body_class: str,
    head: list[str] | tuple[str, ...] = (),
    scripts: str = "",
) -> str:
    """Return a complete HTML document around body.

    Head fragments come before the stylesheet link so page-specific CDN CSS
    (Prism's line-number padding, for instance) is overridden by the palette
    rules instead of the other way round.
    """
    head_html = "\n".join(head)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
{head_html}
  <link rel="stylesheet" href="{CSS_URL}">
</head>
<body class="{body_class}">
<main>
{body}
</main>
{scripts}
</body>
</html>
"""


def parent_navigation(parent_href: str) -> str:
    """Return the up-arrow link to the directory holding a document."""
    return (
        '<nav class="markdown-parent">'
        f'<a href="{html.escape(parent_href, quote=True)}" aria-label="Parent folder" '
        f'title="Parent folder">{UP_ARROW}</a></nav>'
    )


def code_page(source: str, path: Path, display_root: Path, highlight_line: int | None = None) -> str:
    """Return a bare, line-numbered, syntax-highlighted source page."""
    language = language_for(path) or "plain"
    title = str(path.relative_to(display_root)) if path.is_relative_to(display_root) else path.name
    components = "".join(
        f'\n  <script src="{PRISM_BASE}/components/prism-{component}.min.js"></script>'
        for component in PRISM_COMPONENTS.get(language, ())
    )
    line_attribute = f' data-line="{highlight_line}"' if highlight_line else ""
    scroll_script = (
        """
<script>
  setTimeout(function () {
    var line = document.querySelector('.line-highlight');
    if (line) line.scrollIntoView({ block: 'center', behavior: 'auto' });
  }, 0);
</script>"""
        if highlight_line
        else ""
    )
    body = (
        f'<pre class="line-numbers language-{language}"{line_attribute}>'
        f'<code class="language-{language}">{html.escape(source)}</code></pre>'
    )
    scripts = f"""
  <script src="{PRISM_BASE}/prism.min.js"></script>{components}
  <script src="{PRISM_BASE}/plugins/line-numbers/prism-line-numbers.min.js"></script>
  <script src="{PRISM_BASE}/plugins/line-highlight/prism-line-highlight.min.js"></script>
  <script>Prism.highlightAll();</script>{scroll_script}"""
    head = [
        f'<link rel="stylesheet" href="{PRISM_BASE}/plugins/line-numbers/prism-line-numbers.min.css">',
        f'<link rel="stylesheet" href="{PRISM_BASE}/plugins/line-highlight/prism-line-highlight.min.css">',
    ]
    return document(title, body, body_class="code-page", head=head, scripts=scripts)


def format_file_size(size: int) -> str:
    """Return a compact, readable file size."""
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def _listing_row(path: Path, name: str) -> str:
    """Return one listing row with its size and modification time."""
    full = path / name
    is_directory = full.is_dir()
    display = name + "/" if is_directory else name
    if full.is_symlink():
        display += "@"
    try:
        stat = full.stat()
        modified = time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime))
        size = "—" if is_directory else format_file_size(stat.st_size)
    except OSError:
        modified = size = "—"
    item_class = "dir" if is_directory else "file"
    hidden = " hidden-entry" if name.startswith(".") else ""
    href = html.escape(name + ("/" if is_directory else ""), quote=True)
    icon = FOLDER_ICON if is_directory else FILE_ICON
    # The anchor wraps the whole cell, so a click anywhere in the tile opens the
    # entry rather than only the text of its name.
    return (
        f'<li class="{item_class}{hidden}">'
        f'<a class="entry {item_class}" href="{href}">'
        f'<span class="name {item_class}">{icon}'
        f'<span class="label">{html.escape(display)}</span></span>'
        f'<span class="meta"><time>{modified}</time>'
        f'<span class="size">{size}</span></span></a></li>'
    )


def listing_page(path: Path, request_path: str) -> str:
    """Return a directory listing with an up-arrow row and hidden-file switch."""
    try:
        names = list(path.iterdir())
    except OSError as error:
        raise PermissionError(str(error)) from error

    entries = sorted(
        names,
        # Directories first, then case-insensitive name order.
        key=lambda entry: (not entry.is_dir(), entry.name.lower()),
    )
    title = f"Directory listing for {request_path}"
    rows = "".join(_listing_row(path, entry.name) for entry in entries)
    toolbar = (
        '<li class="parent-row">'
        f'<a class="name dir" href="../" aria-label="Parent directory" '
        f'title="Parent directory">{UP_ARROW}</a>'
        '<span class="toolbar"><label class="switch" for="show-hidden">'
        '<input type="checkbox" id="show-hidden">'
        '<span class="slider" aria-hidden="true"></span>'
        '<span class="switch-label">Show hidden files</span></label></span></li>'
    )
    body = (
        f"<h1>{html.escape(title)}</h1>\n"
        f'<ul class="directory-list">{toolbar}{rows}</ul>'
    )
    return document(title, body, body_class="listing-page", scripts=LISTING_SCRIPT)


def read_chemistry_js() -> str:
    """Return the chemistry renderer served at JS_URL."""
    return data_path("js/chemistry.js").read_text()


__all__ = [
    "PRISM_BASE",
    "PRISM_COMPONENTS",
    "prism_components",
    "prism_scripts",
    "code_page",
    "document",
    "format_file_size",
    "listing_page",
    "parent_navigation",
    "read_chemistry_js",
]
