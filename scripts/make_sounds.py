"""Generate the four alert pings (DESIGN §9) as small WAV files in app/alerts/sounds/.

Usage: python scripts/make_sounds.py
The WAVs are committed, so this only needs re-running after changing a pattern here.
Stdlib only: pure sine tones with short fades so they don't click.
"""

from __future__ import annotations

import math
import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.alerts.sounds import SOUNDS_DIR, sound_path  # noqa: E402

RATE = 22050
VOLUME = 0.35   # of full scale: noticeable without being harsh
FADE_S = 0.008

# Each pattern: a list of (start Hz, end Hz, seconds); 0 Hz is silence.
PATTERNS: dict[int, list[tuple[float, float, float]]] = {
    1: [(880.0, 880.0, 0.15), (0.0, 0.0, 0.10), (880.0, 880.0, 0.15)],                  # distraction: two beeps
    2: [(440.0, 440.0, 0.30)],                                                          # posture: one soft low tone
    3: [(1320.0, 1320.0, 0.10), (0.0, 0.0, 0.07)] * 2 + [(1320.0, 1320.0, 0.10)],       # escalated: three fast beeps
    4: [(600.0, 1200.0, 0.25)],                                                         # test: rising chirp
}


def tone(f0: float, f1: float, seconds: float, volume: float) -> list[float]:
    n = int(RATE * seconds)
    out, phase = [], 0.0
    fade = int(RATE * FADE_S)
    for i in range(n):
        if f0 == 0:
            out.append(0.0)
            continue
        freq = f0 + (f1 - f0) * i / max(1, n - 1)
        phase += 2 * math.pi * freq / RATE
        env = min(1.0, i / fade, (n - 1 - i) / fade) if fade else 1.0
        out.append(volume * env * math.sin(phase))
    return out


def write(pattern: int) -> Path:
    samples: list[float] = []
    for f0, f1, s in PATTERNS[pattern]:
        # The posture tone is softer than the others.
        samples += tone(f0, f1, s, VOLUME * (0.7 if pattern == 2 else 1.0))
    path = sound_path(pattern)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(x * 32767)) for x in samples))
    return path


def main() -> int:
    SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
    for p in PATTERNS:
        path = write(p)
        print(f"{path.name}: {path.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
