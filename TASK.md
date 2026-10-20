# serv — self-contained binary rewrite

## Goal

Rewrite `serv` (currently a single ~1.4k-line script at `~/.local/bin/serv`) as a Python
package in `~/dev/serv/`, shipped as one self-contained macOS binary, symlinked into
`~/.local/bin/serv`, run by the existing `local.serv` LaunchAgent from `$HOME`.

- No `pandoc`. Markdown → HTML happens in-process.
- Everything the server needs ships inside the binary (renderer, Prism, KaTeX, fonts, CSS).
- Menu bar (tray) item showing server status.
- All colors live in a config file, not in Python source.
- Chemistry, LaTeX/math, Mermaid are separate plugins, each optional.

## Verified so far (probes, not guesses)

- **Markdown in Python works.** `markdown-it-py` 4.2.0 + `mdit-py-plugins` 0.6.1, both pure
  Python, `requires-python >= 3.10` (local interpreter is 3.14.7).
  - `table` + `strikethrough` (built into the commonmark preset): OK.
  - `footnote`: OK. `deflist`: OK. `tasklists`: OK.
  - `anchors` gives heading ids (`<h1 id="title">`); TOC is built from parsed tokens.
  - Fenced code keeps its info string as `language-<name>` classes, so Prism still works.
- **Math:** `dollarmath` renders `$…$` → `<span class="math inline">` and `$$…$$` →
  `<div class="math block">`. `texmath` does **not** handle `\( … \)` / `\[ … \]`
  (renders literal parens), so those delimiters need a small custom inline rule.
- **Tray is viable.** `rumps` 0.4.0 (pure Python) on `pyobjc-core` 12.2.2, which ships
  `cp314` universal2 wheels. PyInstaller 6.22.3 supports Python < 3.16 and has pyobjc hooks.
- **No tray icon assets needed**: a text-only `NSStatusItem` (rumps title) avoids shipping
  an `.icns`/PNG and scribbling on the user's menu bar.

## Layout

```text
~/dev/serv/
  pyproject.toml            # uv project, src layout, entry point `serv = serv.__main__:main`
  TASK.md
  src/serv/
    __main__.py             # CLI, arg parsing, wire-up
    server.py               # ThreadingHTTPServer + handler (routing, listings, code pages)
    paths.py                # translate_path: home-prefix retry, :line suffix, build/ rule
    cache.py                # sha256-keyed LRU for rendered Markdown
    config.py               # load TOML config + defaults, validate
    theme.py                # palette → CSS variables → stylesheet text
    page.py                 # HTML shell, KaTeX/Prism asset tags, line-highlight, autoscroll
    tray.py                 # rumps status item, background thread, status snapshot
    highlight.py            # Prism language map + component list
    plugins/
      __init__.py           # plugin protocol + registry
      math.py               # $…$, $$…$$, \(…\), \[…\]
      chem.py               # smiles / molecule / reaction / properties fences
      mermaid.py            # mermaid fences
  assets/                   # vendored, embedded into the binary
    prism/                  # prism core + components + line-numbers/line-highlight, ~100 KB
    katex/                  # katex.min.js, katex.min.css, fonts/ subset, ~1.5 MB
    fonts/                  # woff2: Crimson Pro, Fira Code (only weights used), ~300 KB
  tests/
    test_render.py          # markdown parity fixtures
    test_paths.py           # path resolution rules
    test_cache.py
  config/
    serv.toml               # the color scheme + runtime config (see below)
```

## Plugin protocol

Each plugin is a module exposing:

```python
def setup(md: MarkdownIt, cfg: dict) -> None: ...   # register md rules
def assets(cfg: dict) -> list[Asset]: ...           # js/css to include only when used
```

- Page-level plugins render fences/roles; they get the page's used-plugin set so a page with
  no chemistry never loads RDKit.js, and a page with no math never loads KaTeX.
- Chemistry and Mermaid stay client-side (RDKit.js, mermaid ESM), but loaded from vendored
  files rather than CDN, so the binary works offline.
- RDKit.js and Mermaid are the two heavy dependencies (~10 MB wasm and ~3 MB JS). Options to
  decide: vendor both, vendor neither, or vendor them into a sidecar directory next to the
  binary. Binary size target: under ~60 MB, which PyInstaller + pyobjc already costs, so
  vendoring both roughly doubles it.

## Color config

`config/serv.toml`, read once at startup with `tomllib` (stdlib). No colors in Python.

