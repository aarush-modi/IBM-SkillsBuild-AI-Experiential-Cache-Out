"""Event records for the events table (DESIGN §8 and §11).

The state machine and the session logic describe what happened as EventRecords in session
time (seconds since session start). An event is reported once when it opens (ended_at None)
and once more when it closes, with the same key; storage turns those into one row.
Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EventKind = Literal["distraction", "away", "posture", "pause", "break", "snooze", "alert"]


@dataclass(frozen=True)
class EventRecord:
    key: int                 # same key for an event's open and close records
    kind: EventKind
    label: str | None        # phone, window, slouching, ...
    started_at: float        # session seconds
    ended_at: float | None   # None while the event is still open


class EventBook:
    """Hands out event keys and remembers open events, so they can be closed later."""

    def __init__(self) -> None:
        self._next = 1
        self._open: dict[int, EventRecord] = {}

    def open(self, kind: EventKind, label: str | None, t: float) -> EventRecord:
        rec = EventRecord(self._next, kind, label, t, None)
        self._next += 1
        self._open[rec.key] = rec
        return rec

    def close(self, key: int, t: float, label: str | None = None) -> EventRecord:
        """Close an open event; `label` replaces its label if given."""
        rec = self._open.pop(key)
        return EventRecord(rec.key, rec.kind, label if label is not None else rec.label, rec.started_at, t)

    def instant(self, kind: EventKind, label: str | None, t: float) -> EventRecord:
        """An event with no duration, such as an alert."""
        rec = EventRecord(self._next, kind, label, t, t)
        self._next += 1
        return rec

    def close_all(self, t: float) -> list[EventRecord]:
        return [self.close(k, t) for k in list(self._open)]
