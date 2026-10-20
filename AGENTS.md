# Project notes for agents

## Shape of the project

- `src/serv/` — the server: `server.py` (routing), `markdown.py` (renderer),
  `page.py` (HTML shell, code pages, listings), `plugins/` (math, chemistry,
  Mermaid), `config.py` + `theme.py` (settings → CSS), `ui.py` + `tray.py`
  (AppKit), `launchagent.py` (login item), `watch.py` (live config reload).
- `data/` — stylesheet template, chemistry renderer JS, tray and app icons.
  These are application data; third-party libraries are **not** vendored.
- `config/serv.toml` — the built-in defaults, copied into the app bundle.
- `tools/` — `build_app.py` (bundle builder), `make_tray_icon.py`.
- `tests/` — pytest, including an end-to-end HTTP test on an ephemeral port.

## Rules that matter here

- No colours in Python. Every colour is a key in `config/serv.toml`, and the
  prebuilt palettes are data in `config/schemes.toml`; `theme.py` turns the
  active ones into `:root` custom properties and `data/style/serv.css`
  references them with `var(--…)`.
- Font choices are data in `config/fonts.toml`. Each entry carries the Google
  Fonts axis query it needs; an empty `*_weights` value means "installed font,
  no download". Add a family only after checking its CSS URL returns 200.
- No vendored web libraries. Prism, KaTeX, fonts, RDKit.js and Mermaid come from
  pinned CDN URLs inside the plugins, and only on pages that need them.
- The installed app is `~/Applications/serv.app` with plain `.py` sources under
  `Contents/Resources/pysrc/`. Rebuild with
  `uv run python tools/build_app.py --install`, then restart the login item with
  `launchctl kickstart -k gui/$(id -u)/local.serv`.
- Use `deal` contracts at data-flow boundaries (see `paths.py`, `config.py`,
  `cache.py`). When a validator takes `result`, name the parameter `result`.
- `@objc.python_method` is required on every helper in the AppKit controller;
  anything without it is treated as an Objective-C selector.

## Checks before handing work back

```sh
uv run pytest
uv run python tools/build_app.py --install
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:1002/
```

For page changes, compare against the running server with `agent-browser` rather
than assuming the markup renders.
