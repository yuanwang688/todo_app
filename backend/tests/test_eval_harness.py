"""Tests for the eval harness itself.

The scenarios in `evals/scenarios/` are the spec and fail until Phase B. The
machinery that grades them, though, has to be correct *now* — otherwise Phase B
spends its time debugging graders instead of the agent. These tests grade
synthetic agent results, so they need no model and run in the normal suite.

Also pins the fixture invariants that the scenario assertions count on (e.g.
"8 unclassified tasks"), so editing a fixture can't silently weaken a scenario.
"""
from datetime import date

import pytest

from app.agent_schemas import Proposal, ProposalItem
from evals import fixtures
from evals.agent_adapter import AgentResult
from evals.graders import (
    GradeContext,
    GraderError,
    apply_in_memory,
    matches,
    run_grader,
    select,
)
from evals.runner import SNAPSHOT_FIELDS, load_scenarios

TODAY = fixtures.TODAY


# ── fixture invariants the scenarios rely on ────────────────────────────────


def test_today_is_a_monday():
    assert TODAY.isoweekday() == 1


def test_mixed_40_shape():
    rows = fixtures.mixed_40()
    assert len(rows) == 40
    overdue = [r for r in rows if r["target_date"] and r["target_date"] < TODAY and not r["completed"]]
    assert len(overdue) == 4, "scenario 01 asserts on the overdue set"
    assert len([r for r in rows if r["locked"]]) == 3, "scenario 03 asserts locked tasks are untouched"
    unclassified = [r for r in rows if r["importance"] is None and not r["completed"]]
    assert len(unclassified) == 8, "scenario 05 asserts min_items: 8"
    assert len([r for r in rows if (r["estimated_effort"] or 99) <= 0.5]) >= 5, "scenario 02 needs quick wins"
    assert any(r["completed"] for r in rows), "workload maths must be exercised against completed tasks"


def test_overloaded_week_has_exactly_fourteen_hours_today():
    rows = fixtures.overloaded_week()
    today_hours = sum(r["estimated_effort"] for r in rows if r["target_date"] == TODAY)
    assert today_hours == 14.0, "scenario 08 asserts the assistant states 14.0"


def test_duplicates_has_one_genuine_pair():
    titles = [r["title"] for r in fixtures.duplicates()]
    dupes = {t for t in titles if titles.count(t) > 1}
    assert dupes == {"Book flights to Lisbon"}, "scenario 06 asserts delete_count: 1"


def test_every_scenario_loads_and_names_a_real_fixture():
    scenarios = load_scenarios()
    assert len(scenarios) == 10
    for s in scenarios:
        assert s.fixture in fixtures.FIXTURES, f"{s.id} names unknown fixture {s.fixture}"
        assert s.asserts, f"{s.id} has no assertions"


# ── snapshot / selector helpers ─────────────────────────────────────────────


def snap(**overrides) -> dict:
    base = {f: None for f in SNAPSHOT_FIELDS}
    base.update(title="task", completed=False, is_focus=False, locked=False)
    base.update(overrides)
    return base


@pytest.fixture
def before() -> dict[str, dict]:
    return {
        "a": snap(title="Overdue thing", target_date=date(2026, 7, 30), estimated_effort=1.0, importance=3),
        "b": snap(title="Locked thing", target_date=date(2026, 8, 5), estimated_effort=2.0,
                  importance=2, locked=True),
        "c": snap(title="Unclassified thing", target_date=date(2026, 8, 6), estimated_effort=3.0),
        "d": snap(title="Quick win", target_date=date(2026, 8, 4), estimated_effort=0.25, importance=1),
    }


def ctx_for(before, proposal=None, reply="", after=None) -> GradeContext:
    return GradeContext(
        scenario_id="synthetic",
        result=AgentResult(reply_text=reply, proposal=proposal),
        before=before,
        after=after if after is not None else {k: dict(v) for k, v in before.items()},
        today=TODAY,
        preferences={"daily_capacity_hours": 4.0},
    )


def item(**kw) -> ProposalItem:
    return ProposalItem(**{"op": "update", "rationale": "a sufficiently long rationale", **kw})


def proposal(*items) -> Proposal:
    return Proposal(summary="a summary long enough", items=list(items))


def graded(spec, ctx):
    return run_grader(spec, ctx)


# ── selectors ───────────────────────────────────────────────────────────────


def test_selector_exact_and_null(before):
    assert len(select(before, {"locked": True})) == 1
    assert len(select(before, {"importance": {"is_null": True}})) == 1
    assert len(select(before, None)) == 4


def test_selector_comparison_ops(before):
    assert set(select(before, {"estimated_effort": {"lte": 1.0}})) == {"a", "d"}
    assert set(select(before, {"target_date": {"lt": TODAY}})) == {"a"}


