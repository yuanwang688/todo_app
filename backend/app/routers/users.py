from uuid import UUID
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from ..auth import get_current_user
from ..models import User

router = APIRouter(tags=["users"])


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str | None

    model_config = {"from_attributes": True}


@router.get("/api/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user
