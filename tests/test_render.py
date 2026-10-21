"""Markdown rendering: the parity features the old pandoc pipeline provided."""

from __future__ import annotations

import pytest

from serv.config import load_config
from serv.markdown import MarkdownRenderer, pandoc_slug


@pytest.fixture(scope="module")
def renderer() -> MarkdownRenderer:
    return MarkdownRenderer(load_config())


def render(renderer: MarkdownRenderer, source: str, parent: str = "/docs/") -> str:
    return renderer.render_document(source, "page.md", parent)


def test_heading_gets_pandoc_style_anchor(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "# Hello, *World*!\n")
    assert '<h1 id="hello-world">' in html


def test_pandoc_slug_rules() -> None:
    assert pandoc_slug("Hello, World!") == "hello-world"
    assert pandoc_slug("3. Results") == "results"
    assert pandoc_slug("a_b-c.d") == "a_b-c.d"
    assert pandoc_slug("???") == "section"


def test_toc_follows_first_h1(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "Intro\n\n# Title\n\n## Part\n\n### Deep\n")
    toc = html.index('<nav id="TOC"')
    assert html.index("<h1") < toc < html.index("<h2")
    assert 'href="#part"' in html
    assert 'href="#deep"' in html


def test_toc_falls_back_to_document_start(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "## Only a subheading\n")
    assert html.index('<nav id="TOC"') < html.index("<h2")


def test_parent_arrow_links_to_the_files_directory(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "# Title\n", parent="/comp/bio/")
    assert 'class="markdown-parent"' in html
    assert 'href="/comp/bio/"' in html


def test_markdown_page_class(renderer: MarkdownRenderer) -> None:
    assert '<body class="markdown-page">' in render(renderer, "# Title\n")


def test_tables_footnotes_deflists_and_tasklists(renderer: MarkdownRenderer) -> None:
    html = render(
        renderer,
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
        "Term\n: Definition\n\n"
        "- [ ] todo\n- [x] done\n\n"
        "Note[^1]\n\n[^1]: the note\n",
    )
    assert "<table>" in html and "<th>a</th>" in html
    assert "<dl>" in html and "<dt>Term</dt>" in html
    assert 'class="task-list-item-checkbox"' in html
    assert 'class="footnotes"' in html and 'id="fn1"' in html


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("$x^2$", '<span class="math inline">\\(x^2\\)</span>'),
        ("$$x^2$$", '<span class="math display">'),
        (r"\(x^2\)", '<span class="math inline">\\(x^2\\)</span>'),
        (r"\[x^2\]", '<span class="math display">'),
    ],
)
def test_math_delimiters(renderer: MarkdownRenderer, source: str, expected: str) -> None:
    assert expected in render(renderer, f"Text {source} here.\n")


def test_block_math_on_its_own_line_is_a_block(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "$$x^2$$\n")
    assert '<div class="math block">' in html


def test_math_inside_a_code_span_is_left_alone(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "Use `$x$` for math.\n")
    assert "math inline" not in html


def test_chemistry_fence_carries_options(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```{.smiles fixedBondLength=36}\nCCO | ethanol\n```\n")
    assert '<pre class="smiles" data-fixedbondlength="36">' in html
    assert "<code>CCO | ethanol" in html


def test_plugin_assets_only_load_when_used(renderer: MarkdownRenderer) -> None:
    plain = render(renderer, "# Title\n\nJust text.\n")
    assert "RDKit" not in plain and "katex" not in plain and "mermaid" not in plain

    chem_page = render(renderer, "```smiles\nCCO\n```\n")
    assert "RDKit_minimal.js" in chem_page and "katex" not in chem_page

    math_page = render(renderer, "$x$\n")
    assert "katex" in math_page and "RDKit" not in math_page

    mermaid_page = render(renderer, "```mermaid\ngraph TD; A-->B\n```\n")
    assert "mermaid.esm.min.mjs" in mermaid_page and "katex" not in mermaid_page


def test_fenced_code_keeps_its_language_class(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```python\nprint('hi')\n```\n")
    assert '<code class="language-python">' in html


def test_code_fence_content_is_escaped(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```\n<script>alert(1)</script>\n```\n")
    assert "&lt;script&gt;" in html
    assert "<script>alert(1)</script>" not in html


def test_raw_html_is_allowed(renderer: MarkdownRenderer) -> None:
    html = render(renderer, '<div class="note">kept</div>\n')
    assert '<div class="note">kept</div>' in html


def test_single_h1_document_still_renders(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "# Only heading\n\nBody.\n")
    assert html.count("<nav id=\"TOC\"") == 1


def test_fenced_code_loads_prism_for_its_language(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```python\nprint('hi')\n```\n")
    assert "prism.min.js" in html
    assert "prism-python.min.js" in html
    assert "Prism.highlightAll()" in html


def test_pages_without_code_do_not_load_prism(renderer: MarkdownRenderer) -> None:
    assert "prism" not in render(renderer, "# Title\n\nOnly prose.\n")


def test_several_fences_share_one_prism_bundle(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```python\nx = 1\n```\n\n```cpp\nint x;\n```\n")
    assert html.count("prism.min.js") == 1
    assert "prism-python.min.js" in html
    assert "prism-cpp.min.js" in html
    assert html.count("prism-c.min.js") == 1


def test_plugin_fences_are_not_handed_to_prism(renderer: MarkdownRenderer) -> None:
    html = render(renderer, "```smiles\nCCO\n```\n\n```mermaid\ngraph TD; A-->B\n```\n")
    assert "RDKit" in html and "mermaid.esm.min.mjs" in html
    assert "prism.min.js" not in html


def test_footer_shows_size_date_words_and_reading_time(renderer: MarkdownRenderer) -> None:
    html = renderer.render_document(
        "# Title\n\nOne two three four.\n",
        "page.md",
        "/docs/",
        size=2048,
        modified=0,  # 1 Jan 1970 in the local timezone on most machines
    )
    footer = html.split('class="markdown-footer"', 1)[1]
    assert "2.0 KiB" in footer
    assert "Modified 1 Jan 1970" in footer
    assert "5 words" in footer
    assert "1 min read" in footer


def test_footer_is_absent_without_file_metadata(renderer: MarkdownRenderer) -> None:
    assert "markdown-footer" not in render(renderer, "# Title\n")


def test_footer_follows_the_document_body(renderer: MarkdownRenderer) -> None:
    html = renderer.render_document(
        "# Title\n\nBody.\n", "page.md", "/", size=10, modified=0
    )
    assert html.index("Body.") < html.index("markdown-footer")
    assert html.rindex("markdown-footer") < html.index("</main>")


def test_word_count_skips_punctuation_only_tokens() -> None:
    from serv.page import word_count

    assert word_count("one two  three\nfour") == 4
    assert word_count("# Heading\n\n- item | cell") == 3
    assert word_count("") == 0
