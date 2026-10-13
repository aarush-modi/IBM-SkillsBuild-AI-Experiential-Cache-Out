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
from typing import Any

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

    def __init__(self, index: int, width: int, height: int, fps: int, max_read_failures: int = 30) -> None:
        self.index = index
        self.width = width
        self.height = height
        self.fps = fps
        self.max_read_failures = max_read_failures
        self._cap: cv2.VideoCapture | None = None
        self._last_ts = -1
        self._failures = 0
        self._warned_size: tuple[int, int] | None = None

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> Camera:
        v = settings["vision"]
        return cls(
            settings["camera_index"], v["capture_width"], v["capture_height"], v["capture_fps"],
            v["max_read_failures"],
        )

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
        """The next frame, mirrored, or None if the camera returned nothing this time.

        Raises CameraError after max_read_failures empty reads in a row (camera unplugged
        or taken by another app), so callers never spin forever.
        """
        if self._cap is None:
            raise CameraError("Camera is not open")
        ok, raw = self._cap.read()
        if not ok or raw is None:
            self._failures += 1
            if self._failures >= self.max_read_failures:
                raise CameraError(
                    f"Camera {self.index} not responding: no frame {self._failures} times in a row. "
                    "Is it unplugged or in use by another app?"
                )
            return None
        self._failures = 0
        # OpenCV's stubs type frames loosely; camera frames are uint8, so this never copies.
        image = np.asarray(cv2.flip(self._fit(np.asarray(raw, dtype=np.uint8)), 1), dtype=np.uint8)
        ts = max(int(time.monotonic() * 1000), self._last_ts + 1)
        self._last_ts = ts
        return Frame(image=image, timestamp_ms=ts)

    def _fit(self, image: npt.NDArray[np.uint8]) -> npt.NDArray[np.uint8]:
        """Centre-crop to the target aspect ratio, then resize. Never stretches the image,
        because stretching would distort shoulder width, face width and head yaw."""
        h, w = image.shape[:2]
        if (w, h) == (self.width, self.height):
            return image
        if self._warned_size != (w, h):
            self._warned_size = (w, h)
            log.warning(
                "Camera %d gives %dx%d instead of %dx%d; centre-cropping to fit",
                self.index, w, h, self.width, self.height,
            )
        target = self.width / self.height
        if w / h > target:  # too wide: trim the sides
            crop_w = round(h * target)
            x0 = (w - crop_w) // 2
            image = image[:, x0:x0 + crop_w]
        elif w / h < target:  # too tall: trim top and bottom
            crop_h = round(w / target)
            y0 = (h - crop_h) // 2
            image = image[y0:y0 + crop_h, :]
        return np.asarray(cv2.resize(image, (self.width, self.height)), dtype=np.uint8)

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
