"""add conversations, messages, agent_runs

Phase B (read-only assistant). One rolling conversation per user (decided
2026-07-30 — see AI_ASSISTANT_PLAN.md §11). `messages.content` stores raw
Anthropic content blocks so a conversation can be replayed verbatim across
HTTP calls. `agent_runs` is the cost/latency/cache audit log — one row per
assistant turn, not per API request (a turn may call the model several times
across a tool loop; usage is summed).

Revision ID: 005
Revises: 004
Create Date: 2026-07-31
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'conversations',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_conversations_user_id', 'conversations', ['user_id'])

    op.create_table(
        'messages',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('conversation_id', sa.Uuid(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.Text(), nullable=False),  # user | assistant
        sa.Column('content', JSONB(), nullable=False),  # Anthropic content blocks, verbatim
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_messages_conversation_id_created_at', 'messages', ['conversation_id', 'created_at'])

    op.create_table(
        'agent_runs',
        sa.Column('id', sa.Uuid(), primary_key=True),
        sa.Column('conversation_id', sa.Uuid(), sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model', sa.Text(), nullable=False),
        sa.Column('effort', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=False),  # ok | error | refusal
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_read_tokens', sa.Integer(), nullable=True),
        sa.Column('cache_write_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('tool_calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_agent_runs_conversation_id', 'agent_runs', ['conversation_id'])


def downgrade():
    op.drop_table('agent_runs')
    op.drop_table('messages')
    op.drop_table('conversations')
