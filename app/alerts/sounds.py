"""Alert pings: one short sound per alert pattern (DESIGN §9).

The WAVs in app/alerts/sounds/ are made by scripts/make_sounds.py. They are played with
tools every machine already has, so there is no audio dependency: afplay on macOS, the
standard-library winsound on Windows, and paplay or aplay on Linux. Playback never blocks.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

# TODO(packaging): a PyInstaller build must resolve this from sys._MEIPASS instead.
SOUNDS_DIR = Path(__file__).resolve().parent / "sounds"


def sound_path(pattern: int) -> Path:
    return SOUNDS_DIR / f"pattern_{pattern}.wav"


def play(pattern: int) -> bool:
    """Start playing the ping for `pattern` and return at once. False if it can't be played."""
    path = sound_path(pattern)
    if not path.is_file():
        log.warning("No ping for pattern %d (%s missing)", pattern, path)
        return False
    try:
        if sys.platform == "win32":
            import winsound

            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            return True
        player = ["afplay"] if sys.platform == "darwin" else _linux_player()
        if player is None:
            log.warning("No audio player found for alert pings")
            return False
        subprocess.Popen([*player, str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.warning("Could not play ping: %s", e)
        return False


def _linux_player() -> list[str] | None:
    for cmd in ("paplay", "aplay"):
        if shutil.which(cmd):
            return [cmd, "-q"] if cmd == "aplay" else [cmd]
    return None
