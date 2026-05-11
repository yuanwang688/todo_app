import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ..database import get_db
from ..models import Todo
from ..schemas import TodoCreate, TodoUpdate, TodoResponse

router = APIRouter(prefix="/api/todos", tags=["todos"])

# Temporary fixed user for Phase 2 — replaced by real auth in Phase 3
TEMP_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.get("", response_model=list[TodoResponse])
async def list_todos(status: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Todo).where(Todo.user_id == TEMP_USER_ID).order_by(Todo.created_at)
    if status == "active":
        query = query.where(Todo.completed == False)  # noqa: E712
    elif status == "completed":
        query = query.where(Todo.completed == True)  # noqa: E712
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=TodoResponse, status_code=201)
async def create_todo(body: TodoCreate, db: AsyncSession = Depends(get_db)):
    todo = Todo(user_id=TEMP_USER_ID, **body.model_dump())
    db.add(todo)
    await db.commit()
    await db.refresh(todo)
    return todo


@router.patch("/{todo_id}", response_model=TodoResponse)
async def update_todo(todo_id: uuid.UUID, body: TodoUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == TEMP_USER_ID)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(todo, field, value)
    todo.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(todo)
    return todo


@router.delete("/{todo_id}", status_code=204)
async def delete_todo(todo_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Todo).where(Todo.id == todo_id, Todo.user_id == TEMP_USER_ID)
    )
    todo = result.scalar_one_or_none()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    await db.delete(todo)
    await db.commit()
