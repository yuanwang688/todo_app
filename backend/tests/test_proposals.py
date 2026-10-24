import uuid
from datetime import date, datetime, timedelta, timezone

import pytest_asyncio

from app.auth import _mint_jwt
from app.models import Conversation, Proposal, ProposalItem, Todo, TodoRevision


@pytest_asyncio.fixture
async def conversation(db, user):
    c = Conversation(user_id=user.id)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _make_todo(db, user, **kwargs):
    kwargs.setdefault("title", "Task")
    todo = Todo(user_id=user.id, **kwargs)
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return todo


async def _make_proposal(db, user, conversation, items):
    """items: list of dicts with op/todo_id/changes/rationale/quadrant/seen_updated_at."""
    proposal = Proposal(conversation_id=conversation.id, user_id=user.id, summary="Test batch")
    db.add(proposal)
    await db.flush()
    rows = []
    for item in items:
        row = ProposalItem(proposal_id=proposal.id, **item)
        db.add(row)
        rows.append(row)
    await db.commit()
    await db.refresh(proposal)
    for row in rows:
        await db.refresh(row)
    return proposal, rows


# ── get ──────────────────────────────────────────────────────────────────────


async def test_get_proposal_not_found(auth_client):
    r = await auth_client.get(f"/api/proposals/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_get_proposal_other_user_404(client, db, user, other_user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    client.cookies.set("__session", _mint_jwt(str(other_user.id)))
    r = await client.get(f"/api/proposals/{proposal.id}")
    assert r.status_code == 404


async def test_get_proposal_returns_items(auth_client, db, user, conversation):
    todo = await _make_todo(db, user)
    proposal, _ = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": None, "to": 3}},
            "rationale": "urgent and important", "quadrant": "Q1",
            "seen_updated_at": todo.updated_at,
        },
    ])
    r = await auth_client.get(f"/api/proposals/{proposal.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert len(body["items"]) == 1
    assert body["items"][0]["status"] == "pending"


async def test_pending_proposal_expires_after_24h(auth_client, db, user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    proposal.created_at = datetime.now(timezone.utc) - timedelta(hours=25)
    await db.commit()

    r = await auth_client.get(f"/api/proposals/{proposal.id}")
    assert r.status_code == 200
    assert r.json()["status"] == "expired"


# ── apply: happy paths ───────────────────────────────────────────────────────


async def test_apply_update_writes_revision_and_marks_applied(auth_client, db, user, conversation):
    todo = await _make_todo(db, user, importance=None)
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": None, "to": 3}},
            "rationale": "important", "quadrant": "Q2",
            "seen_updated_at": todo.updated_at,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    body = r.json()
    assert body["proposal_status"] == "applied"
    assert body["items"] == [{"item_id": str(items[0].id), "status": "applied", "detail": None}]

    await db.refresh(todo)
    assert todo.importance == 3

    revs = (await db.execute(TodoRevision.__table__.select())).fetchall()
    assert len(revs) == 1
    assert revs[0].source == "agent"
    assert revs[0].before["importance"] is None
    assert revs[0].after["importance"] == 3


async def test_apply_create_inserts_new_todo(auth_client, db, user, conversation):
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "create", "todo_id": None,
            "changes": {"title": "New task", "category": "chores"},
            "rationale": "split from a vague task", "quadrant": "Q2",
            "seen_updated_at": None,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "applied"

    r = await auth_client.get("/api/todos")
    titles = [t["title"] for t in r.json()]
    assert "New task" in titles


async def test_apply_update_with_date_field(auth_client, db, user, conversation):
    """propose_changes sends date fields as raw ISO strings (see
    PROPOSE_CHANGES_SCHEMA) — applying one must parse it into a real date,
    not hand a string straight to the DB driver (asyncpg rejects that,
    though SQLite silently tolerates it, which is why this needs its own
    coverage rather than relying on the importance-only apply test)."""
    todo = await _make_todo(db, user, target_date=date(2026, 8, 1))
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"target_date": {"from": "2026-08-01", "to": "2026-08-12"}},
            "rationale": "defer", "quadrant": "Q4",
            "seen_updated_at": todo.updated_at,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "applied"

    await db.refresh(todo)
    assert todo.target_date == date(2026, 8, 12)


async def test_apply_create_with_date_field(auth_client, db, user, conversation):
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "create", "todo_id": None,
            "changes": {"title": "New task", "target_date": "2026-08-12"},
            "rationale": "split from a vague task", "quadrant": "Q2",
            "seen_updated_at": None,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "applied"

    r = await auth_client.get("/api/todos")
    created = next(t for t in r.json() if t["title"] == "New task")
    assert created["target_date"] == "2026-08-12"


async def test_get_proposal_after_applied_delete_still_shows_title(auth_client, db, user, conversation):
    todo = await _make_todo(db, user, title="Duplicate")
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "delete", "todo_id": todo.id, "changes": {},
            "rationale": "duplicate of another task", "quadrant": "Q4",
            "seen_updated_at": todo.updated_at,
        },
    ])
    await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})

    r = await auth_client.get(f"/api/proposals/{proposal.id}")
    assert r.status_code == 200
    assert r.json()["items"][0]["todo_title"] == "Duplicate"


