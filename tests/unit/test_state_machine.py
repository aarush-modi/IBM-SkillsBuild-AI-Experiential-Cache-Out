"""Focus state machine (DESIGN §8). The §8 table and diagram are the oracle."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from app.contracts import PATTERN_DISTRACTION, PATTERN_ESCALATED
from app.logic.detectors import DetectorState
from app.logic.events import EventBook, EventRecord
from app.logic.state_machine import FocusStateMachine, FocusUpdate
from app.storage.settings import DEFAULTS

FPS = 5
WALL = 1_700_000_000.0


def settings(**kw: Any) -> dict[str, Any]:
    s = copy.deepcopy(DEFAULTS)
    s.update(kw)
    return s


def machine(s: dict[str, Any] | None = None) -> FocusStateMachine:
    return FocusStateMachine(s or settings(), EventBook(), WALL)


def ds(t: float, label: str | None = None, absent_s: float = 0.0) -> DetectorState:
    """Detector output with one distraction (or none). absent_s > 0 without label 'away'
    is a short absence: not yet the away detector."""
    return DetectorState(
        t=t,
        phone=label == "phone",
        desk_object=label == "desk_object",
        looking_away=label in ("looking_away", "window"),
        window=label == "window",
        away=label == "away",
        away_for_s=absent_s if label != "away" else max(absent_s, DEFAULTS["away_detect_s"]),
    )


class Run:
    """Drives a machine through time and collects everything it reports."""

    def __init__(self, m: FocusStateMachine) -> None:
        self.m = m
        self.t = 0.0
        self.updates: list[FocusUpdate] = []

    def hold(self, seconds: float, label: str | None = None, absent_s: float | None = None) -> FocusUpdate:
        """Frames from the current time for `seconds`, at FPS; the clock ends at start + seconds."""
        start = self.t
        for i in range(round(seconds * FPS)):
            t = round(start + i / FPS, 6)
            absent = 0.0 if absent_s is None else absent_s + (t - start)
            self.updates.append(self.m.update(ds(t, label, absent)))
        self.t = round(start + seconds, 6)
        return self.updates[-1]

    @property
    def alerts(self) -> list[tuple[float, str, int]]:
        return [(round(u.t, 1), a.label, a.pattern) for u in self.updates for a in u.alerts]

    @property
    def events(self) -> list[EventRecord]:
        return [e for u in self.updates for e in u.events]


# --- focused and pending ------------------------------------------------------------------

def test_focused_stays_focused_and_counts_time() -> None:
    r = Run(machine())
    u = r.hold(30)
    assert u.state == "focused" and u.focus_seconds == pytest.approx(30, abs=0.3)
    assert r.alerts == [] and r.events == []


def test_first_alert_after_threshold() -> None:
    r = Run(machine())
    r.hold(10)
    u = r.hold(30, "phone")
    assert u.state == "pending" and u.alert_in_s == pytest.approx(30, abs=0.3)
    r.hold(31, "phone")
    assert r.alerts == [(70.0, "phone", PATTERN_DISTRACTION)]
    assert r.updates[-1].state == "distracted"
    opened = r.events[0]
    assert (opened.kind, opened.label, opened.ended_at) == ("distraction", "phone", None)
    assert opened.started_at == pytest.approx(10.0)
    assert r.events[1].kind == "alert"


def test_alert_created_at_is_wall_time() -> None:
    r = Run(machine())
    r.hold(61, "phone")
    alert = next(a for u in r.updates for a in u.alerts)
    assert alert.created_at == pytest.approx(WALL + 60, abs=0.3)
    assert alert.kind == "distraction"


def test_harmless_glance_is_cancelled_and_not_logged() -> None:
    r = Run(machine())
    r.hold(40, "looking_away")
    u = r.hold(6)  # 5 s of continuous focus cancels it
    assert u.state == "focused"
    r.hold(60)
    assert r.alerts == [] and r.events == []


def test_focus_must_be_continuous() -> None:
    r = Run(machine())
    for _ in range(8):  # 4 s focus, 6 s distraction, repeated: never 5 s in a row
        r.hold(6, "phone")
        r.hold(4)
    assert r.alerts and r.alerts[0][1] == "phone"


def test_threshold_is_per_type() -> None:
    s = settings()
    s["distraction_threshold_s"]["phone"] = 30
    r = Run(machine(s))
    r.hold(31, "phone")
    assert r.alerts == [(30.0, "phone", PATTERN_DISTRACTION)]


# --- type changes -------------------------------------------------------------------------

def test_one_timer_across_type_change_and_current_threshold() -> None:
    s = settings()
    s["distraction_threshold_s"]["phone"] = 30
    r = Run(machine(s))
    r.hold(40, "looking_away")  # under the 60 s looking-away threshold
    r.hold(1, "phone")          # already 40 s into the distraction: past the 30 s phone threshold
    assert r.alerts == [(40.0, "phone", PATTERN_DISTRACTION)]


def test_event_keeps_highest_priority_label() -> None:
    r = Run(machine())
    r.hold(30, "phone")
    r.hold(40, "looking_away")
    r.hold(6)
    closed = [e for e in r.events if e.kind == "distraction" and e.ended_at is not None]
    assert closed[0].label == "phone"
    assert r.alerts[0][1] == "looking_away"  # the alert carries the label at that moment


# --- repeats and escalation ---------------------------------------------------------------

def test_repeats_and_escalation() -> None:
    r = Run(machine())
    r.hold(541, "phone")
    # First alert at 60 s, repeats every 120 s; from the 3rd repeat the stronger pattern.
    assert r.alerts == [
        (60.0, "phone", PATTERN_DISTRACTION),
        (180.0, "phone", PATTERN_DISTRACTION),
        (300.0, "phone", PATTERN_DISTRACTION),
        (420.0, "phone", PATTERN_ESCALATED),
        (540.0, "phone", PATTERN_ESCALATED),
    ]


def test_repeats_off() -> None:
    r = Run(machine(settings(repeat_alert_s=None)))
    u = r.hold(400, "phone")
    assert len(r.alerts) == 1 and u.next_repeat_in_s is None


def test_escalation_off() -> None:
    r = Run(machine(settings(escalate_after_repeats=None)))
    r.hold(700, "phone")
    assert all(p == PATTERN_DISTRACTION for _, _, p in r.alerts)


# --- ending an event ------------------------------------------------------------------------

def test_five_seconds_of_focus_ends_the_event() -> None:
    r = Run(machine())
    r.hold(90, "phone")
    u = r.hold(6)
    assert u.state == "focused"
    closed = r.events[-1]
    assert closed.kind == "distraction" and closed.ended_at == pytest.approx(90.0)  # when focus began
    r.hold(200)
    assert len(r.alerts) == 1


def test_short_absence_is_not_focus() -> None:
    r = Run(machine())
    r.hold(30, "phone")
    u = r.hold(6, None, absent_s=0.2)  # stepped out of view for 6 s: not yet "away"
    assert u.state == "pending"
    r.hold(25, "phone")
    assert r.alerts and r.alerts[0][1] == "phone"


def test_focus_seconds_exclude_distraction() -> None:
    r = Run(machine())
    r.hold(100)
    r.hold(80, "phone")
    u = r.hold(20)
    # 100 focused + 20 after (the 80 s distraction, including its pending minute, is not focus).
    assert u.focus_seconds == pytest.approx(120, abs=0.5)


# --- away -----------------------------------------------------------------------------------

def test_away_alert_after_hold_and_logged_as_away() -> None:
    r = Run(machine())
    r.hold(61, "away")
    assert r.alerts == [(60.0, "away", PATTERN_DISTRACTION)]
    assert r.events[0].kind == "away"


def test_auto_pause_after_long_absence() -> None:
    r = Run(machine())
    u = r.hold(DEFAULTS["auto_pause_away_s"] + 1, "away", absent_s=10)
    assert u.state == "paused" and u.pause_reason == "away"
    kinds = [(e.kind, e.label, e.ended_at is None) for e in r.events if e.kind != "alert"]
    assert kinds[-2:] == [("away", "away", False), ("pause", "away", True)]


# --- pause, break, snooze, end ---------------------------------------------------------------

def test_pause_ends_distraction_and_ignores_frames() -> None:
    m = machine()
    r = Run(m)
    r.hold(70, "phone")
    events = m.pause(r.t)
    assert [e.kind for e in events] == ["distraction", "pause"]
    assert events[0].ended_at is not None
    u = r.hold(300, "phone")
    assert u.state == "paused" and len(r.alerts) == 1
    assert not m.distraction_alert_active


def test_resume_returns_to_focused_and_pause_is_not_focus_time() -> None:
    m = machine()
    r = Run(m)
    r.hold(50)
    m.pause(r.t, "break")
    r.t += 600  # ten minutes on a break
    events = m.resume(r.t)
    assert events[0].kind == "break" and events[0].ended_at == pytest.approx(r.t)
    u = r.hold(10)
    assert u.state == "focused" and u.focus_seconds == pytest.approx(60, abs=0.5)


def test_snooze_mutes_alerts_but_keeps_tracking() -> None:
    m = machine()
    r = Run(m)
    r.hold(30, "phone")
    m.snooze(r.t)
    u = r.hold(100, "phone")
    assert r.alerts == [] and u.state == "distracted" and u.snoozed_for_s > 0
    assert any(e.kind == "distraction" for e in r.events)  # still logged
    assert m.distraction_alert_active


def test_snooze_ends_by_itself_and_repeats_resume() -> None:
    m = machine()
    r = Run(m)
    m.snooze(0.0)
    r.hold(DEFAULTS["snooze_s"] + 130, "phone")
    assert r.alerts and r.alerts[0][0] >= DEFAULTS["snooze_s"]
    snooze = [e for e in r.events if e.kind == "snooze"]
    assert snooze and snooze[-1].ended_at == pytest.approx(DEFAULTS["snooze_s"])


def test_unsnooze_early() -> None:
    m = machine()
    r = Run(m)
    m.snooze(0.0)
    r.hold(70, "phone")
    m.unsnooze(r.t)
    r.hold(DEFAULTS["repeat_alert_s"], "phone")
    assert len(r.alerts) == 1  # the repeat after the silent first alert


def test_end_closes_everything() -> None:
    m = machine()
    r = Run(m)
    r.hold(70, "phone")
    m.snooze(r.t)
    events = m.end(r.t)
    assert {e.kind for e in events} == {"distraction", "snooze"}
    assert all(e.ended_at == pytest.approx(r.t) for e in events)
