import uuid

from app.auth import _mint_jwt


async def test_list_todos_unauthenticated(client):
    r = await client.get("/api/todos")
    assert r.status_code == 401


async def test_list_todos_empty(auth_client):
    r = await auth_client.get("/api/todos")
    assert r.status_code == 200
    assert r.json() == []


async def test_create_todo(auth_client):
    r = await auth_client.post("/api/todos", json={"title": "Buy milk"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Buy milk"
    assert data["completed"] is False
    assert data["description"] is None


async def test_create_todo_with_description(auth_client):
    r = await auth_client.post("/api/todos", json={"title": "Read book", "description": "Chapter 1"})
    assert r.status_code == 201
    assert r.json()["description"] == "Chapter 1"


async def test_list_todos_returns_created(auth_client):
    await auth_client.post("/api/todos", json={"title": "Task A"})
    await auth_client.post("/api/todos", json={"title": "Task B"})
    r = await auth_client.get("/api/todos")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    assert "Task A" in titles
    assert "Task B" in titles


async def test_filter_active(auth_client):
    await auth_client.post("/api/todos", json={"title": "Active task"})
    r1 = await auth_client.post("/api/todos", json={"title": "Done task"})
    todo_id = r1.json()["id"]
    await auth_client.patch(f"/api/todos/{todo_id}", json={"completed": True})

    r = await auth_client.get("/api/todos?status=active")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    assert "Active task" in titles
    assert "Done task" not in titles


async def test_filter_completed(auth_client):
    await auth_client.post("/api/todos", json={"title": "Still active"})
    r1 = await auth_client.post("/api/todos", json={"title": "Finished"})
    todo_id = r1.json()["id"]
    await auth_client.patch(f"/api/todos/{todo_id}", json={"completed": True})

    r = await auth_client.get("/api/todos?status=completed")
    assert r.status_code == 200
    titles = [t["title"] for t in r.json()]
    assert "Finished" in titles
    assert "Still active" not in titles


async def test_update_todo(auth_client):
    r = await auth_client.post("/api/todos", json={"title": "Original"})
    todo_id = r.json()["id"]

    r = await auth_client.patch(f"/api/todos/{todo_id}", json={"title": "Updated", "completed": True})
    assert r.status_code == 200
    assert r.json()["title"] == "Updated"
    assert r.json()["completed"] is True


async def test_update_todo_other_user_returns_404(client, db, other_user):
    # create a todo as other_user
    token = _mint_jwt(str(other_user.id))
    client.cookies.set("__session", token)
    r = await client.post("/api/todos", json={"title": "Other's todo"})
    todo_id = r.json()["id"]

    # try to update it as a third user
    from app.models import User
    import uuid
    third = User(google_id="google-third-789", email="third@example.com", name="Third")
    db.add(third)
    await db.commit()
    await db.refresh(third)

    client.cookies.set("__session", _mint_jwt(str(third.id)))
    r = await client.patch(f"/api/todos/{todo_id}", json={"title": "Stolen"})
    assert r.status_code == 404


async def test_delete_todo(auth_client):
    r = await auth_client.post("/api/todos", json={"title": "To delete"})
    todo_id = r.json()["id"]

    r = await auth_client.delete(f"/api/todos/{todo_id}")
    assert r.status_code == 204

    r = await auth_client.get("/api/todos")
    assert all(t["id"] != todo_id for t in r.json())


async def test_delete_todo_other_user_returns_404(client, db, other_user, user):
    # create todo as other_user
    token = _mint_jwt(str(other_user.id))
    client.cookies.set("__session", token)
    r = await client.post("/api/todos", json={"title": "Other's todo"})
    todo_id = r.json()["id"]

    # try to delete as user
    client.cookies.set("__session", _mint_jwt(str(user.id)))
    r = await client.delete(f"/api/todos/{todo_id}")
    assert r.status_code == 404


async def test_todos_isolated_between_users(client, user, other_user):
    # user creates a todo
    client.cookies.set("__session", _mint_jwt(str(user.id)))
    await client.post("/api/todos", json={"title": "User's private todo"})

    # other_user sees an empty list
    client.cookies.set("__session", _mint_jwt(str(other_user.id)))
    r = await client.get("/api/todos")
    assert r.status_code == 200
    assert r.json() == []


# ── importance & locked (Phase A — see TRIAGE.md) ───────────────────────────


async def test_create_todo_defaults_importance_null_and_unlocked(auth_client):
    r = await auth_client.post("/api/todos", json={"title": "Fresh task"})
    assert r.status_code == 201
    body = r.json()
    assert body["importance"] is None, "new tasks start unclassified"
    assert body["locked"] is False


async def test_create_and_update_importance(auth_client):
    created = (await auth_client.post("/api/todos", json={"title": "T", "importance": 3})).json()
    assert created["importance"] == 3

    updated = (await auth_client.patch(f"/api/todos/{created['id']}", json={"importance": 1})).json()
    assert updated["importance"] == 1

    cleared = (await auth_client.patch(f"/api/todos/{created['id']}", json={"importance": None})).json()
    assert cleared["importance"] is None


async def test_importance_is_rejected_outside_1_to_3(auth_client):
    for bad in (0, 4, -1):
        r = await auth_client.post("/api/todos", json={"title": "T", "importance": bad})
        assert r.status_code == 422, f"importance={bad} should be rejected"


async def test_lock_and_unlock_round_trip(auth_client):
    created = (await auth_client.post("/api/todos", json={"title": "Protected"})).json()

    locked = (await auth_client.patch(f"/api/todos/{created['id']}", json={"locked": True})).json()
    assert locked["locked"] is True

    listed = (await auth_client.get("/api/todos")).json()
    assert listed[0]["locked"] is True, "lock must survive a round trip"

    unlocked = (await auth_client.patch(f"/api/todos/{created['id']}", json={"locked": False})).json()
    assert unlocked["locked"] is False


async def test_locking_does_not_block_the_user_editing_their_own_task(auth_client):
    """`locked` is a veto against the assistant, not against the owner."""
    created = (await auth_client.post("/api/todos", json={"title": "Protected"})).json()
    await auth_client.patch(f"/api/todos/{created['id']}", json={"locked": True})

    r = await auth_client.patch(f"/api/todos/{created['id']}", json={"title": "Renamed by owner"})
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed by owner"


# ── todo_revisions audit trail (Phase C) ────────────────────────────────────


async def test_create_todo_writes_a_revision(auth_client, db):
    from app.models import TodoRevision

    created = (await auth_client.post("/api/todos", json={"title": "Tracked"})).json()

    result = await db.execute(TodoRevision.__table__.select())
    revs = result.fetchall()
    assert len(revs) == 1
    assert revs[0].todo_id == uuid.UUID(created["id"])
    assert revs[0].source == "user"
    assert revs[0].before is None
    assert revs[0].after["title"] == "Tracked"


async def test_update_todo_writes_a_revision_with_before_and_after(auth_client, db):
    from app.models import TodoRevision

    created = (await auth_client.post("/api/todos", json={"title": "Original"})).json()
    await auth_client.patch(f"/api/todos/{created['id']}", json={"title": "Updated"})

    result = await db.execute(
        TodoRevision.__table__.select().where(TodoRevision.__table__.c.todo_id == uuid.UUID(created["id"]))
    )
    revs = result.fetchall()
    assert len(revs) == 2, "one revision for create, one for update"
    update_rev = revs[-1]
    assert update_rev.source == "user"
    assert update_rev.before["title"] == "Original"
    assert update_rev.after["title"] == "Updated"


async def test_update_with_no_fields_does_not_write_a_revision(auth_client, db):
    from app.models import TodoRevision

    created = (await auth_client.post("/api/todos", json={"title": "Untouched"})).json()
    await auth_client.patch(f"/api/todos/{created['id']}", json={})

    result = await db.execute(
        TodoRevision.__table__.select().where(TodoRevision.__table__.c.todo_id == uuid.UUID(created["id"]))
    )
    assert len(result.fetchall()) == 1, "only the create revision, no-op update writes nothing"


async def test_delete_todo_writes_a_revision_with_after_none(auth_client, db):
    from app.models import TodoRevision

    created = (await auth_client.post("/api/todos", json={"title": "Doomed"})).json()
    await auth_client.delete(f"/api/todos/{created['id']}")

    result = await db.execute(
        TodoRevision.__table__.select().where(TodoRevision.__table__.c.todo_id == uuid.UUID(created["id"]))
    )
    revs = result.fetchall()
    delete_rev = revs[-1]
    assert delete_rev.source == "user"
    assert delete_rev.before["title"] == "Doomed"
    assert delete_rev.after is None
