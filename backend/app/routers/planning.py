"""Planning preferences (Phase D) — capacity, workdays, urgency horizon,
timezone, and free-text policy the assistant plans against.

    GET /api/planning-preferences  -> the user's preferences, or the defaults
    PUT /api/planning-preferences  -> replace them (validated; upserts the row)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from .. import planning
from ..auth import get_current_user
from ..database import get_db
from ..models import User

router = APIRouter(prefix="/api/planning-preferences", tags=["planning"])


@router.get("", response_model=planning.PlanningPreferences)
async def get_planning_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await planning.load_preferences(db, current_user.id)


@router.put("", response_model=planning.PlanningPreferences)
async def put_planning_preferences(
    body: planning.PlanningPreferences,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await planning.save_preferences(db, current_user.id, body)
