"""OpenCV webcam capture (DESIGN §5, step 1).

The camera is opened only for an active session and released on pause or end. Frames
stay in memory: this module never writes anything to disk.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from types import TracebackType

import cv2
import numpy as np
import numpy.typing as npt

log = logging.getLogger(__name__)


def _backend() -> int:
    # AVFoundation on macOS; DirectShow on Windows opens much faster than the MSMF default.
    if sys.platform == "darwin":
        return cv2.CAP_AVFOUNDATION
    if sys.platform == "win32":
        return cv2.CAP_DSHOW
    return cv2.CAP_ANY


@dataclass(frozen=True)
class Frame:
    image: npt.NDArray[np.uint8]  # BGR, already mirrored
    timestamp_ms: int             # strictly increasing, as MediaPipe VIDEO mode requires


class CameraError(RuntimeError):
    pass


class Camera:
    """One webcam for one session. Use as a context manager, or call open() and close()."""

    def __init__(self, index: int, width: int, height: int, fps: int) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self._cap: cv2.VideoCapture | None = None
        self._last_ts = -1

    @classmethod
    def from_settings(cls, settings: dict) -> Camera:
        v = settings["vision"]
        return cls(settings["camera_index"], v["capture_width"], v["capture_height"], v["capture_fps"])

    @property
    def is_open(self) -> bool:
        return self._cap is not None and self._cap.isOpened()

    def open(self) -> None:
        if self.is_open:
            return
        cap = cv2.VideoCapture(self.index, _backend())
        if not cap.isOpened():
            cap.release()
            raise CameraError(
                f"Could not open camera {self.index}. Check that no other app is using it "
                "and that camera permission is granted."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # keep latency low: always the newest frame
        self._cap = cap
        log.info(
            "Camera %d open at %dx%d",
            self.index, int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        )

    def read(self) -> Frame | None:
        """The next frame, mirrored, or None if the camera returned nothing this time."""
        if self._cap is None:
            raise CameraError("Camera is not open")
        ok, image = self._cap.read()
        if not ok or image is None:
            return None
        if image.shape[1] != self.width or image.shape[0] != self.height:
            image = cv2.resize(image, (self.width, self.height))
        image = cv2.flip(image, 1)
        ts = max(int(time.monotonic() * 1000), self._last_ts + 1)
        self._last_ts = ts
        return Frame(image=image, timestamp_ms=ts)

    def close(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            log.info("Camera %d released", self.index)

    def __enter__(self) -> Camera:
        self.open()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()


def list_cameras(max_index: int = 5) -> list[int]:
    """Indexes of cameras that open, for the Settings camera picker. Each is released at once."""
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, _backend())
        if cap.isOpened():
            found.append(i)
        cap.release()
    return found
