"""Head rotation relative to the calibrated head pose, independent of camera angle.

FrameFeatures carries head yaw, pitch and roll relative to the camera (vision/features.py:
R = Ry(yaw) · Rx(-pitch) · Rz(roll), with pitch negative when looking down). Subtracting
baseline angles one by one is only right when the camera faces the user squarely. With a
camera above or beside the screen, an ordinary head turn shows up partly as pitch or roll.

relative_angles() rebuilds both rotations, takes R_rel = R_baseᵀ · R_now (the head's rotation
expressed in its own calibrated frame) and decomposes that instead. A head turn is then pure
yaw and a nod pure pitch, whatever the camera angle. Stdlib only.
"""

from __future__ import annotations

import math

Matrix = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]
Angles = tuple[float, float, float]  # yaw, pitch, roll in degrees (pitch < 0 looking down)


def _rx(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return ((1, 0, 0), (0, c, -s), (0, s, c))


def _ry(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return ((c, 0, s), (0, 1, 0), (-s, 0, c))


def _rz(a: float) -> Matrix:
    c, s = math.cos(a), math.sin(a)
    return ((c, -s, 0), (s, c, 0), (0, 0, 1))


def _mul(a: Matrix, b: Matrix) -> Matrix:
    return tuple(  # type: ignore[return-value]
        tuple(sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)) for i in range(3)
    )


def _t(a: Matrix) -> Matrix:
    return tuple(tuple(a[j][i] for j in range(3)) for i in range(3))  # type: ignore[return-value]


def to_matrix(angles: Angles) -> Matrix:
    yaw, pitch, roll = (math.radians(x) for x in angles)
    return _mul(_mul(_ry(yaw), _rx(-pitch)), _rz(roll))


def to_angles(r: Matrix) -> Angles:
    yaw = math.atan2(r[0][2], r[2][2])
    x_rot = math.asin(max(-1.0, min(1.0, -r[1][2])))
    roll = math.atan2(r[1][0], r[1][1])
    return math.degrees(yaw), -math.degrees(x_rot), math.degrees(roll)


def relative_angles(baseline: Angles, now: Angles) -> Angles:
    """Yaw, pitch and roll of the head now, measured in the calibrated head's own frame."""
    return to_angles(_mul(_t(to_matrix(baseline)), to_matrix(now)))
