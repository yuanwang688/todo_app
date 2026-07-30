"""Scenario loading and execution.

A scenario is a YAML file: a named fixture, a user message, and a list of
assertions. The runner seeds the database, runs one assistant turn through the
adapter, snapshots the database either side, and grades the result.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select as sa_select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Todo

from . import fixtures
from .agent_adapter import AgentNotImplemented, AgentResult, run_agent
from .graders import GradeContext, GradeResult, GraderError, run_grader

SCENARIO_DIR = Path(__file__).parent / "scenarios"

DEFAULT_PREFERENCES: dict[str, Any] = {
    "daily_capacity_hours": 4.0,
    "workdays": [1, 2, 3, 4, 5],
    "urgency_horizon_days": 3,
    "timezone": "UTC",
    "notes": None,
}

#: Fields compared between the before/after snapshots and exposed to selectors.
SNAPSHOT_FIELDS = (
    "title", "description", "completed", "category", "target_date", "start_date",
    "end_date", "estimated_effort", "is_focus", "importance", "locked", "updated_at",
)


@dataclass
class Scenario:
    id: str
    fixture: str
    message: str
    asserts: list[dict]
    path: Path
    today: date = fixtures.TODAY
    preferences: dict = field(default_factory=lambda: dict(DEFAULT_PREFERENCES))
    description: str = ""

    @property
    def name(self) -> str:
        return self.id


def load_scenarios(directory: Path = SCENARIO_DIR) -> list[Scenario]:
    scenarios: list[Scenario] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text())
        missing = {"id", "fixture", "message", "assert"} - set(raw)
        if missing:
            raise GraderError(f"{path.name}: missing key(s) {sorted(missing)}")
        prefs = dict(DEFAULT_PREFERENCES)
        prefs.update(raw.get("preferences") or {})
        today = raw.get("today")
        scenarios.append(
            Scenario(
                id=raw["id"],
                fixture=raw["fixture"],
                message=raw["message"],
                asserts=raw["assert"],
                path=path,
                today=date.fromisoformat(today) if today else fixtures.TODAY,
                preferences=prefs,
                description=raw.get("description", ""),
            )
        )
    ids = [s.id for s in scenarios]
    duplicated = {i for i in ids if ids.count(i) > 1}
    if duplicated:
        raise GraderError(f"duplicate scenario id(s): {sorted(duplicated)}")
    return scenarios


async def seed(db: AsyncSession, user_id, fixture_name: str) -> None:
    for row in fixtures.build(fixture_name):
        db.add(Todo(user_id=user_id, **row))
    await db.commit()


async def snapshot(db: AsyncSession, user_id) -> dict[str, dict]:
    result = await db.execute(sa_select(Todo).where(Todo.user_id == user_id))
    return {
        str(t.id): {f: getattr(t, f) for f in SNAPSHOT_FIELDS}
        for t in result.scalars().all()
    }


@dataclass
class ScenarioOutcome:
    scenario: Scenario
    grades: list[GradeResult]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(g.passed for g in self.grades)

    def report(self) -> str:
        if self.error:
            return f"[{self.scenario.id}] {self.error}"
        lines = [f"[{self.scenario.id}] {sum(g.passed for g in self.grades)}/{len(self.grades)} assertions passed"]
        lines += [f"  ✗ {g.name}: {g.message}" for g in self.grades if not g.passed]
        return "\n".join(lines)


async def run_scenario(scenario: Scenario, db: AsyncSession, user_id) -> ScenarioOutcome:
    await seed(db, user_id, scenario.fixture)
    before = await snapshot(db, user_id)

    try:
        result: AgentResult = await run_agent(
            message=scenario.message,
            user_id=str(user_id),
            db=db,
            today=scenario.today,
            preferences=scenario.preferences,
        )
    except AgentNotImplemented as exc:
        return ScenarioOutcome(scenario, [], error=f"agent not implemented: {exc}")

    db.expire_all()
    after = await snapshot(db, user_id)

    ctx = GradeContext(
        scenario_id=scenario.id,
        result=result,
        before=before,
        after=after,
        today=scenario.today,
        preferences=scenario.preferences,
    )
    grades = [run_grader(spec, ctx) for spec in scenario.asserts]
    return ScenarioOutcome(scenario, grades)
