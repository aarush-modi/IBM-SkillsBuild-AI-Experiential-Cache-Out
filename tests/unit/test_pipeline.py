"""VisionPipeline scheduling with fake models: no camera or model files needed."""

from __future__ import annotations

import copy
from typing import Any

import numpy as np
import pytest

pytest.importorskip("cv2")

from app.contracts import Detection  # noqa: E402
from app.storage.settings import DEFAULTS  # noqa: E402
from app.vision.capture import Frame  # noqa: E402
from app.vision.features import RawHand, RawLandmarks  # noqa: E402
from app.vision.pipeline import VisionPipeline  # noqa: E402

PHONE = Detection(cls="cell phone", confidence=0.9, bbox=(0.4, 0.6, 0.5, 0.8))


def a_hand() -> RawHand:
    return RawHand(image=np.full((21, 3), 0.5), world=np.zeros((21, 3)))


class FakeLandmarkers:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []
        self.closed = False
        self.pose: np.ndarray | None = None

    def detect(self, rgb: Any, timestamp_ms: int, run_hands: bool = True) -> RawLandmarks:
        self.calls.append((timestamp_ms, run_hands))
        return RawLandmarks(pose=self.pose, hands=[a_hand()] if run_hands else [])

    def close(self) -> None:
        self.closed = True


class FakeObjects:
    def __init__(self) -> None:
        self.calls = 0

    def detect(self, bgr: Any) -> list[Detection]:
        self.calls += 1
        return [PHONE]


def settings(**vision: Any) -> dict[str, Any]:
    s = copy.deepcopy(DEFAULTS)
    s["vision"].update(vision)
    return s


def frame(ts: int) -> Frame:
    return Frame(image=np.zeros((480, 640, 3), dtype=np.uint8), timestamp_ms=ts)


def make(**vision: Any) -> tuple[VisionPipeline, FakeLandmarkers, FakeObjects]:
    lm, obj = FakeLandmarkers(), FakeObjects()
    return VisionPipeline(settings(**vision), lm, obj), lm, obj


def test_yolo_runs_every_nth_frame_and_is_reused_between() -> None:
    p, _, obj = make(yolo_every_n=3)
    results = [p.process(frame(1000 + i * 33))[0] for i in range(7)]
    assert obj.calls == 3  # frames 0, 3, 6
    assert all(f.objects == [PHONE] for f in results)


def test_hands_every_nth_frame_reuses_last_hands() -> None:
    p, lm, _ = make(hands_every_n=2)
    results = [p.process(frame(1000 + i * 33))[0] for i in range(4)]
    assert [run for _, run in lm.calls] == [True, False, True, False]
    assert all(len(f.hands) == 1 for f in results)


def test_t_counts_from_first_frame_and_restarts_on_reset() -> None:
    p, lm, _ = make()
    assert p.process(frame(5000))[0].t == 0.0
    assert p.process(frame(6500))[0].t == pytest.approx(1.5)
    assert [ts for ts, _ in lm.calls] == [5000, 6500]
    p.reset()
    assert p.process(frame(9000))[0].t == 0.0


def test_preview_carries_frame_points_and_boxes() -> None:
    p, lm, _ = make()
    lm.pose = np.full((33, 4), 0.5)
    f, preview = p.process(frame(1000))
    assert f.person_present
    assert preview.image.shape == (480, 640, 3)
    assert set(preview.pose) >= {0, 11, 12}
    assert len(preview.hands) == 1 and len(preview.hands[0]) == 21
    assert preview.objects == [PHONE]
    assert preview.process_ms >= 0


def test_close_frees_landmarkers() -> None:
    p, lm, _ = make()
    with p:
        pass
    assert lm.closed
