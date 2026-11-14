"""Feature geometry and smoothing with synthetic landmarks: no camera or models needed."""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.contracts import Detection
from app.storage.settings import DEFAULTS
from app.vision import features as F
from app.vision.features import RawHand, RawLandmarks

GRASP = DEFAULTS["vision"]["grasp_curl_ratio"]
ASPECT = 480 / 640


def rot_x(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)], [0, math.sin(a), math.cos(a)]])


def rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), 0, math.sin(a)], [0, 1, 0], [-math.sin(a), 0, math.cos(a)]])


def rot_z(deg: float) -> np.ndarray:
    a = math.radians(deg)
    return np.array([[math.cos(a), -math.sin(a), 0], [math.sin(a), math.cos(a), 0], [0, 0, 1]])


def matrix(r: np.ndarray, scale: float = 1.0) -> np.ndarray:
    m = np.eye(4)
    m[:3, :3] = r * scale
    m[:3, 3] = (0.5, -1.0, -40.0)  # translation must not matter
    return m


def pose(nose=(0.5, 0.35), left=(0.65, 0.6), right=(0.35, 0.6), vis=(0.99, 0.98)) -> np.ndarray:
    p = np.zeros((33, 4))
    p[:, 3] = 0.9
    p[F.NOSE, :2] = nose
    p[F.LEFT_SHOULDER, :2] = left
    p[F.RIGHT_SHOULDER, :2] = right
    p[F.LEFT_SHOULDER, 3], p[F.RIGHT_SHOULDER, 3] = vis
    return p


def hand(curled: bool, centre=(0.5, 0.8)) -> RawHand:
    """A hand in metres: knuckles 9 cm from the wrist, tips straight out or folded back."""
    world = np.zeros((21, 3))
    for k, (mcp, tip) in enumerate(zip(F.FINGER_MCP, F.FINGER_TIP)):
        x = (k - 1.5) * 0.02
        world[mcp] = (x, -0.09, 0)
        world[tip] = (x, -0.07, 0.03) if curled else (x, -0.165, 0)
    image = np.zeros((21, 3))
    image[:, 0] = centre[0] + np.linspace(-0.05, 0.05, 21)
    image[:, 1] = centre[1] + np.linspace(-0.04, 0.04, 21)
    return RawHand(image=image, world=world)


# --- head pose --------------------------------------------------------------------------

def test_facing_camera_is_zero() -> None:
    assert F.head_angles(matrix(np.eye(3))) == pytest.approx((0, 0, 0), abs=1e-9)


def test_nose_tipping_down_is_negative_pitch() -> None:
    # Positive rotation about x moves the nose (0, 0, 1) toward -y: looking down.
    nose = rot_x(20) @ np.array([0, 0, 1])
    assert nose[1] < 0
    yaw, pitch, roll = F.head_angles(matrix(rot_x(20)))
    assert pitch == pytest.approx(-20)
    assert yaw == pytest.approx(0, abs=1e-9) and roll == pytest.approx(0, abs=1e-9)


@pytest.mark.parametrize("yaw,pitch,roll", [(30, 0, 0), (-40, 10, 0), (25, -15, 8), (0, 0, -12)])
def test_combined_rotation_round_trips(yaw: float, pitch: float, roll: float) -> None:
    r = rot_y(yaw) @ rot_x(-pitch) @ rot_z(roll)
    assert F.head_angles(matrix(r)) == pytest.approx((yaw, pitch, roll))


def test_scale_in_matrix_is_ignored() -> None:
    r = rot_y(20) @ rot_x(-10)
    assert F.head_angles(matrix(r, scale=1.7)) == pytest.approx(F.head_angles(matrix(r)))


# --- shoulders and face -------------------------------------------------------------------

def test_level_shoulders() -> None:
    m = F.shoulder_metrics(pose(), ASPECT)
    assert m is not None
    assert m.width == pytest.approx(0.3)
    assert m.angle == pytest.approx(0)
    # Nose 0.25 of frame height above the shoulders = 0.1875 frame widths, / 0.3 width.
    assert m.nose_to_shoulder_y == pytest.approx(0.25 * ASPECT / 0.3)
    assert m.visibility == pytest.approx(0.98)


def test_shoulder_angle_sign_ignores_left_right_labels() -> None:
    raised_right = F.shoulder_metrics(pose(left=(0.35, 0.6), right=(0.65, 0.55)), ASPECT)
    swapped = F.shoulder_metrics(pose(left=(0.65, 0.55), right=(0.35, 0.6)), ASPECT)
    assert raised_right is not None and swapped is not None
    assert raised_right.angle > 0
    assert raised_right.angle == pytest.approx(swapped.angle)
    assert raised_right.angle == pytest.approx(math.degrees(math.atan2(0.05 * ASPECT, 0.3)))


