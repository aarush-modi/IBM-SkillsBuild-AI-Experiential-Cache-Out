"""Calibration steps fed with synthetic FrameFeatures (DESIGN §7)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import pytest

from app.contracts import FrameFeatures, HandInfo
from app.logic import calibration as C
from app.storage.settings import DEFAULTS

FPS = 15


def settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def feat(t: float, **kw: Any) -> FrameFeatures:
    base: dict[str, Any] = dict(
        t=t, person_present=True, shoulder_visibility=0.95,
        head_yaw=2.0, head_pitch=-5.0, head_roll=1.0,
        shoulder_width=0.3, shoulder_angle=0.5, shoulder_mid=(0.5, 0.45),
        nose_to_shoulder_y=0.8, face_width=0.2,
        hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


def hands(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> list[HandInfo]:
    return [HandInfo(bbox=left, grasp=False, near_keyboard=False), HandInfo(bbox=right, grasp=False, near_keyboard=False)]


def run(step: C._Step[Any], seconds: float, make: Any = None) -> None:
    """Feed frames at FPS from t=100 until the step is done (or `seconds` pass)."""
    n = int(seconds * FPS) + 1
    for i in range(n):
        t = 100 + i / FPS
        step.add(make(i, t) if make else feat(t))
        if step.done():
            return


def baseline() -> C.Baseline:
    step = C.UprightStep(settings())
    run(step, 10)
    result = step.result()
    assert result.value is not None
    return result.value


# --- upright ---------------------------------------------------------------------------

def test_upright_stores_medians_after_its_duration() -> None:
    step = C.UprightStep(settings())
    jitter = [-1.0, 0.0, 1.0]

    def make(i: int, t: float) -> FrameFeatures:
        j = jitter[i % 3]
        return feat(t, head_yaw=2.0 + j, nose_to_shoulder_y=0.8 + j / 100, shoulder_mid=(0.5 + j / 100, 0.45))

    run(step, 20, make)

    assert step.done() and step.progress == 1.0
    assert step.elapsed_s == pytest.approx(10.0)
    r = step.result()
    assert r.passed and r.reason is None and r.value is not None
    assert r.value.head_yaw == pytest.approx(2.0)
    assert r.value.nose_to_shoulder_y == pytest.approx(0.8)
    assert r.value.shoulder_mid == pytest.approx((0.5, 0.45))
    assert r.value.head_pitch == -5.0 and r.value.face_width == 0.2


def test_not_done_before_duration() -> None:
    step = C.UprightStep(settings())
    run(step, 5)
    assert not step.done()
    assert step.progress == pytest.approx(0.5)


def test_upright_fails_when_shoulders_are_hidden() -> None:
    step = C.UprightStep(settings())
    run(step, 10, lambda i, t: feat(t, shoulder_visibility=0.3 if i % 2 else 0.9))
    r = step.result()
    assert not r.passed and r.reason == C.NO_SHOULDERS


def test_upright_fails_with_no_face() -> None:
    step = C.UprightStep(settings())
    run(step, 10, lambda i, t: feat(t, head_yaw=None, head_pitch=None, head_roll=None, face_width=None))
    assert step.result().reason == C.NO_FACE


def test_upright_fails_when_nobody_is_there() -> None:
    step = C.UprightStep(settings())
    run(step, 10, lambda i, t: feat(t, person_present=False, shoulder_visibility=None))
    assert step.result().reason == C.NO_PERSON


def test_upright_tolerates_a_few_bad_frames() -> None:
    step = C.UprightStep(settings())
    # 1 frame in 10 unusable: 90% valid, above the 80% default.
    run(step, 10, lambda i, t: feat(t, person_present=i % 10 != 0))
    assert step.result().passed


def test_min_valid_ratio_comes_from_settings() -> None:
    s = settings()
    s["calibration"]["min_valid_ratio"] = 0.95
    step = C.UprightStep(s)
    run(step, 10, lambda i, t: feat(t, person_present=i % 10 != 0))
    assert not step.result().passed


def test_frames_after_done_are_ignored() -> None:
    step = C.UprightStep(settings())
    run(step, 10)
    step.add(feat(500, person_present=False))
    assert step.result().passed and step.elapsed_s == pytest.approx(10.0)


# --- window ----------------------------------------------------------------------------

def test_window_yaw_is_stored() -> None:
    step = C.WindowStep(settings(), baseline())
    run(step, 3, lambda i, t: feat(t, head_yaw=60.0))
    r = step.result()
    assert r.passed and r.value == pytest.approx(60.0)


def test_window_too_close_to_screen_fails() -> None:
    b = baseline()
    step = C.WindowStep(settings(), b)
    run(step, 3, lambda i, t: feat(t, head_yaw=b.head_yaw + DEFAULTS["detectors"]["look_yaw_deg"] - 1))
    r = step.result()
    assert not r.passed and r.reason == C.WINDOW_TOO_CLOSE


# --- work zone ---------------------------------------------------------------------------

def test_work_zone_is_padded_box_around_both_hands() -> None:
    step = C.WorkZoneStep(settings())
    run(step, 3, lambda i, t: feat(t, hands=hands((0.3, 0.7, 0.4, 0.8), (0.6, 0.72, 0.7, 0.82))))
    r = step.result()
    assert r.passed and r.value is not None
    # Box (0.3, 0.7)-(0.7, 0.82): 0.4 x 0.12, grown 30% about the centre (0.5, 0.76).
    assert r.value == pytest.approx((0.24, 0.682, 0.76, 0.838))


def test_work_zone_needs_both_hands() -> None:
    step = C.WorkZoneStep(settings())
    one = [HandInfo(bbox=(0.3, 0.7, 0.4, 0.8), grasp=False, near_keyboard=False)]
    run(step, 3, lambda i, t: feat(t, hands=one))
    r = step.result()
    assert not r.passed and r.reason == C.NO_HANDS


def test_pad_box_is_clamped_to_frame() -> None:
    assert C.pad_box((0.0, 0.8, 0.5, 1.0), 0.3) == pytest.approx((0.0, 0.77, 0.575, 1.0))


# --- camera shift check ---------------------------------------------------------------------

def test_camera_not_moved() -> None:
    check = C.CameraShiftCheck(settings(), baseline())
    run(check, 3, lambda i, t: feat(t, shoulder_mid=(0.55, 0.45)))
    r = check.result()
    assert r.passed and r.value is False


def test_camera_moved() -> None:
    check = C.CameraShiftCheck(settings(), baseline())
    run(check, 3, lambda i, t: feat(t, shoulder_mid=(0.5 + 0.16, 0.45)))
    assert check.result().value is True


def test_camera_check_inconclusive_when_user_absent() -> None:
    check = C.CameraShiftCheck(settings(), baseline())
    run(check, 3, lambda i, t: feat(t, person_present=False, shoulder_mid=None))
    r = check.result()
    assert not r.passed and r.reason == C.NO_PERSON


# --- Calibration ------------------------------------------------------------------------------

def test_calibration_round_trips_through_json() -> None:
    cal = C.Calibration(baseline=baseline(), window_yaw=55.0, work_zone=(0.2, 0.6, 0.8, 0.9))
    again = C.Calibration.from_dict(json.loads(json.dumps(cal.to_dict())))
    assert again == cal
    skipped = replace(cal, window_yaw=None)
    assert C.Calibration.from_dict(json.loads(json.dumps(skipped.to_dict()))) == skipped
