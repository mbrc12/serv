<div align="center">
  <img src="data/app/serv-icon.svg" width="104" alt="White download arrow in a triangle on a black rounded square">
  <h1>serv</h1>
  <p>A local file server with rendered Markdown, highlighted code, and browser settings.</p>
</div>

`serv` serves a folder at <http://localhost:1002/>. It runs on macOS, Linux, and
Windows. On macOS, it can also run as a menu-bar app.

## Features

- Browse local folders and files in a web browser.
- Render Markdown and highlight source code.
- Add KaTeX math, chemistry diagrams, and Mermaid diagrams to Markdown.
- Pause or resume the server from the tray menu.
- Change the serving folder and settings in the browser; changes are saved
  automatically.

## Run from source

Requirements: Python 3.14 or newer and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --dev
uv run serv --root ~/Documents
```

- Omit `--root` to serve the current directory.
- Open **Settings…** from the tray menu to choose a persistent root and adjust
  other settings.
- `--root PATH` overrides the saved root for that run.
- The content server uses port `1002` by default. Use `--port PORT` to choose a
  different port.

## Build the macOS app

From the repository root, run:

```sh
uv run python tools/build_app.py --install
open -a "$HOME/Applications/serv.app"
```

The app bundle includes Python and its dependencies. The settings page uses a
separate loopback-only port; it does not share the content server's port.

## Settings and configuration

Settings are stored at `${XDG_CONFIG_HOME:-~/.config}/serv/serv.toml` on macOS and
Linux, or `%APPDATA%\serv\serv.toml` on Windows. The server watches the file and
applies valid external edits while running.

- Changing the root folder restarts the file server on its current port.
- Changing the configured port takes effect after restarting `serv`.
- An omitted root uses the directory from which `serv` starts.

## Development checks

```sh
uv run pytest
uvx ruff check src tests tools
node --check data/settings/settings.js
```
