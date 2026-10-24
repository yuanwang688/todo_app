"""The propose_changes tool: the assistant's only write path.

Two layers of validation, deliberately not merged into one:

1. The tool's `input_schema` (below) is loose — no `minLength`/`minItems`,
   because strict tool schemas don't support numerical or string-length
   constraints (search_todos's `limit` field hit exactly this in Phase B).
2. `agent_schemas.Proposal` (Pydantic) enforces everything the JSON Schema
   can't: rationale length, the writable-field whitelist, op/todo_id
   consistency, duplicate targets. A failure here becomes an `is_error` tool
   result, not a crash — the model sees exactly what's wrong and can
   resubmit in the same turn. Verified against the real API: a deliberately
   incomplete proposal was rejected by this layer, fed back, and the model
   corrected it.

A third check happens only here, against the database, and is stricter than
either: **a proposal touching a locked task is rejected in full**, not
partially. Locked tasks never appear even transiently in a persisted
proposal — same structural guarantee as "no apply tool means no unapproved
mutation."
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_schemas import Proposal as ProposalContract
from ..models import Proposal as ProposalRow, ProposalItem as ProposalItemRow, Todo
from ..triage import AGENT_WRITABLE_FIELDS

PROPOSE_CHANGES_SCHEMA: dict = {
    "name": "propose_changes",
    "description": (
        "Propose a batch of task changes for the user to review and selectively approve. "
        "This never writes to the database — it only creates a proposal the user can accept, "
        "partially accept, or discard. After calling it, tell the user a proposal is ready for "
        "their review. Never describe the changes as already made. Every item needs a rationale "
        "explaining the change in terms of its Eisenhower quadrant. A task with locked=true in "
        "search_todos results can never be targeted — omit it entirely, don't propose it anyway."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "One line describing what this batch does — the card header the user sees.",
            },
            "items": {
                "type": "array",
                "description": "1 to 50 proposed changes.",
                "items": {
                    "type": "object",
                    "properties": {
                        "op": {"type": "string", "enum": ["create", "update", "delete"]},
                        "todo_id": {
                            "type": "string",
                            "description": "Required for update/delete — the id from search_todos. Omit for create.",
                        },
                        "changes": {
                            "type": "object",
                            "description": (
                                "update: only category, target_date, start_date, end_date, "
                                "estimated_effort, importance, is_focus — omit fields you're not "
                                "changing, don't set them to their current value. create: also "
                                "requires title; description is optional. Never completed. "
                                "Empty object for delete."
                            ),
                            "properties": {
                                "title": {"type": "string"},
                                "description": {"type": "string"},
                                "category": {"type": "string"},
                                "target_date": {"type": "string", "format": "date"},
                                "start_date": {"type": "string", "format": "date"},
                                "end_date": {"type": "string", "format": "date"},
                                "estimated_effort": {"type": "number"},
                                "importance": {"type": "integer", "description": "1 low, 2 medium, 3 high."},
                                "is_focus": {"type": "boolean"},
                            },
                            "additionalProperties": False,
                        },
                        "rationale": {
                            "type": "string",
                            "description": "Why this change, in terms of the task's quadrant. Shown to the user verbatim.",
                        },
                        "quadrant": {"type": "string", "enum": ["Q1", "Q2", "Q3", "Q4"]},
                    },
                    "required": ["op", "rationale"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "items"],
        "additionalProperties": False,
    },
    "strict": True,
}


def _serialize(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _current_fields(todo: Todo) -> dict[str, Any]:
    return {field: _serialize(getattr(todo, field)) for field in AGENT_WRITABLE_FIELDS}


def _enrich_changes(op: str, changes: dict[str, Any], todo: Todo | None) -> dict[str, Any]:
    """Model gives {field: new_value}. Stored form is {field: {from, to}} for
    update (so the UI can render a diff without a second fetch), {field:
    value} for create (nothing to diff against), {} for delete."""
    if op == "delete":
        return {}
    if op == "create":
        return {k: _serialize(v) for k, v in changes.items()}
    current = _current_fields(todo) if todo else {}
    return {field: {"from": current.get(field), "to": _serialize(new)} for field, new in changes.items()}


class ProposeChangesResult:
    __slots__ = ("content", "is_error", "proposal", "proposal_id")

    def __init__(self, content: str, is_error: bool, proposal: ProposalContract | None = None, proposal_id: uuid.UUID | None = None):
        self.content = content
        self.is_error = is_error
        self.proposal = proposal
        self.proposal_id = proposal_id


def _error(message: str) -> ProposeChangesResult:
    return ProposeChangesResult(json.dumps({"error": message}), True)


async def execute_propose_changes(
    tool_input: dict[str, Any],
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
) -> ProposeChangesResult:
    # Layer 1: shape + policy validation. Failures are retryable tool errors.
    try:
        contract = ProposalContract.model_validate(tool_input)
        contract.check_consistency()
    except (ValidationError, ValueError) as exc:
        return _error(f"Invalid proposal, fix and resubmit: {exc}")

    # Layer 2: does every referenced todo exist, belong to this user, and
    # (the structural guarantee) is none of them locked?
    todos_by_id: dict[str, Todo] = {}
    for item in contract.items:
        if item.todo_id is None:
            continue
        try:
            parsed = uuid.UUID(item.todo_id)
        except ValueError:
            return _error(f"'{item.todo_id}' is not a valid task id — fix and resubmit.")
        if item.todo_id in todos_by_id:
            continue
        result = await db.execute(select(Todo).where(Todo.id == parsed, Todo.user_id == user_id))
        todo = result.scalar_one_or_none()
        if todo is None:
            return _error(f"Task {item.todo_id} doesn't exist — fix and resubmit.")
        if todo.locked:
            return _error(
                f"Task {item.todo_id} ('{todo.title}') is locked and can never be targeted. "
                "Remove it from the proposal entirely and resubmit."
            )
        todos_by_id[item.todo_id] = todo

    # Persist. Nothing above this line touches the database with a write.
    proposal_row = ProposalRow(conversation_id=conversation_id, user_id=user_id, summary=contract.summary)
    db.add(proposal_row)
    await db.flush()  # assigns proposal_row.id without committing yet

    for item in contract.items:
        todo = todos_by_id.get(item.todo_id) if item.todo_id else None
        db.add(
            ProposalItemRow(
                proposal_id=proposal_row.id,
                op=item.op,
                todo_id=todo.id if todo else None,
                changes=_enrich_changes(item.op, item.changes, todo),
                rationale=item.rationale,
                quadrant=item.quadrant,
                seen_updated_at=todo.updated_at if todo else None,
            )
        )
    await db.commit()
    await db.refresh(proposal_row)

    content = json.dumps(
        {
            "proposal_id": str(proposal_row.id),
            "item_count": len(contract.items),
            "status": "awaiting user approval — nothing has been changed yet",
        }
    )
    return ProposeChangesResult(content, False, contract, proposal_row.id)
