# serv

A local file server for macOS: it renders Markdown in process, highlights source
files, and serves everything under your home directory at
`http://localhost:1002/`. It ships as a menu-bar app with a small settings
window.

- No `pandoc`; Markdown → HTML happens in Python (`markdown-it-py`).
- Math, chemistry and Mermaid are optional plugins, loaded from a CDN on pages
  that use them.
- All colours live in a TOML config file, not in the source.
- The installed app is a bundle of readable `.py` files, so an agent can edit
  the running code directly.

## Where things live

```text
~/Applications/serv.app/                  the app (this is what runs)
  Contents/MacOS/serv                     shell launcher
  Contents/Resources/pysrc/serv/*.py      the server, as plain source
  Contents/Resources/data/                stylesheet template, icons, chemistry JS
  Contents/Resources/config/serv.toml     built-in defaults
  Contents/Resources/config/schemes.toml  prebuilt colour schemes
  Contents/Resources/python/              standalone CPython + dependencies
~/.config/serv/serv.toml                  your settings (created on first save)
~/Library/LaunchAgents/local.serv.plist   start-at-login item
~/Library/Logs/serv.log, serv.err.log     server output
```

Source checkout: `~/dev/serv/` (`src/serv/`, `data/`, `config/`, `tests/`,
`tools/`).

## Running

- The login item starts the app with `--agent`: server plus menu-bar item, no
  window. It serves `$HOME` on the configured port.
- Double-clicking the app starts the same thing and opens the settings window.
  Closing that window leaves the menu-bar item running.
- The menu-bar icon opens: Open in Browser, Copy URL, Pause/Resume, Start at
  login, cache counters, last error, Settings…, Quit.

Control it from a terminal:

```sh
launchctl kickstart -k gui/$(id -u)/local.serv   # restart after editing code
launchctl print gui/$(id -u)/local.serv          # state and program path
```

Development runs (from the checkout, no bundle):

```sh
uv run serv --no-tray --port 1010 --root "$HOME"
uv run serv --settings                          # settings window only
uv run pytest
```

## Editing the running app

The bundle contains no compiled Python archive. To change behaviour:

1. Edit `~/Applications/serv.app/Contents/Resources/pysrc/serv/*.py`.
2. Restart: `launchctl kickstart -k gui/$(id -u)/local.serv`.

`tools/build_app.py` rebuilds the bundle from `~/dev/serv`, replacing those
files, so copy edits back into the checkout if you want to keep them.

## Configuration

`~/.config/serv/serv.toml` is read at startup and watched while running: save a
change (or let the settings window save it) and the server applies it within two
seconds, without a restart.

Resolution order: `--config PATH`, then `$SERV_CONFIG`, then
`~/.config/serv/serv.toml`, then the bundled defaults. Values are validated at
startup; a bad colour or size stops the server with a clear message.

| Section | Keys |
| --- | --- |
| `server` | `port`, `no_process` (glob list), `max_render_bytes` |
| `cache` | `entries` (rendered pages kept in memory) |
| `palette` | `bg`, `text`, `muted`, `border`, `hover`, `selected`, `zebra`, `red`, `orange`, `green`, `blue`, `teal`, `purple` |
| `accents` | `markdown`, `listing`, `directory` |
| `code` | `base`, `comment`, `keyword`, `operator`, `string`, `function`, `number`, `tag`, `highlight` |
| `type` | `reading`, `mono`, `md_size`, `md_table`, `code_size` |
| `layout` | `md_width`, `md_gutter`, `listing_width` |

The Colours section of the settings window has a **Scheme** dropdown with
prebuilt palettes (Tokyo Night Day, Tokyo Night, Catppuccin Latte and Mocha,
Gruvbox Light, Nord, Solarized Light and Dark). Picking one copies its colours
into the fields; editing any swatch afterwards switches the dropdown to
"Custom". The schemes are data in `config/schemes.toml`, not code.

Two rules keep big and generated files out of the renderer:

- `no_process` globs are served verbatim (default: `~/dev/game/**/build/**`).
- Files larger than `max_render_bytes` (default 1 MiB) are served as plain text
  instead of being rendered or highlighted.

## What the server does

- `.md` → rendered page: table of contents after the first `h1`, an up-arrow to
  the containing folder, tables, footnotes, definition lists, task lists.
- Source files (`.py`, `.rs`, `.odin`, …) → a bare page with Prism
  highlighting, line numbers, wrapped lines, and `:line` / `:line:col` support
  that highlights and centres that line.
- Directories → a grid listing with a hidden-file switch (remembered in
  `localStorage`), sizes and modification times.
- `.odin` in a verbatim area stays `text/plain` instead of downloading.
- Filed under `build/` (or any `no_process` glob) → served untouched.
- Two in-memory endpoints: `/__serv__/style.css` (generated from the config) and
  `/__serv__/js/chemistry.js` (the chemistry renderer).

Markdown extensions come from plugins in `src/serv/plugins/`:

- `math.py` — `$…$`, `$$…$$`, `\(…\)`, `\[…\]`, rendered by KaTeX.
- `chem.py` — `smiles`, `molecule`, `reaction`, `properties` fences, drawn by
  RDKit.js.
- `mermaid.py` — `mermaid` fences.

Each plugin only adds its CDN assets to pages that actually use it.

## Build

```sh
uv run python tools/build_app.py            # writes dist/serv.app
uv run python tools/build_app.py --install  # also copies to ~/Applications
uv run python tools/make_tray_icon.py       # re-render the menu-bar glyph
```

The build embeds a uv-managed standalone CPython (`uv python install 3.14`) with
the runtime dependencies installed into its `site-packages`, then copies the
sources and data unmodified. The bundle is ad-hoc signed.

## Decisions that differ from the original plan

- **App bundle, not a single binary.** A PyInstaller onefile would hide the
  source inside an archive. The bundle keeps readable `.py` files, which is
  friendlier for both people and agents.
- **No vendored web libraries.** Prism, KaTeX, fonts, RDKit.js and Mermaid come
  from pinned CDN versions, so the bundle stays ~100 MB instead of ~150 MB and
  library updates do not need a rebuild.
- **Black-and-white app icon and template menu-bar glyph.** The same geometry,
  so the icon reads on light and dark menu bars.
