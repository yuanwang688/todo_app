"""Tools for the todo assistant.

The three read-only tools wrap application services, never raw SQL from the
model, and every number the model can state (quadrant, days-left phrasing,
workload hours) is computed by `app.triage`, not by the model. See TRIAGE.md
§3. Each read-only executor returns `(content_str, is_error)` — the shape the
tool-result block needs. Errors are reported to the model as data, not
raised, so a bad `todo_id` becomes a turn the model can recover from instead
of a crashed request.

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
            "— never estimate this yourself. Also lists incomplete undated tasks, since they don't "
            f"land on any specific day. Range is capped at {MAX_WORKLOAD_DAYS} days."
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
    PROPOSE_CHANGES_SCHEMA,
]


# ── helpers ──────────────────────────────────────────────────────────────────


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


def _row(todo: Todo, today: date) -> dict[str, Any]:
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
        "quadrant": triage.quadrant(todo, today),
        "due": triage.describe_due(todo, today),
        "days_left": triage.days_left(todo, today),
    }


# ── executors ────────────────────────────────────────────────────────────────


async def search_todos(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
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
        "tasks": [_row(t, today) for t in page],
        "total_matches": total,
        "returned": len(page),
    }
    if total > len(page):
        payload["note"] = f"{total - len(page)} more match your filters — narrow the search to see them."
    return json.dumps(payload), False


async def get_todo_details(
    db: AsyncSession, user_id: uuid.UUID, today: date, *, todo_id: str
) -> tuple[str, bool]:
    try:
        parsed_id = uuid.UUID(todo_id)
    except ValueError:
        return json.dumps({"error": "not_found", "todo_id": todo_id}), True

    result = await db.execute(select(Todo).where(Todo.id == parsed_id, Todo.user_id == user_id))
    todo = result.scalar_one_or_none()
    if todo is None:
        return json.dumps({"error": "not_found", "todo_id": todo_id}), True

    payload = _row(todo, today)
    payload["description"] = todo.description
    return json.dumps(payload), False


async def get_workload_summary(
    db: AsyncSession,
    user_id: uuid.UUID,
    today: date,
    preferences: dict,
    *,
    start_date: str,
    end_date: str,
) -> tuple[str, bool]:
    start = _parse_date(start_date, "start_date")
    end = _parse_date(end_date, "end_date")
    if end < start:
        return json.dumps({"error": "end_date is before start_date"}), True
    if (end - start).days + 1 > MAX_WORKLOAD_DAYS:
        end = start + timedelta(days=MAX_WORKLOAD_DAYS - 1)

    result = await db.execute(select(Todo).where(Todo.user_id == user_id, Todo.completed.is_(False)))
    todos = list(result.scalars().all())

    capacity = preferences.get("daily_capacity_hours", triage.DEFAULT_DAILY_CAPACITY_HOURS)
    workdays = frozenset(preferences.get("workdays") or [1, 2, 3, 4, 5])
    days = triage.workload(todos, start, end, capacity, workdays)

    undated = [
        {"id": str(t.id), "title": t.title, "estimated_effort": t.estimated_effort, "quadrant": triage.quadrant(t, today)}
        for t in todos
        if triage.effective_due_date(t) is None
    ]

    payload = {
        "days": [
            {
                "date": d.day.isoformat(),
                "scheduled_hours": d.scheduled_hours,
                "capacity_hours": d.capacity_hours,
                "overage_hours": d.overage_hours,
                "is_overloaded": d.is_overloaded,
            }
            for d in days
        ],
        "total_scheduled_hours": round(sum(d.scheduled_hours for d in days), 2),
        "total_capacity_hours": round(sum(d.capacity_hours for d in days), 2),
        "undated_incomplete_tasks": undated,
    }
    return json.dumps(payload), False


Executor = Callable[..., Awaitable[tuple[str, bool]]]

EXECUTORS: dict[str, Executor] = {
    "search_todos": search_todos,
    "get_todo_details": get_todo_details,
    "get_workload_summary": get_workload_summary,
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
    try:
        if name == "get_workload_summary":
            return await executor(db, user_id, today, preferences, **tool_input)
        return await executor(db, user_id, today, **tool_input)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}), True
