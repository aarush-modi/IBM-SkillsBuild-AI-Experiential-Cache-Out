"""Calibration steps fed with synthetic FrameFeatures (DESIGN §7)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

import pytest

from app.contracts import FrameFeatures
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
        nose_to_shoulder_y=0.8, face_width=0.2, face_bbox=(0.42, 0.2, 0.58, 0.42),
        hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


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


def test_window_waits_for_the_turn_before_timing() -> None:
    b = baseline()
    step = C.WindowStep(settings(), b)
    # Still facing the screen (reading the instruction): the clock doesn't start.
    run(step, 5, lambda i, t: feat(t, head_yaw=b.head_yaw + 5))
    assert step.waiting and not step.done() and step.progress == 0.0
    # Turned: now it times 3 s and passes.
    for i in range(3 * 15 + 1):
        step.add(feat(200 + i / 15, head_yaw=b.head_yaw + 50))
    assert not step.waiting and step.done()
    assert step.result().value == pytest.approx(b.head_yaw + 50)


def test_window_turning_back_too_soon_fails_with_measured_angle() -> None:
    b = baseline()
    step = C.WindowStep(settings(), b)
    # Turns past the threshold for one frame, then mostly back toward the screen.
    run(step, 3, lambda i, t: feat(t, head_yaw=b.head_yaw + (40 if i == 0 else 12)))
    r = step.result()
    assert not r.passed and r.reason is not None
    # The message reports what was measured, so a failing setup can be diagnosed.
    assert r.reason.startswith("Your head turned only 12° from the screen; it needs more than 25°.")


def test_window_face_lost_while_turned() -> None:
    b = baseline()
    step = C.WindowStep(settings(), b)
    run(step, 3, lambda i, t: feat(t, head_yaw=b.head_yaw + 40 if i == 0 else None))
    assert step.result().reason == C.WINDOW_FACE_LOST


def test_window_to_the_other_side_also_counts() -> None:
    b = baseline()
    step = C.WindowStep(settings(), b)
    run(step, 3, lambda i, t: feat(t, head_yaw=b.head_yaw - 50))
    assert step.result().value == pytest.approx(b.head_yaw - 50)


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
    cal = C.Calibration(baseline=baseline(), window_yaw=55.0)
    again = C.Calibration.from_dict(json.loads(json.dumps(cal.to_dict())))
    assert again == cal
    skipped = replace(cal, window_yaw=None)
    assert C.Calibration.from_dict(json.loads(json.dumps(skipped.to_dict()))) == skipped


def test_older_calibrations_must_be_redone() -> None:
    d = C.Calibration(baseline=baseline(), window_yaw=None).to_dict()
    assert d["version"] == C.CALIBRATION_VERSION
    old = {k: v for k, v in d.items() if k != "version"}  # saved before versioning
    old["work_zone"] = [0.2, 0.6, 0.8, 0.9]
    with pytest.raises(C.OutdatedCalibration):
        C.Calibration.from_dict(old)
