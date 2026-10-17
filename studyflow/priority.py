"""Priority engine: how much time is left for each study point, and which to start first.

Pure logic. It reads a Database and never changes it, and it never reads the clock by itself
(pass `now=`), so every result can be tested exactly.

The rules (the numbers are in PlanSettings):

1. effort      A point's own effort estimate, or `default_effort_hours` if it has none.
2. start_by    deadline - (effort / hours_per_day) days.
                 e.g. 3 h of effort at 2 h/day needs 1.5 days, so start 1.5 days before the deadline.
3. status      OVERDUE      deadline has passed
               START_NOW    start_by has passed (you are already late to start)
               SOON         start_by is within `soon_days` from now
               ON_TRACK     start_by is further away
               NO_DEADLINE  no deadline set
               DONE         marked done (only listed with include_done=True)
4. order       OVERDUE (most overdue first), then by start_by (earliest first), then NO_DEADLINE
               (oldest first), then DONE. Ranking by start_by instead of deadline means a big task
               due later can correctly come before a small task due sooner.
5. at_risk     True when the TOTAL effort of every unfinished point due on or before this one is more
               than the study hours available before its deadline (hours_per_day x days left).
               Rule 2 looks at each point alone; this rule catches the case where several deadlines
               pile up and you cannot do them all. It always looks at all subjects together,
               because you study with the same hours whatever the subject.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from .models import Database, StudyPoint, to_utc, utc_now


class Status(str, Enum):
    OVERDUE = "overdue"
    START_NOW = "start_now"
    SOON = "soon"
    ON_TRACK = "on_track"
    NO_DEADLINE = "no_deadline"
    DONE = "done"


@dataclass(frozen=True)
class PlanSettings:
    hours_per_day: float = 2.0  # study hours the user can realistically give per day
    default_effort_hours: float = 1.0  # used for points without an estimate
    soon_days: float = 2.0  # "SOON" = start_by is at most this many days away

    def __post_init__(self) -> None:
        if not (math.isfinite(self.hours_per_day) and 0 < self.hours_per_day <= 24):
            raise ValueError("hours_per_day must be more than 0 and at most 24")
        if not (math.isfinite(self.default_effort_hours) and self.default_effort_hours > 0):
            raise ValueError("default_effort_hours must be more than 0")
        if not (math.isfinite(self.soon_days) and self.soon_days >= 0):
            raise ValueError("soon_days cannot be negative")


@dataclass(frozen=True)
class PointPriority:
    subject_id: str
    subject_name: str
    point: StudyPoint
    status: Status
    deadline: Optional[datetime]
    time_remaining: Optional[timedelta]  # negative when overdue; None without deadline or when done
    effort_hours: float  # the effort actually used (estimate or default)
    effort_estimated: bool  # False when the default was used
    start_by: Optional[datetime]
    at_risk: bool

    @property
    def remaining_text(self) -> str:
        return "done" if self.status is Status.DONE else format_remaining(self.time_remaining)


def format_remaining(delta: Optional[timedelta]) -> str:
    """'3d 4h left', '5h 30m left', '20m left', 'overdue by 2d 1h', 'no deadline'."""
    if delta is None:
        return "no deadline"
    total = int(abs(delta.total_seconds()))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    text = f"{days}d {hours}h" if days else f"{hours}h {minutes}m" if hours else f"{minutes}m"
    return f"overdue by {text}" if delta.total_seconds() < 0 else f"{text} left"


def _effort(point: StudyPoint, settings: PlanSettings) -> float:
    return point.effort_hours if point.effort_hours else settings.default_effort_hours


def _at_risk_ids(pending, now: datetime, settings: PlanSettings) -> set[str]:
    """Rule 5: running total of effort in deadline order versus the study hours available."""
    dated = sorted(
        ((p.deadline, p.id, _effort(p, settings)) for _s, p in pending if p.deadline is not None),
        key=lambda t: (t[0], t[1]),
    )
    risky, total = set(), 0.0
    for deadline, point_id, effort in dated:
        total += effort
        days_left = max(0.0, (deadline - now).total_seconds()) / 86400
        if total > settings.hours_per_day * days_left + 1e-9:
            risky.add(point_id)
    return risky


def rank_points(
    db: Database,
    now: Optional[datetime] = None,
    settings: Optional[PlanSettings] = None,
    subject_id: Optional[str] = None,
    include_done: bool = False,
) -> list[PointPriority]:
    """Every (unfinished) study point, most urgent first. Pass subject_id to list one subject only."""
    settings = settings or PlanSettings()
    now = utc_now() if now is None else to_utc(now)
    soon = timedelta(days=settings.soon_days)
    if subject_id is not None:
        db.get_subject(subject_id)  # NotFoundError for a bad id

    pending = [(s, p) for s in db.subjects for p in s.points if not p.done]
    risky = _at_risk_ids(pending, now, settings)

    rows: list[PointPriority] = []
    for subject in db.subjects:
        if subject_id is not None and subject.id != subject_id:
            continue
        for p in subject.points:
            effort = _effort(p, settings)
            base = dict(
                subject_id=subject.id,
                subject_name=subject.name,
                point=p,
                deadline=p.deadline,
                effort_hours=effort,
                effort_estimated=bool(p.effort_hours),
            )
            if p.done:
                if include_done:
                    rows.append(PointPriority(status=Status.DONE, time_remaining=None, start_by=None, at_risk=False, **base))
                continue
            if p.deadline is None:
                rows.append(PointPriority(status=Status.NO_DEADLINE, time_remaining=None, start_by=None, at_risk=False, **base))
                continue
            remaining = p.deadline - now
            start_by = p.deadline - timedelta(days=effort / settings.hours_per_day)
            if remaining <= timedelta(0):
                status = Status.OVERDUE
            elif start_by <= now:
                status = Status.START_NOW
            elif start_by - now <= soon:
                status = Status.SOON
            else:
                status = Status.ON_TRACK
            rows.append(
                PointPriority(status=status, time_remaining=remaining, start_by=start_by, at_risk=p.id in risky, **base)
            )

    rows.sort(key=_sort_key)
    return rows


def _sort_key(r: PointPriority):
    tail = (r.point.title.casefold(), r.point.id)
    if r.status is Status.OVERDUE:
        return (0, r.deadline, *tail)
    if r.status is Status.NO_DEADLINE:
        return (2, r.point.created_at, *tail)
    if r.status is Status.DONE:
        return (3, r.point.created_at, *tail)
    return (1, r.start_by, *tail)


def next_up(
    db: Database,
    now: Optional[datetime] = None,
    settings: Optional[PlanSettings] = None,
    subject_id: Optional[str] = None,
) -> Optional[PointPriority]:
    """The single point to study next, or None when nothing is left to do."""
    ranked = rank_points(db, now=now, settings=settings, subject_id=subject_id)
    return ranked[0] if ranked else None
