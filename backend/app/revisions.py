"""Shared helper for writing `todo_revisions` rows.

Used by both the GUI mutation paths (routers/todos.py, source='user') and
the proposal apply/undo paths (routers/proposals.py, source='agent') so the
two audit trails stay in the same shape.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .models import Todo

# Full-row snapshot — deliberately broader than AGENT_WRITABLE_FIELDS, since
# undo must be able to fully recreate a deleted row (title, completed,
# locked, etc. are never agent-writable but are still part of what a
# snapshot needs).
SNAPSHOT_FIELDS = (
    "title", "description", "category", "completed", "target_date", "start_date",
    "end_date", "estimated_effort", "importance", "is_focus", "locked", "created_at",
)


def _serialize(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def snapshot_todo(todo: Todo) -> dict[str, Any]:
    return {f: _serialize(getattr(todo, f)) for f in SNAPSHOT_FIELDS}


_DATE_FIELDS = frozenset({"target_date", "start_date", "end_date"})
_DATETIME_FIELDS = frozenset({"created_at"})


def deserialize_field(field: str, value: Any) -> Any:
    """Parses a single field's ISO-string form (whether from a JSON snapshot
    or a raw tool-call value from the model) back into the date/datetime
    object the Todo column actually needs. asyncpg — unlike SQLite — rejects
    a plain string for a Date/DateTime column outright, so this has to run
    before any setattr(todo, field, value) or Todo(**kwargs)."""
    if value is None:
        return None
    if field in _DATE_FIELDS:
        return value if isinstance(value, date) else date.fromisoformat(value)
    if field in _DATETIME_FIELDS:
        return value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return value


def deserialize_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Inverse of snapshot_todo — parses the ISO strings a JSON column round
    -trips back into date/datetime objects so the values are safe to feed
    back into a Todo() constructor or setattr during undo."""
    return {field: deserialize_field(field, value) for field, value in snapshot.items()}
