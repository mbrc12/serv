"""Plugin base classes and registry.

A plugin owns one optional feature. Subclass :class:`Plugin` (or
:class:`FencePlugin` when the feature is triggered by a fenced block) and
implement:

``setup(md, config)``
    register Markdown-It rules and renderers.
``detect(html)``
    report whether a rendered page uses this feature.
``head(config)``
    return the ``<head>`` fragments — CDN links, scripts, init snippets — a page
    using this feature needs.

Nothing is loaded on a page that does not need it: a page without chemistry
never mentions RDKit.js.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from ..config import Config


class Plugin(ABC):
    """One optional page feature."""

    name: ClassVar[str]
    fences: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def setup(self, md, config: Config) -> None:
        """Register Markdown-It rules on the shared instance."""

    @abstractmethod
    def detect(self, html: str) -> bool:
        """Report whether a rendered page uses this plugin."""

    @abstractmethod
    def head(self, config: Config) -> list[str]:
        """Return the head fragments a page using this plugin needs."""


class FencePlugin(Plugin):
    """A plugin triggered by fenced code blocks with matching info strings."""

    @abstractmethod
    def render_fence(self, token, attrs: dict[str, str]) -> str:
        """Render one fenced block, with the attributes from its info string."""


class Registry:
    """The ordered set of plugins available to the renderer."""

    def __init__(self, plugins: list[Plugin]) -> None:
        self.plugins = plugins
        self._by_fence: dict[str, FencePlugin] = {
            fence.lower(): plugin
            for plugin in plugins
            if isinstance(plugin, FencePlugin)
            for fence in plugin.fences
        }

    def setup(self, md, config: Config) -> None:
        """Let every plugin register its Markdown-It rules."""
        for plugin in self.plugins:
            plugin.setup(md, config)

    def fence_owner(self, info: str) -> tuple[FencePlugin, dict[str, str]] | None:
        """Return the plugin that owns a fence info string and its attributes."""
        name, attrs = parse_fence_info(info)
        if name is None:
            return None
        plugin = self._by_fence.get(name.lower())
        return (plugin, attrs) if plugin else None

    def for_page(self, html: str) -> list[Plugin]:
        """Return the plugins one rendered page actually uses."""
        return [plugin for plugin in self.plugins if plugin.detect(html)]

    def head(self, html: str, config: Config) -> list[str]:
        """Return every head fragment the page needs, in plugin order."""
        return [
            fragment
            for plugin in self.for_page(html)
            for fragment in plugin.head(config)
        ]


def parse_fence_info(info: str) -> tuple[str | None, dict[str, str]]:
    """Split a fence info string into a language/name and its attributes.

    Handles both the plain form (``smiles``) and the braced form used for
    options (``{.smiles fixedBondLength=36}``). Values may be bare or quoted.
    """
    info = info.strip()
    if not info:
        return None, {}
    if info.startswith("{"):
        info = info.strip("{}").strip()
    name: str | None = None
    attrs: dict[str, str] = {}
    tokens = info.split()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.startswith(".") or token.startswith("#"):
            if name is None and token.startswith("."):
                name = token[1:]
            continue
        if "=" in token:
            key, value = token.split("=", 1)
            if value.startswith('"'):
                value = value[1:]
                while not value.endswith('"') and index < len(tokens):
                    value += " " + tokens[index]
                    index += 1
                value = value.rstrip('"')
            attrs[key] = value
            continue
        if name is None:
            name = token
    return name, attrs


def default_registry() -> Registry:
    """Build the registry with the plugins serv ships."""
    from .chem import ChemPlugin
    from .math import MathPlugin
    from .mermaid import MermaidPlugin

    return Registry([MathPlugin(), ChemPlugin(), MermaidPlugin()])
