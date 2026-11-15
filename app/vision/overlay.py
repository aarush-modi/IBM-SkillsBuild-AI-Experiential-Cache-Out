"""Draws the skeleton, hands and object boxes from a PreviewFrame onto a copy of its image.

Used by scripts/camera_check.py, and by the session screen before handing the image to Qt.
Drawing happens on an in-memory copy; nothing is written to disk.
"""

from __future__ import annotations

from collections.abc import Iterable

import cv2
import numpy as np
import numpy.typing as npt

from app.vision.features import (
    LEFT_EAR, LEFT_ELBOW, LEFT_EYE, LEFT_SHOULDER, LEFT_WRIST, NOSE,
    RIGHT_EAR, RIGHT_ELBOW, RIGHT_EYE, RIGHT_SHOULDER, RIGHT_WRIST,
)
from app.vision.pipeline import PreviewFrame

Color = tuple[int, int, int]  # BGR

POSE_CONNECTIONS = (
    (LEFT_SHOULDER, RIGHT_SHOULDER),
    (LEFT_SHOULDER, LEFT_ELBOW), (LEFT_ELBOW, LEFT_WRIST),
    (RIGHT_SHOULDER, RIGHT_ELBOW), (RIGHT_ELBOW, RIGHT_WRIST),
    (NOSE, LEFT_EYE), (LEFT_EYE, LEFT_EAR), (NOSE, RIGHT_EYE), (RIGHT_EYE, RIGHT_EAR),
)
HAND_CONNECTIONS = (
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
    (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
)

GREEN: Color = (80, 200, 80)
AMBER: Color = (0, 170, 255)
GREY: Color = (150, 150, 150)
CYAN: Color = (220, 200, 0)

_HEAD_LINES = ((NOSE, LEFT_EYE), (LEFT_EYE, LEFT_EAR), (NOSE, RIGHT_EYE), (RIGHT_EYE, RIGHT_EAR))
_SHOULDER_LINE = ((LEFT_SHOULDER, RIGHT_SHOULDER),)

# Which skeleton lines show each posture issue (names from app/logic/posture.py).
ISSUE_LINES: dict[str, tuple[tuple[int, int], ...]] = {
    "slouching": _HEAD_LINES + _SHOULDER_LINE,
    "leaning_in": _HEAD_LINES,
    "neck_down": _HEAD_LINES,
    "head_tilt": _HEAD_LINES,
    "uneven_shoulders": _SHOULDER_LINE,
}


def posture_line_colors(issues: Iterable[str]) -> dict[tuple[int, int], Color]:
    """Amber for the lines of each posture issue past its threshold; the rest stay green."""
    return {line: AMBER for issue in issues for line in ISSUE_LINES.get(issue, ())}


def draw_overlay(
    preview: PreviewFrame,
    line_colors: dict[tuple[int, int], Color] | None = None,
    min_visibility: float = 0.0,
) -> npt.NDArray[np.uint8]:
    """A copy of the preview image with the overlay drawn on it.

    line_colors lets the caller colour a pose connection by its posture metric (green or
    amber); unlisted connections are green. Joints under min_visibility are skipped.
    """
    img = preview.image.copy()
    h, w = img.shape[:2]

    def px(x: float, y: float) -> tuple[int, int]:
        return int(x * w), int(y * h)

    colors = line_colors or {}
    for a, b in POSE_CONNECTIONS:
        pa, pb = preview.pose.get(a), preview.pose.get(b)
        if pa is None or pb is None or min(pa[2], pb[2]) < min_visibility:
            continue
        cv2.line(img, px(pa[0], pa[1]), px(pb[0], pb[1]), colors.get((a, b), GREEN), 2, cv2.LINE_AA)
    for x, y, vis in preview.pose.values():
        if vis >= min_visibility:
            cv2.circle(img, px(x, y), 3, GREEN, -1, cv2.LINE_AA)

    for hand in preview.hands:
        for a, b in HAND_CONNECTIONS:
            cv2.line(img, px(*hand[a]), px(*hand[b]), CYAN, 1, cv2.LINE_AA)

    for d in preview.objects:
        x0, y0, x1, y1 = d.bbox
        cv2.rectangle(img, px(x0, y0), px(x1, y1), AMBER, 1)
        cv2.putText(img, f"{d.cls} {d.confidence:.2f}", px(x0, y0 - 0.01),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, AMBER, 1, cv2.LINE_AA)
    return np.asarray(img, dtype=np.uint8)
