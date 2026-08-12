"""Resolve bundled assets in source and PyInstaller environments."""
from __future__ import annotations

import sys
from pathlib import Path


def resource_path(relative: str | Path) -> Path:
    """Return a path relative to the source tree or frozen app bundle."""
    bundle_root = getattr(sys, "_MEIPASS", None)
    base = Path(bundle_root) if bundle_root else Path(__file__).resolve().parents[2]
    return base / Path(relative)
