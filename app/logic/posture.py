"""Posture metrics, score, tips and posture alert timing (DESIGN §7).

Posture is judged as change from the user's calibrated upright baseline. Each frame gives
five penalties; they are averaged per whole second into a score. A rolling window of those
seconds decides whether posture is bad, a timer turns sustained bad posture into an alert,
and every sample_interval_s a sample is emitted for the posture_samples table.

Stdlib only, and every number comes from settings.json.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from app.contracts import FrameFeatures
from app.logic.calibration import Baseline, relative_head
from app.logic.detectors import DetectorState

Issue = Literal["slouching", "leaning_in", "neck_down", "head_tilt", "uneven_shoulders"]
ISSUES: tuple[Issue, ...] = ("slouching", "leaning_in", "neck_down", "head_tilt", "uneven_shoulders")

TIPS: dict[Issue, str] = {
    "slouching": "Sit up tall: you're sinking into your chair.",
    "leaning_in": "Lean back: you're getting close to the screen.",
    "neck_down": "Raise your chin, or raise your screen to eye level.",
    "head_tilt": "Level your head.",
    "uneven_shoulders": "Even out your shoulders. Leaning on one elbow?",
}

Penalties = dict[Issue, float]


@dataclass(frozen=True)
class PostureSample:
    """One posture_samples row."""
    t: int                    # seconds since session start, at the end of the interval
    score: float | None       # mean of the scored seconds; None if none were scored
    worst_issue: Issue | None


@dataclass(frozen=True)
class PostureUpdate:
    t: float
    score: float | None           # last completed second; None if it wasn't scored
    penalties: Penalties | None   # this frame's penalties; None when not scored
    past_threshold: frozenset[Issue]  # issues beyond their threshold this frame (overlay colours)
    bad: bool
    bad_seconds: int              # bad seconds in the rolling window
    bad_for_s: float              # how long posture has been bad (0 when not bad)
    worst_issue: Issue | None     # largest total penalty over the window
    tip: str | None               # shown while posture is bad
    alert: bool                   # True on the frame a posture alert should be sent
    sample: PostureSample | None  # emitted every sample_interval_s


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class PostureTracker:
    def __init__(self, settings: dict[str, Any], baseline: Baseline) -> None:
        p = settings["posture"]
        self.thresholds: dict[Issue, float] = {
            "slouching": p["slouch_pct"],
            "leaning_in": p["lean_pct"],
            "neck_down": p["neck_pitch_deg"],
            "head_tilt": p["tilt_roll_deg"],
            "uneven_shoulders": p["shoulder_angle_deg"],
        }
        self.penalty_weight: float = p["penalty_weight"]
        self.dead_zone: float = p["dead_zone"]
        self.bad_score: float = p["bad_score"]
        self.bad_window_s: int = int(p["bad_window_s"])
        self.bad_needed: float = p["bad_ratio"] * p["bad_window_s"]
        self.sample_interval_s: int = int(p["sample_interval_s"])
        self.threshold_s: float = settings["posture_threshold_s"]
        self.cooldown_s: float = settings["posture_cooldown_s"]
        self.baseline = baseline
        self.reset()

    def reset(self) -> None:
        """New session or resume: forget all history and timers."""
        self._second: int | None = None
        self._frame_pens: list[Penalties] = []
        # Rolling window of completed seconds: (second, score or None, penalties or None).
        self._window: deque[tuple[int, float | None, Penalties | None]] = deque()
        self._last_score: float | None = None
        self._bad_since: float | None = None
        self._last_alert: float | None = None
        self._sample_scores: list[float] = []
        self._sample_pens: dict[Issue, float] = {i: 0.0 for i in ISSUES}
        self._next_sample: int | None = None

    # --- metrics ----------------------------------------------------------------------

    def deviations(self, f: FrameFeatures) -> dict[Issue, float] | None:
        """How far each metric is from baseline in its harmful direction (same units as
        its threshold), or None if a metric can't be measured this frame."""
        b = self.baseline
        # Head pitch and roll in the calibrated head's own frame, so an angled camera
        # doesn't turn an ordinary head turn into "neck down" or "tilt".
        rel = relative_head(b, f)
        if rel is None or f.nose_to_shoulder_y is None or f.face_width is None or f.shoulder_angle is None:
            return None
        _, pitch, roll = rel
        return {
            "slouching": 100 * (b.nose_to_shoulder_y - f.nose_to_shoulder_y) / b.nose_to_shoulder_y,
            "leaning_in": 100 * (f.face_width - b.face_width) / b.face_width,
            "neck_down": -pitch,
            "head_tilt": abs(roll),
            "uneven_shoulders": abs(f.shoulder_angle - b.shoulder_angle),
        }

    def penalty(self, ratio: float) -> float:
        """Penalty for a deviation of `ratio` × threshold.

        0 up to dead_zone (normal wobble is free), rising to 0.5 at the threshold and 1 at
        twice it. Continuous, so the score moves smoothly."""
        if ratio <= self.dead_zone:
            return 0.0
        if ratio < 1:
            return 0.5 * (ratio - self.dead_zone) / (1 - self.dead_zone)
        return 0.5 + 0.5 * _clamp01(ratio - 1)

    def penalties(self, deviations: dict[Issue, float]) -> Penalties:
        """Per-issue penalties; the harmless direction (negative deviation) is 0."""
        return {i: self.penalty(deviations[i] / self.thresholds[i]) for i in ISSUES}

    def score(self, pens: Penalties) -> float:
        return max(0.0, min(100.0, 100 - self.penalty_weight * sum(pens.values())))

    # --- per frame --------------------------------------------------------------------

    def update(self, f: FrameFeatures, detectors: DetectorState, distraction_alert_active: bool) -> PostureUpdate:
        second = math.floor(f.t)
        if self._next_sample is None:
            self._next_sample = second + self.sample_interval_s
        if self._second is not None and second != self._second:
            self._close_second(self._second)
        self._second = second

        skip = detectors.looking_away or detectors.away_for_s > 0
        devs = None if skip else self.deviations(f)
        pens = self.penalties(devs) if devs is not None else None
        if pens is not None:
            self._frame_pens.append(pens)

        bad_seconds = sum(1 for _, s, _ in self._window if s is not None and s < self.bad_score)
        bad = bad_seconds >= self.bad_needed
        if bad:
            if self._bad_since is None:
                self._bad_since = f.t
        else:
            self._bad_since = None
        bad_for = f.t - self._bad_since if self._bad_since is not None else 0.0

        alert = (
            bad and bad_for >= self.threshold_s and not distraction_alert_active
            and (self._last_alert is None or f.t - self._last_alert >= self.cooldown_s)
        )
        if alert:
            self._last_alert = f.t

        worst = self._worst(p for _, _, p in self._window)
        sample = None
        if second >= self._next_sample:
            sample = self._take_sample(self._next_sample)
            self._next_sample += self.sample_interval_s

        return PostureUpdate(
            t=f.t,
            score=self._last_score,
            penalties=pens,
            past_threshold=frozenset(i for i in ISSUES if devs is not None and devs[i] > self.thresholds[i]),
            bad=bad,
            bad_seconds=bad_seconds,
            bad_for_s=bad_for,
            worst_issue=worst,
            tip=TIPS[worst] if bad and worst is not None else None,
            alert=alert,
            sample=sample,
        )

    # --- helpers ----------------------------------------------------------------------

    def _close_second(self, second: int) -> None:
        score: float | None = None
        mean: Penalties | None = None
        if self._frame_pens:
            n = len(self._frame_pens)
            mean = {i: sum(p[i] for p in self._frame_pens) / n for i in ISSUES}
            score = self.score(mean)
            self._sample_scores.append(score)
            for i in ISSUES:
                self._sample_pens[i] += mean[i]
        self._frame_pens = []
        self._last_score = score
        self._window.append((second, score, mean))
        while self._window and self._window[0][0] <= second - self.bad_window_s:
            self._window.popleft()

    @staticmethod
    def _worst(pens: Iterable[Penalties | None]) -> Issue | None:
        totals = {i: 0.0 for i in ISSUES}
        for p in pens:
            if p is not None:
                for i in ISSUES:
                    totals[i] += p[i]
        issue = max(ISSUES, key=lambda i: totals[i])
        return issue if totals[issue] > 0 else None

    def _take_sample(self, t: int) -> PostureSample:
        scores = self._sample_scores
        worst = max(ISSUES, key=lambda i: self._sample_pens[i])
        sample = PostureSample(
            t=t,
            score=sum(scores) / len(scores) if scores else None,
            worst_issue=worst if self._sample_pens[worst] > 0 else None,
        )
        self._sample_scores = []
        self._sample_pens = {i: 0.0 for i in ISSUES}
        return sample
