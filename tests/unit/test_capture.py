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
        self.fail = False  # when True, read() returns no frame
        self.image: Any = None  # when set, read() returns this exact image
        FakeCapture.instances.append(self)

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def set(self, prop: int, value: Any) -> bool:
        return True

    def get(self, prop: int) -> float:
        return 0.0

    def read(self) -> tuple[bool, Any]:
        if self.fail:
            return False, None
        if self.image is not None:
            return True, self.image.copy()
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
    assert (cam.index, cam.width, cam.height, cam.fps, cam.max_read_failures) == (0, 640, 480, 30, 30)


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
        fake(cam).shape = (720, 1280)
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


def fake(cam: Camera) -> FakeCapture:
    assert isinstance(cam._cap, FakeCapture)
    return cam._cap


def test_empty_read_returns_none() -> None:
    with Camera(0, 640, 480, 30) as cam:
        fake(cam).fail = True
        assert cam.read() is None


def test_too_many_empty_reads_raise() -> None:
    with Camera(0, 640, 480, 30, max_read_failures=5) as cam:
        fake(cam).fail = True
        for _ in range(4):
            assert cam.read() is None
        with pytest.raises(CameraError, match="not responding"):
            cam.read()


def test_a_good_frame_resets_the_failure_count() -> None:
    with Camera(0, 640, 480, 30, max_read_failures=3) as cam:
        for _ in range(5):  # 2 failures, 1 success, repeated: never reaches 3 in a row
            fake(cam).fail = True
            assert cam.read() is None and cam.read() is None
            fake(cam).fail = False
            assert cam.read() is not None


def test_wide_frames_are_centre_cropped_not_stretched(caplog: pytest.LogCaptureFixture) -> None:
    # 1280x720 (16:9). A 4:3 centre crop keeps columns 160..1119 and drops the sides.
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:, :160] = 255         # left side band: must be cropped away
    img[:, 1120:] = 255        # right side band: must be cropped away
    img[300:420, 580:700] = 128  # a 120x120 square in the centre
    with Camera(0, 640, 480, 30) as cam:
        fake(cam).image = img
        frame = cam.read()
        cam.read()
    assert frame is not None and frame.image.shape == (480, 640, 3)
    assert frame.image.max() == 128  # side bands are gone
    ys, xs = np.nonzero(frame.image[:, :, 0] == 128)
    h, w = ys.max() - ys.min() + 1, xs.max() - xs.min() + 1
    assert abs(h - w) <= 2  # the square is still square
    assert sum("centre-cropping" in r.message for r in caplog.records) == 1  # warned once


def test_tall_frames_are_centre_cropped() -> None:
    img = np.zeros((960, 640, 3), dtype=np.uint8)  # 2:3, too tall for 4:3
    img[:240] = 255
    img[720:] = 255
    with Camera(0, 640, 480, 30) as cam:
        fake(cam).image = img
        frame = cam.read()
    assert frame is not None and frame.image.shape == (480, 640, 3)
    assert frame.image.max() == 0
