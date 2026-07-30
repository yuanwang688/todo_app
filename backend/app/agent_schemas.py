"""Contract for assistant-generated proposals.

Production-owned on purpose: Phase B's `propose_changes` tool derives its JSON
schema from these models, and `backend/evals/` grades against the same models —
so there is no second copy to drift.

Nothing here touches the database. Validation that needs DB state (locked tasks,
optimistic concurrency, field whitelists) lives in the apply layer (Phase C).
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .triage import AGENT_WRITABLE_FIELDS, AGENT_WRITABLE_ON_CREATE

Quadrant = Literal["Q1", "Q2", "Q3", "Q4"]
Operation = Literal["create", "update", "delete"]


class ProposalItem(BaseModel):
    """A single proposed mutation, always paired with its reasoning."""

    model_config = {"extra": "forbid"}

    op: Operation
    todo_id: Optional[str] = Field(
        default=None, description="Target task. Required for update/delete, omitted for create."
    )
    changes: dict[str, Any] = Field(
        default_factory=dict,
        description="For update: {field: new_value}. For create: the new task's fields. Empty for delete.",
    )
    rationale: Annotated[str, Field(min_length=15)] = Field(
        description="Why this change, in terms of the task's quadrant. Shown to the user verbatim."
    )
    quadrant: Optional[Quadrant] = None

    @field_validator("changes")
    @classmethod
    def _no_forbidden_fields(cls, v: dict[str, Any]) -> dict[str, Any]:
        illegal = set(v) - AGENT_WRITABLE_ON_CREATE
        if illegal:
            raise ValueError(f"fields not writable by the assistant: {sorted(illegal)}")
        return v

    def check_consistency(self) -> None:
        """Cross-field rules the shape alone can't express."""
        if self.op in ("update", "delete") and not self.todo_id:
            raise ValueError(f"op={self.op} requires todo_id")
        if self.op == "create" and self.todo_id:
            raise ValueError("op=create must not carry a todo_id")
        if self.op == "delete" and self.changes:
            raise ValueError("op=delete must not carry changes")
        if self.op == "update":
            if not self.changes:
                raise ValueError("op=update requires at least one change")
            illegal = set(self.changes) - AGENT_WRITABLE_FIELDS
            if illegal:
                raise ValueError(f"fields not writable on update: {sorted(illegal)}")
        if self.op == "create" and "title" not in self.changes:
            raise ValueError("op=create requires a title")


class Proposal(BaseModel):
    """A batch of changes the user approves or rejects item by item."""

    model_config = {"extra": "forbid"}

    summary: Annotated[str, Field(min_length=10)] = Field(
        description="One line describing what this batch does, shown as the card header."
    )
    items: Annotated[list[ProposalItem], Field(min_length=1, max_length=50)]

    def check_consistency(self) -> None:
        for item in self.items:
            item.check_consistency()
        targets = [i.todo_id for i in self.items if i.todo_id]
        if len(targets) != len(set(targets)):
            raise ValueError("a task may appear at most once per proposal")
