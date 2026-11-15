"""Focus state machine and alert timing (DESIGN §8).

Focused -> Pending when any detector fires; Pending -> Distracted (first alert) once the
distraction has lasted distraction_threshold_s of its current type; repeats every
repeat_alert_s, escalating from the escalate_after_repeats-th repeat; focus_reset_s of
continuous focus ends Pending or Distracted. Pause or Break from any state; auto-pause after
auto_pause_away_s away. Snooze only mutes alerts: timers, states and logging carry on.

One distraction is one event even if its label changes (e.g. looking away, then the phone):
the clock runs from when it began and is compared with the current type's threshold.
Alerts carry the current label; the logged event keeps the highest-priority label seen.

"Focus" means present and facing the screen: no detector firing and not absent. Being absent
for less than away_detect_s is neither focus nor distraction.

Stdlib only, and every number comes from settings.json.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.contracts import PATTERN_DISTRACTION, PATTERN_ESCALATED, Alert
from app.logic.detectors import DetectorState, Label
from app.logic.events import EventBook, EventKind, EventRecord

FocusState = Literal["focused", "pending", "distracted", "paused"]
PauseReason = Literal["pause", "break", "away"]

# Lower is higher priority (DESIGN §6).
_RANK: dict[str, int] = {"phone": 0, "desk_object": 1, "window": 2, "looking_away": 2, "away": 3}


def _higher(a: Label | None, b: Label) -> Label:
    return b if a is None or _RANK[b] < _RANK[a] else a


@dataclass(frozen=True)
class FocusUpdate:
    t: float
    state: FocusState
    label: Label | None              # the current distraction's label, or None
    pending_s: float                 # how long the current distraction has lasted
    alert_in_s: float | None         # Pending: time until the first alert
    next_repeat_in_s: float | None   # Distracted: time until the next repeat (None if off)
    repeats: int
    focus_run_s: float               # continuous focus so far (ends a distraction at focus_reset_s)
    snoozed_for_s: float             # snooze time left, 0 when not snoozed
    focus_seconds: float             # session total of focused time
    pause_reason: PauseReason | None
    alerts: list[Alert] = field(default_factory=list)
    events: list[EventRecord] = field(default_factory=list)


class FocusStateMachine:
    def __init__(self, settings: dict[str, Any], book: EventBook, wall_start: float) -> None:
        self.thresholds: dict[str, float] = dict(settings["distraction_threshold_s"])
        self.focus_reset_s: float = settings["focus_reset_s"]
        self.repeat_alert_s: float | None = settings["repeat_alert_s"]
        self.escalate_after: int | None = settings["escalate_after_repeats"]
        self.snooze_s: float = settings["snooze_s"]
        self.auto_pause_away_s: float = settings["auto_pause_away_s"]
        self.book = book
        self.wall_start = wall_start  # epoch seconds at session t = 0, for Alert.created_at

        self.state: FocusState = "focused"
        self.pause_reason: PauseReason | None = None
        self.focus_seconds = 0.0
        self._last_t: float | None = None
        self._focus_since: float | None = None
        self._event_start = 0.0
        self._event_label: Label | None = None
        self._event_key: int | None = None
        self._last_alert = 0.0
        self._repeats = 0
        self._snoozed_until: float | None = None
        self._snooze_key: int | None = None
        self._pause_key: int | None = None

    @property
    def distraction_alert_active(self) -> bool:
        """True while a distraction alert stands; posture alerts are held back then."""
        return self.state == "distracted"

    # --- per frame ----------------------------------------------------------------------

    def update(self, ds: DetectorState) -> FocusUpdate:
        t = ds.t
        events: list[EventRecord] = []
        alerts: list[Alert] = []
        if self.state == "paused":
            return self._report(t, None, alerts, events)

        dt = 0.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t

        if self._snoozed_until is not None and t >= self._snoozed_until:
            events += self.unsnooze(t)

        if ds.away_for_s >= self.auto_pause_away_s:
            events += self.pause(t, "away")
            return self._report(t, None, alerts, events)

        label = ds.label
        focused_now = label is None and ds.away_for_s == 0
        if focused_now:
            if self._focus_since is None:
                self._focus_since = t
        else:
            self._focus_since = None
        focus_run = t - self._focus_since if self._focus_since is not None else 0.0

        if self.state == "focused":
            self.focus_seconds += dt
            if label is not None:
                self.state = "pending"
                self._event_start = t
                self._event_label = label

        elif self.state == "pending":
            self.focus_seconds += dt
            if label is not None:
                self._event_label = _higher(self._event_label, label)
            if focus_run >= self.focus_reset_s:
                self.state = "focused"  # a harmless moment: not logged
                self._event_label = None
            elif label is not None and t - self._event_start >= self._threshold(ds):
                # The pending time turned out to be distraction, not focus.
                self.focus_seconds -= t - self._event_start
                self.state = "distracted"
                assert self._event_label is not None
                kind: EventKind = "away" if self._event_label == "away" else "distraction"
                rec = self.book.open(kind, self._event_label, self._event_start)
                self._event_key = rec.key
                events.append(rec)
                self._repeats = 0
                self._alert(t, label, PATTERN_DISTRACTION, alerts, events)

        elif self.state == "distracted":
            if label is not None:
                self._event_label = _higher(self._event_label, label)
            if focus_run >= self.focus_reset_s:
                events += self._end_distraction(t)
                self.focus_seconds += focus_run
            elif (
                label is not None and self.repeat_alert_s is not None
                and t - self._last_alert >= self.repeat_alert_s
            ):
                self._repeats += 1
                escalated = self.escalate_after is not None and self._repeats >= self.escalate_after
                self._alert(t, label, PATTERN_ESCALATED if escalated else PATTERN_DISTRACTION, alerts, events)

        return self._report(t, ds, alerts, events)

    # --- user actions -------------------------------------------------------------------

    def pause(self, t: float, reason: PauseReason = "pause") -> list[EventRecord]:
        """Pause, Break or auto-pause. Ends any distraction; Resume returns to Focused."""
        if self.state == "paused":
            return []
        events = self._end_distraction(t) if self.state == "distracted" else []
        self.state = "paused"
        self.pause_reason = reason
        rec = self.book.open("break" if reason == "break" else "pause", "away" if reason == "away" else None, t)
        self._pause_key = rec.key
        return events + [rec]

    def resume(self, t: float) -> list[EventRecord]:
        if self.state != "paused":
            return []
        events = []
        if self._pause_key is not None:
            events.append(self.book.close(self._pause_key, t))
            self._pause_key = None
        self.state = "focused"
        self.pause_reason = None
        self._event_label = None
        self._focus_since = None
        self._last_t = None  # don't count the pause as focus time
        return events

    def snooze(self, t: float) -> list[EventRecord]:
        """Mute alerts for snooze_s; detection, timers and logging carry on."""
        if self._snoozed_until is not None:
            return []
        self._snoozed_until = t + self.snooze_s
        rec = self.book.open("snooze", None, t)
        self._snooze_key = rec.key
        return [rec]

    def unsnooze(self, t: float) -> list[EventRecord]:
        if self._snoozed_until is None:
            return []
        end = min(t, self._snoozed_until)
        self._snoozed_until = None
        key, self._snooze_key = self._snooze_key, None
        return [self.book.close(key, end)] if key is not None else []

    def end(self, t: float) -> list[EventRecord]:
        """End of session: close everything still open."""
        events = self._end_distraction(t) if self.state == "distracted" else []
        events += self.book.close_all(t)
        self.state = "paused"
        self._pause_key = self._snooze_key = None
        self._snoozed_until = None
        return events

    # --- helpers --------------------------------------------------------------------------

    def _threshold(self, ds: DetectorState) -> float:
        kind = ds.distraction_type
        assert kind is not None
        return self.thresholds[kind]

    def _alert(self, t: float, label: Label, pattern: int, alerts: list[Alert], events: list[EventRecord]) -> None:
        self._last_alert = t  # the repeat schedule carries on through a snooze
        if self._snoozed_until is not None:
            return
        alerts.append(Alert(kind="distraction", label=label, pattern=pattern, created_at=self.wall_start + t))
        events.append(self.book.instant("alert", label, t))

    def _end_distraction(self, t: float) -> list[EventRecord]:
        """Close the open distraction event. It ended when the focus run began, if it did."""
        end = self._focus_since if self._focus_since is not None else t
        events = []
        if self._event_key is not None:
            events.append(self.book.close(self._event_key, end, self._event_label))
        self._event_key = None
        self._event_label = None
        self.state = "focused"
        self._repeats = 0
        return events

    def _report(self, t: float, ds: DetectorState | None, alerts: list[Alert], events: list[EventRecord]) -> FocusUpdate:
        pending = self.state in ("pending", "distracted")
        alert_in = None
        if self.state == "pending" and ds is not None and ds.distraction_type is not None:
            alert_in = max(0.0, self._threshold(ds) - (t - self._event_start))
        next_repeat = None
        if self.state == "distracted" and self.repeat_alert_s is not None:
            next_repeat = max(0.0, self.repeat_alert_s - (t - self._last_alert))
        return FocusUpdate(
            t=t,
            state=self.state,
            label=self._event_label if pending else None,
            pending_s=t - self._event_start if pending else 0.0,
            alert_in_s=alert_in,
            next_repeat_in_s=next_repeat,
            repeats=self._repeats,
            focus_run_s=t - self._focus_since if self._focus_since is not None else 0.0,
            snoozed_for_s=max(0.0, self._snoozed_until - t) if self._snoozed_until is not None else 0.0,
            focus_seconds=self.focus_seconds,
            pause_reason=self.pause_reason,
            alerts=alerts,
            events=events,
        )
