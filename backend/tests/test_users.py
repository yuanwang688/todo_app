async def test_get_me(auth_client, user):
    r = await auth_client.get("/api/me")
    assert r.status_code == 200
    data = r.json()
    assert data["email"] == user.email
    assert data["name"] == user.name


async def test_get_me_unauthenticated(client):
    r = await client.get("/api/me")
    assert r.status_code == 401
