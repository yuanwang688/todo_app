"""Unit tests for the deterministic triage policy (TRIAGE.md §1 and §4).

These are the half of triage that must never involve a model. They pass from
Phase A onwards — unlike the eval scenarios, which are the spec for the agent
and fail until Phase B.
"""
from datetime import date

import pytest

from app import triage

MONDAY = date(2026, 8, 3)
SATURDAY = date(2026, 8, 8)


class Task:
    """Minimal stand-in for a Todo row."""

    def __init__(self, **kw):
        defaults = dict(
            title="t", completed=False, target_date=None, start_date=None, end_date=None,
            estimated_effort=None, importance=None, is_focus=False, locked=False,
        )
        self.__dict__.update({**defaults, **kw})


# ── urgency ─────────────────────────────────────────────────────────────────


def test_undated_task_is_never_urgent():
    assert not triage.is_urgent(Task(), MONDAY)
    assert not triage.is_urgent(Task(importance=3), MONDAY)


@pytest.mark.parametrize("offset,expected", [(-5, True), (0, True), (3, True), (4, False), (30, False)])
def test_urgency_horizon(offset, expected):
    task = Task(target_date=date.fromordinal(MONDAY.toordinal() + offset))
    assert triage.is_urgent(task, MONDAY) is expected


def test_focus_task_is_urgent_even_without_a_date():
    assert triage.is_urgent(Task(is_focus=True), MONDAY)


def test_end_date_is_used_when_no_target_date():
    task = Task(start_date=MONDAY, end_date=date(2026, 8, 4))
    assert triage.effective_due_date(task) == date(2026, 8, 4)
    assert triage.is_urgent(task, MONDAY)


def test_overdue_detection():
    assert triage.is_overdue(Task(target_date=date(2026, 7, 30)), MONDAY)
    assert not triage.is_overdue(Task(target_date=MONDAY), MONDAY)
    assert not triage.is_overdue(Task(), MONDAY)


# ── quadrants ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "importance,offset,expected",
    [
        (3, 1, "Q1"),   # urgent + important
        (3, 30, "Q2"),  # important, not urgent
        (1, 1, "Q3"),   # urgent, not important
        (1, 30, "Q4"),  # neither
    ],
)
def test_quadrant_assignment(importance, offset, expected):
    task = Task(importance=importance, target_date=date.fromordinal(MONDAY.toordinal() + offset))
    assert triage.quadrant(task, MONDAY) == expected


def test_unclassified_importance_is_not_treated_as_important():
    task = Task(target_date=date(2026, 8, 4))  # urgent, importance None
    assert triage.is_unclassified(task)
    assert triage.quadrant(task, MONDAY) == "Q3"


def test_every_quadrant_has_a_documented_action():
    assert set(triage.QUADRANT_ACTIONS) == {"Q1", "Q2", "Q3", "Q4"}


# ── phrasing ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "offset,expected",
    [(-1, "overdue by 1 day"), (-4, "overdue by 4 days"), (0, "due today"),
     (1, "due tomorrow"), (5, "due in 5 days")],
)
def test_describe_due(offset, expected):
    task = Task(target_date=date.fromordinal(MONDAY.toordinal() + offset))
    assert triage.describe_due(task, MONDAY) == expected


def test_describe_due_undated():
    assert triage.describe_due(Task(), MONDAY) == "no date"


# ── workload ────────────────────────────────────────────────────────────────


def test_target_date_task_consumes_full_effort_on_its_day():
    load = triage.day_load([Task(target_date=MONDAY, estimated_effort=3.0)], MONDAY)
    assert load.scheduled_hours == 3.0
    assert load.capacity_hours == 4.0
    assert not load.is_overloaded


def test_ranged_task_spreads_effort_evenly():
    task = Task(start_date=MONDAY, end_date=date(2026, 8, 5), estimated_effort=6.0)  # 3 days
    assert triage.day_load([task], MONDAY).scheduled_hours == 2.0
    assert triage.total_scheduled_hours([task], MONDAY, date(2026, 8, 5)) == 6.0


def test_completed_tasks_consume_nothing():
    task = Task(target_date=MONDAY, estimated_effort=8.0, completed=True)
    assert triage.day_load([task], MONDAY).scheduled_hours == 0.0


def test_non_workdays_have_zero_capacity():
    load = triage.day_load([Task(target_date=SATURDAY, estimated_effort=1.0)], SATURDAY)
    assert load.capacity_hours == 0.0
    assert load.is_overloaded


def test_overage_is_reported_as_a_number():
    tasks = [Task(target_date=MONDAY, estimated_effort=e) for e in (5.0, 3.0, 2.0, 2.0, 1.5, 0.5)]
    load = triage.day_load(tasks, MONDAY)
    assert load.scheduled_hours == 14.0
    assert load.overage_hours == 10.0


def test_week_bounds_is_monday_to_sunday():
    assert triage.week_bounds(date(2026, 8, 5)) == (date(2026, 8, 3), date(2026, 8, 9))
    assert triage.week_bounds(date(2026, 8, 9)) == (date(2026, 8, 3), date(2026, 8, 9))


# ── field whitelist ─────────────────────────────────────────────────────────


def test_forbidden_fields_are_disjoint_from_writable_ones():
    assert not (triage.AGENT_WRITABLE_ON_CREATE & triage.AGENT_FORBIDDEN_FIELDS)


def test_completed_and_locked_are_never_writable():
    assert "completed" in triage.AGENT_FORBIDDEN_FIELDS
    assert "locked" in triage.AGENT_FORBIDDEN_FIELDS


def test_title_is_writable_only_on_create():
    assert "title" not in triage.AGENT_WRITABLE_FIELDS
    assert "title" in triage.AGENT_WRITABLE_ON_CREATE
