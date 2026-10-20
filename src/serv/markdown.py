"""Markdown → HTML, in process.

This module owns the Markdown-It instance, the TOC, and the shell a rendered
document is placed in. Rendering is pure: the same source and config always
produce the same HTML, which is what makes the digest-keyed cache safe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from markdown_it.token import Token
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from .config import Config
from .page import document, parent_navigation, prism_scripts
from .plugins import Registry, default_registry, parse_fence_info

# Pandoc's auto-identifier rules: keep word characters, underscores, hyphens and
# periods, turn whitespace into hyphens, and never let an id start with a digit.
_ID_STRIP = re.compile(r"[^\w\s\-.]", re.UNICODE)
_ID_SPACE = re.compile(r"\s+")
_ID_LEADING = re.compile(r"^[^a-zA-Z\u0080-\uffff]+")

# The first h1, used both to place the TOC and to title the page.
_FIRST_H1 = re.compile(r"<h1\b[^>]*>.*?</h1>", re.DOTALL)

TOC_LEVELS = (1, 2, 3)


def pandoc_slug(text: str) -> str:
    """Return a heading id that matches pandoc's auto-identifier rules."""
    slug = _ID_STRIP.sub("", text.strip().lower())
    slug = _ID_SPACE.sub("-", slug)
    slug = _ID_LEADING.sub("", slug)
    return slug or "section"


@dataclass
class Heading:
    """One heading in the document, used to build the table of contents."""

    level: int
    anchor: str
    html: str
    children: list[Heading] = field(default_factory=list)


def _nest(entries: list[tuple[int, str, str]], level: int) -> tuple[list[Heading], int]:
    """Group flat (level, anchor, html) entries into a tree by heading level."""
    nodes: list[Heading] = []
    index = 0
    while index < len(entries):
        entry_level, anchor, text = entries[index]
        if entry_level < level:
            break
        if entry_level > level:
            # A skipped level (h1 → h3): treat the deeper heading as a child.
            if nodes:
                nested, consumed = _nest(entries[index:], entry_level)
                nodes[-1].children.extend(nested)
                index += consumed
                continue
            level = entry_level
        nodes.append(Heading(entry_level, anchor, text))
        index += 1
        if index < len(entries) and entries[index][0] > entry_level:
            children, consumed = _nest(entries[index:], entries[index][0])
            nodes[-1].children.extend(children)
            index += consumed
    return nodes, index


def _render_toc_list(nodes: list[Heading]) -> str:
    items = []
    for node in nodes:
        nested = _render_toc_list(node.children) if node.children else ""
        items.append(f'<li><a href="#{escapeHtml(node.anchor)}">{node.html}</a>{nested}</li>')
    return "<ul>" + "".join(items) + "</ul>"


def build_toc(entries: list[tuple[int, str, str]]) -> str:
    """Return a pandoc-shaped table of contents, or '' for a headingless page."""
    if not entries:
        return ""
    top = min(level for level, _, _ in entries)
    nodes, _ = _nest(entries, level=top)
    return f'<nav id="TOC" role="doc-toc">{_render_toc_list(nodes)}</nav>'


def place_toc(body: str, toc: str) -> str:
    """Put the TOC after the first h1, or at the document start if there is none."""
    if not toc:
        return body
    match = _FIRST_H1.search(body)
    if match:
        return body[: match.end()] + "\n" + toc + body[match.end() :]
    return toc + body


class MarkdownRenderer:
    """A configured Markdown-It pipeline plus the page shell around it."""

    def __init__(self, config: Config, registry: Registry | None = None) -> None:
        self.config = config
        self.registry = registry or default_registry()
        md = MarkdownIt("commonmark", {"html": True, "typographer": True})
        md.enable(["table", "strikethrough"])
        footnote_plugin(md)
        deflist_plugin(md)
        tasklists_plugin(md)
        anchors_plugin(md, min_level=1, max_level=max(TOC_LEVELS), slug_func=pandoc_slug)
        self.registry.setup(md, config)
        default_fence = md.renderer.fence

        # add_render_rule rebinds the function to the renderer, so this is a
        # plain function taking the renderer as its first argument, closing over
        # the registry held by this MarkdownRenderer.
        def fence_rule(renderer, tokens, idx, options, env) -> str:
            token = tokens[idx]
            owner = self.registry.fence_owner(token.info)
            if owner is None:
                return default_fence(tokens, idx, options, env)
            plugin, attrs = owner
            return plugin.render_fence(token, attrs)

        md.add_render_rule("fence", fence_rule)
        self.md = md

    def _headings(self, tokens: list[Token]) -> list[tuple[int, str, str]]:
        entries: list[tuple[int, str, str]] = []
        for index, token in enumerate(tokens):
            if token.type != "heading_open":
                continue
            level = int(token.tag[1])
            if level not in TOC_LEVELS:
                continue
            inline = tokens[index + 1]
            anchor = token.attrGet("id") or pandoc_slug(inline.content)
            text = self.md.renderer.renderInline(
                inline.children or [], self.md.options, {}
            )
            entries.append((level, anchor, text))
        return entries

    def _code_languages(self, tokens: list[Token]) -> set[str]:
        """Return the languages of the fences Prism should highlight.

        Plugin fences (chemistry, Mermaid) are drawn by their own code and are
        skipped here, so their CDN payloads stay off the page.
        """
        languages: set[str] = set()
        for token in tokens:
            if token.type != "fence":
                continue
            owner = self.registry.fence_owner(token.info)
            if owner is not None:
                continue
            name, _ = parse_fence_info(token.info)
            if name:
                languages.add(name.lower())
        return languages

    def render_body(self, source: str) -> tuple[str, list[tuple[int, str, str]]]:
        """Render Markdown source to a body fragment and its heading list."""
        tokens = self.md.parse(source)
        headings = self._headings(tokens)
        return self.md.renderer.render(tokens, self.md.options, {}), headings

    def render_document(self, source: str, title: str, parent_href: str) -> str:
        """Render Markdown source to a complete page."""
        tokens = self.md.parse(source)
        headings = self._headings(tokens)
        body = self.md.renderer.render(tokens, self.md.options, {})
        toc = build_toc(headings)
        content = parent_navigation(parent_href) + "\n" + place_toc(body, toc)
        page_title = heading_title(headings) or title
        return document(
            page_title,
            content,
            body_class="markdown-page",
            head=self.registry.head(content, self.config),
            scripts=prism_scripts(self._code_languages(tokens)),
        )


def heading_title(entries: list[tuple[int, str, str]]) -> str | None:
    """Return the text of the first level-1 heading, without its markup."""
    for level, _, html_text in entries:
        if level == 1:
            return re.sub(r"<[^>]+>", "", html_text).strip() or None
    return None
