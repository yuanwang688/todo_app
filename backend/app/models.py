import uuid
from datetime import date, datetime, timezone
from typing import Any
from sqlalchemy import String, Boolean, Date, Float, ForeignKey, Integer, JSON, SmallInteger, Text, func, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import DateTime
from .database import Base

# JSONB on Postgres (indexable, binary); plain JSON on SQLite (tests) since
# SQLite has no JSONB type.
_JSONVariant = JSONB().with_variant(JSON(), "sqlite")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    google_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    todos: Mapped[list["Todo"]] = relationship("Todo", back_populates="user", cascade="all, delete-orphan")


class Todo(Base):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    category: Mapped[str | None] = mapped_column(String, nullable=True)
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    estimated_effort: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_focus: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Eisenhower importance: 1 low / 2 medium / 3 high. Null = unclassified.
    importance: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    # User veto — the assistant may read locked tasks but never propose changes to them.
    locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="todos")


class Conversation(Base):
    """One rolling conversation per user — see AI_ASSISTANT_PLAN.md §11."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.seq"
    )


class Message(Base):
    """One turn of a conversation. `content` stores raw Anthropic content
    blocks (verbatim) so history can be replayed to the API unchanged."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)  # user | assistant
    content: Mapped[list[dict[str, Any]]] = mapped_column(_JSONVariant, nullable=False)
    # App-managed insertion order within a conversation — see migration 007.
    # created_at alone can't be replayed on: every message in one turn shares
    # a single timestamp (Postgres's now() is transaction-start time), and
    # ORDER BY over tied values isn't guaranteed to preserve insertion order.
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


class AgentRun(Base):
    """Cost/latency/cache audit log. One row per assistant turn — a turn may
    call the model several times across a tool loop; usage is summed."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model: Mapped[str] = mapped_column(Text, nullable=False)
    effort: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, nullable=False)  # ok | error | refusal
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tool_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Proposal(Base):
    """A batch of assistant-proposed changes, awaiting selective approval.

    Scoped to `conversation_id` rather than the `AgentRun` that produced it —
    the AgentRun row for a turn doesn't exist until the turn finishes, but
    propose_changes persists mid-turn. See the migration 006 docstring.
    """

    __tablename__ = "proposals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # pending | applied | rejected | expired | undone
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    items: Mapped[list["ProposalItem"]] = relationship(
        "ProposalItem", back_populates="proposal", cascade="all, delete-orphan", order_by="ProposalItem.id"
    )


class ProposalItem(Base):
    """One proposed mutation within a Proposal. `changes` here is the
    *enriched* form for display — {field: {from, to}} on update, {field:
    value} on create — not the model's raw tool-call input (see
    app/agent/tools.py's `_enrich_changes`)."""

    __tablename__ = "proposal_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("proposals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    op: Mapped[str] = mapped_column(Text, nullable=False)  # create | update | delete
    todo_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("todos.id", ondelete="SET NULL"), nullable=True
    )
    changes: Mapped[dict[str, Any]] = mapped_column(_JSONVariant, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    quadrant: Mapped[str | None] = mapped_column(Text, nullable=True)
    seen_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # pending | applied | skipped | stale | invalid | undone
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)

    proposal: Mapped["Proposal"] = relationship("Proposal", back_populates="items")


class TodoRevision(Base):
    """Audit trail for every todo mutation, agent- or user-driven. `todo_id`
    is deliberately not a foreign key — a revision must survive the todo
    it describes being deleted, since undo needs it to recreate the row."""

    __tablename__ = "todo_revisions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    todo_id: Mapped[uuid.UUID] = mapped_column(Uuid(), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    before: Mapped[dict[str, Any] | None] = mapped_column(_JSONVariant, nullable=True)
    after: Mapped[dict[str, Any] | None] = mapped_column(_JSONVariant, nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)  # user | agent
    proposal_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(), ForeignKey("proposal_items.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
