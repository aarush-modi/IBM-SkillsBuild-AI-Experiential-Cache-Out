"""Posture scoring, bad window, tips, alert timing and samples (DESIGN §7)."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.contracts import FrameFeatures
from app.logic.calibration import Baseline
from app.logic.head_pose import _mul, to_angles, to_matrix
from app.logic.detectors import DetectorState
from app.logic.posture import ISSUES, TIPS, PostureTracker, PostureUpdate
from app.storage.settings import DEFAULTS

FPS = 5  # enough frames per second for the per-second averaging, and keeps minutes-long tests fast
BASE = Baseline(
    head_yaw=0.0, head_pitch=-5.0, head_roll=0.0, shoulder_width=0.3, shoulder_angle=0.0,
    shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8, face_width=0.2,
)
FOCUSED = DetectorState(t=0, phone=False, desk_object=False, looking_away=False, window=False, away=False, away_for_s=0)
LOOKING = DetectorState(t=0, phone=False, desk_object=False, looking_away=True, window=False, away=False, away_for_s=0)

SLOUCH = dict(nose_to_shoulder_y=0.8 * 0.7)  # gap down 30%: twice the 15% threshold
SLIGHT_SLOUCH = dict(nose_to_shoulder_y=0.8 * 0.9)  # down 10%: under the threshold


def settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def tracker(s: dict[str, Any] | None = None) -> PostureTracker:
    return PostureTracker(s or settings(), BASE)


def feat(t: float, **kw: Any) -> FrameFeatures:
    base: dict[str, Any] = dict(
        t=t, person_present=True, shoulder_visibility=0.95, head_yaw=0.0, head_pitch=BASE.head_pitch,
        head_roll=0.0, shoulder_width=0.3, shoulder_angle=0.0, shoulder_mid=(0.5, 0.45),
        nose_to_shoulder_y=BASE.nose_to_shoulder_y, face_width=BASE.face_width,
        face_bbox=(0.4, 0.2, 0.6, 0.4), hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


def run(
    tr: PostureTracker, seconds: float, start: float = 0.0,
    det: DetectorState = FOCUSED, distraction: bool = False, **kw: Any,
) -> list[PostureUpdate]:
    return [
        tr.update(feat(start + i / FPS, **kw), det, distraction)
        for i in range(int(seconds * FPS))
    ]


# --- metrics and score -------------------------------------------------------------------

def test_upright_scores_100() -> None:
    tr = tracker()
    ups = run(tr, 3)
    assert ups[-1].score == 100.0 and ups[-1].penalties == {i: 0.0 for i in ISSUES}
    assert not ups[-1].past_threshold


@pytest.mark.parametrize("issue,kw", [
    ("slouching", dict(nose_to_shoulder_y=0.8 * 0.7)),
    ("leaning_in", dict(face_width=0.2 * 1.4)),
    ("neck_down", dict(head_pitch=-5.0 - 40)),
    ("head_tilt", dict(head_roll=-20.0)),
    ("uneven_shoulders", dict(shoulder_angle=14.0)),
])
def test_each_metric_at_twice_threshold_gives_full_penalty(issue: str, kw: dict[str, float]) -> None:
    tr = tracker()
    pens = tr.penalties(tr.deviations(feat(0, **kw)) or {})
    assert pens[issue] == pytest.approx(1.0)  # type: ignore[index]
    assert sum(pens.values()) == pytest.approx(1.0)


def test_harmless_direction_is_not_penalised() -> None:
    tr = tracker()
    devs = tr.deviations(feat(0, nose_to_shoulder_y=1.0, face_width=0.15, head_pitch=10.0))
    assert devs is not None
    assert tr.penalties(devs) == {i: 0.0 for i in ISSUES}


def test_one_issue_past_threshold_scores_under_bad_score() -> None:
    tr = tracker()
    just_past = tr.penalties(tr.deviations(feat(0, nose_to_shoulder_y=0.8 * 0.84)) or {})  # down 16%
    assert tr.score(just_past) < DEFAULTS["posture"]["bad_score"]
    under = tr.penalties(tr.deviations(feat(0, **SLIGHT_SLOUCH)) or {})
    assert tr.score(under) > DEFAULTS["posture"]["bad_score"]


def test_score_is_clamped_at_zero() -> None:
    tr = tracker()
    devs = tr.deviations(feat(0, nose_to_shoulder_y=0.4, face_width=0.4, head_pitch=-60.0))
    assert devs is not None
    assert tr.score(tr.penalties(devs)) == 0.0


def test_past_threshold_names_issues() -> None:
    up = run(tracker(), 1, **SLOUCH)[-1]
    assert up.past_threshold == {"slouching"}


def test_missing_metric_skips_frame() -> None:
    tr = tracker()
    assert tr.deviations(feat(0, face_width=None)) is None


# --- bad window and tip --------------------------------------------------------------------

def test_bad_after_most_of_the_window() -> None:
    tr = tracker()
    ups = run(tr, 26, **SLOUCH)
    assert not ups[-1].bad and ups[-1].tip is None
    ups = run(tr, 3, start=26, **SLOUCH)
    assert ups[-1].bad and ups[-1].bad_seconds >= 27
    assert ups[-1].worst_issue == "slouching" and ups[-1].tip == TIPS["slouching"]


def test_slight_slouch_never_goes_bad() -> None:
    ups = run(tracker(), 60, **SLIGHT_SLOUCH)
    assert not any(u.bad for u in ups)


def test_tip_names_largest_penalty() -> None:
    ups = run(tracker(), 31, nose_to_shoulder_y=0.8 * 0.8, face_width=0.2 * 1.38)
    assert ups[-1].bad and ups[-1].worst_issue == "leaning_in"


def test_looking_away_seconds_are_not_scored_and_not_bad() -> None:
    tr = tracker()
    ups = run(tr, 40, det=LOOKING, **SLOUCH)
    assert ups[-1].score is None and ups[-1].penalties is None
    assert not ups[-1].bad


def test_seconds_before_away_fires_are_not_scored() -> None:
    absent = DetectorState(t=0, phone=False, desk_object=False, looking_away=False, window=False, away=False, away_for_s=3)
    ups = run(tracker(), 5, det=absent, **SLOUCH)
    assert ups[-1].score is None


# --- alerts ----------------------------------------------------------------------------------

def first_alert(ups: list[PostureUpdate]) -> float | None:
    return next((u.t for u in ups if u.alert), None)


def test_alert_after_threshold_of_bad_posture() -> None:
    ups = run(tracker(), 200, **SLOUCH)
    t = first_alert(ups)
    # Bad once 27 whole bad seconds are in the window (t = 27), then posture_threshold_s more.
    assert t == pytest.approx(27 + DEFAULTS["posture_threshold_s"])
    assert sum(u.alert for u in ups) == 1


def test_alert_repeats_after_cooldown_if_still_bad() -> None:
    ups = run(tracker(), 500, **SLOUCH)
    times = [u.t for u in ups if u.alert]
    assert len(times) == 2
    assert times[1] - times[0] == pytest.approx(DEFAULTS["posture_cooldown_s"], abs=1 / FPS)


def test_good_posture_resets_the_clock() -> None:
    tr = tracker()
    ups = run(tr, 120, **SLOUCH)  # bad for ~90 s, not yet alerted
    ups += run(tr, 40, start=120)  # sit up: window empties of bad seconds
    ups += run(tr, 130, start=160, **SLOUCH)  # bad again, but only ~100 s of it
    assert first_alert(ups) is None


def test_alert_held_back_during_distraction_then_sent() -> None:
    tr = tracker()
    ups = run(tr, 200, distraction=True, **SLOUCH)
    assert first_alert(ups) is None
    ups = run(tr, 2, start=200, **SLOUCH)
    assert ups[0].alert


def test_alert_timing_comes_from_settings() -> None:
    s = settings()
    s["posture_threshold_s"] = 60
    t = first_alert(run(tracker(s), 120, **SLOUCH))
    assert t is not None and t <= 30 + 60


def test_reset_forgets_everything() -> None:
    tr = tracker()
    run(tr, 60, **SLOUCH)
    tr.reset()
    up = tr.update(feat(100), FOCUSED, False)
    assert not up.bad and up.bad_seconds == 0 and up.score is None


# --- samples -------------------------------------------------------------------------------

def test_samples_every_interval_with_mean_and_worst() -> None:
    ups = run(tracker(), 31, face_width=0.2 * 1.4)
    samples = [u.sample for u in ups if u.sample is not None]
    assert [s.t for s in samples] == [10, 20, 30]
    assert all(s.worst_issue == "leaning_in" for s in samples)
    assert samples[1].score == pytest.approx(100 - 60 * 1.0)


def test_sample_with_nothing_scored() -> None:
    ups = run(tracker(), 11, det=LOOKING)
    sample = next(u.sample for u in ups if u.sample is not None)
    assert sample.score is None and sample.worst_issue is None


# --- free zone and angled camera -----------------------------------------------------------

@pytest.mark.parametrize("ratio,expected", [(0.0, 0.0), (0.4, 0.0), (0.5, 0.0), (0.75, 0.25), (1.0, 0.5), (1.5, 0.75), (2.0, 1.0), (5.0, 1.0)])
def test_penalty_curve(ratio: float, expected: float) -> None:
    assert tracker().penalty(ratio) == pytest.approx(expected)


def test_wobble_inside_the_free_zone_scores_100() -> None:
    # Every metric 40% of the way to its threshold at once: all inside the free zone.
    ups = run(tracker(), 3, nose_to_shoulder_y=0.8 * 0.94, face_width=0.2 * 1.08,
              head_pitch=-5.0 - 8, head_roll=4.0, shoulder_angle=2.8)
    assert ups[-1].score == 100.0


def test_angled_camera_head_turn_is_not_neck_or_tilt() -> None:
    camera = to_matrix((30, -20, 0))  # camera above and beside the screen
    base_yaw, base_pitch, base_roll = to_angles(camera)
    base = Baseline(
        head_yaw=base_yaw, head_pitch=base_pitch, head_roll=base_roll, shoulder_width=0.3,
        shoulder_angle=0.0, shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8, face_width=0.2,
    )
    yaw, pitch, roll = to_angles(_mul(camera, to_matrix((30, 0, 0))))  # reading across the screen
    tr = PostureTracker(settings(), base)
    devs = tr.deviations(feat(0, head_yaw=yaw, head_pitch=pitch, head_roll=roll))
    assert devs is not None
    assert devs["neck_down"] == pytest.approx(0, abs=1e-6)
    assert devs["head_tilt"] == pytest.approx(0, abs=1e-6)
