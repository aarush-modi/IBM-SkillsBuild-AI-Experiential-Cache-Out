"""Optional Pomodoro timer (DESIGN §8, FR-01): work and break periods that pause detection.

Pure timing on a monotonic clock (seconds), driven by the UI once a tick. A break pauses the
session like the Break button; when it ends, work resumes by itself. Manual pauses don't
stop the clock, so the rhythm stays predictable. Stdlib only; durations from settings.json.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Phase = Literal["work", "break"]


@dataclass(frozen=True)
class PomodoroTick:
    phase: Phase
    left_s: float                  # time left in this phase
    changed_to: Phase | None       # set on the tick a new phase begins


class Pomodoro:
    def __init__(self, work_min: float, break_min: float, now: float) -> None:
        self.work_s = work_min * 60
        self.break_s = break_min * 60
        self.phase: Phase = "work"
        self._phase_start = now

    @classmethod
    def from_settings(cls, settings: dict[str, Any], now: float) -> Pomodoro:
        p = settings["pomodoro"]
        return cls(p["work_min"], p["break_min"], now)

    def tick(self, now: float) -> PomodoroTick:
        length = self.work_s if self.phase == "work" else self.break_s
        changed: Phase | None = None
        if now - self._phase_start >= length:
            self.phase = "break" if self.phase == "work" else "work"
            self._phase_start = now
            changed = self.phase
            length = self.work_s if self.phase == "work" else self.break_s
        return PomodoroTick(self.phase, max(0.0, length - (now - self._phase_start)), changed)
