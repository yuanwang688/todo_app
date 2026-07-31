"""The seam between the eval harness and the assistant.

Phase A shipped this raising `AgentNotImplemented` unconditionally, so every
scenario failed for the right reason before the agent existed. Phase B wires
it to the real agent loop — nothing else in `evals/` changed.
"""
from __future__ import annotations

import uuid as uuid_module
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import service
from app.agent_schemas import Proposal


class AgentNotImplemented(NotImplementedError):
    """The scenario can't run and should be skipped, not failed.

    Raised when the agent has no code path yet (pre–Phase B) or, now, when
    `ANTHROPIC_API_KEY` isn't set — there's no meaningful way to grade a model
    response the harness never got to make.
    """


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
    if not service.is_configured():
        raise AgentNotImplemented(
            "ANTHROPIC_API_KEY is not set. Add it to backend/.env (or export it) "
            "to run scenarios against the real assistant."
        )

    convo = await service.get_or_create_conversation(db, uuid_module.UUID(user_id))
    result = await service.run_turn(
        db=db,
        user_id=uuid_module.UUID(user_id),
        conversation_id=convo.id,
        message=message,
        today=today,
        preferences=preferences,
    )
    if result.error:
        raise RuntimeError(f"agent turn errored: {result.error}")

    return AgentResult(
        reply_text=result.reply_text,
        proposal=result.proposal,
        tool_calls=result.tool_calls,
    )
