"""HTTP surface for the todo assistant (Phase B).

    GET  /api/chat            -> the user's rolling conversation + display history
    POST /api/chat/messages   -> send a message; SSE stream of the reply

`app/agent/service.py` owns the model loop and persistence; this router is a
thin adapter — load/save the conversation, format events as SSE, translate the
user-planning defaults until Phase D ships real settings.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent import service
from ..auth import get_current_user
from ..database import get_db
from ..models import Message, Proposal, User
from .proposals import PROPOSAL_EXPIRY_HOURS, ProposalOut, _to_proposal_out

router = APIRouter(prefix="/api/chat", tags=["chat"])

# Until Phase D ships `user_planning_preferences`, every conversation uses
# these. Keep in sync with evals/runner.py's DEFAULT_PREFERENCES in spirit —
# they don't share code (the eval harness must not depend on the router).
DEFAULT_PREFERENCES: dict = {
    "daily_capacity_hours": 4.0,
    "workdays": [1, 2, 3, 4, 5],
    "urgency_horizon_days": 3,
    "timezone": "UTC",  # unused until Phase D — `today` is the server date
    "notes": None,
}

_DATE_PREFIX_RE = re.compile(r"^\(Today is [^)]*\)\n\n")


class ChatMessageIn(BaseModel):
    message: str


class ChatHistoryItem(BaseModel):
    role: str
    text: str
    tool_calls: list[str] = []


class ChatHistoryOut(BaseModel):
    conversation_id: str
    configured: bool
    messages: list[ChatHistoryItem]
    pending_proposals: list[ProposalOut] = []


def _strip_date_prefix(text: str) -> str:
    return _DATE_PREFIX_RE.sub("", text, count=1)


def _is_tool_result_row(content: list[dict]) -> bool:
    return bool(content) and content[0].get("type") == "tool_result"


def _summarize_history(rows: list[Message]) -> list[ChatHistoryItem]:
    """Collapses persisted turns (which include intermediate tool_use/
    tool_result rows) into one bubble per user message and one per assistant
    reply, with every tool call used along the way attached to the reply."""
    items: list[ChatHistoryItem] = []
    pending_tool_calls: list[str] = []

    for i, row in enumerate(rows):
        content = row.content or []
        if row.role == "user":
            if _is_tool_result_row(content):
                continue
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            items.append(ChatHistoryItem(role="user", text=_strip_date_prefix(text)))
            pending_tool_calls = []
            continue

        pending_tool_calls.extend(b["name"] for b in content if b.get("type") == "tool_use")
        next_row = rows[i + 1] if i + 1 < len(rows) else None
        is_intermediate = next_row is not None and next_row.role == "user" and _is_tool_result_row(next_row.content or [])
        if not is_intermediate:
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            items.append(ChatHistoryItem(role="assistant", text=text, tool_calls=pending_tool_calls))
            pending_tool_calls = []

    return items


async def _pending_proposals(db: AsyncSession, conversation_id) -> list[ProposalOut]:
    """Proposals awaiting the user's review, for reload scenarios where the
    live SSE `proposal_ready` event was never seen. Filters out anything
    old enough that /api/proposals would lazily expire it on interaction —
    that write happens there, not here, so this stays read-only."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=PROPOSAL_EXPIRY_HOURS)
    result = await db.execute(
        select(Proposal)
        .where(Proposal.conversation_id == conversation_id, Proposal.status == "pending")
        .order_by(Proposal.created_at)
    )
    proposals = list(result.scalars().all())
    fresh = [p for p in proposals if (p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=timezone.utc)) >= cutoff]
    return [await _to_proposal_out(db, p) for p in fresh]


@router.get("", response_model=ChatHistoryOut)
async def get_chat(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = await service.get_or_create_conversation(db, current_user.id)
    await db.refresh(convo, attribute_names=["messages"])
    return ChatHistoryOut(
        conversation_id=str(convo.id),
        configured=service.is_configured(),
        messages=_summarize_history(convo.messages),
        pending_proposals=await _pending_proposals(db, convo.id),
    )


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/messages")
async def post_chat_message(
    body: ChatMessageIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not body.message.strip():
        raise HTTPException(status_code=422, detail="message must not be empty")
    if not service.is_configured():
        raise HTTPException(status_code=503, detail="The assistant isn't configured on this server yet.")

    convo = await service.get_or_create_conversation(db, current_user.id)

    async def event_stream():
        async for event in service.stream_turn(
            db=db,
            user_id=current_user.id,
            conversation_id=convo.id,
            message=body.message,
            today=date.today(),
            preferences=DEFAULT_PREFERENCES,
        ):
            if event["type"] == "result":
                result = event["result"]
                yield _sse(
                    {
                        "type": "done",
                        "reply_text": result.reply_text,
                        "tool_calls": result.tool_calls,
                        "refusal": result.refusal,
                        "error": result.error,
                    }
                )
            else:
                yield _sse(event)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