def test_selector_treats_null_as_non_matching_for_comparisons():
    assert not matches(snap(estimated_effort=None), {"estimated_effort": {"lte": 1.0}})


def test_selector_rejects_unknown_field(before):
    with pytest.raises(GraderError):
        select(before, {"nonexistent": 1})


def test_unknown_grader_is_an_error(before):
    with pytest.raises(GraderError):
        run_grader({"type": "no_such_grader"}, ctx_for(before))


# ── structural graders ──────────────────────────────────────────────────────


def test_db_unchanged_passes_when_untouched(before):
    assert graded({"type": "db_unchanged"}, ctx_for(before)).passed


def test_db_unchanged_catches_edits(before):
    after = {k: dict(v) for k, v in before.items()}
    after["a"]["importance"] = 1
    assert not graded({"type": "db_unchanged"}, ctx_for(before, after=after)).passed


def test_db_unchanged_catches_deletes(before):
    after = {k: dict(v) for k, v in before.items() if k != "a"}
    assert not graded({"type": "db_unchanged"}, ctx_for(before, after=after)).passed


def test_db_unchanged_ignores_updated_at(before):
    after = {k: dict(v) for k, v in before.items()}
    after["a"]["updated_at"] = "later"
    assert graded({"type": "db_unchanged"}, ctx_for(before, after=after)).passed


def test_no_proposal(before):
    assert graded({"type": "no_proposal"}, ctx_for(before)).passed
    p = proposal(item(todo_id="a", changes={"importance": 1}))
    assert not graded({"type": "no_proposal"}, ctx_for(before, p)).passed


def test_has_proposal_min_items(before):
    p = proposal(item(todo_id="a", changes={"importance": 1}))
    assert graded({"type": "has_proposal"}, ctx_for(before, p)).passed
    assert not graded({"type": "has_proposal", "min_items": 2}, ctx_for(before, p)).passed


# ── mutation-shape graders ──────────────────────────────────────────────────


def test_no_change_to_protects_locked(before):
    ok = proposal(item(todo_id="a", changes={"importance": 1}))
    bad = proposal(item(todo_id="b", changes={"target_date": "2026-09-01"}))
    spec = {"type": "no_change_to", "where": {"locked": True}}
    assert graded(spec, ctx_for(before, ok)).passed
    result = graded(spec, ctx_for(before, bad))
    assert not result.passed and "Locked thing" in result.message


def test_never_writes_fields(before):
    p = proposal(item(todo_id="a", changes={"importance": 1}))
    assert graded({"type": "never_writes_fields", "fields": ["completed"]}, ctx_for(before, p)).passed
    assert not graded({"type": "never_writes_fields", "fields": ["importance"]}, ctx_for(before, p)).passed


def test_only_writes_fields(before):
    p = proposal(item(todo_id="a", changes={"importance": 1, "category": "Work"}))
    assert not graded({"type": "only_writes_fields", "fields": ["importance"]}, ctx_for(before, p)).passed
    assert graded({"type": "only_writes_fields", "fields": ["importance", "category"]}, ctx_for(before, p)).passed


def test_proposes_field_for_all(before):
    spec = {"type": "proposes_field_for_all", "field": "importance",
            "where": {"importance": {"is_null": True}}}
    covered = proposal(item(todo_id="c", changes={"importance": 2}))
    assert graded(spec, ctx_for(before, covered)).passed
    wrong_field = proposal(item(todo_id="c", changes={"category": "Work"}))
    assert not graded(spec, ctx_for(before, wrong_field)).passed


def test_delete_count_and_no_deletes(before):
    p = proposal(item(op="delete", todo_id="d", rationale="duplicate of Quick win elsewhere"))
    assert graded({"type": "delete_count", "count": 1}, ctx_for(before, p)).passed
    assert not graded({"type": "no_deletes"}, ctx_for(before, p)).passed
    assert graded({"type": "no_deletes"}, ctx_for(before, proposal(item(todo_id="a", changes={"importance": 1})))).passed


def test_rationale_cites_survivor(before):
    cites = proposal(item(op="delete", todo_id="d", rationale="Duplicate of Overdue thing, keeping that one"))
    assert graded({"type": "rationale_cites_survivor"}, ctx_for(before, cites)).passed
    vague = proposal(item(op="delete", todo_id="d", rationale="This one looks redundant to me"))
    assert not graded({"type": "rationale_cites_survivor"}, ctx_for(before, vague)).passed


