"""Stats history across days (DESIGN §10, FR-15): focus minutes per day, distractions per
hour of work and average posture score, for the last 7 or 30 days.

Aggregates per-session SessionReports (app/logic/report.py), so the dashboard and each
session's report always agree. Stdlib only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from app.logic.report import SessionReport


@dataclass(frozen=True)
class DayStats:
    day: date
    sessions: int
    focus_s: float
    active_s: float          # running time, without pauses and breaks
    distractions: int
    posture_avg: float | None
    posture_samples: int

    @property
    def distractions_per_hour(self) -> float | None:
        return self.distractions / (self.active_s / 3600) if self.active_s > 0 else None


@dataclass(frozen=True)
class PeriodStats:
    days: list[DayStats]     # every day in the period, oldest first, including empty days

    @property
    def total(self) -> DayStats:
        n = sum(d.posture_samples for d in self.days)
        weighted = sum((d.posture_avg or 0) * d.posture_samples for d in self.days)
        return DayStats(
            day=self.days[-1].day if self.days else date.today(),
            sessions=sum(d.sessions for d in self.days),
            focus_s=sum(d.focus_s for d in self.days),
            active_s=sum(d.active_s for d in self.days),
            distractions=sum(d.distractions for d in self.days),
            posture_avg=weighted / n if n else None,
            posture_samples=n,
        )


def build_stats(reports: list[SessionReport], last_day: date, n_days: int) -> PeriodStats:
    """Group sessions by the local day they started on, over the n_days ending on last_day."""
    first_day = last_day - timedelta(days=n_days - 1)
    by_day: dict[date, list[SessionReport]] = defaultdict(list)
    for r in reports:
        day = r.started_at.astimezone().date()
        if first_day <= day <= last_day:
            by_day[day].append(r)

    days = []
    for i in range(n_days):
        day = first_day + timedelta(days=i)
        rs = by_day.get(day, [])
        n = sum(len(r.posture_points) for r in rs)
        weighted = sum((r.posture_avg or 0) * len(r.posture_points) for r in rs)
        days.append(DayStats(
            day=day,
            sessions=len(rs),
            focus_s=sum(r.focus_s for r in rs),
            active_s=sum(r.active_s for r in rs),
            distractions=sum(r.distraction_count for r in rs),
            posture_avg=weighted / n if n else None,
            posture_samples=n,
        ))
    return PeriodStats(days)
