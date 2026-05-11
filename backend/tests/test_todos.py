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
