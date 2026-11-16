"""Where bundled read-only files live: the repo when run from source, the PyInstaller bundle
when packaged (DESIGN §4, Packaging). User data never lives here; see storage.settings.app_data_dir."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_root() -> Path:
    """The folder that holds models/ and app/alerts/sounds/."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[1]
