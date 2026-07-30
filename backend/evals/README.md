# Eval harness

Behaviour scenarios for the todo assistant. Written **before** the assistant, so
they double as its spec — see `AI_ASSISTANT_PLAN.md` §7 and `TRIAGE.md`.

```bash
cd backend
pytest evals                      # all scenarios
pytest evals -k dedupe            # one family
pytest evals --collect-only -q    # list them
```

They are **not** part of `pytest` (the default run is `testpaths = tests`). From
Phase E they make real API calls and cost money, so they must never run
implicitly on every push.

## Status

Phase A: all 10 scenarios fail with `agent not implemented`. That is correct —
`agent_adapter.run_agent` is the seam, and Phase B fills it in. The harness that
grades them is tested separately and passes today: `tests/test_eval_harness.py`.

## Anatomy of a scenario

```yaml
id: preserve-locked-tasks       # unique; becomes the pytest case id
description: >                  # why this scenario exists
  ...
fixture: mixed_40               # a seed from fixtures.py
message: "Clear out my week."   # the single user turn
preferences:                    # optional; overrides DEFAULT_PREFERENCES
  notes: "Never schedule Work tasks on a weekend."
today: 2026-08-03               # optional; defaults to fixtures.TODAY (a Monday)
assert:
  - type: no_change_to
    where: { locked: true }
```

Every scenario should assert `db_unchanged`. A turn may propose; it may never
write. If that grader ever fails, the propose/apply separation is broken and
that is a stop-the-line bug, not a quality regression.

## Fixtures

Built relative to `fixtures.TODAY` (2026-08-03, a Monday) so no scenario depends
on the wall clock. `tests/test_eval_harness.py` pins the invariants scenarios
rely on — e.g. "`mixed_40` contains exactly 8 unclassified tasks" — so editing a
fixture can't silently weaken an assertion.

| Fixture | Shape |
|---|---|
| `mixed_40` | 40 tasks: 4 overdue, 3 locked, 8 unclassified, 9 undated, 3 completed, an over-capacity week |
| `overloaded_week` | 14h stacked on a single 4h day |
| `duplicates` | one genuine duplicate pair, plus two pairs that only look similar |

## Selectors

`where` clauses match on any snapshot field. A matcher is a scalar (exact), or
`{op: value}` with `lte`, `gte`, `lt`, `gt`, `ne`, `contains`, `is_null`.

```yaml
where:
  completed: false
  estimated_effort: { lte: 0.5 }
  importance: { is_null: true }
```

Null never satisfies a comparison operator — `{lte: 1.0}` does not match a task
with no estimate.

## Graders

| Grader | Checks |
|---|---|
| `db_unchanged` | No task was created, edited or deleted during the turn |
| `no_proposal` / `has_proposal` | Read-only answer vs. a proposal of at least `min_items` |
| `schema_valid` | The proposal satisfies `app.agent_schemas` including cross-field rules |
| `no_deletes` / `delete_count` | Deletion restraint |
| `no_change_to` | No item targets a task matching the selector (this is the locked-task guard) |
| `never_writes_fields` / `only_writes_fields` | Field whitelist adherence |
| `proposes_field_for_all` | Every task matching the selector got a value for a field |
| `every_item_has_rationale` / `every_item_has_quadrant` | Explainability |
| `rationale_cites_survivor` | A deletion names the task that survives |
| `no_dates_on_weekend` | Scheduling respects non-workdays |
| `workload_decreases` / `no_day_over_capacity` | The proposal actually helps, projected in memory |
| `reply_mentions` / `reply_omits` / `reply_states_value` / `reply_declines` | Answer quality for read-only turns |
| `judge` | LLM-as-judge rubric — **fails until Phase E** rather than passing blind |

## Adding a scenario

Every real failure found while dogfooding becomes a scenario. Write the YAML,
add a fixture only if an existing one can't express the situation, and add the
grader only if no existing one fits. Target for Phase E: 25 scenarios.
