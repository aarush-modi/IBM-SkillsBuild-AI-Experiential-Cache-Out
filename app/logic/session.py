"""One session's judgement, frame by frame: detectors, posture tracker and focus state machine
(DESIGN §6 to §8). The logic thread feeds it FrameFeatures and gets back what to show, which
alerts to send and which events and posture samples to store. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.contracts import PATTERN_POSTURE, Alert, FrameFeatures
from app.logic.calibration import NO_SHOULDERS, Calibration, CameraShiftCheck
from app.logic.detectors import DetectorState, Detectors
from app.logic.events import EventBook, EventRecord
from app.logic.posture import PostureSample, PostureTracker, PostureUpdate
from app.logic.state_machine import FocusStateMachine, FocusUpdate, PauseReason


@dataclass(frozen=True)
class SessionUpdate:
    detectors: DetectorState
    posture: PostureUpdate
    focus: FocusUpdate
    alerts: list[Alert] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)
    sample: PostureSample | None = None
    camera_hint: str | None = None     # "Move back or tilt the camera down..." (DESIGN §5)
    camera_moved: bool | None = None   # set on the frame the start-of-session check finishes


class SessionLogic:
    def __init__(self, settings: dict[str, Any], calibration: Calibration, wall_start: float) -> None:
        self.book = EventBook()
        self.detectors = Detectors(settings, calibration)
        self.posture = PostureTracker(settings, calibration.baseline)
        self.focus = FocusStateMachine(settings, self.book, wall_start)
        self.wall_start = wall_start
        self._posture_key: int | None = None
        self._posture_label: str | None = None
        self.last_t = 0.0
        self._shift: CameraShiftCheck | None = CameraShiftCheck(settings, calibration.baseline)
        self._hint_after_s: float = settings["vision"]["shoulders_missing_warn_s"]
        self._min_shoulder_vis: float = settings["detectors"]["away_shoulder_vis"]
        self._shoulders_missing_since: float | None = None

    @property
    def paused(self) -> bool:
        return self.focus.state == "paused"

    def update(self, f: FrameFeatures) -> SessionUpdate:
        self.last_t = f.t
        ds = self.detectors.update(f)
        fu = self.focus.update(ds)
        events = list(fu.events)
        if self.paused:  # paused before or by this frame (auto-pause after long absence)
            events += self._end_posture_event(f.t)
            return SessionUpdate(ds, self._idle_posture(f.t), fu, list(fu.alerts), events)
        hint = self._camera_hint(f)
        moved = self._check_shift(f)

        pu = self.posture.update(f, ds, self.focus.distraction_alert_active)
        alerts = list(fu.alerts)
        if pu.alert and fu.snoozed_for_s == 0 and pu.worst_issue is not None:
            alerts.append(Alert(kind="posture", label=pu.worst_issue, pattern=PATTERN_POSTURE,
                                created_at=self.wall_start + f.t))
            events.append(self.book.instant("alert", pu.worst_issue, f.t))

        # Posture events: one per stretch of bad posture, labelled with its worst issue.
        if pu.bad:
            if self._posture_key is None:
                rec = self.book.open("posture", pu.worst_issue, f.t - pu.bad_for_s)
                self._posture_key = rec.key
                events.append(rec)
            self._posture_label = pu.worst_issue
        else:
            events += self._end_posture_event(f.t)
        return SessionUpdate(ds, pu, fu, alerts, events, pu.sample, hint, moved)

    # --- user actions -------------------------------------------------------------------

    def pause(self, reason: PauseReason = "pause") -> list[EventRecord]:
        return self._end_posture_event(self.last_t) + self.focus.pause(self.last_t, reason)

    def resume(self) -> list[EventRecord]:
        """Back from a pause: detectors and posture start fresh, the session clock carries on."""
        self.detectors.reset()
        self.posture.reset()
        return self.focus.resume(self.last_t)

    def snooze(self) -> list[EventRecord]:
        return self.focus.snooze(self.last_t)

    def unsnooze(self) -> list[EventRecord]:
        return self.focus.unsnooze(self.last_t)

    def end(self) -> list[EventRecord]:
        return self._end_posture_event(self.last_t) + self.focus.end(self.last_t)

    # --- helpers --------------------------------------------------------------------------

    def _camera_hint(self, f: FrameFeatures) -> str | None:
        """The user is in view but their shoulders aren't, for shoulders_missing_warn_s."""
        missing = f.person_present and (
            f.shoulder_visibility is None or f.shoulder_visibility < self._min_shoulder_vis
        )
        if not missing:
            self._shoulders_missing_since = None
            return None
        if self._shoulders_missing_since is None:
            self._shoulders_missing_since = f.t
        return NO_SHOULDERS if f.t - self._shoulders_missing_since >= self._hint_after_s else None

    def _check_shift(self, f: FrameFeatures) -> bool | None:
        """Runs CameraShiftCheck over the first frames; returns its answer once, then None.
        An inconclusive check (user not in view) says nothing."""
        if self._shift is None:
            return None
        self._shift.add(f)
        if not self._shift.done():
            return None
        result = self._shift.result()
        self._shift = None
        return result.value if result.passed else None

    def _end_posture_event(self, t: float) -> list[EventRecord]:
        if self._posture_key is None:
            return []
        rec = self.book.close(self._posture_key, t, self._posture_label)
        self._posture_key = None
        self._posture_label = None
        return [rec]

    @staticmethod
    def _idle_posture(t: float) -> PostureUpdate:
        return PostureUpdate(
            t=t, score=None, penalties=None, past_threshold=frozenset(), bad=False, bad_seconds=0,
            bad_for_s=0.0, worst_issue=None, tip=None, alert=False, sample=None,
        )
