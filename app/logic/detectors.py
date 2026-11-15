"""The four distraction detectors (DESIGN §6).

Each frame, every detector gives a raw yes/no from smoothed FrameFeatures and the user's
calibration. Each raw signal is then smoothed over a rolling window (smoothing.bool_window_s,
smoothing.bool_ratio), and the away signal must also hold for away_detect_s before the away
detector fires. The result names the highest-priority distraction; the state machine
(section 8) decides whether and when to alert.

Stdlib only, and every number comes from settings.json.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Literal

from app.contracts import BBox, Detection, FrameFeatures, HandInfo
from app.logic.calibration import Calibration

Label = Literal["phone", "desk_object", "window", "looking_away", "away"]
DistractionType = Literal["phone", "desk_object", "looking_away", "away"]  # keys of distraction_threshold_s

PHONE_CLASS = "cell phone"


@dataclass(frozen=True)
class DetectorState:
    """Smoothed detector outputs for one frame."""
    t: float
    phone: bool
    desk_object: bool
    looking_away: bool
    window: bool          # looking away, toward the calibrated window
    away: bool            # absent for at least away_detect_s
    away_for_s: float     # how long the smoothed away signal has held (0 when present)

    @property
    def label(self) -> Label | None:
        """The highest-priority distraction: phone, desk object, looking away, away."""
        if self.phone:
            return "phone"
        if self.desk_object:
            return "desk_object"
        if self.looking_away:
            return "window" if self.window else "looking_away"
        if self.away:
            return "away"
        return None

    @property
    def distraction_type(self) -> DistractionType | None:
        """The label as a distraction_threshold_s key: window uses the looking_away timer."""
        label = self.label
        return "looking_away" if label == "window" else label


# --- geometry -----------------------------------------------------------------------------

def overlaps(a: BBox, b: BBox) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def box_gap(a: BBox, b: BBox, aspect: float) -> float:
    """Shortest distance between two boxes in frame-width units; 0 if they overlap.
    aspect is frame height / width, so vertical gaps are scaled to width units."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3]) * aspect
    return float((dx * dx + dy * dy) ** 0.5)


# --- smoothing ----------------------------------------------------------------------------

class BoolSmoother:
    """On when the signal held in at least `ratio` of the frames in the last `window_s`."""

    def __init__(self, window_s: float, ratio: float) -> None:
        self.window_s = window_s
        self.ratio = ratio
        self._frames: deque[tuple[float, bool]] = deque()
        self._true = 0

    def reset(self) -> None:
        self._frames.clear()
        self._true = 0

    def update(self, t: float, value: bool) -> bool:
        self._frames.append((t, value))
        self._true += value
        while self._frames and self._frames[0][0] < t - self.window_s:
            _, old = self._frames.popleft()
            self._true -= old
        return self._true >= self.ratio * len(self._frames)


# --- detectors ----------------------------------------------------------------------------

@dataclass(frozen=True)
class RawSignals:
    """Unsmoothed per-frame decisions, exposed for the live check and for tests."""
    phone: bool
    desk_object: bool
    looking_away: bool
    window: bool
    away: bool


class Detectors:
    def __init__(self, settings: dict[str, Any], calibration: Calibration) -> None:
        d = settings["detectors"]
        v = settings["vision"]
        s = settings["smoothing"]
        self.phone_conf: float = d["phone_conf"]
        self.phone_hand_dist: float = d["phone_hand_dist"]
        self.phone_pitch_down_deg: float = d["phone_pitch_down_deg"]
        self.look_yaw_deg: float = d["look_yaw_deg"]
        self.look_pitch_up_deg: float = d["look_pitch_up_deg"]
        self.window_yaw_tol_deg: float = d["window_yaw_tol_deg"]
        self.away_shoulder_vis: float = d["away_shoulder_vis"]
        self.work_classes: frozenset[str] = frozenset(d["work_classes"])
        self.away_detect_s: float = settings["away_detect_s"]
        self.aspect: float = v["capture_height"] / v["capture_width"]
        self.baseline = calibration.baseline
        self.window_yaw = calibration.window_yaw
        self._smoothers = {
            name: BoolSmoother(s["bool_window_s"], s["bool_ratio"])
            for name in ("phone", "desk_object", "looking_away", "window", "away")
        }
        self._away_since: float | None = None
        self.last_raw: RawSignals | None = None

    def reset(self) -> None:
        """After a pause or break: forget smoothing history and the away clock."""
        for sm in self._smoothers.values():
            sm.reset()
        self._away_since = None
        self.last_raw = None

    # Raw per-frame rules ------------------------------------------------------------

    def _is_absent(self, f: FrameFeatures) -> bool:
        return (
            not f.person_present
            or f.shoulder_visibility is None
            or f.shoulder_visibility < self.away_shoulder_vis
        )

    def _phones(self, f: FrameFeatures) -> list[Detection]:
        return [o for o in f.objects if o.cls == PHONE_CLASS and o.confidence >= self.phone_conf]

    def _phone(self, f: FrameFeatures) -> bool:
        phones = self._phones(f)
        if not phones:
            return False
        if any(box_gap(p.bbox, h.bbox, self.aspect) <= self.phone_hand_dist for p in phones for h in f.hands):
            return True
        return f.head_pitch is not None and self.baseline.head_pitch - f.head_pitch >= self.phone_pitch_down_deg

    def _hand_off_task(self, hand: HandInfo, f: FrameFeatures) -> bool:
        if not hand.grasp:
            return False
        if f.face_bbox is not None and overlaps(hand.bbox, f.face_bbox):
            return False  # chin or cheek resting on a hand
        held = [o for o in f.objects if overlaps(hand.bbox, o.bbox)]
        if not held:
            return True  # grasping something YOLO doesn't recognize
        return any(o.cls not in self.work_classes for o in held)

    def _desk_object(self, f: FrameFeatures) -> bool:
        return any(self._hand_off_task(h, f) for h in f.hands)

    def _looking(self, f: FrameFeatures) -> tuple[bool, bool]:
        """(looking away, toward the window)."""
        if f.head_yaw is None or f.head_pitch is None:
            return True, False  # body seen, face lost: head turned beyond the face tracker
        b = self.baseline
        away = (
            abs(f.head_yaw - b.head_yaw) > self.look_yaw_deg
            or f.head_pitch - b.head_pitch > self.look_pitch_up_deg
        )
        window = (
            away and self.window_yaw is not None
            and abs(f.head_yaw - self.window_yaw) <= self.window_yaw_tol_deg
        )
        return away, window

    def raw(self, f: FrameFeatures) -> RawSignals:
        absent = self._is_absent(f)
        looking, window = (False, False) if absent else self._looking(f)
        return RawSignals(
            phone=self._phone(f),
            desk_object=self._desk_object(f),
            looking_away=looking,
            window=window,
            away=absent,
        )

    # Per frame ------------------------------------------------------------------------

    def update(self, f: FrameFeatures) -> DetectorState:
        r = self.raw(f)
        self.last_raw = r
        sm = {name: s.update(f.t, getattr(r, name)) for name, s in self._smoothers.items()}

        if sm["away"]:
            if self._away_since is None:
                self._away_since = f.t
            away_for = f.t - self._away_since
        else:
            self._away_since = None
            away_for = 0.0

        return DetectorState(
            t=f.t,
            phone=sm["phone"],
            desk_object=sm["desk_object"],
            looking_away=sm["looking_away"],
            window=sm["looking_away"] and sm["window"],
            away=away_for >= self.away_detect_s,
            away_for_s=away_for,
        )
