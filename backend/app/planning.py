"""User planning preferences (Phase D) — capacity, workdays, urgency
horizon, timezone, and free-text planning policy.

Preferences reach the assistant as a plain dict (`load_preferences`), the
same shape the eval harness passes in directly, so the agent never needs to
know whether a value came from the database or a scenario file. A user who
has never saved preferences gets `DEFAULT_PREFERENCES`; GET never writes a row.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import triage
from .models import UserPlanningPreferences

MAX_NOTES_LENGTH = 2000

DEFAULT_PREFERENCES: dict[str, Any] = {
    "daily_capacity_hours": triage.DEFAULT_DAILY_CAPACITY_HOURS,
    "workdays": [1, 2, 3, 4, 5],
    "urgency_horizon_days": triage.DEFAULT_URGENCY_HORIZON_DAYS,
    "timezone": "UTC",
    "notes": None,
}


class PlanningPreferences(BaseModel):
    """Request and response body for /api/planning-preferences. Bounds are
    sanity limits, not policy — 24h is the most a day can hold."""

    model_config = {"extra": "forbid"}

    daily_capacity_hours: float = Field(gt=0, le=24)
    workdays: list[int] = Field(min_length=1, max_length=7)
    urgency_horizon_days: int = Field(ge=0, le=30)
    timezone: str
    notes: str | None = Field(default=None, max_length=MAX_NOTES_LENGTH)

    @field_validator("workdays")
    @classmethod
    def _iso_weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("workdays must be ISO weekdays, 1 (Mon) to 7 (Sun)")
        return sorted(set(v))

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, v: str) -> str:
        if v not in available_timezones():
            raise ValueError(f"unknown timezone {v!r} — use an IANA name like 'America/New_York'")
        return v

    @field_validator("notes")
    @classmethod
    def _blank_notes_are_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None


def _to_dict(row: UserPlanningPreferences) -> dict[str, Any]:
    return {
        "daily_capacity_hours": row.daily_capacity_hours,
        "workdays": list(row.workdays),
        "urgency_horizon_days": row.urgency_horizon_days,
        "timezone": row.timezone,
        "notes": row.notes,
    }


async def load_preferences(db: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    result = await db.execute(select(UserPlanningPreferences).where(UserPlanningPreferences.user_id == user_id))
    row = result.scalar_one_or_none()
    return _to_dict(row) if row else dict(DEFAULT_PREFERENCES)


async def save_preferences(db: AsyncSession, user_id: uuid.UUID, prefs: PlanningPreferences) -> dict[str, Any]:
    result = await db.execute(select(UserPlanningPreferences).where(UserPlanningPreferences.user_id == user_id))
    row = result.scalar_one_or_none()
    if row is None:
        row = UserPlanningPreferences(user_id=user_id)
        db.add(row)
    row.daily_capacity_hours = prefs.daily_capacity_hours
    row.workdays = prefs.workdays
    row.urgency_horizon_days = prefs.urgency_horizon_days
    row.timezone = prefs.timezone
    row.notes = prefs.notes
    row.updated_at = datetime.now(ZoneInfo("UTC"))
    await db.commit()
    return _to_dict(row)


def today_for(preferences: dict[str, Any], now: datetime | None = None) -> date:
    """The user's local date. "Today" drives urgency and overdue math, so a
    user in UTC-8 asking at 9pm must not get tomorrow's answers."""
    try:
        tz = ZoneInfo(preferences.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return (now or datetime.now(tz)).astimezone(tz).date()