```toml
[palette]                  # Tokyo Night Day surfaces
bg        = "#e1e2e7"
text      = "#343746"
muted     = "#6172b0"
border    = "#c4c8da"
hover     = "#d0d5e3"
selected  = "#b7c1e3"

[accents]                  # one accent per surface; md and listings both purple
markdown  = "#7146a6"
listing   = "#7146a6"

[code]                     # vivid, high-contrast tokens on the gray canvas
base      = "#403a36"
comment   = "#6a6258"
keyword   = "#a64b00"
operator  = "#9b1c31"
string    = "#1f6b3a"
function  = "#3152a0"
number    = "#7136a2"
tag       = "#006d69"
highlight = "rgba(113, 70, 166, 0.16)"

[type]
reading   = "Crimson Pro"
mono      = "Fira Code"
md_size   = "1.2rem"
md_table  = "1.1rem"
code_size = "12px"

[layout]
md_width  = "46rem"
md_gutter = "3rem"
```

- `theme.py` turns this into a `:root { … }` block; `--css` stays a single in-memory endpoint.
- Config path resolution: `--config`, then `$SERV_CONFIG`, then `config/serv.toml` beside the
  project, then embedded defaults. A bad color should fail loudly at startup, not silently.

## Tray

- `rumps.App("serv", quit_button="Quit serv")`, text title showing state, e.g. `serv · 1002`.
- Status snapshot from the server state: port, root, requests served, cached render count,
  last error + time. Menu items: open in browser, copy URL, pause/resume, quit.
- Threading: run the HTTP server on a worker thread, keep `NSApplication` on the main thread
  (`rumps.App.run()` blocks there). Guard the shared snapshot with a lock.
- `--no-tray` flag for the LaunchAgent if it misbehaves under launchd; verify that first,
  since launchd-started GUI agents can differ from a terminal launch.

## Markdown cache

- Keep the current behavior: `functools.lru_cache` keyed by `(path, sha256_of_file)`.
- Recompute the hash per request by reading the file once; render on miss.
- Report hits/misses in the tray menu.
- Bound it explicitly (e.g. 64 entries) and note the memory cost in a comment.

## Parity checklist (must not regress)

Copy from the current script; this is the acceptance list.

- [ ] Path resolution: `:line` and `:line:col` suffix stripped only when the target exists.
- [ ] Home-prefix retry: `/Users/<user>/…` and `/<user>/…` retried when the original 404s.
- [ ] `~/dev/game/**/build/` served verbatim; other code files highlighted.
- [ ] Code pages: Prism highlight, line numbers, wrapped lines, no inner scrollbar, 5.6em gutter.
- [ ] `:line` requests highlight that line and scroll it to center.
- [ ] Markdown: TOC placed after the first `<h1>`; falls back to document start when no `h1`.
- [ ] Markdown: parent-folder up-arrow at the top, linking to the file's directory.
- [ ] Markdown: `class="markdown-page"` for page-scoped theme variables.
- [ ] Tables, footnotes, deflists, tasklists, chemistry fences, mermaid fences.
- [ ] KaTeX math at 1em relative to body text (`body.markdown-page .katex`).
- [ ] Directory listing: up-arrow row, hidden-file toggle (persisted in localStorage), file
      sizes, mod times, grid alignment, hover row, purple heading.
- [ ] `<PARENT>/style.css` served in-memory with `no-cache`.
- [ ] Raw-area verbatim responses keep `text/plain` for `.odin` rather than downloading.

## Build

1. `uv build` → wheel; run from a venv while developing (`uv run serv`).
2. Binary: **PyInstaller** onefile first (`--collect-all`/hooks for pyobjc, `assets/` added as
   data, resolved through `sys._MEIPASS`). Nuitka `--onefile` is the fallback if startup
   latency or pyobjc bundling is a problem.
3. Symlink `~/.local/bin/serv` → the built artifact; keep the LaunchAgent unchanged
   (`exec /Users/subwave/.local/bin/serv` from `$HOME`).
4. Guard the build with a smoke test that fetches `/style.css`, one `.md`, one `.odin:29`,
   one directory listing, and asserts the marker strings, before the symlink is swapped.

## Open questions

- Vendor RDKit.js and Mermaid into the binary, or fetch them lazily / keep CDN as a fallback?
- Vendored fonts: subset to the weights actually used, or ship full families?
- LaunchAgent + tray: does `NSStatusItem` appear when the process is started by launchd? Test
  before committing to tray-always-on. `--no-tray` covers the failure case.
- `\(…\)` and `\[…\]` math: custom inline rule, or a pre-pass that rewrites them to dollars?
- Keep `--ipython` delegation to `~/.local/share/ipython-html/serv.py`, or fold that viewer
  into this package too?
- Existing files with doubled backslashes (`\\mathrm`) render differently under pandoc's
  `tex_math_single_backslash` than under dollarmath. Decide whether to normalize, and check
  `comp/bio/adm/docs/teaching-notes.md` as the regression case.
