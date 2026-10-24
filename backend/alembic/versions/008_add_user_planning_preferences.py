"""add user_planning_preferences

Phase D (planning simulation). One deliberate deviation from the sketch in
AI_ASSISTANT_PLAN.md §3.2: `workdays` is JSONB (a list of ISO weekdays),
not `SMALLINT[]`. Postgres arrays have no SQLite equivalent, and the test
suite runs the ORM models against SQLite — same portability reasoning as
migration 007's app-managed `seq`. The column is only ever read and written
whole, never queried into, so nothing is lost.

No backfill: a user without a row gets `app.planning.DEFAULT_PREFERENCES`,
and a row is created on their first save.

Revision ID: 008
Revises: 007
Create Date: 2026-10-23
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'user_planning_preferences',
        sa.Column('user_id', sa.Uuid(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('daily_capacity_hours', sa.Float(), nullable=False, server_default='4.0'),
        sa.Column('workdays', JSONB(), nullable=False, server_default=sa.text("'[1, 2, 3, 4, 5]'::jsonb")),
        sa.Column('urgency_horizon_days', sa.SmallInteger(), nullable=False, server_default='3'),
        sa.Column('timezone', sa.Text(), nullable=False, server_default='UTC'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade():
    op.drop_table('user_planning_preferences')
