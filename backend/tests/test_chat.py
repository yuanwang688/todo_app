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
