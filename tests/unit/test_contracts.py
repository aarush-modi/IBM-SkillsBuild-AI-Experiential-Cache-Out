import ast
import dataclasses
from pathlib import Path

import pytest

from app.contracts import Alert, Detection, FrameFeatures, HandInfo, PATTERN_DISTRACTION

ROOT = Path(__file__).parents[2]


def make_features(**overrides: object) -> FrameFeatures:
    base: dict[str, object] = dict(
        t=0.0, person_present=True,
        head_yaw=0.0, head_pitch=0.0, head_roll=0.0,
        shoulder_width=0.3, shoulder_angle=0.0, nose_to_shoulder_y=0.8, face_width=0.2,
        hands=[HandInfo(bbox=(0.4, 0.7, 0.5, 0.8), grasp=False, near_keyboard=True)],
        objects=[Detection(cls="keyboard", confidence=0.9, bbox=(0.3, 0.75, 0.7, 0.9))],
    )
    base.update(overrides)
    return FrameFeatures(**base)  # type: ignore[arg-type]


def test_frame_features_is_frozen() -> None:
    f = make_features()
    with pytest.raises(dataclasses.FrozenInstanceError):
        f.t = 1.0  # type: ignore[misc]


def test_absent_person_has_no_measurements() -> None:
    f = make_features(person_present=False, head_yaw=None, shoulder_width=None, hands=[], objects=[])
    assert f.head_yaw is None and f.hands == []


def test_alert_is_frozen() -> None:
    a = Alert(kind="distraction", label="phone", pattern=PATTERN_DISTRACTION, created_at=0.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.label = "window"  # type: ignore[misc]


FORBIDDEN = {"cv2", "mediapipe", "ultralytics", "torch", "PySide6", "app.vision", "app.ui"}


@pytest.mark.parametrize("path", sorted((ROOT / "app" / "logic").glob("*.py")) + [ROOT / "app" / "contracts.py"])
def test_logic_does_not_import_models_or_ui(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert not any(name == f or name.startswith(f + ".") for f in FORBIDDEN), f"{path.name} imports {name}"
