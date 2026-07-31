"""/auth/dev-login — local-testing-only passwordless login (scripts/dev_up.sh)."""
from app.config import settings
from app.auth import DEV_USER_GOOGLE_ID


async def test_dev_login_creates_the_fixed_dev_user_and_sets_a_session(client, db):
    r = await client.get("/auth/dev-login", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == settings.frontend_url
    assert "__session" in r.cookies

    me = await client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["email"] == "dev@localhost.test"


async def test_dev_login_reuses_the_same_user_on_repeat_calls(client, db):
    await client.get("/auth/dev-login", follow_redirects=False)
    first_id = (await client.get("/api/me")).json()["id"]

    client.cookies.clear()
    await client.get("/auth/dev-login", follow_redirects=False)
    second_id = (await client.get("/api/me")).json()["id"]

    assert first_id == second_id


async def test_dev_login_404s_in_production(client, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    r = await client.get("/auth/dev-login", follow_redirects=False)
    assert r.status_code == 404


async def test_dev_login_user_is_a_normal_authenticated_user(client, db):
    """Sanity check: the seeded todos a real user creates are visible through
    the normal /api/todos path once logged in via dev-login."""
    await client.get("/auth/dev-login", follow_redirects=False)
    r = await client.post("/api/todos", json={"title": "hello from dev-login"})
    assert r.status_code == 201

    listed = await client.get("/api/todos")
    assert any(t["title"] == "hello from dev-login" for t in listed.json())
