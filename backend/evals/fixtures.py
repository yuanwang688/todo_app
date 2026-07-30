"""Named database seeds for eval scenarios.

Every fixture is built relative to `TODAY` so date arithmetic is stable — no
scenario depends on the real clock. `TODAY` is a Monday, which keeps
week-boundary reasoning obvious.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

TODAY = date(2026, 8, 3)  # Monday
assert TODAY.isoweekday() == 1, "fixtures assume TODAY is a Monday"


def d(offset: int) -> date:
    """A date `offset` days from TODAY."""
    return TODAY + timedelta(days=offset)


def _todo(
    title: str,
    *,
    category: str | None = None,
    description: str | None = None,
    completed: bool = False,
    target_date: date | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    estimated_effort: float | None = None,
    importance: int | None = None,
    is_focus: bool = False,
    locked: bool = False,
) -> dict:
    return dict(
        title=title,
        description=description,
        category=category,
        completed=completed,
        target_date=target_date,
        start_date=start_date,
        end_date=end_date,
        estimated_effort=estimated_effort,
        importance=importance,
        is_focus=is_focus,
        locked=locked,
    )


def mixed_40() -> list[dict]:
    """A realistic, cluttered list: 40 tasks across all four quadrants.

    Contains, by construction:
      - 4 overdue tasks
      - 3 locked tasks (2 of which are otherwise prime deferral candidates)
      - 8 tasks with no importance set
      - 5 quick wins (effort <= 0.5h) and several multi-hour tasks
      - 9 undated tasks
      - a week that is over capacity
    """
    return [
        # ── overdue ─────────────────────────────────────────────────────────
        _todo("Submit expense report for June", category="Work", target_date=d(-9),
              estimated_effort=0.5, importance=2),
        _todo("Renew car insurance", category="Personal", target_date=d(-4),
              estimated_effort=1.0, importance=3),
        _todo("Reply to Dana about the contract", category="Work", target_date=d(-2),
              estimated_effort=0.25, importance=3),
        _todo("Return the library books", category="Personal", target_date=d(-1),
              estimated_effort=0.5, importance=1),
        # ── due today / this week, Work ─────────────────────────────────────
        _todo("Finish Q3 roadmap draft", category="Work", target_date=d(0),
              estimated_effort=3.0, importance=3, is_focus=True),
        _todo("Review Priya's pull request", category="Work", target_date=d(0),
              estimated_effort=1.0, importance=3),
        _todo("Update the on-call runbook", category="Work", target_date=d(1),
              estimated_effort=2.0, importance=2),
        _todo("Prep slides for Thursday sync", category="Work", target_date=d(3),
              estimated_effort=2.5, importance=3),
        _todo("Book the offsite venue", category="Work", target_date=d(4),
              estimated_effort=1.5, importance=2, locked=True),
        _todo("Refactor the export job", category="Work", start_date=d(1), end_date=d(4),
              estimated_effort=6.0, importance=2),
        _todo("Chase the vendor invoice", category="Work", target_date=d(2),
              estimated_effort=0.5, importance=1),
        _todo("Write the incident postmortem", category="Work", target_date=d(2),
              estimated_effort=2.0, importance=3),
        # ── this week, Personal / Home ──────────────────────────────────────
        _todo("Dentist appointment", category="Personal", target_date=d(2),
              estimated_effort=1.5, importance=3, locked=True),
        _todo("Buy a birthday present for Sam", category="Personal", target_date=d(5),
              estimated_effort=1.0, importance=2),
        _todo("Fix the leaking tap", category="Home", target_date=d(6),
              estimated_effort=1.0, importance=1),
        _todo("Sort out the recycling", category="Home", target_date=d(3),
              estimated_effort=0.25, importance=1),
        _todo("Water the plants", category="Home", target_date=d(1),
              estimated_effort=0.25, importance=1),
        # ── next week and beyond ────────────────────────────────────────────
        _todo("Draft the 2027 budget", category="Work", target_date=d(11),
              estimated_effort=4.0, importance=3),
        _todo("Performance review self-assessment", category="Work", target_date=d(14),
              estimated_effort=2.0, importance=3),
        _todo("Renew passport", category="Personal", target_date=d(21),
              estimated_effort=2.0, importance=3),
        _todo("Service the boiler", category="Home", target_date=d(18),
              estimated_effort=1.5, importance=2, locked=True),
        _todo("Plan the summer holiday", category="Personal", start_date=d(9), end_date=d(13),
              estimated_effort=3.0, importance=2),
        _todo("Clear out the garage", category="Home", target_date=d(26),
              estimated_effort=4.0, importance=1),
        _todo("Cancel the unused gym membership", category="Personal", target_date=d(10),
              estimated_effort=0.25, importance=2),
        # ── unclassified (importance is None) ───────────────────────────────
        _todo("Look into the new analytics tool", category="Work", target_date=d(8),
              estimated_effort=2.0),
        _todo("Tidy the shared drive", category="Work", estimated_effort=1.5),
        _todo("Read the architecture RFC", category="Work", target_date=d(5),
              estimated_effort=1.0),
        _todo("Set up the standing desk", category="Home", estimated_effort=1.0),
        _todo("Back up the family photos", category="Personal", estimated_effort=2.0),
        _todo("Find a new dentist for the kids", category="Personal", target_date=d(30),
              estimated_effort=1.0),
        _todo("Try the new deployment script", category="Work", estimated_effort=0.5),
        _todo("Sort the bookshelf", category="Home", estimated_effort=1.0),
        # ── undated ─────────────────────────────────────────────────────────
        _todo("Learn more about vector databases", category="Work", estimated_effort=4.0,
              importance=1),
        _todo("Write up the team onboarding notes", category="Work", estimated_effort=3.0,
              importance=2),
        _todo("Replace the hallway bulb", category="Home", estimated_effort=0.25,
              importance=1),
        _todo("Call the bank about the fee", category="Personal", estimated_effort=0.5,
              importance=2),
        _todo("Organise the photo albums", category="Personal", estimated_effort=5.0,
              importance=1),
        # ── completed (must be ignored by workload maths) ───────────────────
        _todo("Pay the electricity bill", category="Home", completed=True,
              target_date=d(-3), estimated_effort=0.25, importance=2),
        _todo("Ship the hotfix", category="Work", completed=True, target_date=d(-1),
              estimated_effort=1.0, importance=3),
        _todo("Send the sprint summary", category="Work", completed=True, target_date=d(0),
              estimated_effort=0.5, importance=2),
    ]


def overloaded_week() -> list[dict]:
    """One day carrying 14h of work against a 4h capacity.

    All effort lands on TODAY so the overage is unambiguous: 14 - 4 = 10.
    """
    return [
        _todo("Migrate the billing schema", category="Work", target_date=d(0),
              estimated_effort=5.0, importance=3),
        _todo("Write the migration tests", category="Work", target_date=d(0),
              estimated_effort=3.0, importance=3),
        _todo("Review the design doc", category="Work", target_date=d(0),
              estimated_effort=2.0, importance=2),
        _todo("Update the API docs", category="Work", target_date=d(0),
              estimated_effort=2.0, importance=1),
        _todo("Triage the bug backlog", category="Work", target_date=d(0),
              estimated_effort=1.5, importance=1),
        _todo("Reply to the support thread", category="Work", target_date=d(0),
              estimated_effort=0.5, importance=2),
        # Elsewhere in the week, comfortably within capacity.
        _todo("One-on-one with Priya", category="Work", target_date=d(2),
              estimated_effort=1.0, importance=3),
        _todo("Groceries", category="Home", target_date=d(5),
              estimated_effort=1.0, importance=2),
    ]


def duplicates() -> list[dict]:
    """One exact-duplicate pair, plus two pairs that only *look* similar."""
    return [
        # Genuine duplicate — same task entered twice.
        _todo("Book flights to Lisbon", category="Personal", target_date=d(7),
              estimated_effort=1.0, importance=3),
        _todo("Book flights to Lisbon", category="Personal", target_date=d(9),
              estimated_effort=1.0, importance=2),
        # Similar wording, genuinely different tasks — must NOT be deduped.
        _todo("Review the auth PR", category="Work", target_date=d(1),
              estimated_effort=1.0, importance=3),
        _todo("Review the billing PR", category="Work", target_date=d(1),
              estimated_effort=1.0, importance=3),
        # Same verb, different object — also must NOT be deduped.
        _todo("Call the dentist", category="Personal", target_date=d(3),
              estimated_effort=0.25, importance=2),
        _todo("Call the plumber", category="Home", target_date=d(3),
              estimated_effort=0.25, importance=2),
        _todo("Pack for the trip", category="Personal", target_date=d(12),
              estimated_effort=2.0, importance=2),
    ]


FIXTURES: dict[str, Callable[[], list[dict]]] = {
    "mixed_40": mixed_40,
    "overloaded_week": overloaded_week,
    "duplicates": duplicates,
}


def build(name: str) -> list[dict]:
    if name not in FIXTURES:
        raise KeyError(f"unknown fixture {name!r}; known: {sorted(FIXTURES)}")
    return FIXTURES[name]()
