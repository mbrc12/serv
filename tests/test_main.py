from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from serv.__main__ import _root_for_config
from serv.config import load_config


def test_cli_root_remains_an_override_for_config_reloads(tmp_path: Path) -> None:
    cli_root = tmp_path / "cli"
    saved_root = tmp_path / "saved"
    default_root = tmp_path / "default"
    for path in (cli_root, saved_root, default_root):
        path.mkdir()

    base = load_config()
    config = replace(base, server=replace(base.server, root=str(saved_root)))

    assert _root_for_config(config, cli_root, default_root) == cli_root
    assert _root_for_config(config, None, default_root) == saved_root

    config_without_root = replace(base, server=replace(base.server, root=None))
    assert _root_for_config(config_without_root, None, default_root) == default_root
