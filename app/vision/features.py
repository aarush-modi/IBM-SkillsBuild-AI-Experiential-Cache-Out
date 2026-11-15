"""Builds and smooths FrameFeatures from landmarker and YOLO output (DESIGN §5, steps 6 and 7).

Pure numpy: no OpenCV, MediaPipe or Ultralytics here, so the geometry is unit-tested with
synthetic landmarks. landmarkers.py converts MediaPipe results into RawLandmarks.

Units: landmark x and y arrive normalized to 0..1 on each axis. Every distance is converted
to frame-width units first (y scaled by height / width), so a distance means the same in
both directions. Boxes stay normalized 0..1 on each axis, as in contracts.BBox.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import numpy.typing as npt

from app.contracts import BBox, Detection, FrameFeatures, HandInfo

FloatArray = npt.NDArray[np.float64]

# PoseLandmarker indices (33-point BlazePose topology).
NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR = 0, 2, 5, 7, 8
LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST = 11, 12, 13, 14, 15, 16
POSE_KEEP = (NOSE, LEFT_EYE, RIGHT_EYE, LEFT_EAR, RIGHT_EAR,
             LEFT_SHOULDER, RIGHT_SHOULDER, LEFT_ELBOW, RIGHT_ELBOW, LEFT_WRIST, RIGHT_WRIST)

# FaceLandmarker indices: the outer cheek points, used for face width.
FACE_LEFT_CHEEK, FACE_RIGHT_CHEEK = 234, 454

# HandLandmarker indices.
HAND_WRIST = 0
FINGER_MCP = (5, 9, 13, 17)   # knuckles of index, middle, ring, little finger
FINGER_TIP = (8, 12, 16, 20)


@dataclass(frozen=True)
class RawHand:
    image: FloatArray   # (21, 3): x, y normalized to the image, z relative depth
    world: FloatArray   # (21, 3): metres, origin at the hand's centre


@dataclass(frozen=True)
class RawLandmarks:
    """One frame of landmarker output as plain arrays. None means nothing was detected."""
    pose: FloatArray | None = None          # (33, 4): x, y, z, visibility
    face: FloatArray | None = None          # (478, 3): x, y, z
    face_matrix: FloatArray | None = None   # (4, 4) facial transformation matrix
    hands: list[RawHand] = field(default_factory=list)


# --- geometry -------------------------------------------------------------------------

def _to_width_units(xy: FloatArray, aspect: float) -> FloatArray:
    """Scale y by height / width so x and y share one unit."""
    out = np.array(xy[..., :2], dtype=np.float64)
    out[..., 1] *= aspect
    return out


def head_angles(matrix: FloatArray) -> tuple[float, float, float]:
    """Yaw, pitch and roll in degrees from MediaPipe's facial transformation matrix.

    The matrix maps the canonical face (x right, y up, z out of the face) into camera
    space (y up, camera looking down -z), so a face looking straight at the camera gives
    the identity rotation. Decomposed as R = Ry(yaw) · Rx(pitch) · Rz(roll).

    Signs (the image is already mirrored): yaw > 0 when the nose turns toward image right,
    which is the user's right; pitch < 0 when looking down; roll > 0 when the head tips so
    the image-right side of the face rises.
    """
    r = np.asarray(matrix, dtype=np.float64)[:3, :3]
    norms = np.linalg.norm(r, axis=0)
    r = r / np.where(norms > 0, norms, 1.0)  # strip any scale
    yaw = math.atan2(r[0, 2], r[2, 2])
    x_rot = math.asin(max(-1.0, min(1.0, -r[1, 2])))  # rotation about x: positive tips the nose down
    roll = math.atan2(r[1, 0], r[1, 1])
    return math.degrees(yaw), -math.degrees(x_rot), math.degrees(roll)


@dataclass(frozen=True)
class ShoulderMetrics:
    width: float
    angle: float               # degrees; positive when the image-right shoulder is higher
    mid: tuple[float, float]   # midpoint, frame-width units
    nose_to_shoulder_y: float  # gap from nose up to shoulder midpoint, / shoulder width
    visibility: float          # lower of the two shoulders


def shoulder_metrics(pose: FloatArray, aspect: float) -> ShoulderMetrics | None:
    pts = _to_width_units(pose, aspect)
    # Order by x rather than by MediaPipe's left/right label, so mirroring can't flip the sign.
    a, b = sorted((pts[LEFT_SHOULDER], pts[RIGHT_SHOULDER]), key=lambda p: float(p[0]))
    width = float(np.linalg.norm(b - a))
    if width <= 0:
        return None
    angle = math.degrees(math.atan2(-(b[1] - a[1]), b[0] - a[0]))  # image y points down
    mid = (float(a[0] + b[0]) / 2, float(a[1] + b[1]) / 2)
    gap = (mid[1] - float(pts[NOSE][1])) / width
    vis = float(min(pose[LEFT_SHOULDER, 3], pose[RIGHT_SHOULDER, 3]))
    return ShoulderMetrics(width=width, angle=angle, mid=mid, nose_to_shoulder_y=gap, visibility=vis)


def face_width(face: FloatArray, aspect: float) -> float:
    """Cheek-to-cheek distance in 3D, in frame-width units.

    FaceLandmarker's z uses roughly the same scale as x, so including it makes the width
    nearly independent of head turn: turning the head shortens the on-image width but
    lengthens the depth difference. Only moving toward or away from the camera changes it,
    which is what the leaning-in metric needs.
    """
    pts = np.column_stack([_to_width_units(face, aspect), face[:, 2]])
    return float(np.linalg.norm(pts[FACE_RIGHT_CHEEK] - pts[FACE_LEFT_CHEEK]))


def points_bbox(points: FloatArray) -> BBox:
    """Box around normalized landmark points, clamped to the frame."""
    xy = np.clip(points[:, :2], 0.0, 1.0)
    x0, y0 = xy.min(axis=0)
    x1, y1 = xy.max(axis=0)
    return float(x0), float(y0), float(x1), float(y1)


def hand_bbox(hand: RawHand) -> BBox:
    return points_bbox(hand.image)


def curl_ratio(world: FloatArray) -> float:
    """Mean fingertip-to-wrist / knuckle-to-wrist distance over four fingers.

    About 1.8 for an open hand, under 1 for a fist. 3D world landmarks make it independent
    of which way the hand faces the camera.
    """
    wrist = world[HAND_WRIST]
    ratios = []
    for mcp, tip in zip(FINGER_MCP, FINGER_TIP):
        knuckle = float(np.linalg.norm(world[mcp] - wrist))
        if knuckle > 0:
            ratios.append(float(np.linalg.norm(world[tip] - wrist)) / knuckle)
    return sum(ratios) / len(ratios) if ratios else math.inf


def hand_info(hand: RawHand, grasp_curl_ratio: float) -> HandInfo:
    return HandInfo(bbox=hand_bbox(hand), grasp=curl_ratio(hand.world) < grasp_curl_ratio)


def build_features(
    raw: RawLandmarks,
    objects: list[Detection],
    t: float,
    aspect: float,
    grasp_curl_ratio: float,
) -> FrameFeatures:
    """Unsmoothed FrameFeatures for one frame. aspect is image height / width."""
    sm = shoulder_metrics(raw.pose, aspect) if raw.pose is not None else None
    yaw = pitch = roll = None
    if raw.face_matrix is not None:
        yaw, pitch, roll = head_angles(raw.face_matrix)
    return FrameFeatures(
        t=t,
        person_present=raw.pose is not None,
        shoulder_visibility=sm.visibility if sm else None,
        head_yaw=yaw,
        head_pitch=pitch,
        head_roll=roll,
        shoulder_width=sm.width if sm else None,
        shoulder_angle=sm.angle if sm else None,
        shoulder_mid=sm.mid if sm else None,
        nose_to_shoulder_y=sm.nose_to_shoulder_y if sm else None,
        face_width=face_width(raw.face, aspect) if raw.face is not None else None,
        face_bbox=points_bbox(raw.face) if raw.face is not None else None,
        hands=[hand_info(h, grasp_curl_ratio) for h in raw.hands],
        objects=list(objects),
    )


# --- smoothing ------------------------------------------------------------------------

SMOOTHED_FIELDS = (
    "shoulder_visibility", "head_yaw", "head_pitch", "head_roll",
    "shoulder_width", "shoulder_angle", "nose_to_shoulder_y", "face_width",
)
SMOOTHED_POINTS = ("shoulder_mid",)  # (x, y) pairs, each coordinate averaged on its own


class FeatureSmoother:
    """Exponential moving average on the numeric fields of FrameFeatures (DESIGN §5, step 7).

    A field that becomes None is passed through as None and its average restarts when it
    comes back, so a value from before the user left never leaks into a new reading.
    Boolean smoothing of detector signals is done in app/logic, not here.
    """

    def __init__(self, alpha: float) -> None:
        self.alpha = alpha
        self._state: dict[str, float] = {}
        self._points: dict[str, tuple[float, float]] = {}

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> FeatureSmoother:
        return cls(settings["smoothing"]["ema_alpha"])

    def reset(self) -> None:
        self._state.clear()
        self._points.clear()

    def _ema(self, prev: float | None, value: float) -> float:
        return value if prev is None else prev + self.alpha * (value - prev)

    def update(self, f: FrameFeatures) -> FrameFeatures:
        smoothed: dict[str, float | tuple[float, float] | None] = {}
        for name in SMOOTHED_FIELDS:
            value: float | None = getattr(f, name)
            if value is None:
                self._state.pop(name, None)
                smoothed[name] = None
                continue
            new = self._ema(self._state.get(name), value)
            self._state[name] = new
            smoothed[name] = new
        for name in SMOOTHED_POINTS:
            point: tuple[float, float] | None = getattr(f, name)
            if point is None:
                self._points.pop(name, None)
                smoothed[name] = None
                continue
            prev_pt = self._points.get(name)
            new_pt = (
                self._ema(prev_pt[0] if prev_pt else None, point[0]),
                self._ema(prev_pt[1] if prev_pt else None, point[1]),
            )
            self._points[name] = new_pt
            smoothed[name] = new_pt
        return replace(f, **smoothed)  # type: ignore[arg-type]
