"""Test configuration.

Tests must not depend on the developer's own ``~/.config/serv/serv.toml``.
Pointing ``SERV_CONFIG`` at the shipped defaults keeps assertions stable while
the real app is free to hold a different theme or font.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config" / "serv.toml"
os.environ["SERV_CONFIG"] = str(DEFAULT_CONFIG)