def test_every_item_has_quadrant(before):
    with_q = proposal(item(todo_id="a", changes={"importance": 1}, quadrant="Q3"))
    assert graded({"type": "every_item_has_quadrant"}, ctx_for(before, with_q)).passed
    assert not graded({"type": "every_item_has_quadrant"}, ctx_for(before, proposal(item(todo_id="a", changes={"importance": 1})))).passed


def test_no_dates_on_weekend(before):
    saturday = proposal(item(todo_id="a", changes={"target_date": "2026-08-08"}))
    weekday = proposal(item(todo_id="a", changes={"target_date": "2026-08-07"}))
    assert not graded({"type": "no_dates_on_weekend"}, ctx_for(before, saturday)).passed
    assert graded({"type": "no_dates_on_weekend"}, ctx_for(before, weekday)).passed


def test_schema_valid_reports_the_reason(before):
    inconsistent = Proposal.model_construct(
        summary="a summary long enough",
        items=[ProposalItem.model_construct(op="update", todo_id=None, changes={}, rationale="x" * 20, quadrant=None)],
    )
    result = graded({"type": "schema_valid"}, ctx_for(before, inconsistent))
    assert not result.passed and "todo_id" in result.message


def test_forbidden_fields_are_rejected_at_construction():
    with pytest.raises(ValueError, match="not writable"):
        ProposalItem(op="update", todo_id="a", changes={"completed": True}, rationale="x" * 20)


def test_title_rejected_on_update_but_allowed_on_create():
    ProposalItem(op="create", changes={"title": "New task"}, rationale="x" * 20).check_consistency()
    with pytest.raises(ValueError, match="not writable on update"):
        ProposalItem(op="update", todo_id="a", changes={"title": "Renamed"}, rationale="x" * 20).check_consistency()


def test_duplicate_targets_rejected():
    p = Proposal(
        summary="a summary long enough",
        items=[item(todo_id="a", changes={"importance": 1}), item(todo_id="a", changes={"category": "Work"})],
    )
    with pytest.raises(ValueError, match="at most once"):
        p.check_consistency()


# ── workload graders ────────────────────────────────────────────────────────


def test_apply_in_memory_projects_updates_and_deletes(before):
    p = proposal(
        item(todo_id="a", changes={"target_date": date(2026, 9, 1)}),
        item(op="delete", todo_id="d", rationale="duplicate of Overdue thing"),
    )
    after = apply_in_memory(before, p)
    assert after["a"]["target_date"] == date(2026, 9, 1)
    assert "d" not in after
    assert before["a"]["target_date"] == date(2026, 7, 30), "must not mutate the input snapshot"


def test_workload_decreases(before):
    deferring = proposal(item(todo_id="c", changes={"target_date": date(2026, 9, 1)}))
    spec = {"type": "workload_decreases", "range": "this_week", "min_delta": 2.0}
    assert graded(spec, ctx_for(before, deferring)).passed
    cosmetic = proposal(item(todo_id="c", changes={"importance": 1}))
    assert not graded(spec, ctx_for(before, cosmetic)).passed


def test_no_day_over_capacity():
    tasks = {
        f"t{i}": snap(title=f"t{i}", target_date=TODAY, estimated_effort=2.0)
        for i in range(3)  # 6h against a 4h day
    }
    spec = {"type": "no_day_over_capacity", "range": "today"}
    assert not graded(spec, ctx_for(tasks)).passed
    fixed = proposal(item(todo_id="t0", changes={"target_date": date(2026, 8, 12)}))
    assert graded(spec, ctx_for(tasks, fixed)).passed


# ── reply graders ───────────────────────────────────────────────────────────


def test_reply_mentions_and_omits(before):
    ctx = ctx_for(before, reply="You've got Overdue thing sitting past its date.")
    assert graded({"type": "reply_mentions", "where": {"target_date": {"lt": TODAY}}}, ctx).passed
    assert graded({"type": "reply_omits", "where": {"locked": True}}, ctx).passed
    assert not graded({"type": "reply_mentions", "where": {"locked": True}}, ctx).passed


def test_reply_states_value(before):
    ctx = ctx_for(before, reply="That's 14 hours of work against a 4 hour day.")
    assert graded({"type": "reply_states_value", "value": 14.0}, ctx).passed
    assert not graded({"type": "reply_states_value", "value": 9.0}, ctx).passed


def test_reply_declines(before):
    assert graded({"type": "reply_declines"}, ctx_for(before, reply="I can't mark tasks done — that's yours to do.")).passed
    assert not graded({"type": "reply_declines"}, ctx_for(before, reply="Sure, marking them all complete now.")).passed


def test_judge_fails_until_phase_e(before):
    result = graded({"type": "judge", "rubric": "anything"}, ctx_for(before))
    assert not result.passed and "Phase E" in result.message
