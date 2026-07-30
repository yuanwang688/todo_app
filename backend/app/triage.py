"""Deterministic triage policy — the executable form of TRIAGE.md.

Urgency, quadrant assignment and workload arithmetic are computed here, in
application code, and handed to the model as facts. The model explains and
proposes; it never computes these. Keep this module and TRIAGE.md in sync.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Protocol

DEFAULT_URGENCY_HORIZON_DAYS = 3
DEFAULT_DAILY_CAPACITY_HOURS = 4.0

#: Fields the assistant may write on an existing task. Enforced by the apply
#: layer (Phase C), not merely requested in the prompt.
AGENT_WRITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "category",
        "target_date",
        "start_date",
        "end_date",
        "estimated_effort",
        "importance",
        "is_focus",
    }
)

#: Additionally writable when creating a task (e.g. splitting a vague one).
AGENT_WRITABLE_ON_CREATE: frozenset[str] = AGENT_WRITABLE_FIELDS | {"title", "description"}

#: Never writable by the assistant, under any operation.
AGENT_FORBIDDEN_FIELDS: frozenset[str] = frozenset(
    {"completed", "locked", "id", "user_id", "created_at", "updated_at"}
)

DEFAULT_IMPORTANCE = 2  # used for sorting only; the task is still "unclassified"


class TaskLike(Protocol):
    """Structural type covering both the ORM model and plain fixture dicts."""

    title: str
    completed: bool
    target_date: date | None
    start_date: date | None
    end_date: date | None
    estimated_effort: float | None
    importance: int | None
    is_focus: bool
    locked: bool


def effective_due_date(task: TaskLike) -> date | None:
    """The date urgency is measured against: target_date, else end_date."""
    return task.target_date or task.end_date


def days_left(task: TaskLike, today: date) -> int | None:
    """Days until the task is due. Negative when overdue, None when undated."""
    due = effective_due_date(task)
    if due is None:
        return None
    return (due - today).days


def is_urgent(task: TaskLike, today: date, horizon_days: int = DEFAULT_URGENCY_HORIZON_DAYS) -> bool:
    """Urgency is derived, never stored. Undated tasks are never urgent."""
    if task.is_focus:
        return True
    remaining = days_left(task, today)
    if remaining is None:
        return False
    return remaining <= horizon_days


def is_overdue(task: TaskLike, today: date) -> bool:
    remaining = days_left(task, today)
    return remaining is not None and remaining < 0


def is_important(task: TaskLike) -> bool:
    """High importance only. Unclassified tasks fall back to the default."""
    return (task.importance if task.importance is not None else DEFAULT_IMPORTANCE) >= 3


def quadrant(task: TaskLike, today: date, horizon_days: int = DEFAULT_URGENCY_HORIZON_DAYS) -> str:
    """Eisenhower quadrant: Q1 do, Q2 schedule, Q3 minimise, Q4 defer/drop."""
    urgent = is_urgent(task, today, horizon_days)
    important = is_important(task)
    if urgent and important:
        return "Q1"
    if not urgent and important:
        return "Q2"
    if urgent and not important:
        return "Q3"
    return "Q4"


QUADRANT_ACTIONS = {
    "Q1": "Do — keep the date; consider making it the focus task.",
    "Q2": "Schedule — give it a target date or a start/end block.",
    "Q3": "Minimise — reduce the effort estimate or batch with similar tasks.",
    "Q4": "Defer or drop — push the date out, or propose deletion if also a duplicate.",
}


def describe_due(task: TaskLike, today: date) -> str:
    """Human-readable due phrasing — tools return this alongside raw dates."""
    remaining = days_left(task, today)
    if remaining is None:
        return "no date"
    if remaining < 0:
        n = -remaining
        return f"overdue by {n} day{'s' if n != 1 else ''}"
    if remaining == 0:
        return "due today"
    if remaining == 1:
        return "due tomorrow"
    return f"due in {remaining} days"


def is_unclassified(task: TaskLike) -> bool:
    return task.importance is None


# ── workload ────────────────────────────────────────────────────────────────


def occupies_day(task: TaskLike, day: date) -> bool:
    """Whether a task consumes effort on a given day.

    Mirrors the daily-view filter in the frontend: a target date lands on that
    day; a start/end range covers every day it spans.
    """
    if task.completed:
        return False
    if task.target_date == day:
        return True
    if task.start_date and task.end_date:
        return task.start_date <= day <= task.end_date
    return False


def _spread_effort(task: TaskLike, day: date) -> float:
    """Effort attributed to a single day.

    A ranged task spreads its estimate evenly across the days it spans, so a
    6-hour task over 3 days counts as 2 hours a day rather than 6 on each.
    """
    effort = task.estimated_effort or 0.0
    if task.target_date == day:
        return effort
    if task.start_date and task.end_date:
        span = (task.end_date - task.start_date).days + 1
        return effort / span if span > 0 else effort
    return 0.0


@dataclass(frozen=True)
class DayLoad:
    day: date
    scheduled_hours: float
    capacity_hours: float

    @property
    def overage_hours(self) -> float:
        return round(max(0.0, self.scheduled_hours - self.capacity_hours), 2)

    @property
    def is_overloaded(self) -> bool:
        return self.scheduled_hours > self.capacity_hours


def daterange(start: date, end: date) -> Iterable[date]:
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def day_load(
    tasks: Iterable[TaskLike],
    day: date,
    capacity_hours: float = DEFAULT_DAILY_CAPACITY_HOURS,
    workdays: frozenset[int] = frozenset({1, 2, 3, 4, 5}),
) -> DayLoad:
    """Scheduled effort for one day. Non-workdays have zero capacity."""
    scheduled = sum(_spread_effort(t, day) for t in tasks if occupies_day(t, day))
    effective_capacity = capacity_hours if day.isoweekday() in workdays else 0.0
    return DayLoad(day=day, scheduled_hours=round(scheduled, 2), capacity_hours=effective_capacity)


def workload(
    tasks: Iterable[TaskLike],
    start: date,
    end: date,
    capacity_hours: float = DEFAULT_DAILY_CAPACITY_HOURS,
    workdays: frozenset[int] = frozenset({1, 2, 3, 4, 5}),
) -> list[DayLoad]:
    tasks = list(tasks)
    return [day_load(tasks, d, capacity_hours, workdays) for d in daterange(start, end)]


def total_scheduled_hours(tasks: Iterable[TaskLike], start: date, end: date) -> float:
    """Total effort landing inside a window — the number `workload_decreases` grades."""
    tasks = list(tasks)
    return round(sum(_spread_effort(t, d) for d in daterange(start, end) for t in tasks if occupies_day(t, d)), 2)


def week_bounds(day: date) -> tuple[date, date]:
    """Monday–Sunday week containing `day`, matching the frontend weekly view."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)
