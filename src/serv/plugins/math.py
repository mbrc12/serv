"""Math: ``$…$``, ``$$…$$``, ``\\(…\\)`` and ``\\[…\\]``.

The Markdown side only marks the TeX; KaTeX renders it in the browser, from the
CDN, exactly like the pandoc ``--katex`` pipeline did. Keeping the delimiters in
the emitted HTML means the same page also degrades to readable TeX when
JavaScript is off.
"""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml
from mdit_py_plugins.dollarmath import dollarmath_plugin

from ..config import Config
from . import Plugin

KATEX_VERSION = "0.16.11"
KATEX_BASE = f"https://cdn.jsdelivr.net/npm/katex@{KATEX_VERSION}/dist"

# KaTeX's auto-render walks text nodes, so the delimiters have to survive in
# the markup. Longer delimiters are listed first so "$$" wins over "$".
_INLINE = '<span class="math inline">\\({}\\)</span>'
_DISPLAY = '<span class="math display">\\[{}\\]</span>'
_BLOCK = '<div class="math block">\n\\[{}\\]\n</div>\n'

_INIT = """<script>
  document.addEventListener('DOMContentLoaded', function () {
    if (typeof renderMathInElement !== 'function') return;
    renderMathInElement(document.body, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '\\\\[', right: '\\\\]', display: true },
        { left: '$', right: '$', display: false },
        { left: '\\\\(', right: '\\\\)', display: false }
      ],
      throwOnError: false,
      strict: false
    });
  });
</script>"""


def _inline_rule(state, silent: bool) -> bool:
    """Rule for ``\\(…\\)`` and ``\\[…\\]``, which dollarmath does not cover."""
    source = state.src
    start = state.pos
    if source[start] != "\\" or start + 1 >= state.posMax:
        return False
    opener = source[start : start + 2]
    if opener == "\\(":
        closer, display = "\\)", False
    elif opener == "\\[":
        closer, display = "\\]", True
    else:
        return False
    end = source.find(closer, start + 2)
    if end < 0:
        return False
    content = source[start + 2 : end]
    if not content.strip():
        return False
    if not silent:
        token = state.push("math_inline", "math", 0)
        token.content = content
        token.markup = opener + closer
        token.block = display
    state.pos = end + len(closer)
    return True


def _inline_html(content: str, display: bool) -> str:
    template = _DISPLAY if display else _INLINE
    return template.format(escapeHtml(content.strip()))


def _block_html(content: str) -> str:
    return _BLOCK.format(escapeHtml(content.strip()))


class MathPlugin(Plugin):
    """Dollar math plus the parenthesis and bracket delimiters."""

    name = "math"

    def setup(self, md: MarkdownIt, config: Config) -> None:
        dollarmath_plugin(md, double_inline=True)
        md.inline.ruler.before("escape", "math_paren", _inline_rule)
        # The plugin's own renderers wrap TeX without delimiters; these keep the
        # delimiters so KaTeX auto-render can find the expressions.
        md.add_render_rule(
            "math_inline",
            lambda self, tokens, idx, options, env: _inline_html(
                str(tokens[idx].content), bool(tokens[idx].block)
            ),
        )
        md.add_render_rule(
            "math_inline_double",
            lambda self, tokens, idx, options, env: _inline_html(
                str(tokens[idx].content), True
            ),
        )
        md.add_render_rule(
            "math_block",
            lambda self, tokens, idx, options, env: _block_html(str(tokens[idx].content)),
        )
        md.add_render_rule(
            "math_block_label",
            lambda self, tokens, idx, options, env: (
                f'<div id="{escapeHtml(str(tokens[idx].info))}" class="math block">\n'
                + _block_html(str(tokens[idx].content))
                + "</div>\n"
            ),
        )

    def detect(self, html: str) -> bool:
        return 'class="math ' in html

    def head(self, config: Config) -> list[str]:
        return [
            f'<link rel="stylesheet" href="{KATEX_BASE}/katex.min.css">',
            f'<script src="{KATEX_BASE}/katex.min.js"></script>',
            f'<script src="{KATEX_BASE}/contrib/auto-render.min.js"></script>',
            _INIT,
        ]
