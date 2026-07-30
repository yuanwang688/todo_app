"""The seam between the eval harness and the assistant.

Phase A ships this unimplemented on purpose: the scenarios are the spec, and they
must fail until the agent exists. Phase B replaces the body of `run_agent` with a
call into `app.agent.agent_service.run()` and deletes `AgentNotImplemented`.

Nothing else in `evals/` may import the agent directly — this is the only seam.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent_schemas import Proposal


class AgentNotImplemented(NotImplementedError):
    """Raised until Phase B wires the real agent in behind this adapter."""


@dataclass
class AgentResult:
    """Everything the graders are allowed to see from one assistant turn."""

    reply_text: str
    proposal: Proposal | None = None
    tool_calls: list[str] = field(default_factory=list)
    #: Raw proposal payload as returned by the model, before validation. Lets the
    #: `schema_valid` grader report *why* a malformed proposal was rejected
    #: rather than silently seeing `proposal is None`.
    raw_proposal: dict | None = None
    schema_error: str | None = None


async def run_agent(
    *,
    message: str,
    user_id: str,
    db: AsyncSession,
    today: date,
    preferences: dict,
) -> AgentResult:
    """Run one assistant turn against a seeded database.

    The assistant must not mutate any task here — it may only read and propose.
    The `db_unchanged` grader enforces that for every scenario.
    """
    raise AgentNotImplemented(
        "The assistant is not built yet (Phase B). "
        "These scenarios are the spec and are expected to fail until then."
    )
