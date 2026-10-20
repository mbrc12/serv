"""Chemistry fences: ``smiles``, ``molecule``, ``reaction`` and ``properties``.

RDKit.js draws all four, so every structure on a page shares one depiction
style. RDKit.js is a large WebAssembly payload, so it is fetched from the CDN
only when a page actually uses one of these blocks.
"""

from __future__ import annotations

from markdown_it.common.utils import escapeHtml

from ..config import Config
from ..constants import JS_URL
from . import FencePlugin, parse_fence_info

RDKIT_VERSION = "2026.9.1"
RDKIT_URL = f"https://cdn.jsdelivr.net/npm/@rdkit/rdkit@{RDKIT_VERSION}/dist/RDKit_minimal.js"

# Fence options become HTML attributes; the drawing script reads them
# case-insensitively after stripping the data- prefix.
_BLOCK = '<pre class="{name}"{attributes}><code>{content}</code></pre>\n'


class ChemPlugin(FencePlugin):
    """Structures, reaction schemes and descriptor tables drawn by RDKit.js."""

    name = "chem"
    fences = ("smiles", "molecule", "reaction", "properties", "chem-options")

    def setup(self, md, config: Config) -> None:
        """Chemistry needs no Markdown-It rules; the fence renderer handles it."""

    # Fences that need RDKit.js. A chem-options block only sets defaults, so on
    # its own it must not pull in the WebAssembly payload.
    DRAWING_FENCES = ("smiles", "molecule", "reaction", "properties")

    def detect(self, html: str) -> bool:
        return any(f'<pre class="{fence}"' in html for fence in self.DRAWING_FENCES)

    def head(self, config: Config) -> list[str]:
        return [
            f'<script>window.SERV_RDKIT_URL = "{RDKIT_URL}";</script>',
            f'<script src="{JS_URL}"></script>',
        ]

    def render_fence(self, token, attrs: dict[str, str]) -> str:
        name, _ = parse_fence_info(token.info)
        attributes = "".join(
            f' data-{key.lower()}="{escapeHtml(value)}"'
            for key, value in attrs.items()
        )
        return _BLOCK.format(
            name=(name or self.name).lower(),
            attributes=attributes,
            content=escapeHtml(token.content),
        )
