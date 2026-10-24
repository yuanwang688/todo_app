from datetime import datetime, timedelta, timezone

import pytest_asyncio

from app.models import Conversation, Proposal, ProposalItem, Todo


@pytest_asyncio.fixture
async def conversation(db, user):
    c = Conversation(user_id=user.id)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def test_get_chat_unauthenticated(client):
    r = await client.get("/api/chat")
    assert r.status_code == 401


async def test_get_chat_includes_pending_proposal(auth_client, db, user, conversation):
    todo = Todo(user_id=user.id, title="Task")
    db.add(todo)
    await db.commit()
    await db.refresh(todo)

    proposal = Proposal(conversation_id=conversation.id, user_id=user.id, summary="Batch")
    db.add(proposal)
    await db.flush()
    db.add(ProposalItem(
        proposal_id=proposal.id, op="update", todo_id=todo.id,
        changes={"importance": {"from": None, "to": 2}},
        rationale="r", quadrant="Q2", seen_updated_at=todo.updated_at,
    ))
    await db.commit()

    r = await auth_client.get("/api/chat")
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == str(conversation.id)
    assert len(body["pending_proposals"]) == 1
    assert body["pending_proposals"][0]["status"] == "pending"
    assert len(body["pending_proposals"][0]["items"]) == 1


async def test_get_chat_omits_resolved_proposals(auth_client, db, user, conversation):
    proposal = Proposal(conversation_id=conversation.id, user_id=user.id, summary="Batch", status="rejected")
    db.add(proposal)
    await db.commit()

    r = await auth_client.get("/api/chat")
    assert r.json()["pending_proposals"] == []


async def test_get_chat_omits_expired_proposal(auth_client, db, user, conversation):
    proposal = Proposal(conversation_id=conversation.id, user_id=user.id, summary="Batch")
    db.add(proposal)
    await db.commit()
    await db.refresh(proposal)
    proposal.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    await db.commit()

    r = await auth_client.get("/api/chat")
    assert r.json()["pending_proposals"] == []


async def test_post_message_uses_saved_planning_preferences(auth_client, monkeypatch):
    """Phase D: the turn plans against the user's saved preferences and their
    local date, not the hardcoded defaults the router used before."""
    from app.agent import service
    from app.routers import chat as chat_router

    prefs = {
        "daily_capacity_hours": 6.0, "workdays": [1, 2, 3, 4, 5, 6], "urgency_horizon_days": 2,
        "timezone": "Pacific/Kiritimati", "notes": "Mornings only.",
    }
    assert (await auth_client.put("/api/planning-preferences", json=prefs)).status_code == 200

    seen = {}

    async def fake_stream_turn(**kwargs):
        seen.update(kwargs)
        yield {"type": "result", "result": service.AgentTurnResult(reply_text="ok")}

    monkeypatch.setattr(service, "is_configured", lambda: True)
    monkeypatch.setattr(service, "stream_turn", fake_stream_turn)
    r = await auth_client.post("/api/chat/messages", json={"message": "hi"})
    assert r.status_code == 200
    assert seen["preferences"] == prefs
    assert seen["today"] == chat_router.planning.today_for(prefs)


async def test_get_chat_shows_only_the_message_not_the_context_block(auth_client, db, user, conversation):
    """User turns are [context, message] since Phase D; turns persisted before
    that are a single block with a date prefix. Both display as the message."""
    from app.models import Message

    db.add_all([
        Message(conversation_id=conversation.id, role="user", seq=0,
                content=[{"type": "text", "text": "(Today is Monday, August 03, 2026.)\n\nold question"}]),
        Message(conversation_id=conversation.id, role="assistant", seq=1,
                content=[{"type": "text", "text": "old answer"}]),
        Message(conversation_id=conversation.id, role="user", seq=2,
                content=[{"type": "text", "text": "(Today is …)\n\nThe user's current planning preferences…"},
                         {"type": "text", "text": "new question"}]),
        Message(conversation_id=conversation.id, role="assistant", seq=3,
                content=[{"type": "text", "text": "new answer"}]),
    ])
    await db.commit()

    r = await auth_client.get("/api/chat")
    assert [m["text"] for m in r.json()["messages"]] == ["old question", "old answer", "new question", "new answer"]
