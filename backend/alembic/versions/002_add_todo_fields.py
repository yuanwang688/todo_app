"""add category, dates, and estimated_effort to todos

Revision ID: 002
Revises: 001
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('todos', sa.Column('category', sa.String(), nullable=True))
    op.add_column('todos', sa.Column('target_date', sa.Date(), nullable=True))
    op.add_column('todos', sa.Column('start_date', sa.Date(), nullable=True))
    op.add_column('todos', sa.Column('end_date', sa.Date(), nullable=True))
    op.add_column('todos', sa.Column('estimated_effort', sa.Float(), nullable=True))


def downgrade():
    op.drop_column('todos', 'estimated_effort')
    op.drop_column('todos', 'end_date')
    op.drop_column('todos', 'start_date')
    op.drop_column('todos', 'target_date')
    op.drop_column('todos', 'category')
