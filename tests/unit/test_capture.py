"""Camera wrapper tests with a fake cv2.VideoCapture, so no webcam is needed."""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")

from app.storage.settings import DEFAULTS  # noqa: E402
from app.vision import capture  # noqa: E402
from app.vision.capture import Camera, CameraError  # noqa: E402


class FakeCapture:
    instances: list[FakeCapture] = []

    def __init__(self, index: int, backend: int, opened: bool = True, shape: tuple[int, int] = (480, 640)) -> None:
        self.opened = opened
        self.released = False
        self.shape = shape
        FakeCapture.instances.append(self)

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def set(self, prop: int, value: Any) -> bool:
        return True

    def get(self, prop: int) -> float:
        return 0.0

    def read(self) -> tuple[bool, Any]:
        h, w = self.shape
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:, 0] = 255  # mark the left column so mirroring is visible
        return True, img

    def release(self) -> None:
        self.released = True


@pytest.fixture(autouse=True)
def fake_cv2(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeCapture.instances = []
    monkeypatch.setattr(capture.cv2, "VideoCapture", FakeCapture)


def test_from_settings_uses_vision_block() -> None:
    cam = Camera.from_settings(DEFAULTS)
    assert (cam.index, cam.width, cam.height, cam.fps) == (0, 640, 480, 30)


def test_frames_are_mirrored() -> None:
    with Camera(0, 640, 480, 30) as cam:
        frame = cam.read()
    assert frame is not None
    assert frame.image[0, -1, 0] == 255 and frame.image[0, 0, 0] == 0


def test_timestamps_strictly_increase() -> None:
    with Camera(0, 640, 480, 30) as cam:
        stamps = [f.timestamp_ms for f in (cam.read() for _ in range(50)) if f]
    assert all(b > a for a, b in zip(stamps, stamps[1:]))


def test_wrong_size_frames_are_resized() -> None:
    with Camera(0, 640, 480, 30) as cam:
        cam._cap.shape = (720, 1280)  # type: ignore[union-attr]
        frame = cam.read()
    assert frame is not None and frame.image.shape == (480, 640, 3)


def test_camera_is_released_on_exit_even_after_error() -> None:
    with pytest.raises(ValueError):
        with Camera(0, 640, 480, 30):
            raise ValueError
    assert FakeCapture.instances[-1].released


def test_failed_open_raises_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture.cv2, "VideoCapture", lambda i, b: FakeCapture(i, b, opened=False))
    with pytest.raises(CameraError):
        Camera(3, 640, 480, 30).open()
    assert FakeCapture.instances[-1].released


def test_read_before_open_raises() -> None:
    with pytest.raises(CameraError):
        Camera(0, 640, 480, 30).read()


def test_capture_never_writes_to_disk() -> None:
    import inspect

    src = inspect.getsource(capture)
    for forbidden in ("imwrite", "VideoWriter", "write_bytes", "write_text"):
        assert forbidden not in src
