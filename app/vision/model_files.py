"""Model files: where they live and where to download them from (DESIGN §5).

Shared by scripts/download_models.py and the vision modules. Stdlib only.
"""

from __future__ import annotations

from pathlib import Path

MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

_MP = "https://storage.googleapis.com/mediapipe-models"

POSE = "pose_landmarker_lite.task"
FACE = "face_landmarker.task"
HAND = "hand_landmarker.task"
YOLO = "yolo26n.pt"

URLS: dict[str, str] = {
    POSE: f"{_MP}/pose_landmarker/pose_landmarker_lite/float16/latest/{POSE}",
    FACE: f"{_MP}/face_landmarker/face_landmarker/float16/latest/{FACE}",
    HAND: f"{_MP}/hand_landmarker/hand_landmarker/float16/latest/{HAND}",
    YOLO: f"https://github.com/ultralytics/assets/releases/download/v8.4.0/{YOLO}",
}


def path(name: str) -> Path:
    """Path to a model file, with a clear error if it hasn't been downloaded."""
    p = MODELS_DIR / name
    if not p.is_file():
        raise FileNotFoundError(f"{p} is missing. Run: python scripts/download_models.py")
    return p
