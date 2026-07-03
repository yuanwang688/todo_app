"""add is_focus to todos

Revision ID: 003
Revises: 002
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = '003'
down_revision = '002'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('todos', sa.Column('is_focus', sa.Boolean(), nullable=False, server_default='false'))


def downgrade():
    op.drop_column('todos', 'is_focus')
