# serv

A local file server: it renders Markdown in process, highlights source files,
and serves everything under your home directory at `http://localhost:1002/`. It
runs on macOS, Linux and Windows with a tray icon and browser-based settings.

- No `pandoc`; Markdown → HTML happens in Python (`markdown-it-py`).
- Math, chemistry, Mermaid, and Shoelace settings widgets load from pinned CDNs.
- All colours live in a TOML config file, not in the source.
- Settings open in the browser from the tray menu and save each change immediately.
- The macOS build is an app bundle of readable `.py` files, so an agent can edit
  the running code directly.

## Where things live

```text
<install>/serv.app/                       macOS app bundle (see Build below)
  Contents/MacOS/serv                     native launcher with embedded Python
  Contents/Resources/pysrc/serv/*.py      the server, as plain source
  Contents/Resources/data/                stylesheet template, icons, chemistry JS
  Contents/Resources/config/*.toml        default config, schemes, fonts, labels
  Contents/Resources/python/              standalone CPython and dependencies
~/.config/serv/serv.toml                  your settings (created on first save)
```

On Windows the config sits in `%APPDATA%\serv\serv.toml`; `$XDG_CONFIG_HOME` is
honoured on Linux and macOS. The login item is a LaunchAgent on macOS, a systemd
user unit (or an XDG autostart entry) on Linux, and the per-user Run key on
Windows.

Source checkout: `~/dev/serv/` (`src/serv/`, `data/`, `config/`, `tests/`,
`tools/`).

## Running

- The tray owns the server in one process: starting the tray starts the server,
  quitting the tray (Quit serv) stops it.
- The login item runs the same app with `--no-gui`: tray and server, no window.
  It has no `KeepAlive`, so quitting stays quit until the next login.
- Opening the macOS app starts the tray and server without opening a window.
  Use **Settings…** in the tray menu to open the browser settings page on a
  separate, OS-assigned loopback port.
- A second copy cannot share the content port: it reports the conflict and exits.
- The tray menu: status, Open in Browser, Copy URL, Pause/Resume, Start at
  login, cache counters, last error, Settings…, Quit.
- Pause releases the listening port so another program can use it; Resume takes
  it back. If something else grabbed the port meanwhile, Resume leaves serv
  paused and shows the reason in the menu.

From a checkout or a terminal:

```sh
open -a "$HOME/Applications/serv.app"           # macOS: start the tray and server
uv run pytest
launchctl kickstart -k gui/$(id -u)/local.serv   # macOS: restart the login item
systemctl --user restart serv                    # Linux: restart the login item
```

- `uv run serv` is a foreground development command. It keeps the terminal
  occupied while its tray and server run.

## Editing the running app

The macOS bundle contains no compiled Python archive. To change behaviour:

1. Edit `~/Applications/serv.app/Contents/Resources/pysrc/serv/*.py`.
2. Restart: `launchctl kickstart -k gui/$(id -u)/local.serv`.

`tools/build_app.py` rebuilds the bundle from `~/dev/serv`, replacing those
files, so copy edits back into the checkout if you want to keep them.

## Configuration

`serv.toml` is read at startup and watched while running. Browser settings are
validated, saved, and applied immediately. External file edits are applied within
two seconds.

Resolution order: `--config PATH`, then `$SERV_CONFIG`, then the user file, then
the bundled defaults. Values are validated at startup; a bad colour or size stops
the server with a clear message.

| Section | Keys |
| --- | --- |
| `server` | `port`, `no_process` (glob list), `max_render_bytes` |
| `cache` | `entries` (rendered pages kept in memory) |
| `palette` | `bg`, `text`, `muted`, `border`, `hover`, `selected`, `selected_text`, `zebra`, `red`, `orange`, `green`, `blue`, `teal`, `purple` |
| `accents` | `markdown`, `listing`, `directory` |
| `code` | `base`, `comment`, `keyword`, `operator`, `string`, `function`, `number`, `tag`, `highlight` |
| `type` | `reading`, `mono`, `reading_weights`, `mono_weights`, `md_size`, `md_table`, `code_size` |
| `layout` | `md_width`, `md_gutter`, `listing_width` |

The browser settings page edits that file directly:

- **General** — port, render size limit, cache size, verbatim globs, and login item.
- **Colors** — a scheme selector and a labeled color picker for every interface,
  accent, and syntax color.
- **Type & Layout** — curated web fonts or a locally installed family name, plus
  sliders for text sizes and page widths.
- Changes save as you edit; there is no Save button. The configured content port
  takes effect after serv restarts.

Every scheme value is a member of that theme's published palette — nothing is
lightened or darkened. Where a role needed more contrast it borrows a different
palette member (for example a table header uses the theme's dark surface with
`selected_text` on top) rather than inventing a shade. A few pastel syntax
colours in the light variants are low-contrast by design of those palettes.

The supporting tables are data, not code: `config/schemes.toml` (palettes),
`config/fonts.toml` (families and their Google Fonts axis queries) and
`config/labels.toml` (swatch names).

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
- Directories → a grid listing with folder and file icons, a hidden-file switch
  (remembered in `localStorage`), sizes and modification times.
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
uv run python tools/build_app.py            # macOS: writes dist/serv.app
uv run python tools/build_app.py --install  # also copies to ~/Applications
uv run python tools/make_tray_icon.py       # re-render tray and app icons
```

The macOS build embeds a uv-managed standalone CPython (`uv python install 3.14`)
with the runtime dependencies installed into its `site-packages`, then copies the
sources and data unmodified. The browser settings server binds to loopback on an
OS-assigned ephemeral port, separate from the content server. The bundle is
ad-hoc signed. On Linux and Windows, run from a checkout (`uv run serv`) or
package with your usual tool; the code path is identical apart from the login
item and tray backend.

## Decisions

- **Browser settings, pystray tray.** The tray starts a loopback-only settings
  server on an ephemeral port and opens it in the browser. It does not use the
  content server's port.
- **Save on change.** Each setting is validated, written to TOML, and applied to
  the running server as soon as the user changes it.
- **macOS ships as an app bundle with plain sources**, not a single binary, so
  the running code stays readable and editable.
- **No vendored web libraries.** Prism, KaTeX, fonts, RDKit.js, Mermaid, and
  Shoelace come from pinned CDN versions.
- **Black-and-white app icon, appearance-aware tray glyph.** A black glyph on
  light panels, a white one on dark ones, and a template image on macOS so the
  system handles inversion.
