"""The agent loop.

`stream_turn` is the one entry point — it runs the model↔tool loop, persists
the new conversation turns and an `agent_runs` audit row, and yields events an
SSE endpoint can forward directly. `run_turn` drains it for callers (the eval
harness, tests) that just want the final result.

Design notes that matter if you're changing this file:

- **`max_tokens` is generous (8000) on purpose.** Claude Opus 5 thinks by
  default when `thinking` is omitted, and `max_tokens` caps thinking *and*
  response text together — too tight a budget truncates the answer before any
  text comes out. See shared/model-migration.md → Migrating to Claude Opus 5.
- **Thinking is left on (adaptive, the default).** Disabling it on this model
  has two documented failure modes — tool calls can arrive as plain text
  instead of a `tool_use` block, and `<thinking>` tags can leak into the
  visible reply — so `effort` is the depth/cost lever here, not
  `thinking: {type: "disabled"}`.
- **No mutation tool exists yet.** `propose_changes` is Phase C. Until then
  `AgentTurnResult.proposal` is always `None` — there is nothing to validate
  because the model has no way to write.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any, AsyncIterator

import anthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent_schemas import Proposal
from ..config import settings
from ..models import AgentRun, Conversation, Message
from .prompt import build_system_blocks, build_user_turn
from .tools import TOOL_SCHEMAS, execute_tool

MODEL = "claude-opus-5"
EFFORT = "medium"
MAX_TOKENS = 8000
MAX_TOOL_ITERATIONS = 6


@dataclass
class AgentTurnResult:
    reply_text: str
    tool_calls: list[str] = field(default_factory=list)
    proposal: Proposal | None = None  # always None until Phase C ships propose_changes
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    latency_ms: int = 0
    stop_reason: str | None = None
    refusal: bool = False
    error: str | None = None


_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic | None:
    global _client
    if not settings.anthropic_api_key:
        return None
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


def is_configured() -> bool:
    return bool(settings.anthropic_api_key)


# ── conversation persistence ─────────────────────────────────────────────────


async def get_or_create_conversation(db: AsyncSession, user_id: uuid.UUID) -> Conversation:
    """One rolling conversation per user — see AI_ASSISTANT_PLAN.md §11."""
    result = await db.execute(
        select(Conversation).where(Conversation.user_id == user_id).order_by(Conversation.created_at.desc()).limit(1)
    )
    convo = result.scalar_one_or_none()
    if convo is not None:
        return convo
    convo = Conversation(user_id=user_id)
    db.add(convo)
    await db.commit()
    await db.refresh(convo)
    return convo


async def _load_history(db: AsyncSession, conversation_id: uuid.UUID) -> list[dict[str, Any]]:
    result = await db.execute(select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at))
    return [{"role": m.role, "content": m.content} for m in result.scalars().all()]


async def _persist_new_messages(db: AsyncSession, conversation_id: uuid.UUID, new_messages: list[dict]) -> None:
    for m in new_messages:
        db.add(Message(conversation_id=conversation_id, role=m["role"], content=m["content"]))
    await db.commit()


async def _log_run(db: AsyncSession, conversation_id: uuid.UUID, result: AgentTurnResult) -> None:
    status = "error" if result.error else ("refusal" if result.refusal else "ok")
    db.add(
        AgentRun(
            conversation_id=conversation_id,
            model=MODEL,
            effort=EFFORT,
            status=status,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            cache_read_tokens=result.cache_read_tokens,
            cache_write_tokens=result.cache_write_tokens,
            latency_ms=result.latency_ms,
            tool_calls=len(result.tool_calls),
            error=result.error,
        )
    )
    await db.commit()


# ── the loop ─────────────────────────────────────────────────────────────────


async def _run_loop(
    *,
    client: anthropic.AsyncAnthropic,
    message: str,
    history: list[dict[str, Any]],
    today: date,
    preferences: dict,
    db: AsyncSession,
    user_id: uuid.UUID,
) -> AsyncIterator[dict]:
    """Yields streaming events (`text_delta`, `tool_call`) and, last, one
    `result` event carrying everything the caller needs to persist and log."""
    system = build_system_blocks(preferences)

    # `messages` mixes SDK response objects (needed to make the next API call
    # within this turn) with plain dicts (history, tool results). `persistable`
    # tracks the same new entries in JSON-safe form for the DB — kept as a
    # parallel list rather than re-derived later, since the SDK objects it
    # would need to re-derive from are gone once the loop exits.
    messages: list[dict[str, Any]] = [dict(m) for m in history]
    persistable: list[dict[str, Any]] = []

    user_entry = {"role": "user", "content": [{"type": "text", "text": build_user_turn(today, message)}]}
    messages.append(user_entry)
    persistable.append(user_entry)

    tool_call_names: list[str] = []
    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }
    reply_text = ""
    stop_reason: str | None = None
    refusal = False

    for _ in range(MAX_TOOL_ITERATIONS):
        async with client.messages.stream(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOL_SCHEMAS,
            messages=messages,
            output_config={"effort": EFFORT},
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    yield {"type": "text_delta", "text": event.delta.text}
                elif event.type == "content_block_start" and event.content_block.type == "tool_use":
                    yield {"type": "tool_call", "name": event.content_block.name}
            response = await stream.get_final_message()

        for key in usage_totals:
            usage_totals[key] += getattr(response.usage, key, 0) or 0

        stop_reason = response.stop_reason
        if stop_reason == "refusal":
            refusal = True
            reply_text = "I'm not able to help with that request."
            break

        assistant_content_json = [block.model_dump(mode="json") for block in response.content]
        messages.append({"role": "assistant", "content": response.content})
        persistable.append({"role": "assistant", "content": assistant_content_json})

        if stop_reason != "tool_use":
            reply_text = "".join(b.text for b in response.content if b.type == "text").strip()
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_call_names.append(block.name)
            content_str, is_error = await execute_tool(
                block.name, block.input, db=db, user_id=user_id, today=today, preferences=preferences
            )
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block.id, "content": content_str, "is_error": is_error}
            )
        tool_result_entry = {"role": "user", "content": tool_results}
        messages.append(tool_result_entry)
        persistable.append(tool_result_entry)
    else:
        reply_text = "I wasn't able to finish that within my tool-call budget — try narrowing the question."
        # Drop the dangling tool-result-less state: don't persist a turn that
        # ends mid-loop with no assistant answer to show for it.
        persistable = persistable[:1]

    yield {
        "type": "result",
        "reply_text": reply_text,
        "tool_calls": tool_call_names,
        "usage": usage_totals,
        "stop_reason": stop_reason,
        "refusal": refusal,
        "new_messages": persistable,
    }


async def stream_turn(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message: str,
    today: date,
    preferences: dict,
) -> AsyncIterator[dict]:
    client = _get_client()
    if client is None:
        yield {"type": "error", "message": "The assistant isn't configured (no ANTHROPIC_API_KEY)."}
        yield {"type": "result", "result": AgentTurnResult(reply_text="", error="not_configured")}
        return

    history = await _load_history(db, conversation_id)
    started = time.monotonic()
    result: AgentTurnResult

    try:
        async for event in _run_loop(
            client=client, message=message, history=history, today=today, preferences=preferences, db=db, user_id=user_id
        ):
            if event["type"] != "result":
                yield event
                continue
            result = AgentTurnResult(
                reply_text=event["reply_text"],
                tool_calls=event["tool_calls"],
                input_tokens=event["usage"]["input_tokens"],
                output_tokens=event["usage"]["output_tokens"],
                cache_read_tokens=event["usage"]["cache_read_input_tokens"],
                cache_write_tokens=event["usage"]["cache_creation_input_tokens"],
                latency_ms=int((time.monotonic() - started) * 1000),
                stop_reason=event["stop_reason"],
                refusal=event["refusal"],
            )
            if not result.refusal:
                await _persist_new_messages(db, conversation_id, event["new_messages"])
    except anthropic.APIError as exc:
        result = AgentTurnResult(
            reply_text="", latency_ms=int((time.monotonic() - started) * 1000), error=str(exc)
        )
        yield {"type": "error", "message": "The assistant hit an error talking to the model. Try again shortly."}

    await _log_run(db, conversation_id, result)
    yield {"type": "result", "result": result}


async def run_turn(
    *,
    db: AsyncSession,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    message: str,
    today: date,
    preferences: dict,
) -> AgentTurnResult:
    """Drains `stream_turn` for callers that just want the final answer."""
    result: AgentTurnResult | None = None
    async for event in stream_turn(
        db=db, user_id=user_id, conversation_id=conversation_id, message=message, today=today, preferences=preferences
    ):
        if event["type"] == "result":
            result = event["result"]
    assert result is not None
    return result
