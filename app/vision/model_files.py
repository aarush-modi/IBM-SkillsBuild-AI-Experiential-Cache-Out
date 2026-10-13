"""Model files: where they live, where to download them from, and their checksums (DESIGN §5).

Shared by scripts/download_models.py and the vision modules. Stdlib only.
URLs are pinned to a fixed version, and every file is checked against its SHA-256, so a
model can never change silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

# TODO(packaging): a PyInstaller build must resolve this from sys._MEIPASS instead.
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

_MP = "https://storage.googleapis.com/mediapipe-models"


class ModelFile(NamedTuple):
    url: str
    sha256: str


POSE = "pose_landmarker_lite.task"
FACE = "face_landmarker.task"
HAND = "hand_landmarker.task"
YOLO = "yolo26n.pt"

MODELS: dict[str, ModelFile] = {
    POSE: ModelFile(
        f"{_MP}/pose_landmarker/pose_landmarker_lite/float16/1/{POSE}",
        "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a",
    ),
    FACE: ModelFile(
        f"{_MP}/face_landmarker/face_landmarker/float16/1/{FACE}",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
    ),
    HAND: ModelFile(
        f"{_MP}/hand_landmarker/hand_landmarker/float16/1/{HAND}",
        "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1",
    ),
    YOLO: ModelFile(
        f"https://github.com/ultralytics/assets/releases/download/v8.4.0/{YOLO}",
        "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef",
    ),
}


def path(name: str) -> Path:
    """Path to a model file, with a clear error if it hasn't been downloaded."""
    p = MODELS_DIR / name
    if not p.is_file():
        raise FileNotFoundError(f"{p} is missing. Run: python scripts/download_models.py")
    return p
