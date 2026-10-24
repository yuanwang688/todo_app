"""Tools for the todo assistant.

The three read-only tools wrap application services, never raw SQL from the
model, and every number the model can state (quadrant, days-left phrasing,
workload hours) is computed by `app.triage`, not by the model. See TRIAGE.md
§3. Each read-only executor returns `(content_str, is_error)` — the shape the
tool-result block needs. Errors are reported to the model as data, not
raised, so a bad `todo_id` becomes a turn the model can recover from instead
of a crashed request.

`simulate_changes` (Phase D) is read-only too: it projects a candidate batch
onto an in-memory copy of the list and reports per-day load before and
after, so a rebalance can be checked against capacity *before* it becomes a
proposal the user has to review. It persists nothing.

`propose_changes` (Phase C, the one write path) lives in `propose.py` — its
validation and persistence are substantial enough, and different enough in
shape, to not force through the read-only tools' dispatch. `TOOL_SCHEMAS`
below is still the single list the model sees; `service.py`'s `_run_loop`
special-cases the name to call `propose.execute_propose_changes` directly.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import triage
from ..models import Todo
from .propose import PROPOSE_CHANGES_SCHEMA

MAX_SEARCH_LIMIT = 50
DEFAULT_SEARCH_LIMIT = 20
MAX_WORKLOAD_DAYS = 31

# ── schemas ──────────────────────────────────────────────────────────────────

TOOL_SCHEMAS: list[dict] = [
    {
        "name": "search_todos",
        "description": (
            "Search the user's tasks. Returns compact rows with derived fields "
            "(quadrant, human due-date phrasing, days_left) so you don't have to "
            "compute them. Defaults to incomplete tasks only. Use this before "
            "answering any question about which tasks exist, are due, or match "
            "some criterion — never answer from assumption."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Case-insensitive substring match on title."},
                "completed": {"type": "boolean", "description": "Defaults to false (incomplete tasks only)."},
                "category": {"type": "string", "description": "Exact category match, case-insensitive."},
                "due_before": {
                    "type": "string",
                    "format": "date",
                    "description": (
                        "ISO date. Only tasks due strictly before this date. "
                        "Pass today's date to find overdue tasks."
                    ),
                },
                "due_after": {
                    "type": "string",
                    "format": "date",
                    "description": "ISO date. Only tasks due on or after this date.",
                },
                "undated": {
                    "type": "boolean",
                    "description": "If true, only tasks with no target date and no start/end range.",
                },
                "unclassified": {
                    "type": "boolean",
                    "description": "If true, only tasks with no importance set.",
                },
                "min_effort": {"type": "number", "description": "Only tasks with an estimate >= this many hours."},
                "max_effort": {"type": "number", "description": "Only tasks with an estimate <= this many hours."},
                "limit": {
                    "type": "integer",
                    # `minimum`/`maximum` aren't supported on strict tool schemas
                    # (numerical constraints are a documented JSON-Schema gap for
                    # structured outputs) — the range is stated here for the model
                    # and enforced in Python by `execute_tool` regardless of what's
                    # passed in.
                    "description": f"Max rows to return (default {DEFAULT_SEARCH_LIMIT}, max {MAX_SEARCH_LIMIT}).",
                },
            },
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_todo_details",
        "description": "Fetch the full record for one task, including its description, by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "The task's id, as returned by search_todos."},
            },
            "required": ["todo_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "get_workload_summary",
        "description": (
            "Scheduled effort vs. capacity for each day in a date range, computed deterministically "
            "— never estimate this yourself. Each day lists the tasks landing on it and the hours each "
            "contributes (a start/end range spreads its estimate evenly across its days), plus "
            "free_hours and overage_hours. Non-workdays have 0h capacity. Also lists incomplete "
            "undated tasks and overdue tasks, since neither lands on a day in the range. "
            f"Range is capped at {MAX_WORKLOAD_DAYS} days."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
            },
            "required": ["start_date", "end_date"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "simulate_changes",
        "description": (
            "Dry run: project a candidate batch of changes onto the task list and return each day's "
            "load before and after, against capacity. Changes nothing and creates no proposal. Use it "
            "to check a rebalance or reschedule before calling propose_changes — if any day is still "
            "over capacity, or work landed on a non-workday or in the past, adjust the batch and "
            "simulate again. Items use the same op/todo_id/changes shape as propose_changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "format": "date"},
                "end_date": {"type": "string", "format": "date"},
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["create", "update", "delete"]},
                            "todo_id": {"type": "string", "description": "Required for update/delete."},
                            "changes": PROPOSE_CHANGES_SCHEMA["input_schema"]["properties"]["items"]["items"][
                                "properties"
                            ]["changes"],
                        },
                        "required": ["op"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["start_date", "end_date", "items"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    PROPOSE_CHANGES_SCHEMA,
]


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _horizon(preferences: dict) -> int:
    return preferences.get("urgency_horizon_days", triage.DEFAULT_URGENCY_HORIZON_DAYS)


def _row(todo: Todo, today: date, horizon: int = triage.DEFAULT_URGENCY_HORIZON_DAYS) -> dict[str, Any]:
    return {
        "id": str(todo.id),
        "title": todo.title,
        "category": todo.category,
        "completed": todo.completed,
        "target_date": todo.target_date.isoformat() if todo.target_date else None,
        "start_date": todo.start_date.isoformat() if todo.start_date else None,
        "end_date": todo.end_date.isoformat() if todo.end_date else None,
        "estimated_effort": todo.estimated_effort,
        "importance": todo.importance,
        "unclassified": triage.is_unclassified(todo),
        "is_focus": todo.is_focus,
        "locked": todo.locked,
        "quadrant": triage.quadrant(todo, today, horizon),
        "due": triage.describe_due(todo, today),
        "days_left": triage.days_left(todo, today),
    }


# ── executors ────────────────────────────────────────────────────────────────


async def search_todos(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    preferences: dict,
    *,
    query: str | None = None,
    completed: bool | None = None,
    category: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    undated: bool | None = None,
    unclassified: bool | None = None,
    min_effort: float | None = None,
    max_effort: float | None = None,
    limit: int | None = None,
) -> tuple[str, bool]:
    stmt = select(Todo).where(Todo.user_id == user_id)
    stmt = stmt.where(Todo.completed == (completed if completed is not None else False))
    if query:
        stmt = stmt.where(Todo.title.ilike(f"%{query}%"))
    if category:
        stmt = stmt.where(Todo.category.ilike(category))
    if unclassified is True:
        stmt = stmt.where(Todo.importance.is_(None))
    elif unclassified is False:
        stmt = stmt.where(Todo.importance.isnot(None))
    if min_effort is not None:
        stmt = stmt.where(Todo.estimated_effort.isnot(None), Todo.estimated_effort >= min_effort)
    if max_effort is not None:
        stmt = stmt.where(Todo.estimated_effort.isnot(None), Todo.estimated_effort <= max_effort)

    result = await db.execute(stmt)
    todos = list(result.scalars().all())

    if due_before is not None or due_after is not None:
        before = _parse_date(due_before, "due_before") if due_before else None
        after = _parse_date(due_after, "due_after") if due_after else None
        filtered = []
        for t in todos:
            due = triage.effective_due_date(t)
            if due is None:
                continue
            if before is not None and not (due < before):
                continue
            if after is not None and not (due >= after):
                continue
            filtered.append(t)
        todos = filtered

    if undated is True:
        todos = [t for t in todos if triage.effective_due_date(t) is None]
    elif undated is False:
        todos = [t for t in todos if triage.effective_due_date(t) is not None]

    todos.sort(key=lambda t: (triage.effective_due_date(t) or date.max, t.title.lower()))

    effective_limit = min(max(int(limit), 1), MAX_SEARCH_LIMIT) if limit else DEFAULT_SEARCH_LIMIT
    total = len(todos)
    page = todos[:effective_limit]

    payload = {
        "tasks": [_row(t, today, _horizon(preferences)) for t in page],
        "total_matches": total,
        "returned": len(page),
    }
    if total > len(page):
        payload["note"] = f"{total - len(page)} more match your filters — narrow the search to see them."
    return json.dumps(payload), False


async def get_todo_details(
    db: AsyncSession, user_id: uuid.UUID, today: date, preferences: dict, *, todo_id: str
) -> tuple[str, bool]:
    try:
        parsed_id = uuid.UUID(todo_id)
    except ValueError:
        return json.dumps({"error": "not_found", "todo_id": todo_id}), True

    result = await db.execute(select(Todo).where(Todo.id == parsed_id, Todo.user_id == user_id))
    todo = result.scalar_one_or_none()
    if todo is None:
        return json.dumps({"error": "not_found", "todo_id": todo_id}), True

    payload = _row(todo, today, _horizon(preferences))
    payload["description"] = todo.description
    return json.dumps(payload), False


def _parse_range(start_date: str, end_date: str) -> tuple[date, date]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        raise ValueError("end_date is before start_date")
    if (end - start).days + 1 > MAX_WORKLOAD_DAYS:
        end = start + timedelta(days=MAX_WORKLOAD_DAYS - 1)
    return start, end


def _capacity(preferences: dict) -> tuple[float, frozenset[int]]:
    capacity = preferences.get("daily_capacity_hours", triage.DEFAULT_DAILY_CAPACITY_HOURS)
    workdays = frozenset(preferences.get("workdays") or [1, 2, 3, 4, 5])
    return capacity, workdays


async def _incomplete_todos(db: AsyncSession, user_id: uuid.UUID) -> list[Todo]:
    result = await db.execute(select(Todo).where(Todo.user_id == user_id, Todo.completed.is_(False)))
    return list(result.scalars().all())


async def get_workload_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    preferences: dict,
    *,
    start_date: str,
    end_date: str,
) -> tuple[str, bool]:
    start, end = _parse_range(start_date, end_date)
    todos = await _incomplete_todos(db, user_id)
    capacity, workdays = _capacity(preferences)
    horizon = _horizon(preferences)
    days = triage.workload(todos, start, end, capacity, workdays)

    def day_entry(d: triage.DayLoad) -> dict[str, Any]:
        landing = [t for t in todos if triage.occupies_day(t, d.day)]
        landing.sort(key=lambda t: -triage.attributed_hours(t, d.day))
        return {
            "date": d.day.isoformat(),
            "weekday": d.day.strftime("%A"),
            "is_workday": d.day.isoweekday() in workdays,
            "scheduled_hours": d.scheduled_hours,
            "capacity_hours": d.capacity_hours,
            "free_hours": round(max(0.0, d.capacity_hours - d.scheduled_hours), 2),
            "overage_hours": d.overage_hours,
            "is_overloaded": d.is_overloaded,
            "tasks": [
                {
                    "id": str(t.id),
                    "title": t.title,
                    "hours": triage.attributed_hours(t, d.day),
                    "estimated_effort": t.estimated_effort,
                    "spread_over_range": t.target_date != d.day,
                    "quadrant": triage.quadrant(t, today, horizon),
                    "importance": t.importance,
                    "locked": t.locked,
                }
                for t in landing
            ],
        }

    def brief(t: Todo) -> dict[str, Any]:
        return {
            "id": str(t.id),
            "title": t.title,
            "estimated_effort": t.estimated_effort,
            "quadrant": triage.quadrant(t, today, horizon),
            "locked": t.locked,
        }

    overloaded = [d for d in days if d.is_overloaded]
    total_scheduled = round(sum(d.scheduled_hours for d in days), 2)
    total_capacity = round(sum(d.capacity_hours for d in days), 2)
    overdue = [t for t in todos if triage.is_overdue(t, today)]

    payload = {
        "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "days": [day_entry(d) for d in days],
        "total_scheduled_hours": total_scheduled,
        "total_capacity_hours": total_capacity,
        "overloaded_days": [d.day.isoformat() for d in overloaded],
        "total_overage_hours": round(sum(d.overage_hours for d in overloaded), 2),
        # Whether the range as a whole has room for everything scheduled in it —
        # i.e. whether a rebalance *within* the range is arithmetically possible.
        # Individual tasks may still be too large for any single day's capacity.
        "fits_in_range": total_scheduled <= total_capacity,
        "undated_incomplete_tasks": [brief(t) for t in todos if triage.effective_due_date(t) is None],
        "overdue_tasks": [{**brief(t), "due": triage.describe_due(t, today)} for t in overdue],
    }
    return json.dumps(payload), False


def _check_sim_item(item: dict[str, Any]) -> None:
    op = item.get("op")
    changes = item.get("changes") or {}
    if op in ("update", "delete") and not item.get("todo_id"):
        raise ValueError(f"op={op} requires todo_id")
    if op == "create" and "title" not in changes:
        raise ValueError("op=create requires a title")
    allowed = triage.AGENT_WRITABLE_ON_CREATE if op == "create" else triage.AGENT_WRITABLE_FIELDS
    illegal = set(changes) - allowed
    if illegal:
        raise ValueError(f"fields not writable on {op}: {sorted(illegal)}")
    for field in ("target_date", "start_date", "end_date"):
        if isinstance(changes.get(field), str):
            _parse_date(changes[field], field)


async def simulate_changes(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    preferences: dict,
    *,
    start_date: str,
    end_date: str,
    items: list[dict[str, Any]],
) -> tuple[str, bool]:
    start, end = _parse_range(start_date, end_date)
    todos = await _incomplete_todos(db, user_id)
    by_id = {str(t.id): t for t in todos}

    for item in items:
        _check_sim_item(item)
        todo_id = item.get("todo_id")
        if todo_id is None:
            continue
        if todo_id not in by_id:
            raise ValueError(f"task {todo_id} doesn't exist or is already completed")
        if by_id[todo_id].locked:
            raise ValueError(
                f"task {todo_id} ('{by_id[todo_id].title}') is locked — it can't be part of any "
                "proposal, so leave it out of the simulation too"
            )

    before = [triage.TaskSnapshot.of(t, str(t.id)) for t in todos]
    after = triage.project(before, items)
    capacity, workdays = _capacity(preferences)
    load_before = triage.workload(before, start, end, capacity, workdays)
    load_after = triage.workload(after, start, end, capacity, workdays)

    # Things a valid-looking batch can still get wrong, surfaced as facts.
    warnings: list[str] = []
    after_by_id = {t.id: t for t in after}
    for n, item in enumerate(items):
        if item.get("op") == "delete":
            continue
        task = after_by_id[item.get("todo_id") or f"new-{n}"]
        label = f"'{task.title}'"
        for field in ("target_date", "start_date", "end_date"):
            value = getattr(task, field)
            if field in (item.get("changes") or {}) and value is not None:
                if value < today:
                    warnings.append(f"{label}: {field} {value.isoformat()} is in the past")
                if field == "target_date" and value.isoweekday() not in workdays:
                    warnings.append(f"{label}: target_date {value.isoformat()} is a non-workday (0h capacity)")
        if task.start_date and task.end_date and task.end_date < task.start_date:
            warnings.append(f"{label}: end_date is before start_date")
        if (task.start_date is None) != (task.end_date is None):
            warnings.append(f"{label}: has only one of start_date/end_date, so it lands on no day")

    still_over = [a for a in load_after if a.is_overloaded]
    payload = {
        "range": {"start_date": start.isoformat(), "end_date": end.isoformat()},
        "days": [
            {
                "date": b.day.isoformat(),
                "weekday": b.day.strftime("%A"),
                "capacity_hours": b.capacity_hours,
                "scheduled_hours_before": b.scheduled_hours,
                "scheduled_hours_after": a.scheduled_hours,
                "overage_hours_after": a.overage_hours,
            }
            for b, a in zip(load_before, load_after)
        ],
        "total_scheduled_hours_before": round(sum(d.scheduled_hours for d in load_before), 2),
        "total_scheduled_hours_after": round(sum(d.scheduled_hours for d in load_after), 2),
        "overloaded_days_after": [d.day.isoformat() for d in still_over],
        "all_days_within_capacity": not still_over,
        "warnings": warnings,
        "note": "Simulation only — nothing was changed and no proposal was created.",
    }
    return json.dumps(payload), False


Executor = Callable[..., Awaitable[tuple[str, bool]]]

EXECUTORS: dict[str, Executor] = {
    "search_todos": search_todos,
    "get_todo_details": get_todo_details,
    "get_workload_summary": get_workload_summary,
    "simulate_changes": simulate_changes,
}


# Each tool's allowed and required argument names, from its schema. The Claude
# API enforces these itself (`strict: true`), but Anthropic-compatible local
# servers like Ollama don't — a stray argument would otherwise reach the
# executor as a TypeError and crash the turn.
_TOOL_ARGS: dict[str, tuple[set[str], set[str]]] = {
    t["name"]: (set(t["input_schema"]["properties"]), set(t["input_schema"].get("required", [])))
    for t in TOOL_SCHEMAS
}


async def execute_tool(
    name: str,
    tool_input: dict[str, Any],
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    preferences: dict,
) -> tuple[str, bool]:
    executor = EXECUTORS.get(name)
    if executor is None:
        return json.dumps({"error": f"unknown tool {name!r}"}), True
    allowed, required = _TOOL_ARGS[name]
    unexpected = sorted(set(tool_input) - allowed)
    missing = sorted(required - set(tool_input))
    if unexpected or missing:
        return json.dumps({
            "error": "invalid arguments",
            "unexpected": unexpected,
            "missing": missing,
            "allowed": sorted(allowed),
        }), True
    try:
        return await executor(db, user_id, today, preferences, **tool_input)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}), True
