"""Loads the real MediaPipe and YOLO models and runs them on blank frames.

Skipped when the model files haven't been downloaded (python scripts/download_models.py).
"""

from __future__ import annotations

import copy
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from app.storage.settings import DEFAULTS
from app.vision import model_files

pytest.importorskip("mediapipe")
pytest.importorskip("ultralytics")

if not all((model_files.MODELS_DIR / name).is_file() for name in model_files.MODELS):
    pytest.skip("model files not downloaded", allow_module_level=True)

from app.vision.capture import Frame  # noqa: E402
from app.vision.objects import ObjectDetector  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402


def test_real_pipeline_on_empty_frames() -> None:
    with VisionPipeline.from_settings(copy.deepcopy(DEFAULTS)) as p:
        for i in range(4):
            f, preview = p.process(Frame(image=np.zeros((480, 640, 3), dtype=np.uint8), timestamp_ms=1000 + 33 * i))
            assert not f.person_present
            assert f.head_yaw is None and f.hands == [] and f.objects == []
            assert preview.pose == {}


def test_unknown_yolo_class_is_rejected() -> None:
    with pytest.raises(ValueError, match="phablet"):
        ObjectDetector(416, 0.25, ["cell phone", "phablet"])


def test_ultralytics_analytics_are_off() -> None:
    from ultralytics.utils import events

    assert not events.events.enabled  # holds whatever imported ultralytics first


def test_app_import_puts_ultralytics_offline() -> None:
    # A fresh interpreter, as in the app, where objects.py is the first ultralytics import.
    code = (
        "import app.vision.objects\n"
        "from ultralytics.utils import ONLINE, events\n"
        "assert not ONLINE and not events.events.enabled\n"
    )
    root = Path(__file__).parents[2]
    env = {k: v for k, v in os.environ.items() if k != "YOLO_OFFLINE"}
    subprocess.run([sys.executable, "-c", code], cwd=root, env=env, check=True, timeout=60)
