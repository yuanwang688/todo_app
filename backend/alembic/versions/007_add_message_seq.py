"""add messages.seq for deterministic replay ordering

`_load_history` (app/agent/service.py) replays a conversation to the model by
`ORDER BY created_at`. All messages persisted in one turn share a single
`created_at` (Postgres's `now()` returns transaction start time, not
per-statement time), so ties had no deterministic tiebreaker — Postgres does
not guarantee insertion order is preserved for tied sort keys. On a real
conversation this surfaced as a `tool_result` replayed before its `tool_use`,
which the Messages API rejects outright, permanently breaking that
conversation (every future turn hits the same malformed-history error).

`seq` is populated by the application (see service.py's `_persist_new_messages`),
not by a DB identity/serial column — a plain app-managed counter is portable
across the Postgres (prod/dev) and SQLite (tests) backends this project runs
on, where SQLite only auto-populates an integer column that is itself the
sole primary key.

Existing rows are backfilled by `ctid` (physical row order) rather than
`created_at`, since these are append-only inserts that are never updated —
physical order reconstructs the true original insertion order even for
conversations already affected by the bug this migration fixes.

Revision ID: 007
Revises: 006
Create Date: 2026-08-01
"""
from alembic import op
import sqlalchemy as sa

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('messages', sa.Column('seq', sa.Integer(), nullable=True))
    op.execute("""
        UPDATE messages
        SET seq = backfill.rownum
        FROM (
            SELECT id, ROW_NUMBER() OVER (PARTITION BY conversation_id ORDER BY ctid) AS rownum
            FROM messages
        ) AS backfill
        WHERE messages.id = backfill.id
    """)
    op.alter_column('messages', 'seq', nullable=False)
    op.create_index('ix_messages_conversation_id_seq', 'messages', ['conversation_id', 'seq'])


def downgrade():
    op.drop_index('ix_messages_conversation_id_seq', table_name='messages')
    op.drop_column('messages', 'seq')
