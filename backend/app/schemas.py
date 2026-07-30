from uuid import UUID
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field

# Eisenhower importance — see TRIAGE.md. Null means unclassified.
Importance = Optional[int]


class TodoCreate(BaseModel):
    title: str
    description: Optional[str] = None
    category: Optional[str] = None
    target_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_effort: Optional[float] = None
    importance: Optional[int] = Field(default=None, ge=1, le=3)
    locked: Optional[bool] = None


class TodoUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    completed: Optional[bool] = None
    category: Optional[str] = None
    target_date: Optional[date] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    estimated_effort: Optional[float] = None
    is_focus: Optional[bool] = None
    importance: Optional[int] = Field(default=None, ge=1, le=3)
    locked: Optional[bool] = None


class TodoResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    description: Optional[str]
    completed: bool
    category: Optional[str]
    target_date: Optional[date]
    start_date: Optional[date]
    end_date: Optional[date]
    estimated_effort: Optional[float]
    is_focus: bool
    importance: Optional[int]
    locked: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
