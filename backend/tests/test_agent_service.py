"""Tests for the agent loop against a fake Anthropic client.

There's no ANTHROPIC_API_KEY in CI or most dev environments, so these tests
never touch the network. Instead they drive `app.agent.service` with a fake
client whose `messages.stream(...)` returns scripted, real SDK response
objects (`anthropic.types.Message`, `TextBlock`, `ToolUseBlock`, ...) — real
types so nothing here can drift from the actual response shape, fake data so
it costs nothing and runs in milliseconds.

This is what stands in for "browser-verified Q&A" until a key is available:
it proves the loop — history, tool execution, persistence, usage accounting,
refusal handling — is wired correctly, even though it can't prove the model
picks the right tool for a given question. `pytest evals` (with a real key)
is what proves that.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from anthropic import APIConnectionError
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage
from anthropic.types.parsed_message import ParsedTextBlock
from sqlalchemy import select

from app.agent import service
from app.agent.service import _replayable_block
from app.models import AgentRun, Message as MessageRow, Todo

TODAY = date(2026, 8, 3)
PREFS = {"daily_capacity_hours": 4.0, "workdays": [1, 2, 3, 4, 5], "urgency_horizon_days": 3, "notes": None}


def usage(**over) -> Usage:
    base = dict(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0)
    base.update(over)
    return Usage(**base)


def text_message(text: str, *, stop_reason: str = "end_turn", **usage_over) -> Message:
    return Message(
        id="msg_1", model="claude-opus-5", role="assistant", type="message",
        content=[TextBlock(type="text", text=text, citations=None)],
        stop_reason=stop_reason, stop_sequence=None, usage=usage(**usage_over),
    )


def tool_use_message(name: str, tool_input: dict, *, tool_id: str = "toolu_1", **usage_over) -> Message:
    return Message(
        id="msg_1", model="claude-opus-5", role="assistant", type="message",
        content=[ToolUseBlock(type="tool_use", id=tool_id, name=name, input=tool_input)],
        stop_reason="tool_use", stop_sequence=None, usage=usage(**usage_over),
    )


def refusal_message() -> Message:
    return Message(
        id="msg_1", model="claude-opus-5", role="assistant", type="message",
        content=[], stop_reason="refusal", stop_sequence=None, usage=usage(),
    )


class FakeStream:
    def __init__(self, final_message: Message):
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def __aiter__(self):
        async def _empty():
            return
            yield  # pragma: no cover - makes this an async generator
        return _empty()

    async def get_final_message(self) -> Message:
        return self._final_message


class RaisingStream:
    """Simulates a network failure while the stream is open."""

    async def __aenter__(self):
        raise APIConnectionError(message="connection reset", request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))

    async def __aexit__(self, *exc):
        return False


class FakeMessagesAPI:
    def __init__(self, script: list[Message | Exception]):
        self._script = list(script)
        self.calls: list[dict] = []

    def stream(self, **kwargs):
        # `messages` is the same list `_run_loop` keeps mutating across
        # iterations — snapshot it now, or a later append would retroactively
        # change what an earlier call appears to have sent.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return FakeStream(item)


class FakeClient:
    def __init__(self, script: list[Message | Exception]):
        self.messages = FakeMessagesAPI(script)


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    """`service.is_configured()` gates every entry point — make it True and
    inject a fake client via the module-level singleton hook."""
    monkeypatch.setattr(service.settings, "anthropic_api_key", "test-key-not-real")
    service._client = None
    yield
    service._client = None


def install_fake_client(monkeypatch, script: list[Message | Exception]) -> FakeClient:
    fake = FakeClient(script)
    monkeypatch.setattr(service, "_get_client", lambda: fake)
    return fake


@pytest.fixture
async def conversation(db, user):
    return await service.get_or_create_conversation(db, user.id)


async def seed_todo(db, user, **kw):
    t = Todo(user_id=user.id, title=kw.pop("title", "A task"), **kw)
    db.add(t)
    await db.commit()
    await db.refresh(t)
    return t


# ── replayable-block serialization ──────────────────────────────────────────
# Regression coverage for a bug only a real API call surfaced: client.messages
# .stream() returns Parsed* convenience subclasses carrying extra response-only
# fields (e.g. `parsed_output`) that the API rejects if echoed back as request
# content on a later turn ("Extra inputs are not permitted"). These tests use
# the actual SDK type responsible, not a hand-rolled stand-in, so a future SDK
# upgrade that changes its fields would still be caught here.


def test_replayable_block_strips_parsed_output_from_text_blocks():
    block = ParsedTextBlock(type="text", text="hello", citations=None, parsed_output=None)
    assert _replayable_block(block) == {"type": "text", "text": "hello"}


def test_replayable_block_strips_caller_from_tool_use_blocks():
    block = ToolUseBlock(type="tool_use", id="toolu_1", name="search_todos", input={"limit": 5})
    assert _replayable_block(block) == {
        "type": "tool_use", "id": "toolu_1", "name": "search_todos", "input": {"limit": 5},
    }


async def test_second_turn_with_real_block_types_does_not_reintroduce_parsed_output(db, user, conversation, monkeypatch):
    """Turn 1's assistant content must be persisted in a form turn 2 can
    replay — this is the exact shape that 400'd against the real API before
    `_replayable_block` existed."""
    parsed_reply = Message(
        id="msg_1", model="claude-opus-5", role="assistant", type="message",
        content=[ParsedTextBlock(type="text", text="All clear.", citations=None, parsed_output=None)],
        stop_reason="end_turn", stop_sequence=None, usage=usage(),
    )
    install_fake_client(monkeypatch, [parsed_reply, text_message("Still clear.")])

    await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                            message="first", today=TODAY, preferences=PREFS)
    result = await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                                     message="second", today=TODAY, preferences=PREFS)

    assert result.error is None
    rows = (await db.execute(
        select(MessageRow).where(MessageRow.conversation_id == conversation.id).order_by(MessageRow.seq)
    )).scalars().all()
    assert "parsed_output" not in rows[1].content[0]


# ── the direct-answer path ──────────────────────────────────────────────────


async def test_direct_text_answer_no_tools(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [text_message("Nothing's overdue.")])

    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="Anything overdue?", today=TODAY, preferences=PREFS,
    )

    assert result.reply_text == "Nothing's overdue."
    assert result.tool_calls == []
    assert result.error is None
    assert result.refusal is False
    assert result.input_tokens == 100
    assert result.output_tokens == 20


async def test_persists_user_and_assistant_turns(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [text_message("All clear.")])
    await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="Anything overdue?", today=TODAY, preferences=PREFS,
    )

    rows = (await db.execute(
        select(MessageRow).where(MessageRow.conversation_id == conversation.id).order_by(MessageRow.seq)
    )).scalars().all()
    assert [r.role for r in rows] == ["user", "assistant"]
    assert "Anything overdue?" in rows[0].content[0]["text"]
    assert rows[0].content[0]["text"].startswith("(Today is Monday, August 03, 2026.)")
    assert rows[1].content[0]["text"] == "All clear."


async def test_logs_agent_run(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [text_message("Done.", input_tokens=42, output_tokens=7)])
    await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="hi", today=TODAY, preferences=PREFS,
    )
    runs = (await db.execute(select(AgentRun).where(AgentRun.conversation_id == conversation.id))).scalars().all()
    assert len(runs) == 1
    assert runs[0].status == "ok"
    assert runs[0].input_tokens == 42
    assert runs[0].output_tokens == 7
    assert runs[0].model == service.MODEL
    assert runs[0].effort == service.EFFORT


# ── the tool-use path ────────────────────────────────────────────────────────


async def test_executes_tool_and_feeds_result_back(db, user, conversation, monkeypatch):
    await seed_todo(db, user, title="Renew passport", completed=False)
    client = install_fake_client(monkeypatch, [
        tool_use_message("search_todos", {"limit": 10}),
        text_message("You have one task: Renew passport."),
    ])

    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="what do I have?", today=TODAY, preferences=PREFS,
    )

    assert result.tool_calls == ["search_todos"]
    assert "Renew passport" in result.reply_text

    # The second API call must include the tool_result the loop generated —
    # this is the actual DB query result reaching the model, not a stub.
    second_call_messages = client.messages.calls[1]["messages"]
    tool_result_entry = second_call_messages[-1]
    assert tool_result_entry["role"] == "user"
    assert tool_result_entry["content"][0]["type"] == "tool_result"
    assert "Renew passport" in tool_result_entry["content"][0]["content"]


async def test_tool_error_is_reported_as_is_error_not_raised(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [
        tool_use_message("get_todo_details", {"todo_id": "not-a-uuid"}),
        text_message("I couldn't find that task."),
    ])
    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="tell me about task xyz", today=TODAY, preferences=PREFS,
    )
    assert result.error is None  # the tool error didn't crash the turn
    assert "couldn't find" in result.reply_text


async def test_unresolved_tool_loop_stops_gracefully(db, user, conversation, monkeypatch):
    """The model keeps calling tools forever — must not hang or crash."""
    script = [tool_use_message("search_todos", {}) for _ in range(service.MAX_TOOL_ITERATIONS)]
    install_fake_client(monkeypatch, script)

    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="keep looking", today=TODAY, preferences=PREFS,
    )
    assert "wasn't able to finish" in result.reply_text
    assert len(result.tool_calls) == service.MAX_TOOL_ITERATIONS

    # A broken turn persists nothing beyond the user's own message — no
    # half-finished assistant turn sits in history for the next request.
    rows = (await db.execute(select(MessageRow).where(MessageRow.conversation_id == conversation.id))).scalars().all()
    assert [r.role for r in rows] == ["user"]


# ── refusal and error paths ─────────────────────────────────────────────────


async def test_refusal_persists_nothing_and_is_logged(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [refusal_message()])
    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="something disallowed", today=TODAY, preferences=PREFS,
    )
    assert result.refusal is True
    assert result.reply_text  # a friendly message, not blank — see service.py

    rows = (await db.execute(select(MessageRow).where(MessageRow.conversation_id == conversation.id))).scalars().all()
    assert rows == []
    runs = (await db.execute(select(AgentRun).where(AgentRun.conversation_id == conversation.id))).scalars().all()
    assert runs[0].status == "refusal"


async def test_api_error_is_caught_and_logged(db, user, conversation, monkeypatch):
    install_fake_client(monkeypatch, [
        APIConnectionError(message="boom", request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    ])
    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="hi", today=TODAY, preferences=PREFS,
    )
    assert result.error is not None
    rows = (await db.execute(select(MessageRow).where(MessageRow.conversation_id == conversation.id))).scalars().all()
    assert rows == []
    runs = (await db.execute(select(AgentRun).where(AgentRun.conversation_id == conversation.id))).scalars().all()
    assert runs[0].status == "error"


async def test_mid_stream_failure_is_caught(db, user, conversation, monkeypatch):
    """The exception can also surface inside the stream context manager."""
    fake = FakeClient([])
    fake.messages.stream = lambda **kw: RaisingStream()
    monkeypatch.setattr(service, "_get_client", lambda: fake)

    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="hi", today=TODAY, preferences=PREFS,
    )
    assert result.error is not None


async def test_not_configured_short_circuits(db, user, conversation, monkeypatch):
    monkeypatch.setattr(service.settings, "anthropic_api_key", "")
    result = await service.run_turn(
        db=db, user_id=user.id, conversation_id=conversation.id,
        message="hi", today=TODAY, preferences=PREFS,
    )
    assert result.error == "not_configured"


# ── conversation continuity ──────────────────────────────────────────────────


async def test_second_turn_sees_first_turns_history(db, user, conversation, monkeypatch):
    client = install_fake_client(monkeypatch, [
        text_message("First answer."),
        text_message("Second answer."),
    ])
    await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                            message="first question", today=TODAY, preferences=PREFS)
    await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                            message="second question", today=TODAY, preferences=PREFS)

    second_request_messages = client.messages.calls[1]["messages"]
    # history (2 rows from turn 1) + this turn's new user message
    assert len(second_request_messages) == 3
    assert "first question" in second_request_messages[0]["content"][0]["text"]
    assert second_request_messages[1]["content"][0]["text"] == "First answer."
    assert "second question" in second_request_messages[2]["content"][0]["text"]


async def test_get_or_create_conversation_is_idempotent(db, user):
    first = await service.get_or_create_conversation(db, user.id)
    second = await service.get_or_create_conversation(db, user.id)
    assert first.id == second.id


# ── prompt / caching shape ──────────────────────────────────────────────────


async def test_cache_control_on_last_system_block_only(db, user, conversation, monkeypatch):
    client = install_fake_client(monkeypatch, [text_message("ok")])
    await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                            message="hi", today=TODAY, preferences=PREFS)

    system = client.messages.calls[0]["system"]
    assert len(system) == 2
    assert "cache_control" not in system[0]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}


async def test_effort_and_model_are_set(db, user, conversation, monkeypatch):
    client = install_fake_client(monkeypatch, [text_message("ok")])
    await service.run_turn(db=db, user_id=user.id, conversation_id=conversation.id,
                            message="hi", today=TODAY, preferences=PREFS)
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-5"
    assert call["output_config"] == {"effort": "medium"}
    assert "thinking" not in call  # adaptive-by-default; never disabled (see service.py docstring)
