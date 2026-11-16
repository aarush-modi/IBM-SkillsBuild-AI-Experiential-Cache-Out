"""End-of-session report data (DESIGN §10, FR-14), built only from what was stored.

The report reads the sessions, events and posture_samples rows, never live state, so it
matches the events logged during the session (DESIGN §12). Stdlib only.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.logic.posture import TIPS


@dataclass(frozen=True)
class DistractionStat:
    label: str        # phone, desk_object, looking_away, window, away
    count: int
    seconds: float


@dataclass(frozen=True)
class IssueStat:
    issue: str        # slouching, leaning_in, ...
    seconds: float    # total time posture was bad with this as the worst issue
    count: int
    tip: str


@dataclass(frozen=True)
class SessionReport:
    session_id: int
    started_at: datetime
    total_s: float                       # wall time from start to end
    paused_s: float                      # pauses and breaks (camera off)
    focus_s: float
    distractions: list[DistractionStat]  # most time first
    alerts: int
    posture_avg: float | None
    posture_points: list[tuple[float, float]]  # (minutes since start, score)
    top_issues: list[IssueStat]          # most time first

    @property
    def active_s(self) -> float:
        """Time the session was running (not paused or on a break)."""
        return max(0.0, self.total_s - self.paused_s)

    @property
    def focus_ratio(self) -> float | None:
        return self.focus_s / self.active_s if self.active_s > 0 else None

    @property
    def distraction_count(self) -> int:
        return sum(d.count for d in self.distractions)


def _seconds(e: dict[str, Any]) -> float:
    if not e.get("ended_at"):
        return 0.0
    return max(0.0, (datetime.fromisoformat(e["ended_at"]) - datetime.fromisoformat(e["started_at"])).total_seconds())


def build_report(
    session: dict[str, Any], events: list[dict[str, Any]], samples: list[dict[str, Any]], top_issues: int,
) -> SessionReport:
    started = datetime.fromisoformat(session["started_at"])
    ended = datetime.fromisoformat(session["ended_at"]) if session.get("ended_at") else started

    distraction_n: dict[str, int] = defaultdict(int)
    distraction_s: dict[str, float] = defaultdict(float)
    issue_n: dict[str, int] = defaultdict(int)
    issue_s: dict[str, float] = defaultdict(float)
    paused = 0.0
    alerts = 0
    for e in events:
        kind, label = e["kind"], e.get("label")
        if kind in ("distraction", "away") and label:
            distraction_n[label] += 1
            distraction_s[label] += _seconds(e)
        elif kind == "posture" and label:
            issue_n[label] += 1
            issue_s[label] += _seconds(e)
        elif kind in ("pause", "break"):
            paused += _seconds(e)
        elif kind == "alert":
            alerts += 1

    tips: dict[str, str] = {str(k): v for k, v in TIPS.items()}
    scored = [s for s in samples if s.get("score") is not None]
    return SessionReport(
        session_id=int(session["id"]),
        started_at=started,
        total_s=(ended - started).total_seconds(),
        paused_s=paused,
        focus_s=float(session.get("focus_seconds") or 0),
        distractions=sorted(
            (DistractionStat(k, distraction_n[k], distraction_s[k]) for k in distraction_n),
            key=lambda d: (-d.seconds, -d.count),
        ),
        alerts=alerts,
        posture_avg=sum(s["score"] for s in scored) / len(scored) if scored else None,
        posture_points=[(s["t"] / 60, s["score"]) for s in scored],
        top_issues=sorted(
            (IssueStat(k, issue_s[k], issue_n[k], tips.get(k, "")) for k in issue_n),
            key=lambda i: (-i.seconds, -i.count),
        )[:top_issues],
    )
