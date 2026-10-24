"""The assistant's planning tools (Phase D): get_workload_summary's per-day
breakdown and simulate_changes' dry-run projection. Every number the model
can state comes from here, so these pin the arithmetic directly."""
import json
from datetime import date, timedelta

import pytest_asyncio
from sqlalchemy import select

from app.agent.tools import TOOL_SCHEMAS, execute_tool
from app.models import Todo
from app.planning import DEFAULT_PREFERENCES

MONDAY = date(2026, 8, 3)
SUNDAY = MONDAY + timedelta(days=6)


def d(n: int) -> str:
    return (MONDAY + timedelta(days=n)).isoformat()


@pytest_asyncio.fixture
async def week(db, user):
    """Monday 7h (3h over), a locked 2h task Tuesday, a ranged 6h task Wed–Fri,
    one undated, one overdue, one completed (ignored)."""
    rows = {
        "big": Todo(user_id=user.id, title="Big", target_date=MONDAY, estimated_effort=5.0, importance=3),
        "small": Todo(user_id=user.id, title="Small", target_date=MONDAY, estimated_effort=2.0, importance=1),
        "locked": Todo(user_id=user.id, title="Locked", target_date=MONDAY + timedelta(days=1),
                       estimated_effort=2.0, locked=True),
        "ranged": Todo(user_id=user.id, title="Ranged", start_date=MONDAY + timedelta(days=2),
                       end_date=MONDAY + timedelta(days=4), estimated_effort=6.0, importance=2),
        "undated": Todo(user_id=user.id, title="Undated", estimated_effort=1.0),
        "overdue": Todo(user_id=user.id, title="Overdue", target_date=MONDAY - timedelta(days=2),
                        estimated_effort=1.0),
        "done": Todo(user_id=user.id, title="Done", target_date=MONDAY, estimated_effort=9.0, completed=True),
    }
    db.add_all(rows.values())
    await db.commit()
    return {k: str(v.id) for k, v in rows.items()}


async def run(db, user, name, prefs=None, **tool_input):
    content, is_error = await execute_tool(
        name, tool_input, db=db, user_id=user.id, today=MONDAY, preferences=prefs or DEFAULT_PREFERENCES
    )
    return json.loads(content), is_error


# ── get_workload_summary ────────────────────────────────────────────────────


async def test_workload_summary_totals_and_overage(db, user, week):
    out, err = await run(db, user, "get_workload_summary", start_date=d(0), end_date=d(6))
    assert not err
    days = {x["date"]: x for x in out["days"]}
    assert days[d(0)]["scheduled_hours"] == 7.0
    assert days[d(0)]["overage_hours"] == 3.0
    assert days[d(0)]["free_hours"] == 0.0
    assert days[d(1)]["free_hours"] == 2.0
    assert days[d(2)]["scheduled_hours"] == 2.0  # 6h spread over 3 days
    assert days[d(5)]["capacity_hours"] == 0.0 and not days[d(5)]["is_workday"]
    assert out["total_scheduled_hours"] == 15.0
    assert out["total_capacity_hours"] == 20.0
    assert out["overloaded_days"] == [d(0)]
    assert out["total_overage_hours"] == 3.0
    assert out["fits_in_range"] is True


async def test_workload_summary_lists_tasks_per_day_largest_first(db, user, week):
    out, _ = await run(db, user, "get_workload_summary", start_date=d(0), end_date=d(6))
    days = {x["date"]: x for x in out["days"]}
    assert [(t["title"], t["hours"]) for t in days[d(0)]["tasks"]] == [("Big", 5.0), ("Small", 2.0)]
    assert days[d(1)]["tasks"][0]["locked"] is True
    ranged = days[d(3)]["tasks"][0]
    assert ranged["title"] == "Ranged" and ranged["hours"] == 2.0 and ranged["spread_over_range"] is True


async def test_workload_summary_reports_undated_and_overdue(db, user, week):
    out, _ = await run(db, user, "get_workload_summary", start_date=d(0), end_date=d(6))
    assert [t["title"] for t in out["undated_incomplete_tasks"]] == ["Undated"]
    assert [(t["title"], t["due"]) for t in out["overdue_tasks"]] == [("Overdue", "overdue by 2 days")]


async def test_workload_summary_uses_preferences(db, user, week):
    prefs = {**DEFAULT_PREFERENCES, "daily_capacity_hours": 8.0, "workdays": [1, 2, 3, 4, 5, 6, 7]}
    out, _ = await run(db, user, "get_workload_summary", prefs, start_date=d(0), end_date=d(6))
    assert out["total_capacity_hours"] == 56.0
    assert out["overloaded_days"] == []


async def test_workload_summary_rejects_inverted_range(db, user, week):
    out, err = await run(db, user, "get_workload_summary", start_date=d(3), end_date=d(0))
    assert err and "before" in out["error"]


# ── urgency horizon threads through every read tool ─────────────────────────