async def test_apply_delete_removes_todo(auth_client, db, user, conversation):
    todo = await _make_todo(db, user, title="Duplicate")
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "delete", "todo_id": todo.id, "changes": {},
            "rationale": "duplicate of another task", "quadrant": "Q4",
            "seen_updated_at": todo.updated_at,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "applied"

    r = await auth_client.get("/api/todos")
    assert all(t["id"] != str(todo.id) for t in r.json())


async def test_apply_unselected_items_marked_skipped(auth_client, db, user, conversation):
    todo1 = await _make_todo(db, user, title="One")
    todo2 = await _make_todo(db, user, title="Two")
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo1.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r1", "quadrant": "Q2", "seen_updated_at": todo1.updated_at,
        },
        {
            "op": "update", "todo_id": todo2.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r2", "quadrant": "Q2", "seen_updated_at": todo2.updated_at,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    statuses = {i["item_id"]: i["status"] for i in r.json()["items"]}
    assert statuses[str(items[0].id)] == "applied"
    assert statuses[str(items[1].id)] == "skipped"

    await db.refresh(todo2)
    assert todo2.importance is None, "unselected item must not mutate its todo"


# ── apply: blocking cases (all-or-nothing) ──────────────────────────────────


async def test_apply_stale_item_blocks_and_rolls_back_whole_batch(auth_client, db, user, conversation):
    todo1 = await _make_todo(db, user, title="Fresh")
    todo2 = await _make_todo(db, user, title="Edited elsewhere")
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo1.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r1", "quadrant": "Q2", "seen_updated_at": todo1.updated_at,
        },
        {
            "op": "update", "todo_id": todo2.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r2", "quadrant": "Q2",
            "seen_updated_at": todo2.updated_at - timedelta(seconds=5),  # stale on purpose
        },
    ])

    r = await auth_client.post(
        f"/api/proposals/{proposal.id}/apply",
        json={"item_ids": [str(items[0].id), str(items[1].id)]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["proposal_status"] == "pending"
    statuses = {i["item_id"]: i["status"] for i in body["items"]}
    assert statuses[str(items[1].id)] == "stale"
    assert statuses[str(items[0].id)] == "invalid"  # blocked by its batch-mate, not committed

    await db.refresh(todo1)
    assert todo1.importance is None, "nothing should have been written when the batch was blocked"

    r = await auth_client.get(f"/api/proposals/{proposal.id}")
    assert r.json()["status"] == "pending", "proposal must stay pending so the user can retry"


async def test_apply_after_deselecting_stale_item_succeeds(auth_client, db, user, conversation):
    todo1 = await _make_todo(db, user, title="Fresh")
    todo2 = await _make_todo(db, user, title="Edited elsewhere")
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo1.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r1", "quadrant": "Q2", "seen_updated_at": todo1.updated_at,
        },
        {
            "op": "update", "todo_id": todo2.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r2", "quadrant": "Q2",
            "seen_updated_at": todo2.updated_at - timedelta(seconds=5),
        },
    ])

    # first attempt blocked
    await auth_client.post(
        f"/api/proposals/{proposal.id}/apply",
        json={"item_ids": [str(items[0].id), str(items[1].id)]},
    )
    # retry with only the clean item selected
    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["proposal_status"] == "applied"
    await db.refresh(todo1)
    assert todo1.importance == 2


async def test_apply_locked_at_apply_time_blocks(auth_client, db, user, conversation):
    todo = await _make_todo(db, user)
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r", "quadrant": "Q2", "seen_updated_at": todo.updated_at,
        },
    ])
    # user locks the task after the proposal was created but before applying
    await auth_client.patch(f"/api/todos/{todo.id}", json={"locked": True})

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "invalid"
    assert r.json()["proposal_status"] == "pending"


