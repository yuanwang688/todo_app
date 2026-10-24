"""Planning preferences (Phase D): the /api/planning-preferences router, the
dict the assistant receives, and the user's local "today"."""
from datetime import datetime, timezone

from app import planning

VALID = {
    "daily_capacity_hours": 6.0,
    "workdays": [1, 2, 3, 4, 5, 6],
    "urgency_horizon_days": 2,
    "timezone": "America/Los_Angeles",
    "notes": "No Work tasks on weekends.",
}


# ── router ──────────────────────────────────────────────────────────────────


async def test_get_returns_defaults_before_any_save(auth_client):
    res = await auth_client.get("/api/planning-preferences")
    assert res.status_code == 200
    assert res.json() == planning.DEFAULT_PREFERENCES


async def test_get_does_not_create_a_row(auth_client, db, user):
    from sqlalchemy import select
    from app.models import UserPlanningPreferences

    await auth_client.get("/api/planning-preferences")
    rows = (await db.execute(select(UserPlanningPreferences))).scalars().all()
    assert rows == []


async def test_put_then_get_round_trips(auth_client):
    res = await auth_client.put("/api/planning-preferences", json=VALID)
    assert res.status_code == 200
    assert res.json() == VALID
    assert (await auth_client.get("/api/planning-preferences")).json() == VALID


async def test_put_twice_updates_in_place(auth_client):
    await auth_client.put("/api/planning-preferences", json=VALID)
    res = await auth_client.put("/api/planning-preferences", json={**VALID, "daily_capacity_hours": 3.5})
    assert res.json()["daily_capacity_hours"] == 3.5


async def test_put_normalises_workdays_and_blank_notes(auth_client):
    res = await auth_client.put(
        "/api/planning-preferences", json={**VALID, "workdays": [5, 1, 1, 3], "notes": "   "}
    )
    assert res.status_code == 200
    assert res.json()["workdays"] == [1, 3, 5]
    assert res.json()["notes"] is None


async def test_put_rejects_invalid_values(auth_client):
    bad = [
        {"daily_capacity_hours": 0},
        {"daily_capacity_hours": 25},
        {"workdays": []},
        {"workdays": [0, 1]},
        {"workdays": [8]},
        {"urgency_horizon_days": -1},
        {"urgency_horizon_days": 31},
        {"timezone": "Mars/Olympus_Mons"},
        {"notes": "x" * (planning.MAX_NOTES_LENGTH + 1)},
        {"unknown_field": True},
    ]
    for override in bad:
        res = await auth_client.put("/api/planning-preferences", json={**VALID, **override})
        assert res.status_code == 422, override


async def test_preferences_are_per_user(auth_client, db, other_user):
    await auth_client.put("/api/planning-preferences", json=VALID)
    assert await planning.load_preferences(db, other_user.id) == planning.DEFAULT_PREFERENCES


async def test_requires_auth(client):
    assert (await client.get("/api/planning-preferences")).status_code == 401
    assert (await client.put("/api/planning-preferences", json=VALID)).status_code == 401


# ── load / today ────────────────────────────────────────────────────────────


async def test_load_preferences_returns_saved_values(db, user):
    await planning.save_preferences(db, user.id, planning.PlanningPreferences(**VALID))
    assert await planning.load_preferences(db, user.id) == VALID


async def test_load_preferences_default_is_a_copy(db, user):
    prefs = await planning.load_preferences(db, user.id)
    prefs["daily_capacity_hours"] = 99
    assert planning.DEFAULT_PREFERENCES["daily_capacity_hours"] == 4.0


def test_today_for_uses_the_users_timezone():
    # 05:00 UTC on Aug 4 is still the evening of Aug 3 in Los Angeles.
    now = datetime(2026, 8, 4, 5, 0, tzinfo=timezone.utc)
    assert planning.today_for({"timezone": "America/Los_Angeles"}, now).isoformat() == "2026-08-03"
    assert planning.today_for({"timezone": "UTC"}, now).isoformat() == "2026-08-04"
    assert planning.today_for({"timezone": "Asia/Tokyo"}, now).isoformat() == "2026-08-04"


def test_today_for_falls_back_to_utc_on_a_bad_timezone():
    now = datetime(2026, 8, 4, 5, 0, tzinfo=timezone.utc)
    assert planning.today_for({"timezone": "Not/AZone"}, now).isoformat() == "2026-08-04"
    assert planning.today_for({}, now).isoformat() == "2026-08-04"
