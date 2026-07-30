"""add importance and locked to todos

Importance is the user-owned half of the Eisenhower matrix (urgency is derived
from dates — see TRIAGE.md). `locked` is the user's veto: the assistant may
read locked tasks but may never propose changes to them.

Revision ID: 004
Revises: 003
Create Date: 2026-07-30
"""
from alembic import op
import sqlalchemy as sa

revision = '004'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('todos', sa.Column('importance', sa.SmallInteger(), nullable=True))
    op.add_column('todos', sa.Column('locked', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('todos', 'locked')
    op.drop_column('todos', 'importance')
