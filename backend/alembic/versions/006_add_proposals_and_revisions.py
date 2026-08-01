"""add proposals, proposal_items, todo_revisions

Phase C (propose/approve/undo). Two deliberate deviations from the original
sketch in AI_ASSISTANT_PLAN.md:

- `proposals.conversation_id` (not `run_id`) — the AgentRun row for a turn
  isn't created until the turn finishes (`_log_run`, after the whole tool
  loop), but `propose_changes` needs to persist mid-turn. `conversation_id`
  exists from the start of the turn and is sufficient for scoping.
- `proposal_items.todo_id` is `ON DELETE SET NULL`, not `CASCADE` — deleting
  the target task (via an applied `delete` proposal, or a plain GUI delete)
  should not destroy the proposal_item audit row; it should just lose its
  target reference. `todo_revisions.todo_id` has no FK at all, by design —
  it's the source of truth for undo and must survive the row it describes
  being gone.

Revision ID: 006
Revises: 005
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'proposals',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('conversation_id', sa.Uuid(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('summary', sa.Text(), nullable=False),
        # pending | applied | rejected | expired | undone
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_proposals_user_id', 'proposals', ['user_id'])
    op.create_index('ix_proposals_conversation_id', 'proposals', ['conversation_id'])

    op.create_table(
        'proposal_items',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('proposal_id', sa.Uuid(), sa.ForeignKey('proposals.id', ondelete='CASCADE'), nullable=False),
        sa.Column('op', sa.Text(), nullable=False),  # create | update | delete
        sa.Column('todo_id', sa.Uuid(), sa.ForeignKey('todos.id', ondelete='SET NULL'), nullable=True),
        # update: {field: {from, to}}; create: {field: value}; delete: {}
        sa.Column('changes', JSONB(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=False),
        sa.Column('quadrant', sa.Text(), nullable=True),  # Q1..Q4
        sa.Column('seen_updated_at', sa.DateTime(timezone=True), nullable=True),
        # pending | applied | skipped | stale | invalid | undone
        sa.Column('status', sa.Text(), nullable=False, server_default='pending'),
    )
    op.create_index('ix_proposal_items_proposal_id', 'proposal_items', ['proposal_id'])

    op.create_table(
        'todo_revisions',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('todo_id', sa.Uuid(), nullable=False),  # no FK — must survive the todo's deletion
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('before', JSONB(), nullable=True),  # null for create
        sa.Column('after', JSONB(), nullable=True),   # null for delete
        sa.Column('source', sa.Text(), nullable=False),  # user | agent
        sa.Column('proposal_item_id', sa.Uuid(), sa.ForeignKey('proposal_items.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_todo_revisions_todo_id', 'todo_revisions', ['todo_id'])
    op.create_index('ix_todo_revisions_user_id_created_at', 'todo_revisions', ['user_id', 'created_at'])


def downgrade():
    op.drop_table('todo_revisions')
    op.drop_table('proposal_items')
    op.drop_table('proposals')
