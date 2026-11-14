"""Calibration baseline from FrameFeatures (DESIGN §7).

Two steps, each fed smoothed FrameFeatures by the wizard until done():

1. UprightStep -> Baseline (medians of every posture metric, head angles, shoulder midpoint)
2. WindowStep  -> window yaw (optional; the user may skip it)

There is no keyboard step: on a normal desk the keyboard is below the webcam's view.

Each step's result() says whether it passed and, if not, why, in words the wizard can show.
CameraShiftCheck runs at session start and says whether the camera has probably moved.
Every threshold and duration comes from settings.json; nothing here touches the camera.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from statistics import median
from typing import Any, Generic, TypeVar

from app.contracts import FrameFeatures

T = TypeVar("T")

# Retry messages shown by the wizard.
NO_PERSON = "We couldn't see you. Sit in front of the camera, facing the screen."
NO_SHOULDERS = "Move back or tilt the camera down so both shoulders are in view."
NO_FACE = "Face the screen so the camera can see your face clearly."
WINDOW_TOO_CLOSE = "Your head turned only {measured:.0f}° from the screen; it needs more than {needed:.0f}°."
WINDOW_TOO_CLOSE_HINT = " Turn your whole head toward the window, not just your eyes, or skip this step."


@dataclass(frozen=True)
class Baseline:
    head_yaw: float
    head_pitch: float
    head_roll: float
    shoulder_width: float
    shoulder_angle: float
    shoulder_mid: tuple[float, float]
    nose_to_shoulder_y: float
    face_width: float


@dataclass(frozen=True)
class Calibration:
    baseline: Baseline
    window_yaw: float | None  # None when the window step was skipped

    def to_dict(self) -> dict[str, Any]:
        """The calibration table's values_json content."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Calibration:
        b = dict(d["baseline"])
        b["shoulder_mid"] = tuple(b["shoulder_mid"])
        # Older rows may also hold a "work_zone"; it is no longer used and is ignored.
        return cls(baseline=Baseline(**b), window_yaw=d.get("window_yaw"))


@dataclass(frozen=True)
class StepResult(Generic[T]):
    value: T | None
    reason: str | None = None  # why it failed; None when it passed

    @property
    def passed(self) -> bool:
        return self.value is not None


class _Step(Generic[T]):
    """Collects frames for a fixed duration, timed from the first frame's t."""

    def __init__(self, duration_s: float, min_valid_ratio: float) -> None:
        self.duration_s = duration_s
        self.min_valid_ratio = min_valid_ratio
        self._start: float | None = None
        self._last: float | None = None
        self._frames = 0
        self._failures: Counter[str] = Counter()

    def add(self, f: FrameFeatures) -> None:
        if self.done():
            return
        if self._start is None:
            self._start = f.t
        self._last = f.t
        self._frames += 1
        failure = self._collect(f)
        if failure is not None:
            self._failures[failure] += 1

    @property
    def elapsed_s(self) -> float:
        return 0.0 if self._start is None or self._last is None else self._last - self._start

    @property
    def progress(self) -> float:
        """0 to 1, for the wizard's countdown."""
        return 1.0 if self.duration_s <= 0 else min(1.0, self.elapsed_s / self.duration_s)

    def done(self) -> bool:
        return self._frames > 0 and self.elapsed_s >= self.duration_s

    def result(self) -> StepResult[T]:
        valid = self._frames - sum(self._failures.values())
        if self._frames == 0 or valid / self._frames < self.min_valid_ratio:
            reason = self._failures.most_common(1)[0][0] if self._failures else NO_PERSON
            return StepResult(None, reason)
        return self._finish()

    def _collect(self, f: FrameFeatures) -> str | None:
        """Store what this frame contributes; return a retry message if it can't be used."""
        raise NotImplementedError

    def _finish(self) -> StepResult[T]:
        raise NotImplementedError


