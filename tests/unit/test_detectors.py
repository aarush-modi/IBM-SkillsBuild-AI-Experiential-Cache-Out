"""Distraction detectors (DESIGN §6) with synthetic FrameFeatures. The §6 table is the oracle."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.contracts import BBox, Detection, FrameFeatures, HandInfo
from app.logic.calibration import Baseline, Calibration
from app.logic.detectors import BoolSmoother, DetectorState, Detectors, box_gap, overlaps
from app.storage.settings import DEFAULTS

FPS = 15
BASE = Baseline(
    head_yaw=2.0, head_pitch=-5.0, head_roll=0.0, shoulder_width=0.3, shoulder_angle=0.0,
    shoulder_mid=(0.5, 0.45), nose_to_shoulder_y=0.8, face_width=0.2,
)
FACE: BBox = (0.42, 0.15, 0.58, 0.4)


def settings() -> dict[str, Any]:
    return copy.deepcopy(DEFAULTS)


def detectors(window_yaw: float | None = 60.0, s: dict[str, Any] | None = None) -> Detectors:
    return Detectors(s or settings(), Calibration(baseline=BASE, window_yaw=window_yaw))


def feat(t: float = 0.0, **kw: Any) -> FrameFeatures:
    """A focused user: present, facing the screen, no hands in view."""
    base: dict[str, Any] = dict(
        t=t, person_present=True, shoulder_visibility=0.95,
        head_yaw=BASE.head_yaw, head_pitch=BASE.head_pitch, head_roll=0.0,
        shoulder_width=0.3, shoulder_angle=0.0, shoulder_mid=(0.5, 0.45),
        nose_to_shoulder_y=0.8, face_width=0.2, face_bbox=FACE, hands=[], objects=[],
    )
    base.update(kw)
    return FrameFeatures(**base)


def hand(box: BBox = (0.6, 0.55, 0.7, 0.7), grasp: bool = True) -> HandInfo:
    return HandInfo(bbox=box, grasp=grasp)


def obj(cls: str, box: BBox = (0.62, 0.55, 0.68, 0.68), conf: float = 0.8) -> Detection:
    return Detection(cls=cls, confidence=conf, bbox=box)


def hold(det: Detectors, seconds: float, start: float = 0.0, **kw: Any) -> DetectorState:
    """Feed the same features for `seconds` at FPS and return the last state."""
    state = None
    for i in range(int(seconds * FPS) + 1):
        state = det.update(feat(start + i / FPS, **kw))
    assert state is not None
    return state


# --- geometry ----------------------------------------------------------------------------

def test_box_gap() -> None:
    a: BBox = (0.1, 0.1, 0.2, 0.2)
    assert box_gap(a, (0.15, 0.15, 0.3, 0.3), 0.75) == 0.0
    assert box_gap(a, (0.3, 0.1, 0.4, 0.2), 0.75) == pytest.approx(0.1)
    assert box_gap(a, (0.1, 0.3, 0.2, 0.4), 0.75) == pytest.approx(0.075)  # 0.1 of height = 0.075 of width


def test_overlaps() -> None:
    assert overlaps((0, 0, 0.5, 0.5), (0.4, 0.4, 1, 1))
    assert not overlaps((0, 0, 0.5, 0.5), (0.5, 0.5, 1, 1))  # touching edges only


# --- smoothing ---------------------------------------------------------------------------

def test_bool_smoother_needs_ratio_over_window() -> None:
    sm = BoolSmoother(window_s=2.0, ratio=0.7)
    # 6 of every 10 frames true: under 70%, stays off once the window is full.
    states = [sm.update(i / FPS, i % 10 < 6) for i in range(60)]
    assert not any(states[30:])
    sm.reset()
    states = [sm.update(i / FPS, i % 10 < 8) for i in range(60)]
    assert all(states[30:])


def test_brief_glance_is_smoothed_out() -> None:
    det = detectors()
    hold(det, 3)
    # 0.5 s glance far to the side, inside a 2 s window: under 70% of frames.
    state = hold(det, 0.5, start=3.1, head_yaw=60.0)
    assert not state.looking_away


# --- focused -----------------------------------------------------------------------------

def test_focused_user_triggers_nothing() -> None:
    state = hold(detectors(), 5)
    assert state.label is None and state.away_for_s == 0.0


# --- phone -------------------------------------------------------------------------------

def test_phone_in_hand() -> None:
    state = hold(detectors(), 3, hands=[hand()], objects=[obj("cell phone")])
    assert state.phone and state.label == "phone"


def test_phone_near_hand_within_distance() -> None:
    # Hand ends at x=0.7; phone starts 0.08 frame-widths to the right (limit 0.1).
    state = hold(detectors(), 3, hands=[hand()], objects=[obj("cell phone", (0.78, 0.55, 0.85, 0.7))])
    assert state.phone


def test_phone_far_from_hand_and_head_up_is_ignored() -> None:
    state = hold(detectors(), 3, hands=[hand()], objects=[obj("cell phone", (0.05, 0.8, 0.12, 0.95))])
    assert not state.phone


def test_phone_on_desk_while_looking_down() -> None:
    down = BASE.head_pitch - DEFAULTS["detectors"]["phone_pitch_down_deg"]
    state = hold(detectors(), 3, head_pitch=down, objects=[obj("cell phone", (0.05, 0.8, 0.12, 0.95))])
    assert state.phone


def test_low_confidence_phone_is_ignored() -> None:
    state = hold(detectors(), 3, hands=[hand()], objects=[obj("cell phone", conf=0.3)])
    assert not state.phone


# --- looking away ------------------------------------------------------------------------

@pytest.mark.parametrize("yaw", [BASE.head_yaw + 30, BASE.head_yaw - 30])
def test_looking_to_either_side(yaw: float) -> None:
    state = hold(detectors(window_yaw=None), 3, head_yaw=yaw)
    assert state.looking_away and state.label == "looking_away"


def test_small_turn_is_not_looking_away() -> None:
    assert not hold(detectors(), 3, head_yaw=BASE.head_yaw + 20).looking_away


def test_looking_up() -> None:
    state = hold(detectors(), 3, head_pitch=BASE.head_pitch + 25)
    assert state.looking_away


def test_looking_down_at_notes_is_not_looking_away() -> None:
    state = hold(detectors(), 3, head_pitch=BASE.head_pitch - 30, objects=[obj("book", (0.3, 0.7, 0.6, 0.95))])
    assert state.label is None


def test_window_label() -> None:
    state = hold(detectors(window_yaw=60.0), 3, head_yaw=55.0)
    assert state.looking_away and state.window
    assert state.label == "window" and state.distraction_type == "looking_away"


def test_away_from_screen_but_not_toward_window() -> None:
    state = hold(detectors(window_yaw=60.0), 3, head_yaw=-50.0)
    assert state.label == "looking_away"


def test_face_lost_with_body_present_counts_as_looking_away() -> None:
    state = hold(detectors(), 3, head_yaw=None, head_pitch=None, head_roll=None, face_width=None, face_bbox=None)
    assert state.looking_away and not state.window and state.label == "looking_away"


# --- desk objects ------------------------------------------------------------------------

def test_holding_an_unknown_object() -> None:
    state = hold(detectors(), 3, hands=[hand()])
    assert state.desk_object and state.label == "desk_object"


def test_holding_a_non_work_object() -> None:
    assert hold(detectors(), 3, hands=[hand()], objects=[obj("cup")]).desk_object


@pytest.mark.parametrize("cls", ["book", "mouse", "keyboard", "laptop"])
def test_holding_a_work_object_is_fine(cls: str) -> None:
    assert not hold(detectors(), 3, hands=[hand()], objects=[obj(cls)]).desk_object


def test_open_hand_is_fine() -> None:
    assert not hold(detectors(), 3, hands=[hand(grasp=False)]).desk_object


def test_chin_resting_on_hand_is_ignored() -> None:
    chin = hand((0.45, 0.35, 0.55, 0.5))
    assert not hold(detectors(), 3, hands=[chin]).desk_object


def test_work_classes_come_from_settings() -> None:
    s = settings()
    s["detectors"]["work_classes"] = ["keyboard", "mouse", "laptop", "book", "cup"]
    assert not hold(detectors(s=s), 3, hands=[hand()], objects=[obj("cup")]).desk_object


# --- away --------------------------------------------------------------------------------

def test_away_fires_only_after_away_detect_s() -> None:
    det = detectors()
    gone = dict(person_present=False, shoulder_visibility=None, head_yaw=None, head_pitch=None, face_bbox=None)
    state = hold(det, 8, **gone)
    assert not state.away and state.label is None
    assert 0 < state.away_for_s < DEFAULTS["away_detect_s"]
    state = hold(det, 3, start=8 + 1 / FPS, **gone)
    assert state.away and state.label == "away"


def test_shoulders_out_of_view_counts_as_away_not_looking_away() -> None:
    state = hold(detectors(), 11, shoulder_visibility=0.3, head_yaw=None, head_pitch=None)
    assert state.away and not state.looking_away and state.label == "away"


def test_coming_back_resets_the_away_clock() -> None:
    det = detectors()
    hold(det, 8, person_present=False, shoulder_visibility=None)
    state = hold(det, 3, start=8 + 1 / FPS)
    assert state.away_for_s == 0.0 and not state.away


# --- priority and reset ------------------------------------------------------------------

def test_phone_beats_looking_away() -> None:
    state = hold(detectors(), 3, head_yaw=60.0, hands=[hand()], objects=[obj("cell phone")])
    assert state.phone and state.looking_away and state.label == "phone"


def test_desk_object_beats_looking_away() -> None:
    state = hold(detectors(window_yaw=None), 3, head_yaw=60.0, hands=[hand()])
    assert state.label == "desk_object"


def test_label_priority_order() -> None:
    s = DetectorState(t=0, phone=False, desk_object=False, looking_away=True, window=False, away=True, away_for_s=20)
    assert s.label == "looking_away"


def test_reset_forgets_history() -> None:
    det = detectors()
    hold(det, 3, head_yaw=60.0)
    det.reset()
    assert det.last_raw is None
    assert not det.update(feat(10.0)).looking_away