def test_slouching_shrinks_the_gap() -> None:
    upright = F.shoulder_metrics(pose(nose=(0.5, 0.35)), ASPECT)
    slouched = F.shoulder_metrics(pose(nose=(0.5, 0.45)), ASPECT)
    assert upright is not None and slouched is not None
    assert slouched.nose_to_shoulder_y < upright.nose_to_shoulder_y


def test_coincident_shoulders_give_none() -> None:
    assert F.shoulder_metrics(pose(left=(0.5, 0.6), right=(0.5, 0.6)), ASPECT) is None


def test_face_width_uses_cheek_points_in_width_units() -> None:
    face = np.zeros((478, 3))
    face[F.FACE_LEFT_CHEEK, :2] = (0.4, 0.4)
    face[F.FACE_RIGHT_CHEEK, :2] = (0.6, 0.4)
    assert F.face_width(face, ASPECT) == pytest.approx(0.2)
    face[F.FACE_RIGHT_CHEEK, :2] = (0.4, 0.6)  # vertical: 0.2 of height = 0.15 of width
    assert F.face_width(face, ASPECT) == pytest.approx(0.15)


# --- hands ---------------------------------------------------------------------------------

def test_open_hand_and_fist_curl_ratios() -> None:
    assert F.curl_ratio(hand(curled=False).world) > GRASP
    assert F.curl_ratio(hand(curled=True).world) < GRASP


def test_hand_bbox_is_clamped() -> None:
    h = hand(curled=False, centre=(0.98, 0.98))
    x0, y0, x1, y1 = F.hand_bbox(h)
    assert (x1, y1) == (1.0, 1.0) and x0 < x1 and y0 < y1


def test_near_keyboard_needs_a_work_zone() -> None:
    h = hand(curled=False, centre=(0.5, 0.8))
    assert not F.hand_info(h, GRASP, None).near_keyboard
    assert F.hand_info(h, GRASP, (0.3, 0.7, 0.7, 0.95)).near_keyboard
    assert not F.hand_info(h, GRASP, (0.0, 0.0, 0.3, 0.3)).near_keyboard


# --- build_features --------------------------------------------------------------------------

def test_nobody_in_frame() -> None:
    f = F.build_features(RawLandmarks(), [], t=1.5, aspect=ASPECT, grasp_curl_ratio=GRASP)
    assert f.t == 1.5 and not f.person_present
    assert f.shoulder_visibility is None and f.head_yaw is None and f.face_width is None
    assert f.hands == [] and f.objects == []


def test_full_frame() -> None:
    face = np.zeros((478, 3))
    face[F.FACE_RIGHT_CHEEK, 0] = 0.2
    phone = Detection(cls="cell phone", confidence=0.8, bbox=(0.4, 0.7, 0.5, 0.9))
    raw = RawLandmarks(pose=pose(), face=face, face_matrix=matrix(rot_x(20)), hands=[hand(curled=True)])

    f = F.build_features(raw, [phone], t=2.0, aspect=ASPECT, grasp_curl_ratio=GRASP)

    assert f.person_present and f.shoulder_visibility == pytest.approx(0.98)
    assert f.head_pitch == pytest.approx(-20)
    assert f.shoulder_width == pytest.approx(0.3) and f.face_width == pytest.approx(0.2)
    assert len(f.hands) == 1 and f.hands[0].grasp
    assert f.objects == [phone]


def test_pose_without_face_has_no_head_angles() -> None:
    f = F.build_features(RawLandmarks(pose=pose()), [], t=0, aspect=ASPECT, grasp_curl_ratio=GRASP)
    assert f.person_present and f.shoulder_width is not None
    assert f.head_yaw is None and f.face_width is None


# --- smoothing --------------------------------------------------------------------------------

def _f(t: float, yaw: float | None) -> F.FrameFeatures:
    return F.FrameFeatures(
        t=t, person_present=yaw is not None, shoulder_visibility=None, head_yaw=yaw, head_pitch=None,
        head_roll=None, shoulder_width=None, shoulder_angle=None, nose_to_shoulder_y=None,
        face_width=None, hands=[], objects=[],
    )


def test_ema_follows_alpha() -> None:
    s = F.FeatureSmoother(alpha=0.3)
    assert s.update(_f(0, 0.0)).head_yaw == 0.0
    assert s.update(_f(1, 10.0)).head_yaw == pytest.approx(3.0)
    assert s.update(_f(2, 10.0)).head_yaw == pytest.approx(5.1)


def test_ema_restarts_after_a_gap() -> None:
    s = F.FeatureSmoother(alpha=0.3)
    s.update(_f(0, 40.0))
    assert s.update(_f(1, None)).head_yaw is None
    assert s.update(_f(2, 0.0)).head_yaw == 0.0  # no leftover from before the gap


def test_smoother_keeps_non_numeric_fields() -> None:
    f = _f(3.0, 5.0)
    out = F.FeatureSmoother.from_settings(DEFAULTS).update(f)
    assert out.t == 3.0 and out.person_present and out.hands is f.hands
