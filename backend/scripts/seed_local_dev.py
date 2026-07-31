"""Seeds a local database with 25 example tasks for testing the todo
assistant interactively.

The set is curated from backend/evals/fixtures.py's mixed_40 and
overloaded_week — the same tasks the eval suite grades against — so every
question a scenario asks has a real answer to check by hand: an overdue
cluster, two locked tasks, several unclassified-importance tasks, a run of
quick wins, an exact duplicate pair, a day stacked well past capacity,
undated tasks, and two completed tasks that a correct answer should never
mention.

Not run directly in normal use — scripts/dev_up.sh invokes this against a
local Postgres with DATABASE_URL already pointed at it. Safe to run by hand
the same way if you're bypassing the wrapper script:

    cd backend
    DATABASE_URL=postgresql+asyncpg://... ENVIRONMENT=development \
        .venv/bin/python scripts/seed_local_dev.py [--fresh]
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.auth import DEV_USER_EMAIL, DEV_USER_GOOGLE_ID, DEV_USER_NAME  # noqa: E402
from app.database import AsyncSessionLocal  # noqa: E402
from app.models import AgentRun, Conversation, Message, Todo, User  # noqa: E402


def d(offset: int) -> date:
    return date.today() + timedelta(days=offset)


def seed_todos() -> list[dict]:
    return [
        # ── overdue — try "what's overdue?" ─────────────────────────────────
        dict(title="Submit expense report for June", category="Work", target_date=d(-9),
             estimated_effort=0.5, importance=2),
        dict(title="Renew car insurance", category="Personal", target_date=d(-4),
             estimated_effort=1.0, importance=3),
        dict(title="Reply to Dana about the contract", category="Work", target_date=d(-2),
             estimated_effort=0.25, importance=3),
        dict(title="Return the library books", category="Personal", target_date=d(-1),
             estimated_effort=0.5, importance=1),
        # ── today — stacked past the default 4h capacity on purpose; try
        #    "am I overcommitted today?" (3.0 + 1.0 + 2.0 = 6h) ──────────────
        dict(title="Finish Q3 roadmap draft", category="Work", target_date=d(0),
             estimated_effort=3.0, importance=3, is_focus=True),
        dict(title="Review Priya's pull request", category="Work", target_date=d(0),
             estimated_effort=1.0, importance=3),
        dict(title="Update the on-call runbook", category="Work", target_date=d(0),
             estimated_effort=2.0, importance=2),
        # ── rest of this week, including two locked tasks — try "clear out
        #    my week, I'm overloaded" and watch the locked ones stay put ────
        dict(title="Prep slides for Thursday sync", category="Work", target_date=d(3),
             estimated_effort=2.5, importance=3),
        dict(title="Book the offsite venue", category="Work", target_date=d(4),
             estimated_effort=1.5, importance=2, locked=True),
        dict(title="Refactor the export job", category="Work", start_date=d(1), end_date=d(4),
             estimated_effort=6.0, importance=2),
        dict(title="Dentist appointment", category="Personal", target_date=d(2),
             estimated_effort=1.5, importance=3, locked=True),
        dict(title="Buy a birthday present for Sam", category="Personal", target_date=d(5),
             estimated_effort=1.0, importance=2),
        dict(title="Fix the leaking tap", category="Home", target_date=d(6),
             estimated_effort=1.0, importance=1),
        dict(title="Water the plants", category="Home", target_date=d(1),
             estimated_effort=0.25, importance=1),
        # ── further out ──────────────────────────────────────────────────
        dict(title="Draft the 2027 budget", category="Work", target_date=d(11),
             estimated_effort=4.0, importance=3),
        dict(title="Renew passport", category="Personal", target_date=d(21),
             estimated_effort=2.0, importance=3),
        dict(title="Cancel the unused gym membership", category="Personal", target_date=d(10),
             estimated_effort=0.25, importance=2),
        # ── unclassified — try "classify my unclassified tasks" ────────────
        dict(title="Look into the new analytics tool", category="Work", target_date=d(8),
             estimated_effort=2.0),
        dict(title="Tidy the shared drive", category="Work", estimated_effort=1.5),
        dict(title="Read the architecture RFC", category="Work", target_date=d(5),
             estimated_effort=1.0),
        dict(title="Back up the family photos", category="Personal", estimated_effort=2.0),
        # ── exact duplicate — try "I think I've entered some things twice" ─
        dict(title="Book flights to Lisbon", category="Personal", target_date=d(7),
             estimated_effort=1.0, importance=3),
        dict(title="Book flights to Lisbon", category="Personal", target_date=d(9),
             estimated_effort=1.0, importance=2),
        # ── completed — should never show up in "what's overdue" etc. ──────
        dict(title="Pay the electricity bill", category="Home", completed=True, target_date=d(-3),
             estimated_effort=0.25, importance=2),
        dict(title="Ship the hotfix", category="Work", completed=True, target_date=d(-1),
             estimated_effort=1.0, importance=3),
    ]


async def main(fresh: bool) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.google_id == DEV_USER_GOOGLE_ID))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(google_id=DEV_USER_GOOGLE_ID, email=DEV_USER_EMAIL, name=DEV_USER_NAME)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            print(f"Created dev user {user.email} ({user.id})")
        else:
            print(f"Using existing dev user {user.email} ({user.id})")

        if fresh:
            convo_ids = select(Conversation.id).where(Conversation.user_id == user.id)
            await db.execute(AgentRun.__table__.delete().where(AgentRun.conversation_id.in_(convo_ids)))
            await db.execute(Message.__table__.delete().where(Message.conversation_id.in_(convo_ids)))
            await db.execute(Conversation.__table__.delete().where(Conversation.user_id == user.id))
            await db.execute(Todo.__table__.delete().where(Todo.user_id == user.id))
            await db.commit()
            print("Cleared existing todos and chat history for a fresh start.")

        existing = (await db.execute(select(Todo.id).where(Todo.user_id == user.id))).scalars().all()
        if existing and not fresh:
            print(f"Dev user already has {len(existing)} todo(s) — skipping seed (pass --fresh to reset).")
            return

        rows = seed_todos()
        for row in rows:
            db.add(Todo(user_id=user.id, **row))
        await db.commit()
        print(f"Seeded {len(rows)} todos for {user.email}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh", action="store_true", help="Wipe existing todos and chat history first")
    args = parser.parse_args()
    asyncio.run(main(args.fresh))
