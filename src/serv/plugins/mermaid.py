"""Mermaid diagrams, loaded from the CDN as an ES module.

The diagram source stays in the page as text, so a page without JavaScript still
shows something readable, and only Mermaid itself is fetched.
"""

from __future__ import annotations

from markdown_it.common.utils import escapeHtml

from ..config import Config
from . import FencePlugin

MERMAID_VERSION = "11"
MERMAID_URL = (
    f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.esm.min.mjs"
)

_BLOCK = '<pre class="mermaid"><code>{}</code></pre>\n'

_INIT = f"""<script type="module">
  import mermaid from '{MERMAID_URL}';
  // Mermaid wants the diagram text, not the surrounding <code> element.
  document.querySelectorAll('pre.mermaid > code:only-child').forEach(code => {{
    code.parentElement.textContent = code.textContent;
  }});
  mermaid.initialize({{ startOnLoad: false, theme: 'neutral' }});
  mermaid.run({{ querySelector: 'pre.mermaid' }});
</script>"""


class MermaidPlugin(FencePlugin):
    """``mermaid`` fences rendered in the browser."""

    name = "mermaid"
    fences = ("mermaid",)

    def setup(self, md, config: Config) -> None:
        """Mermaid needs no Markdown-It rules; the fence renderer handles it."""

    def detect(self, html: str) -> bool:
        return '<pre class="mermaid"' in html

    def head(self, config: Config) -> list[str]:
        return [_INIT]

    def render_fence(self, token, attrs: dict[str, str]) -> str:
        return _BLOCK.format(escapeHtml(token.content))