async def test_apply_deleted_todo_at_apply_time_is_invalid(auth_client, db, user, conversation):
    todo = await _make_todo(db, user)
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r", "quadrant": "Q2", "seen_updated_at": todo.updated_at,
        },
    ])
    await auth_client.delete(f"/api/todos/{todo.id}")

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    assert r.status_code == 200
    assert r.json()["items"][0]["status"] == "invalid"


async def test_apply_non_pending_proposal_returns_409(auth_client, db, user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    proposal.status = "rejected"
    await db.commit()

    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": []})
    assert r.status_code == 409


async def test_apply_unknown_item_id_returns_400(auth_client, db, user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    r = await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(uuid.uuid4())]})
    assert r.status_code == 400


# ── reject ───────────────────────────────────────────────────────────────────


async def test_reject_marks_status_and_does_not_mutate_todos(auth_client, db, user, conversation):
    todo = await _make_todo(db, user)
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": None, "to": 2}},
            "rationale": "r", "quadrant": "Q2", "seen_updated_at": todo.updated_at,
        },
    ])

    r = await auth_client.post(f"/api/proposals/{proposal.id}/reject")
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    await db.refresh(todo)
    assert todo.importance is None


async def test_reject_non_pending_returns_409(auth_client, db, user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    proposal.status = "applied"
    await db.commit()

    r = await auth_client.post(f"/api/proposals/{proposal.id}/reject")
    assert r.status_code == 409


# ── undo ─────────────────────────────────────────────────────────────────────


async def test_undo_update_restores_previous_value(auth_client, db, user, conversation):
    todo = await _make_todo(db, user, importance=1)
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "update", "todo_id": todo.id,
            "changes": {"importance": {"from": 1, "to": 3}},
            "rationale": "r", "quadrant": "Q1", "seen_updated_at": todo.updated_at,
        },
    ])
    await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})

    r = await auth_client.post(f"/api/proposals/{proposal.id}/undo")
    assert r.status_code == 200
    assert r.json()["status"] == "undone"

    await db.refresh(todo)
    assert todo.importance == 1

    # undo itself is audited
    revs = (await db.execute(TodoRevision.__table__.select())).fetchall()
    assert len(revs) == 2
    assert revs[-1].before["importance"] == 3
    assert revs[-1].after["importance"] == 1


async def test_undo_create_deletes_the_todo(auth_client, db, user, conversation):
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "create", "todo_id": None,
            "changes": {"title": "Spawned"},
            "rationale": "r", "quadrant": "Q2", "seen_updated_at": None,
        },
    ])
    await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})
    created_id = (await auth_client.get("/api/todos")).json()[0]["id"]

    r = await auth_client.post(f"/api/proposals/{proposal.id}/undo")
    assert r.status_code == 200

    r = await auth_client.get("/api/todos")
    assert all(t["id"] != created_id for t in r.json())


async def test_undo_delete_recreates_the_todo(auth_client, db, user, conversation):
    todo = await _make_todo(db, user, title="Will be deleted")
    todo_id = todo.id
    proposal, items = await _make_proposal(db, user, conversation, [
        {
            "op": "delete", "todo_id": todo.id, "changes": {},
            "rationale": "duplicate", "quadrant": "Q4", "seen_updated_at": todo.updated_at,
        },
    ])
    await auth_client.post(f"/api/proposals/{proposal.id}/apply", json={"item_ids": [str(items[0].id)]})

    r = await auth_client.post(f"/api/proposals/{proposal.id}/undo")
    assert r.status_code == 200

    r = await auth_client.get("/api/todos")
    titles_by_id = {t["id"]: t["title"] for t in r.json()}
    assert titles_by_id.get(str(todo_id)) == "Will be deleted"

    # ON DELETE SET NULL clears proposal_items.todo_id the moment the delete
    # is applied — undo must re-link it now that the row exists again.
    r = await auth_client.get(f"/api/proposals/{proposal.id}")
    item_out = r.json()["items"][0]
    assert item_out["todo_id"] == str(todo_id)
    assert item_out["todo_title"] == "Will be deleted"


async def test_undo_non_applied_proposal_returns_409(auth_client, db, user, conversation):
    proposal, _ = await _make_proposal(db, user, conversation, [])
    r = await auth_client.post(f"/api/proposals/{proposal.id}/undo")
    assert r.status_code == 409
