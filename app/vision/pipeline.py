"""One frame in, FrameFeatures (for logic) and PreviewFrame (for the UI) out (DESIGN §5).

Runs the landmarkers on every frame, hands on every vision.hands_every_n-th frame and YOLO
on every vision.yolo_every_n-th frame, reusing the last result in between. Single-threaded
and synchronous: the vision thread (app/main.py) calls process() in its loop.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Protocol

import cv2
import numpy as np
import numpy.typing as npt

from app.contracts import BBox, Detection, FrameFeatures
from app.vision.capture import Frame
from app.vision.features import POSE_KEEP, FeatureSmoother, RawHand, RawLandmarks, build_features

Point = tuple[float, float]


class LandmarkerLike(Protocol):
    def detect(self, rgb: npt.NDArray[np.uint8], timestamp_ms: int, run_hands: bool = True) -> RawLandmarks: ...
    def close(self) -> None: ...


class ObjectDetectorLike(Protocol):
    def detect(self, bgr: npt.NDArray[np.uint8]) -> list[Detection]: ...


@dataclass(frozen=True)
class PreviewFrame:
    """What the UI needs to draw the live preview and overlay. In memory only, never saved.

    Points are normalized 0..1 image coordinates. pose maps a POSE_KEEP index to
    (x, y, visibility); it is empty when no person is detected.
    """
    image: npt.NDArray[np.uint8]                     # BGR, mirrored
    pose: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    hands: list[list[Point]] = field(default_factory=list)
    objects: list[Detection] = field(default_factory=list)
    process_ms: float = 0.0                          # time spent in the models for this frame


def _preview_pose(raw: RawLandmarks) -> dict[int, tuple[float, float, float]]:
    if raw.pose is None:
        return {}
    return {i: (float(raw.pose[i, 0]), float(raw.pose[i, 1]), float(raw.pose[i, 3])) for i in POSE_KEEP}


def _preview_hands(hands: list[RawHand]) -> list[list[Point]]:
    return [[(float(x), float(y)) for x, y in h.image[:, :2]] for h in hands]


class VisionPipeline:
    def __init__(
        self,
        settings: dict[str, Any],
        landmarkers: LandmarkerLike,
        objects: ObjectDetectorLike,
        work_zone: BBox | None = None,
    ) -> None:
        v = settings["vision"]
        self.yolo_every_n: int = max(1, v["yolo_every_n"])
        self.hands_every_n: int = max(1, v["hands_every_n"])
        self.grasp_curl_ratio: float = v["grasp_curl_ratio"]
        self.work_zone = work_zone  # set by calibration; hands are never near_keyboard before it
        self._landmarkers = landmarkers
        self._objects = objects
        self._smoother = FeatureSmoother.from_settings(settings)
        self._frame_index = 0
        self._start_ms: int | None = None
        self._last_hands: list[RawHand] = []
        self._last_objects: list[Detection] = []

    @classmethod
    def from_settings(cls, settings: dict[str, Any], work_zone: BBox | None = None) -> VisionPipeline:
        """Load the real models. Takes a few seconds; do it before opening the camera."""
        from app.vision.landmarkers import Landmarkers
        from app.vision.objects import ObjectDetector

        v = settings["vision"]
        detector = ObjectDetector.from_settings(settings)
        detector.warm_up(v["capture_width"], v["capture_height"])
        return cls(settings, Landmarkers.from_settings(settings), detector, work_zone)

    def reset(self) -> None:
        """Start a new session: t restarts at 0 and smoothing and cached results clear."""
        self._frame_index = 0
        self._start_ms = None
        self._last_hands = []
        self._last_objects = []
        self._smoother.reset()

    def process(self, frame: Frame) -> tuple[FrameFeatures, PreviewFrame]:
        t0 = time.perf_counter()
        if self._start_ms is None:
            self._start_ms = frame.timestamp_ms
        i = self._frame_index
        self._frame_index += 1

        rgb = np.asarray(cv2.cvtColor(frame.image, cv2.COLOR_BGR2RGB), dtype=np.uint8)
        run_hands = i % self.hands_every_n == 0
        raw = self._landmarkers.detect(rgb, frame.timestamp_ms, run_hands=run_hands)
        if run_hands:
            self._last_hands = raw.hands
        else:
            raw = RawLandmarks(pose=raw.pose, face=raw.face, face_matrix=raw.face_matrix, hands=self._last_hands)

        if i % self.yolo_every_n == 0:
            self._last_objects = self._objects.detect(frame.image)

        h, w = frame.image.shape[:2]
        features = build_features(
            raw, self._last_objects,
            t=(frame.timestamp_ms - self._start_ms) / 1000,
            aspect=h / w,
            grasp_curl_ratio=self.grasp_curl_ratio,
            work_zone=self.work_zone,
        )
        features = self._smoother.update(features)
        preview = PreviewFrame(
            image=frame.image,
            pose=_preview_pose(raw),
            hands=_preview_hands(raw.hands),
            objects=self._last_objects,
            process_ms=(time.perf_counter() - t0) * 1000,
        )
        return features, preview

    def close(self) -> None:
        self._landmarkers.close()

    def __enter__(self) -> VisionPipeline:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()
