"""Head rotation relative to the calibrated pose, so an angled camera doesn't skew it."""

from __future__ import annotations

import pytest

from app.logic.head_pose import _mul, relative_angles, to_angles, to_matrix


@pytest.mark.parametrize("angles", [(0, 0, 0), (30, -10, 5), (-45, 20, -8), (10, -35, 0)])
def test_matrix_round_trip(angles: tuple[float, float, float]) -> None:
    assert to_angles(to_matrix(angles)) == pytest.approx(angles)


def test_same_pose_is_zero() -> None:
    assert relative_angles((25, -12, 4), (25, -12, 4)) == pytest.approx((0, 0, 0), abs=1e-9)


def test_square_camera_matches_simple_differences() -> None:
    assert relative_angles((0, 0, 0), (0, -20, 0)) == pytest.approx((0, -20, 0))
    assert relative_angles((0, 0, 0), (0, 0, 12)) == pytest.approx((0, 0, 12))


def test_head_turn_under_angled_camera_is_pure_yaw() -> None:
    # Camera above and to the side of the screen: at calibration it sees the head
    # yawed 30° and pitched 20° down.
    camera = to_matrix((30, -20, 0))
    head_turn = to_matrix((30, 0, 0))  # user turns 30° to read the other side of the screen
    now = to_angles(_mul(camera, head_turn))
    base = to_angles(camera)

    naive_roll = now[2] - base[2]
    assert abs(naive_roll) > 8  # subtracting angles reports a tilt that isn't there
    yaw, pitch, roll = relative_angles(base, now)
    assert (yaw, pitch, roll) == pytest.approx((30, 0, 0), abs=1e-6)


def test_nod_under_angled_camera_is_pure_pitch() -> None:
    camera = to_matrix((30, -20, 0))
    nod = to_matrix((0, -25, 0))
    now = to_angles(_mul(camera, nod))
    assert relative_angles(to_angles(camera), now) == pytest.approx((0, -25, 0), abs=1e-6)