class UprightStep(_Step[Baseline]):
    def __init__(self, settings: dict[str, Any]) -> None:
        c = settings["calibration"]
        super().__init__(c["upright_s"], c["min_valid_ratio"])
        self.min_shoulder_vis: float = settings["detectors"]["away_shoulder_vis"]
        self._samples: list[Baseline] = []

    def _collect(self, f: FrameFeatures) -> str | None:
        if not f.person_present:
            return NO_PERSON
        if (
            f.shoulder_visibility is None or f.shoulder_visibility < self.min_shoulder_vis
            or f.shoulder_width is None or f.shoulder_angle is None or f.shoulder_mid is None
            or f.nose_to_shoulder_y is None
        ):
            return NO_SHOULDERS
        if f.head_yaw is None or f.head_pitch is None or f.head_roll is None or f.face_width is None:
            return NO_FACE
        self._samples.append(Baseline(
            head_yaw=f.head_yaw, head_pitch=f.head_pitch, head_roll=f.head_roll,
            shoulder_width=f.shoulder_width, shoulder_angle=f.shoulder_angle, shoulder_mid=f.shoulder_mid,
            nose_to_shoulder_y=f.nose_to_shoulder_y, face_width=f.face_width,
        ))
        return None

    def _finish(self) -> StepResult[Baseline]:
        s = self._samples
        return StepResult(Baseline(
            head_yaw=median(b.head_yaw for b in s),
            head_pitch=median(b.head_pitch for b in s),
            head_roll=median(b.head_roll for b in s),
            shoulder_width=median(b.shoulder_width for b in s),
            shoulder_angle=median(b.shoulder_angle for b in s),
            shoulder_mid=(median(b.shoulder_mid[0] for b in s), median(b.shoulder_mid[1] for b in s)),
            nose_to_shoulder_y=median(b.nose_to_shoulder_y for b in s),
            face_width=median(b.face_width for b in s),
        ))


class WindowStep(_Step[float]):
    def __init__(self, settings: dict[str, Any], baseline: Baseline) -> None:
        c = settings["calibration"]
        super().__init__(c["window_s"], c["min_valid_ratio"])
        self.min_yaw_diff: float = settings["detectors"]["look_yaw_deg"]
        self.baseline_yaw = baseline.head_yaw
        self._yaws: list[float] = []

    def _collect(self, f: FrameFeatures) -> str | None:
        if not f.person_present:
            return NO_PERSON
        if f.head_yaw is None:
            return NO_FACE
        self._yaws.append(f.head_yaw)
        return None

    def _finish(self) -> StepResult[float]:
        yaw = median(self._yaws)
        turn = abs(yaw - self.baseline_yaw)
        if turn <= self.min_yaw_diff:
            msg = WINDOW_TOO_CLOSE.format(measured=turn, needed=self.min_yaw_diff) + WINDOW_TOO_CLOSE_HINT
            return StepResult(None, msg)
        return StepResult(yaw)


class CameraShiftCheck(_Step[bool]):
    """At session start: True if the shoulders have moved far enough that the camera has
    probably moved and calibration should be redone. Fails (value None) if the user can't
    be seen well enough to tell."""

    def __init__(self, settings: dict[str, Any], baseline: Baseline) -> None:
        c = settings["calibration"]
        super().__init__(c["recalibrate_check_s"], c["min_valid_ratio"])
        self.max_shift: float = c["recalibrate_shift"]
        self.min_shoulder_vis: float = settings["detectors"]["away_shoulder_vis"]
        self.baseline_mid = baseline.shoulder_mid
        self._mids: list[tuple[float, float]] = []

    def _collect(self, f: FrameFeatures) -> str | None:
        if not f.person_present:
            return NO_PERSON
        if f.shoulder_mid is None or f.shoulder_visibility is None or f.shoulder_visibility < self.min_shoulder_vis:
            return NO_SHOULDERS
        self._mids.append(f.shoulder_mid)
        return None

    def _finish(self) -> StepResult[bool]:
        x = median(m[0] for m in self._mids)
        y = median(m[1] for m in self._mids)
        shift = math.dist((x, y), self.baseline_mid)
        return StepResult(shift > self.max_shift)
