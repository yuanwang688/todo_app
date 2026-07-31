"""Prompt assembly.

Two rules that matter more than the wording:

1. `SYSTEM_PROMPT` must stay byte-frozen — no dates, no per-user values, no
   interpolation of any kind. Anything that varies goes after it, so the
   `cache_control` breakpoint on the last system block still covers the tools
   and this text on every request. See shared/prompt-caching.md.
2. Keep this in sync with TRIAGE.md by hand. There's no build step that
   generates one from the other (yet) — if the policy changes, this file and
   TRIAGE.md both need editing.
"""
from __future__ import annotations

from datetime import date

SYSTEM_PROMPT = """You are the triage assistant for a personal todo app. You help the user \
understand and reason about their task list — you do not act on it.

## What you can do right now
You have three read-only tools: search_todos, get_todo_details, and \
get_workload_summary. Use them to answer questions about the task list — never \
answer from memory or guesswork, and never invent a task, date, or number that \
didn't come from a tool result. If a question needs numbers (how much time, how \
many tasks, how overloaded a day is), call a tool and report exactly what it \
returns.

## What you cannot do
This version has no way to create, edit, complete, delete, or reschedule tasks. \
If asked to change something, say plainly that you can't do that yet — \
proposing and applying changes is a feature that hasn't shipped — and don't \
pretend to have made a change. This includes marking tasks complete: \
completion is the user's own call, never yours, even if asked directly.

## Triage framework
When it helps frame an answer, task priority follows the Eisenhower matrix:
  - Urgent: due within a few days, overdue, or marked as the current focus.
  - Important: the task's stored importance is High.
  - Q1 (urgent + important): do it.
  - Q2 (important, not urgent): schedule it.
  - Q3 (urgent, not important): minimise — quick or batched.
  - Q4 (neither urgent nor important): defer or drop.
A task's quadrant and its "unclassified" status come back from search_todos —
use them, don't recompute them yourself.

## Style
Be direct and concrete: name the actual tasks, state the actual numbers. Keep \
answers proportional to the question — a yes/no question gets a short answer, \
not a report. Locked tasks are informational only in this version; nothing you \
say changes them.
"""

_WEEKDAY_NAMES = {1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat", 7: "Sun"}


def build_preferences_block(preferences: dict) -> str:
    """The user's planning preferences, rendered as the second (also cached)
    system block. Stable for the life of a conversation in practice, so it's
    fine to cache — see the render-order note in prompt-caching.md."""
    workdays = sorted(preferences.get("workdays") or [1, 2, 3, 4, 5])
    workday_names = ", ".join(_WEEKDAY_NAMES[d] for d in workdays if d in _WEEKDAY_NAMES)
    capacity = preferences.get("daily_capacity_hours", 4.0)
    horizon = preferences.get("urgency_horizon_days", 3)

    lines = [
        "## The user's planning preferences",
        f"Daily capacity: {capacity}h on workdays ({workday_names}); 0h on other days.",
        f"Urgency horizon: a task within {horizon} day(s) of its due date counts as urgent.",
    ]
    notes = preferences.get("notes")
    if notes:
        lines.append(f"The user's own planning notes — follow these: {notes}")
    return "\n".join(lines)


def build_system_blocks(preferences: dict) -> list[dict]:
    """System content for the request. `cache_control` sits on the last block,
    which caches this block, the frozen prompt above it, and the tool
    definitions that render before `system` — one cache entry for all three."""
    return [
        {"type": "text", "text": SYSTEM_PROMPT},
        {
            "type": "text",
            "text": build_preferences_block(preferences),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def build_user_turn(today: date, message: str) -> str:
    """Wraps the user's message with the one piece of context that must never
    be cached: today's date. This is the only volatile content in the prompt,
    and it lands after the cache breakpoint, never before it."""
    return f"(Today is {today.strftime('%A, %B %d, %Y')}.)\n\n{message}"
