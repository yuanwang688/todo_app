"""Apply / reject / undo for assistant-generated proposals.

Semantics (see AI_ASSISTANT_PLAN.md §5.2):

- **Apply is all-or-nothing on the selected set.** Every selected item is
  validated first, with no writes; if any fails, nothing commits and the
  proposal stays `pending` so the user can deselect the blocker and retry.
  Only on full success do writes happen, in one transaction, alongside
  `todo_revisions` rows.
- **Three checks happen again here, on top of what propose_changes already
  enforced at creation time** — defense in depth against races: a task can
  get locked, edited (staleness), or deleted between proposal and apply.
- **Undo is best-effort per item, not all-or-nothing** — it's a recovery
  path, not a transaction the user is actively choosing pieces of. It walks
  `todo_revisions` newest-first and writes compensating revisions, so an
  undo is itself audited.
- **Proposals lazily expire.** A `pending` proposal older than 24h flips to
  `expired` the next time it's read, rather than via a background job.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth import get_current_user
from ..database import get_db
from ..models import Proposal, ProposalItem, Todo, TodoRevision, User
from ..revisions import deserialize_field, deserialize_snapshot, snapshot_todo as _snapshot
from ..triage import AGENT_WRITABLE_FIELDS, AGENT_WRITABLE_ON_CREATE

router = APIRouter(prefix="/api/proposals", tags=["proposals"])

PROPOSAL_EXPIRY_HOURS = 24


class ProposalItemOut(BaseModel):
    id: uuid.UUID
    op: str
    todo_id: uuid.UUID | None
    # Not on the ORM row — looked up at serialization time so the UI can
    # show which task an update/delete targets without a second fetch.
    todo_title: str | None
    changes: dict[str, Any]
    rationale: str
    quadrant: str | None
    status: str


class ProposalOut(BaseModel):
    id: uuid.UUID
    summary: str
    status: str
    created_at: datetime
    applied_at: datetime | None
    items: list[ProposalItemOut]


async def _to_proposal_out(db: AsyncSession, proposal: Proposal) -> ProposalOut:
    await db.refresh(proposal, attribute_names=["items"])
    todo_ids = {item.todo_id for item in proposal.items if item.todo_id}
    titles_by_todo_id: dict[uuid.UUID, str] = {}
    if todo_ids:
        result = await db.execute(select(Todo.id, Todo.title).where(Todo.id.in_(todo_ids)))
        titles_by_todo_id = dict(result.all())

    # Fallback for items whose live Todo can't be joined against — most
    # notably an applied delete, where `proposal_items.todo_id` itself gets
    # nulled by its ON DELETE SET NULL the moment the target row is deleted
    # (see models.py), so there's no todo_id left to join on at all.
    # todo_revisions is keyed by proposal_item_id precisely so this survives
    # that — key the fallback off the item, not the (possibly-gone) todo_id.
    item_ids = [item.id for item in proposal.items]
    titles_by_item_id: dict[uuid.UUID, str] = {}
    if item_ids:
        result = await db.execute(select(TodoRevision).where(TodoRevision.proposal_item_id.in_(item_ids)))
        for rev in result.scalars().all():
            snapshot = rev.after or rev.before
            if snapshot and snapshot.get("title"):
                titles_by_item_id.setdefault(rev.proposal_item_id, snapshot["title"])

    def resolve_title(item: ProposalItem) -> str | None:
        if item.todo_id and item.todo_id in titles_by_todo_id:
            return titles_by_todo_id[item.todo_id]
        return titles_by_item_id.get(item.id)

    return ProposalOut(
        id=proposal.id,
        summary=proposal.summary,
        status=proposal.status,
        created_at=proposal.created_at,
        applied_at=proposal.applied_at,
        items=[
            ProposalItemOut(
                id=item.id,
                op=item.op,
                todo_id=item.todo_id,
                todo_title=resolve_title(item),
                changes=item.changes,
                rationale=item.rationale,
                quadrant=item.quadrant,
                status=item.status,
            )
            for item in proposal.items
        ],
    )


class ApplyIn(BaseModel):
    item_ids: list[uuid.UUID]


class ApplyItemOut(BaseModel):
    item_id: uuid.UUID
    status: str  # applied | skipped | stale | invalid
    detail: str | None = None


class ApplyOut(BaseModel):
    proposal_status: str
    items: list[ApplyItemOut]


async def _get_owned_proposal(db: AsyncSession, proposal_id: uuid.UUID, user_id: uuid.UUID) -> Proposal:
    result = await db.execute(
        select(Proposal).where(Proposal.id == proposal_id, Proposal.user_id == user_id)
    )
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(status_code=404, detail="Proposal not found")
    return proposal


def _as_utc(dt: datetime) -> datetime:
    """SQLite's server_default=func.now() round-trips as a naive datetime
    (it's stored/read as UTC but loses tzinfo); Postgres round-trips aware.
    Treat naive as already-UTC so subtraction works under either backend."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def _maybe_expire(db: AsyncSession, proposal: Proposal) -> None:
    if proposal.status != "pending":
        return
    age = datetime.now(timezone.utc) - _as_utc(proposal.created_at)
    if age.total_seconds() > PROPOSAL_EXPIRY_HOURS * 3600:
        proposal.status = "expired"
        await db.commit()


@router.get("/{proposal_id}", response_model=ProposalOut)
async def get_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposal = await _get_owned_proposal(db, proposal_id, current_user.id)
    await _maybe_expire(db, proposal)
    return await _to_proposal_out(db, proposal)


def _validate_item(item: ProposalItem, todo: Todo | None) -> tuple[str, str | None]:
    """Returns (status, detail). status is 'ok' if the item can be applied."""
    if item.op in ("update", "delete"):
        if todo is None:
            return "invalid", "the task no longer exists"
        if todo.locked:
            return "invalid", "the task is locked"
        if item.seen_updated_at is not None and todo.updated_at != item.seen_updated_at:
            return "stale", "the task changed since this proposal was made"
    if item.op == "update":
        illegal = set(item.changes) - AGENT_WRITABLE_FIELDS
        if illegal:
            return "invalid", f"field(s) not writable: {sorted(illegal)}"
    elif item.op == "create":
        illegal = set(item.changes) - AGENT_WRITABLE_ON_CREATE
        if illegal:
            return "invalid", f"field(s) not writable: {sorted(illegal)}"
        if "title" not in item.changes:
            return "invalid", "missing title"
    return "ok", None


@router.post("/{proposal_id}/apply", response_model=ApplyOut)
async def apply_proposal(
    proposal_id: uuid.UUID,
    body: ApplyIn,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposal = await _get_owned_proposal(db, proposal_id, current_user.id)
    await _maybe_expire(db, proposal)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is {proposal.status}, not pending")

    await db.refresh(proposal, attribute_names=["items"])
    items_by_id = {item.id: item for item in proposal.items}
    selected_ids = set(body.item_ids)
    unknown = selected_ids - set(items_by_id)
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown item id(s): {sorted(str(i) for i in unknown)}")

    # Validation pass — no writes yet. Fetch each referenced todo once.
    todos_by_id: dict[uuid.UUID, Todo] = {}
    for item in items_by_id.values():
        if item.todo_id and item.todo_id not in todos_by_id:
            result = await db.execute(select(Todo).where(Todo.id == item.todo_id, Todo.user_id == current_user.id))
            todo = result.scalar_one_or_none()
            if todo is not None:
                todos_by_id[item.todo_id] = todo

    results: dict[uuid.UUID, ApplyItemOut] = {}
    blocked = False
    for item_id in selected_ids:
        item = items_by_id[item_id]
        status, detail = _validate_item(item, todos_by_id.get(item.todo_id) if item.todo_id else None)
        if status != "ok":
            blocked = True
        results[item_id] = ApplyItemOut(item_id=item_id, status=status, detail=detail)

    if blocked:
        # All-or-nothing: nothing commits, proposal stays pending so the
        # caller can deselect the blocker(s) and retry.
        for item_id in selected_ids:
            if results[item_id].status == "ok":
                results[item_id] = ApplyItemOut(item_id=item_id, status="invalid", detail="blocked by another item in this batch")
        return ApplyOut(proposal_status="pending", items=list(results.values()))

    # All selected items are valid — apply them all in one transaction.
    for item_id in selected_ids:
        item = items_by_id[item_id]
        if item.op == "create":
            new_values = {field: deserialize_field(field, value) for field, value in item.changes.items()}
            new_todo = Todo(user_id=current_user.id, **new_values)
            db.add(new_todo)
            await db.flush()
            db.add(TodoRevision(
                todo_id=new_todo.id, user_id=current_user.id, before=None, after=_snapshot(new_todo),
                source="agent", proposal_item_id=item.id,
            ))
            item.todo_id = new_todo.id
        elif item.op == "update":
            todo = todos_by_id[item.todo_id]
            before = _snapshot(todo)
            for field, enriched in item.changes.items():
                setattr(todo, field, deserialize_field(field, enriched["to"]))
            todo.updated_at = datetime.now(timezone.utc)
            db.add(TodoRevision(
                todo_id=todo.id, user_id=current_user.id, before=before, after=_snapshot(todo),
                source="agent", proposal_item_id=item.id,
            ))
        elif item.op == "delete":
            todo = todos_by_id[item.todo_id]
            before = _snapshot(todo)
            db.add(TodoRevision(
                todo_id=todo.id, user_id=current_user.id, before=before, after=None,
                source="agent", proposal_item_id=item.id,
            ))
            await db.delete(todo)
        item.status = "applied"
        results[item_id] = ApplyItemOut(item_id=item_id, status="applied")

    for item_id, item in items_by_id.items():
        if item_id not in selected_ids:
            item.status = "skipped"
            results[item_id] = ApplyItemOut(item_id=item_id, status="skipped")

    proposal.status = "applied"
    proposal.applied_at = datetime.now(timezone.utc)
    await db.commit()

    return ApplyOut(proposal_status="applied", items=list(results.values()))


@router.post("/{proposal_id}/reject", response_model=ProposalOut)
async def reject_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposal = await _get_owned_proposal(db, proposal_id, current_user.id)
    await _maybe_expire(db, proposal)
    if proposal.status != "pending":
        raise HTTPException(status_code=409, detail=f"Proposal is {proposal.status}, not pending")
    proposal.status = "rejected"
    await db.commit()
    return await _to_proposal_out(db, proposal)


@router.post("/{proposal_id}/undo", response_model=ProposalOut)
async def undo_proposal(
    proposal_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    proposal = await _get_owned_proposal(db, proposal_id, current_user.id)
    if proposal.status != "applied":
        raise HTTPException(status_code=409, detail=f"Proposal is {proposal.status}, not applied")

    await db.refresh(proposal, attribute_names=["items"])
    applied_items = [i for i in proposal.items if i.status == "applied"]

    for item in applied_items:
        result = await db.execute(
            select(TodoRevision)
            .where(TodoRevision.proposal_item_id == item.id)
            .order_by(TodoRevision.created_at.desc())
            .limit(1)
        )
        revision = result.scalar_one_or_none()
        if revision is None:
            continue  # nothing to undo — shouldn't happen, but don't fail the whole undo over it

        if revision.after is None:
            # This item deleted a task — undo means recreating it.
            existing = await db.get(Todo, revision.todo_id)
            if existing is None and revision.before is not None:
                restored = Todo(id=revision.todo_id, user_id=current_user.id, **deserialize_snapshot(revision.before))
                db.add(restored)
                await db.flush()
                # The apply-time delete's ON DELETE SET NULL cleared this —
                # restore the link now that a live row exists again.
                item.todo_id = restored.id
                db.add(TodoRevision(
                    todo_id=restored.id, user_id=current_user.id, before=None, after=_snapshot(restored),
                    source="agent", proposal_item_id=item.id,
                ))
        elif revision.before is None:
            # This item created a task — undo means deleting it.
            existing = await db.get(Todo, revision.todo_id)
            if existing is not None:
                before = _snapshot(existing)
                db.add(TodoRevision(
                    todo_id=existing.id, user_id=current_user.id, before=before, after=None,
                    source="agent", proposal_item_id=item.id,
                ))
                await db.delete(existing)
        else:
            # An update — restore the prior field values.
            existing = await db.get(Todo, revision.todo_id)
            if existing is not None:
                before = _snapshot(existing)
                for field, value in deserialize_snapshot(revision.before).items():
                    setattr(existing, field, value)
                existing.updated_at = datetime.now(timezone.utc)
                db.add(TodoRevision(
                    todo_id=existing.id, user_id=current_user.id, before=before, after=_snapshot(existing),
                    source="agent", proposal_item_id=item.id,
                ))

        item.status = "undone"

    proposal.status = "undone"
    await db.commit()
    return await _to_proposal_out(db, proposal)
