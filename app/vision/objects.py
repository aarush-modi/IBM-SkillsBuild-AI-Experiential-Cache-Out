"""YOLO26n object detection, run every vision.yolo_every_n frames (DESIGN §5, step 5).

COCO-pretrained, CPU. Only the classes in vision.yolo_classes are kept; boxes come back
normalized to 0..1 on each axis. The model sees frames in memory only.

Ultralytics sends anonymous usage analytics on every predict() by default. That breaks the
rule that only alert messages leave the machine, so this module switches it off: it sets
YOLO_OFFLINE before Ultralytics is first imported, and disables the event queue as well.
"""

from __future__ import annotations

import os
from typing import Any

os.environ["YOLO_OFFLINE"] = "1"  # before any ultralytics import: no analytics, no online checks

import numpy as np  # noqa: E402
import numpy.typing as npt  # noqa: E402
from ultralytics.models.yolo import YOLO  # noqa: E402
from ultralytics.utils import events as _ultralytics_events  # noqa: E402

from app.contracts import Detection  # noqa: E402
from app.vision import model_files  # noqa: E402

_ultralytics_events.events.enabled = False


class ObjectDetector:
    def __init__(self, imgsz: int, conf: float, classes: list[str]) -> None:
        # Ultralytics' result types are unions of tensors, arrays and generators; treat as Any.
        self._model: Any = YOLO(str(model_files.path(model_files.YOLO)))
        names: dict[int, str] = self._model.names
        wanted = set(classes)
        unknown = wanted - set(names.values())
        if unknown:
            raise ValueError(f"vision.yolo_classes has names YOLO doesn't know: {sorted(unknown)}")
        self._class_ids = [i for i, n in names.items() if n in wanted]
        self._names = names
        self.imgsz = imgsz
        self.conf = conf

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> ObjectDetector:
        v = settings["vision"]
        return cls(v["yolo_imgsz"], v["yolo_conf"], v["yolo_classes"])

    def warm_up(self, width: int, height: int) -> None:
        """Run once on a blank frame, so the first real frame isn't slow."""
        self.detect(np.zeros((height, width, 3), dtype=np.uint8))

    def detect(self, bgr: npt.NDArray[np.uint8]) -> list[Detection]:
        result: Any = self._model.predict(
            bgr, imgsz=self.imgsz, conf=self.conf, classes=self._class_ids, device="cpu", verbose=False,
        )[0]
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            return []
        xyxyn = boxes.xyxyn.cpu().numpy()
        confs = boxes.conf.cpu().numpy()
        cls_ids = boxes.cls.cpu().numpy().astype(int)
        return [
            Detection(
                cls=self._names[int(c)], confidence=float(p),
                bbox=(float(b[0]), float(b[1]), float(b[2]), float(b[3])),
            )
            for b, p, c in zip(xyxyn, confs, cls_ids)
        ]