async def test_quadrant_uses_the_users_urgency_horizon(db, user):
    todo = Todo(user_id=user.id, title="Due in 5", target_date=MONDAY + timedelta(days=5), importance=3)
    db.add(todo)
    await db.commit()
    default, _ = await run(db, user, "search_todos")
    wide, _ = await run(db, user, "search_todos", {**DEFAULT_PREFERENCES, "urgency_horizon_days": 7})
    assert default["tasks"][0]["quadrant"] == "Q2"
    assert wide["tasks"][0]["quadrant"] == "Q1"
    details, _ = await run(db, user, "get_todo_details", {**DEFAULT_PREFERENCES, "urgency_horizon_days": 7},
                           todo_id=str(todo.id))
    assert details["quadrant"] == "Q1"


# ── simulate_changes ────────────────────────────────────────────────────────


async def test_simulate_reports_before_and_after(db, user, week):
    out, err = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["small"], "changes": {"target_date": d(1)}},
    ])
    assert not err
    days = {x["date"]: x for x in out["days"]}
    assert days[d(0)]["scheduled_hours_before"] == 7.0
    assert days[d(0)]["scheduled_hours_after"] == 5.0
    assert days[d(0)]["overage_hours_after"] == 1.0
    assert days[d(1)]["scheduled_hours_after"] == 4.0
    assert out["overloaded_days_after"] == [d(0)]
    assert out["all_days_within_capacity"] is False
    assert out["total_scheduled_hours_before"] == out["total_scheduled_hours_after"] == 15.0


async def test_simulate_spreading_a_task_with_a_range_fixes_the_day(db, user, week):
    out, _ = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["small"], "changes": {"target_date": d(1)}},
        {"op": "update", "todo_id": week["big"], "changes": {"start_date": d(0), "end_date": d(1)}},
    ])
    # A target_date still set wins over the range — the task stays whole on
    # Monday. The model has to clear target_date to spread it; pin both.
    assert out["all_days_within_capacity"] is False

    out, _ = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["small"], "changes": {"target_date": d(1)}},
        {"op": "update", "todo_id": week["big"],
         "changes": {"target_date": None, "start_date": d(0), "end_date": d(1)}},
    ])
    days = {x["date"]: x for x in out["days"]}
    assert days[d(0)]["scheduled_hours_after"] == 2.5
    assert days[d(1)]["scheduled_hours_after"] == 6.5  # 2.5 + Small 2 + Locked 2
    assert out["overloaded_days_after"] == [d(1)]


async def test_simulate_create_and_delete(db, user, week):
    out, _ = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "delete", "todo_id": week["small"]},
        {"op": "create", "changes": {"title": "New", "target_date": d(3), "estimated_effort": 1.5}},
    ])
    days = {x["date"]: x for x in out["days"]}
    assert days[d(0)]["scheduled_hours_after"] == 5.0
    assert days[d(3)]["scheduled_hours_after"] == 3.5


async def test_simulate_warns_about_past_and_non_workday_dates(db, user, week):
    out, _ = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["small"], "changes": {"target_date": d(-1)}},
        {"op": "update", "todo_id": week["big"], "changes": {"target_date": d(5)}},
    ])
    joined = " ".join(out["warnings"])
    assert "'Small'" in joined and "in the past" in joined
    assert "'Big'" in joined and "non-workday" in joined


async def test_simulate_rejects_locked_and_unknown_tasks(db, user, week):
    out, err = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["locked"], "changes": {"target_date": d(3)}},
    ])
    assert err and "locked" in out["error"]
    out, err = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": "00000000-0000-0000-0000-000000000000", "changes": {"target_date": d(3)}},
    ])
    assert err and "doesn't exist" in out["error"]


async def test_simulate_rejects_forbidden_fields(db, user, week):
    out, err = await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "update", "todo_id": week["small"], "changes": {"completed": True}},
    ])
    assert err and "completed" in out["error"]


async def test_simulate_writes_nothing(db, user, week):
    before = {t.id: (t.target_date, t.start_date, t.end_date) for t in (await db.execute(select(Todo))).scalars()}
    await run(db, user, "simulate_changes", start_date=d(0), end_date=d(6), items=[
        {"op": "delete", "todo_id": week["big"]},
        {"op": "update", "todo_id": week["small"], "changes": {"target_date": d(2)}},
    ])
    db.expire_all()
    after = {t.id: (t.target_date, t.start_date, t.end_date) for t in (await db.execute(select(Todo))).scalars()}
    assert before == after


def test_simulate_schema_shares_propose_changes_field_list():
    schemas = {s["name"]: s for s in TOOL_SCHEMAS}
    sim_changes = schemas["simulate_changes"]["input_schema"]["properties"]["items"]["items"]["properties"]["changes"]
    prop_changes = schemas["propose_changes"]["input_schema"]["properties"]["items"]["items"]["properties"]["changes"]
    assert sim_changes is prop_changes
