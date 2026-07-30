"""Runs every scenario in `scenarios/` as a pytest case.

    pytest evals                    # all scenarios
    pytest evals -k dedupe          # one family
    pytest evals --collect-only -q  # list them

These are expected to fail until the assistant exists (Phase B). That is the
point: the scenarios are the spec, written before the implementation.
"""
import pytest

from .runner import load_scenarios, run_scenario

SCENARIOS = load_scenarios()


def test_scenarios_are_loadable():
    """Cheap guard: every YAML file parses and no ids collide."""
    assert SCENARIOS, "no scenarios found in evals/scenarios/"


@pytest.mark.evals
@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s.id for s in SCENARIOS])
async def test_scenario(scenario, eval_db, eval_user):
    outcome = await run_scenario(scenario, eval_db, eval_user.id)
    assert outcome.passed, "\n" + outcome.report()
