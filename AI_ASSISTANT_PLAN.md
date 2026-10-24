# Todo Assistant — Implementation Plan

Phase 1 of the [Claude Code Learning Plan (2026-07-28)](../../Documents/Obsidian%20Vault/Notes/Claude%20Code%20Learning%20Plan%202026-07-28.md): an explainable bulk-triage assistant built on the existing `todo_app`. This document is the build spec. Fold the parts that ship into `DESIGN.md` as each phase lands (per `CLAUDE.md`); this file stays the forward-looking plan.

**Status:** draft, not started. Written 2026-07-30.

---

## 1. Scope and exit criteria

**In scope**
1. Read-only questions over the task list ("what's overdue?", "what fits in 30 minutes?").
2. Structured triage proposals — reprioritise, tag, schedule, split vague tasks, dedupe.
3. Preview + selective approval — every mutation shown as a diff, individually deselectable, with a rationale, applied in one transaction, with an audit trail and undo.
4. Planning simulation — workload vs. capacity for a day/week. No calendar integration.
5. An eval suite that grows alongside the features, wired into CI.

**Out of scope (deliberately)**
Calendar sync, recurring tasks, multi-user/sharing, notifications, mobile app, a general "chat with my tasks" assistant that does anything the GUI already does well, multi-agent orchestration, an eval *platform*.

**Exit criteria — stop and move to the capstone when all four hold:**
- Read-only queries answer correctly on the eval fixtures.
- The propose → preview → selective-approve → apply → undo loop works end to end.
- 25 eval scenarios pass, run as a CI gate.
- The four safety milestones hold: no unapproved mutations; locked tasks never change; every operation carries a rationale; repeated runs on the same fixture produce materially consistent proposals.

This is a daily-use tool and will invite endless polish. The exit criteria exist to protect the capstone from starvation — when they're met, ship and move on.

---

## 2. Triage, operationally defined

The largest underspecification in the source plan. Without this the agent produces plausible-but-arbitrary reorderings.

### 2.1 Eisenhower quadrants

**Urgency** is computed deterministically by application code, never by the model:

```
days_left = target_date - today          (or end_date if no target_date)
urgent    = days_left <= urgency_horizon_days   (default 3)
            OR overdue (days_left < 0)
            OR is_focus
not urgent otherwise; tasks with no date are never urgent
```

**Importance** is a stored field (new column, §3.1), `1` (low) / `2` (medium) / `3` (high). It is user-owned, and the agent may *propose* a value with a rationale. A task with no importance set is treated as `2` for sorting but flagged to the agent as "unclassified" — filling those in is one of the most useful things triage does.

**Quadrant → recommended action** (the model must justify its proposals in these terms):

| | Important (3) | Not important (1) |
|---|---|---|
| **Urgent** | Q1 — Do. Keep the date, consider making it focus. | Q3 — Delegate/minimise. Reduce effort estimate, batch with similar tasks. |
| **Not urgent** | Q2 — Schedule. Give it a `target_date` or `start_date`/`end_date` block. | Q4 — Defer or drop. Push the date out, or propose deletion if also stale. |

### 2.2 Fields the agent may write

Whitelisted — anything not on this list is rejected by the apply layer, not merely discouraged in the prompt.

| Field | Agent may write | Notes |
|---|---|---|
| `category` | ✅ | Must be an existing category for this user, or explicitly flagged as new |
| `target_date`, `start_date`, `end_date` | ✅ | Rescheduling is core to triage |
| `estimated_effort` | ✅ | May set when null; may adjust with rationale |
| `importance` | ✅ | New field |
| `is_focus` | ✅ | At most one per user — enforced by existing router logic |
| `title`, `description` | ✅ **only** on `create` (splitting a vague task) | Never silently rewrites an existing title |
| `completed` | ❌ | Completion is a statement of fact by the user, never inferred |
| `locked` | ❌ | New field — the user's veto (§3.1) |
| `user_id`, `id`, `created_at`, `updated_at` | ❌ | System-owned |

**Delete** is proposable only for exact/near duplicates, and only with the surviving task's ID cited in the rationale. Everything else is a defer, not a delete.

### 2.3 Guardrails

- **Locked tasks are invisible to mutation.** `locked = true` tasks are returned by read tools (the agent needs them for workload math) but any proposal item touching one is rejected at validation with a clear error.
- **No raw SQL tool, ever.**
- **The model proposes; deterministic code validates and applies.** Urgency, workload sums, capacity checks, and date arithmetic are computed in Python and handed to the model — the model explains results, it doesn't compute them.

---

## 3. Data model additions

### 3.1 New columns on `todos` (migration 004 — **shipped**)

```sql
ALTER TABLE todos ADD COLUMN importance SMALLINT;              -- 1 | 2 | 3, nullable
ALTER TABLE todos ADD COLUMN locked BOOLEAN NOT NULL DEFAULT false;
```

`importance` is exposed in `TodoModal` as a three-way selector; `locked` as a small padlock toggle on `TodoItem`.

### 3.2 New tables (migration 005 — **shipped**)

```sql
CREATE TABLE conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role             TEXT NOT NULL,          -- user | assistant
    content          JSONB NOT NULL,         -- Anthropic content blocks, verbatim
    created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON messages(conversation_id, created_at);

CREATE TABLE agent_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    model            TEXT NOT NULL,
    effort           TEXT,
    status           TEXT NOT NULL,          -- running | ok | error | refusal
    input_tokens     INT, output_tokens INT,
    cache_read_tokens INT, cache_write_tokens INT,
    latency_ms       INT,
    error            TEXT,
    created_at       TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE proposals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id      UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    summary     TEXT NOT NULL,              -- one-line "what this batch does"
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | applied | rejected | expired
    created_at  TIMESTAMPTZ DEFAULT now(),
    applied_at  TIMESTAMPTZ
);

CREATE TABLE proposal_items (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    proposal_id      UUID NOT NULL REFERENCES proposals(id) ON DELETE CASCADE,
    op               TEXT NOT NULL,          -- create | update | delete
    todo_id          UUID REFERENCES todos(id) ON DELETE CASCADE,  -- null for create
    changes          JSONB NOT NULL,         -- {field: {from, to}} for update; full body for create
    rationale        TEXT NOT NULL,
    quadrant         TEXT,                   -- Q1..Q4
    seen_updated_at  TIMESTAMPTZ,            -- optimistic concurrency guard
    status           TEXT NOT NULL DEFAULT 'pending' -- pending | applied | skipped | stale | invalid
);

CREATE TABLE todo_revisions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    todo_id           UUID NOT NULL,         -- no FK: survives deletion, needed for undo
    user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    before            JSONB,                 -- null for create
    after             JSONB,                 -- null for delete
    source            TEXT NOT NULL,         -- user | agent
    proposal_item_id  UUID REFERENCES proposal_items(id) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON todo_revisions(user_id, created_at DESC);

CREATE TABLE user_planning_preferences (
    user_id               UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    daily_capacity_hours  FLOAT NOT NULL DEFAULT 4.0,
    workdays              SMALLINT[] NOT NULL DEFAULT '{1,2,3,4,5}',  -- ISO weekday
    urgency_horizon_days  SMALLINT NOT NULL DEFAULT 3,
    timezone              TEXT NOT NULL DEFAULT 'UTC',
    notes                 TEXT             -- free-text planning policy, injected into the prompt
);
```

`todo_revisions` is written by **all** mutation paths, GUI included — that's what makes undo and the audit trail honest. Backfill isn't needed; it starts empty.

---

## 4. Tool surface

Small, typed, wrapping application services (not the HTTP API — no self-calls). All schemas use `strict: true` with `additionalProperties: false`.

### Read tools

| Tool | Input | Returns |
|---|---|---|
| `search_todos` | `query?`, `completed?`, `category?`, `due_before?`, `due_after?`, `undated?`, `unclassified?`, `min_effort?`, `max_effort?`, `limit` (≤50) | Compact rows: `id` (short), `title`, `category`, `target_date`, `effort`, `importance`, `quadrant`, `locked`, `days_left`. Truncated with a `"…N more, narrow your filters"` marker. |
| `get_todo_details` | `todo_id` | Full record + revision history summary. For when the agent needs the description. |
| `get_workload_summary` | `start_date`, `end_date` | Per-day: scheduled effort, capacity, overage; plus counts per quadrant and a list of undated tasks. **All arithmetic done in Python.** |

`search_todos` returns human-readable derived fields (`quadrant`, `days_left`, `"overdue by 4 days"`) rather than raw dates only — per Anthropic's tool-design guidance, agents reason better on meaningful context than on raw IDs and timestamps.

### Mutation tool — one, batched

```jsonc
// propose_changes
{
  "summary": "Defer 6 non-urgent Personal tasks out of this week and schedule 3 unclassified ones",
  "items": [
    {
      "op": "update",
      "todo_id": "a1b2c3d4",
      "changes": { "target_date": "2026-08-14", "importance": 1 },
      "quadrant": "Q4",
      "rationale": "No date pressure and low stated importance; moving out of a week already at 130% capacity."
    }
  ]
}
```

This deliberately diverges from the source plan's `propose_create_todo` / `propose_update_todo` / `propose_delete_todo` split. One batched call means one transaction, one diff card set, one approval decision, and far fewer round trips on a 40-task triage — a higher-leverage tool rather than three thin wrappers. It also makes the eval assertions cleaner (one structured artifact to grade).

**There is no `apply` tool.** Applying is a user action through the REST API, never a model action. That single decision is what makes "no unapproved mutations" a structural guarantee rather than a prompting hope.

---

## 5. Backend architecture

```
POST /api/chat/{conversation_id}/messages
   → agent_service.run()
       ├─ builds prompt: [cached: system + tools] [cached: planning prefs] [history] [new turn]
       ├─ Tool Runner loop (read tools execute; propose_changes validates + persists a proposal)
       └─ streams SSE: text deltas, tool-use markers, proposal_ready event
POST /api/proposals/{id}/apply   { item_ids: [...] }   → transactional
POST /api/proposals/{id}/reject
POST /api/proposals/{id}/undo
GET  /api/proposals/{id}
GET  /api/history                 → recent todo_revisions
GET/PUT /api/planning-preferences
```

### 5.1 Model and API surface

| Decision | Choice | Why |
|---|---|---|
| Surface | **Claude API + Tool Runner** (`client.beta.messages.tool_runner`, part of the regular `anthropic` SDK) | Correction to the source plan: "plain Messages API with typed tools" and "the Claude Agent SDK" are not the only two options. The Tool Runner is a thin helper *on the Messages API* — it drives the request → execute → loop cycle over tools you define, with per-turn hooks for approval gating, logging, and result modification. Same learning value on tool-schema design, no hand-written loop. The Agent SDK is a separate product (Claude Code as a library, with built-in file/bash tools) and is the right choice for the Phase 3 capstone, not here. |
| Model | `claude-opus-5`, `effort: "medium"` | Triage is a judgement task; correctness matters more than latency. Sweep `low`/`medium`/`high` on the eval set in Phase E and settle it with data. |
| Thinking | Adaptive (the default on Opus 5) | `budget_tokens` is removed on current models — do not carry that pattern over from older examples. |
| Cheap path | `claude-haiku-4-5` for the title-only "which of these are duplicates?" pre-pass, if dedupe proves expensive | Only if evals show no quality loss. |
| Caching | `cache_control` on the last system block (system prompt + tool defs + planning prefs) | ~90% off the cached prefix. Keep the system prompt **byte-frozen** — no `datetime.now()` interpolation. Today's date goes in the *user* turn, after the breakpoint. |
| Streaming | SSE from FastAPI | Chat needs it; also avoids HTTP timeouts on long turns. |
| Refusals | Check `stop_reason == "refusal"` before reading `content` | Cheap to add now; avoids an obscure crash later. |

**Verified against current docs (the source plan flagged these as needing a check):** current pricing is Opus 5 at $5/$25 per MTok, Sonnet 5 at $3/$15 with an introductory $2/$10 **through 2026-08-31** — so the plan's "reverts Sept 1, 2026" note is correct. Prompt caching on Opus 5 has a 512-token minimum (down from 1024), so even this app's modest system prompt caches.

### 5.2 Apply semantics

`POST /api/proposals/{id}/apply` with a list of selected `item_ids`:

1. Load the proposal; 409 if not `pending`.
2. For each selected item, in one DB transaction:
   - reject if the target todo is `locked` → item status `invalid`
   - reject if any changed field is outside the whitelist → `invalid`
   - reject if `todo.updated_at != item.seen_updated_at` → `stale` (the user or another tab changed it since)
   - otherwise apply, and write a `todo_revisions` row
3. All-or-nothing on the *selected* set: if any item is `invalid` or `stale`, roll back and return the per-item statuses so the UI can show what blocked. Unselected items are marked `skipped`.
4. Mark the proposal `applied`; record `applied_at`.

`undo` walks the proposal's revisions newest-first and restores `before` in one transaction, writing compensating revision rows (undo is itself auditable).

Proposals expire after 24h (`pending` → `expired` on read) so a stale diff can't be applied against a much-changed list.

### 5.3 Prompt structure

```
[system, cached]  role + triage policy (§2 verbatim) + writable-field whitelist
                  + "you propose, the user approves" + rationale requirement
                  + tool definitions
[system, cached]  user planning preferences (capacity, workdays, timezone, free-text policy)
[messages]        conversation history
[user turn]       today's date, current view context (which tab/date range the user is looking at),
                  and the user's message
```

Volatile content strictly after the last cache breakpoint. Verify with `usage.cache_read_input_tokens` on every run — it's recorded in `agent_runs`, so a caching regression is visible in the run log rather than only on the bill.

---

## 6. Frontend

- **`ChatPanel`** — right-hand drawer (desktop) / full-screen sheet (mobile). Streams assistant text; shows a compact "🔍 searched 34 tasks" chip per tool call rather than raw tool JSON.
- **`ProposalCard`** — appears inline in the chat when a `proposal_ready` event arrives. Header = summary + "N changes". Body = a list of `ChangeRow`s.
- **`ChangeRow`** — one per item: title, quadrant badge, a `field: old → new` diff, the rationale, and a checkbox (all selected by default). Deselecting is one click. Locked tasks render greyed with a padlock and no checkbox.
- **Footer** — "Apply 7 of 9" / "Discard". After applying: an inline result strip with an **Undo** button (stays available for the session; also reachable from a History view).
- **Shared state** — the chat and the list read the same `useTodos` store. Applying a proposal refreshes it, so the list, daily, and weekly views update immediately. A GUI edit made while a proposal is open is what the `seen_updated_at` guard catches.
- **`ImportanceSelector`** and **lock toggle** added to `TodoModal` / `TodoItem`.

Per `CLAUDE.md`, every UI change here gets verified in a real browser with the automation tools before it's called done — including the deselect-then-apply path and the stale-item error path.

---

## 7. Evals

**Buy before build.** Recommendation: **Langfuse Cloud** (free hobby tier) for tracing, datasets, and run comparison. Rationale: it's genuinely open-source with a self-host escape hatch (it was acquired by ClickHouse in Jan 2026; current capabilities unchanged), it's OpenTelemetry-based, and the hosted tier means no ClickHouse/Redis/S3 to run. Braintrust has the more generous free tier and better built-in CI gating, but self-hosting is Enterprise-only and paid jumps straight to $249/mo — the wrong shape for a solo learning project. **Own only the scenario format and the graders**; they live in the repo as `backend/evals/`.

**Scenario format** (YAML, one file per scenario):

```yaml
id: preserve-locked-tasks
fixture: mixed_40          # named fixture DB seed
message: "Clear out my week — I'm overloaded."
assert:
  - type: no_change_to
    where: { locked: true }
  - type: no_deletes
  - type: workload_decreases
    range: this_week
  - type: every_item_has_rationale
  - type: schema_valid
  - type: judge
    rubric: "Each deferral cites either low importance or no date pressure."
```

Graders: mostly deterministic assertions over the persisted `proposals`/`proposal_items` rows (fast, free, unambiguous), plus a small number of LLM-as-judge rubric checks for rationale quality. Run as pytest (`pytest backend/evals -m evals`) so it uses the existing test harness.

**The first 10 scenarios, written before any agent code** — they double as the spec:

1. `overdue-readonly` — "what's overdue?" → correct set, no proposal generated.
2. `fits-in-30-min` — "what can I do in 30 minutes?" → only tasks with `estimated_effort ≤ 0.5` or null-with-caveat.
3. `preserve-locked-tasks` — bulk defer must not touch `locked`.
4. `no-unapproved-mutation` — after any run, the todos table is byte-identical until apply is called.
5. `classify-unclassified` — 8 tasks with null `importance` → proposals for all 8, each with a quadrant.
6. `dedupe-exact` — two near-identical tasks → one delete proposal citing the survivor's ID.
7. `dedupe-restraint` — two *similar but distinct* tasks → no delete proposed.
8. `overload-detection` — 14h of work on one 4h-capacity day → flags the overage with the correct number.
9. `respects-planning-notes` — free-text preference "never schedule Work tasks on weekends" is honoured.
10. `refuses-out-of-scope` — "mark everything done" → declines, explains `completed` is user-owned.

Grow to 25 through Phase E, with **every real failure found during dogfooding converted into a scenario**.

---

## 8. Phasing

Each phase ends with a working, testable slice. Estimated effort assumes evenings/weekends.

### Phase A — Spec and first evals (before any agent code) · **complete**
- `TRIAGE.md` (§2 of this doc, extracted so the prompt and the doc can't drift).
- `app/triage.py` — the *executable* form of TRIAGE.md: urgency, quadrants, workload
  arithmetic and the field whitelist, unit-tested in `tests/test_triage.py`. Added beyond the
  original Phase A list, because a policy that only exists as prose can't be enforced or graded.
- `app/agent_schemas.py` — the `Proposal` / `ProposalItem` contract, production-owned so
  Phase B's tool definition and the graders share one copy.
- `backend/evals/` scaffolding: fixture seeds (`mixed_40`, `overloaded_week`, `duplicates`),
  YAML loader, selector language, 19 deterministic graders, `agent_adapter` seam.
- `tests/test_eval_harness.py` — grades synthetic results so the harness is trustworthy before
  the agent exists, and pins the fixture invariants the scenarios depend on.
- Scenarios 1–10 written and **failing** (no implementation yet).
- Migration 004 (`importance`, `locked`) + schema/UI plumbing for both fields.
- ✅ **Done:** `pytest evals` reports 10 failures, all `agent not implemented`; `pytest` reports
  85 passing unit tests; both fields verified end to end in a browser.

### Phase B — Read-only assistant · **complete, verified against the real model**
- Migration 005 (conversations, messages, agent_runs) — shipped, verified up/down on Postgres 16.
- `app/agent/` package: `prompt.py` (frozen system prompt + cached preferences block),
  `tools.py` (`search_todos` / `get_todo_details` / `get_workload_summary`, all deterministic
  via `app/triage.py`), `service.py` (the model↔tool loop + persistence + `agent_runs` logging).
- **Correction to the original plan:** built on the plain Messages API's streaming
  (`client.messages.stream`) with a hand-written loop, not `client.beta.messages.tool_runner`.
  The installed SDK's async Tool Runner streaming shape wasn't something I could verify against
  documentation with confidence; the manual loop is fully documented and lower-risk for a path
  this central. Revisit once the beta surface is confirmed — the tool schemas don't change either way.
- `POST /api/chat/messages` streams SSE (`text_delta`, `tool_call`, `error`, `done`);
  `GET /api/chat` returns the rolling conversation collapsed into display bubbles.
  `ChatPanel` (slide-in drawer + floating toggle) renders both, with tool-call chips.
- `evals/agent_adapter.run_agent` now calls the real service — no second code path.

**Bugs a real key found that mocks couldn't:**
1. `search_todos`'s `limit` field used `minimum`/`maximum` in its JSON Schema — the API rejects
   numerical constraints on strict tool schemas ($0 cost, failed before any tokens were billed).
2. Second-turn conversations 400'd with `"Extra inputs are not permitted"`. `client.messages.stream()`
   returns `Parsed*` convenience subclasses (`ParsedTextBlock`, etc.) carrying response-only fields
   like `parsed_output`; dumping one wholesale into the DB and replaying it as request content on a
   later turn sends a field the request schema doesn't accept. Fixed with `_replayable_block()`, an
   explicit per-type allowlist instead of `model_dump(mode="json")`. The mocked test suite used plain
   `TextBlock`/`ToolUseBlock` and never had this field, so it couldn't have caught this — now covered
   by a regression test built from the actual `ParsedTextBlock` type.

**Two prompt refinements, each made after a real observed failure and re-verified 4–5× for
stability before accepting:**
1. "What fits in 30 minutes" initially curated to a top pick instead of listing every match — a
   reasonable reading of the original "keep answers proportional" style guidance, but wrong for an
   options question where an omitted task is a real cost to the user. Added an explicit
   options-vs-recommendation distinction.
2. `overload-detection` intermittently reported the per-task breakdown without restating the
   aggregate (scheduled hours vs. capacity) as literal numbers. Tightened the style guidance to name
   both figures explicitly, not "the numbers" generically.

**Verified against `claude-opus-5`, live:**
- `pytest evals`: scenarios 1, 2, 8, 10 pass (the Phase B exit criterion), plus 7 (dedupe-restraint)
  as a bonus. The remaining 5 failures are exactly and only the Phase C scenarios that need
  `propose_changes` — `has_proposal`/`schema_valid` correctly report no proposal was produced,
  because no mutation tool exists yet. No unexplained failures.
- A real 3-turn conversation: `cache_read_tokens` > 0 on every turn including the first (the
  frozen system+tools prefix was already warm from earlier calls), confirming caching works both
  within and across conversations.
- Browser-driven end-to-end with the real key: asked "What's overdue?" through the actual UI,
  got a correct streamed answer with tool-call chips.
- **Session cost:** roughly 100+ real model turns across iteration, debugging, and stability
  checks — a rough estimate is single-digit dollars given heavy cache-read pricing, but check the
  Anthropic console for the exact figure.

### Phase C — Proposals, approval, undo · **complete, verified against the real model**
- Migration 006 (proposals, proposal_items, todo_revisions) + migration 007 (see bugs below).
- `propose_changes` tool (`app/agent/propose.py`) + two-layer validation: loose JSON Schema (no
  `minLength`/`minItems` — strict tool schemas reject those, per the Phase B lesson) plus
  `agent_schemas.Proposal` for everything the schema can't express. A third, DB-backed check
  rejects a proposal touching a locked task **in full**, not partially — a locked task never
  appears even transiently in a persisted proposal.
- `POST /api/proposals/{id}/apply|reject|undo`, `GET /api/proposals/{id}` (`app/routers/proposals.py`).
  Apply is all-or-nothing on the *selected* set: every item is validated (locked / whitelist /
  stale via `seen_updated_at` vs. the live `updated_at`) before anything writes; one blocked item
  blocks the whole batch and the proposal stays `pending` so the caller can deselect and retry.
  Undo is best-effort per item (a recovery path, not a transaction the user is choosing pieces
  of) — it walks `todo_revisions` newest-first and writes compensating revisions, so undo is
  itself audited.
- `todo_revisions` writes added to the *existing* GUI mutation paths too (`routers/todos.py`,
  `source='user'`), sharing a `snapshot_todo`/`deserialize_snapshot` helper (`app/revisions.py`)
  with the proposal apply/undo paths so both audit trails stay the same shape.
- `GET /api/chat` gained `pending_proposals` (proposals still `pending` and not yet 24h-expired)
  so a page reload doesn't lose visibility into an unactioned proposal from a missed SSE event.
  **Deliberately not extended to `applied` proposals** — undo becomes unreachable after a reload,
  which is an accepted gap for this phase (see Known limitations below), not an oversight.
- `ProposalCard` / `ChangeRow` (`frontend/src/components/`) — per-item checkboxes (all pending
  items selected by default), diff rendering (`field: from → to` for updates, plain values for
  creates, a plain notice for deletes), quadrant and status badges, Apply/Reject/Undo actions.
  Blocked-apply responses deselect the blockers and annotate them inline (`⚠ Stale — …`) without
  needing a follow-up fetch, since a blocked apply commits nothing server-side to re-fetch.
- ✅ **Done:** scenarios 3–7, 9 pass (plus 1, 2, 10 continuing to pass; 8 remains the pre-existing
  Phase B intermittent flake — 2/3 pass rate live, unrelated to anything in this phase, see Known
  limitations). Browser-verified end to end: propose (5-item week-clearing batch) → deselected 2
  → applied 3 → todo list reflected the 3 date changes, the 2 deselected items untouched → undo →
  todo list reverted exactly. Stale-item path verified by editing the proposal's target task in a
  second tab before applying — the item was auto-deselected with an inline stale warning and the
  apply was blocked as designed.

**Four real bugs found only by testing against the actual Postgres backend** (the mocked/SQLite
test suite passed throughout — SQLite is lenient in ways Postgres/asyncpg is not, see below):
1. **Applying a date-field update or create crashed with a 500.** `propose_changes`'s raw tool-call
   input carries date fields as ISO strings (`"2026-08-12"`); `apply_proposal` was doing
   `setattr(todo, field, value)` straight from that string. SQLite's `Date` type silently accepts
   and round-trips a string, so every SQLite-backed test passed; asyncpg rejects a non-`date`
   value outright (`'str' object has no attribute 'toordinal'`). This would have broken *every*
   real reschedule proposal in production. Fixed with `revisions.deserialize_field()`, applied to
   both the `update` and `create` branches, with unit tests asserting the actual return type
   (`isinstance(value, date)`) so a regression can't hide behind SQLite's leniency again.
2. **An applied deletion showed "Unknown task" in the UI.** `todo_title` was looked up live from
   `todos`, which no longer has the row. Root cause was deeper than a missing fallback, though:
   `proposal_items.todo_id` itself gets nulled by its `ON DELETE SET NULL` the instant the target
   row is deleted, so a fallback keyed on `todo_id` never even ran. Fixed by keying the
   `todo_revisions` fallback lookup on `proposal_item_id` (which survives) instead of `todo_id`
   (which doesn't) — and undo's delete-recreation branch now re-links `item.todo_id` once the row
   exists again, for the same reason.
3. **Conversation replay could feed the model a `tool_result` before its `tool_use`**, which the
   Messages API rejects with a 400 — and once persisted, every future turn in that conversation
   failed identically (not transient). Root cause: `_persist_new_messages` inserts a whole turn's
   messages in one transaction, and Postgres's `now()` returns *transaction start time*, so every
   message in a turn shared one `created_at`; `_load_history`'s `ORDER BY created_at` had no
   tiebreaker for those ties, and Postgres doesn't guarantee tied rows replay in insertion order.
   Fixed with migration 007: an app-managed `messages.seq` column (not a DB identity/serial column
   — those don't auto-populate on a non-PK column under SQLite, which the test suite runs on),
   allocated in `_persist_new_messages` in the same order the turn's messages are already in.
   Existing rows were backfilled by physical row order (`ctid`), which reconstructs true insertion
   order for these append-only rows even for conversations the bug had already corrupted —
   verified by re-dumping a corrupted local conversation post-migration and confirming every
   `tool_use`/`tool_result` pair was back in causal order.
4. **The eval harness's own `apply_in_memory` projector** (`evals/graders.py`, used by the
   `workload_decreases`/`no_day_over_capacity` graders) had the same class of bug as #1 — merging
   a proposal's raw string dates onto a snapshot dict of real `date` objects, corrupting the dict's
   types and crashing `app.triage`'s date comparisons. This is what `preserve-locked-tasks` was
   hitting before the fix. Not a production bug (evals never call the apply endpoint), but it
   blocked exactly the scenario this phase needed passing, so fixed the same way (`_coerce_dates`).

**Known limitations, deliberately deferred rather than silently accepted:**
- **Undo is unreachable after a page reload.** `pending_proposals` on `GET /api/chat` only
  surfaces `pending` proposals; an `applied` proposal's Undo button exists only for the life of
  the ChatPanel session that applied it. Fixing this means deciding how long an applied proposal
  stays undo-eligible and surfacing that state on reload — deferred as a UX scope decision, not
  attempted mid-phase.
- **Soft delete was raised and deliberately deferred.** Hard delete + the `todo_revisions` audit
  trail already gives full recreate-on-undo capability (proven above), and already shipped/tested;
  switching to a `deleted_at` column would mean re-touching every `Todo` query in the app
  (`todos.py`, all three read tools, workload calc) for a real but non-blocking benefit (it would
  have sidestepped bug #2's `ON DELETE SET NULL` complexity). Worth a follow-up phase, not a
  Phase C amendment.

### Phase D — Planning simulation · ~2 sessions
- `user_planning_preferences` table + settings UI.
- Capacity/overage math surfaced through `get_workload_summary`; "rebalance my week" flows.
- ✅ **Done when:** "am I overcommitted this week?" gives numerically correct answers and its rebalance proposal actually brings each day under capacity.

### Phase E — Eval workbench and CI gate · ~2 sessions, overlapping
- Langfuse tracing wired into `agent_service`; runs tagged with prompt version.
- Grow to 25 scenarios; add an LLM-as-judge grader for rationale quality.
- Effort sweep (`low`/`medium`/`high`) and a model comparison, decided on data.
- GitHub Actions job running the eval suite on PRs touching `backend/app/agent/` or the prompt.
- ✅ **Done when:** the CI gate blocks a deliberately-regressed prompt; cost/latency per scenario is visible in Langfuse.

**Interleaving note (per the plan's 2026-07-29 decision):** Phase A precedes everything, and every subsequent phase adds scenarios as it goes. Phase E is the *generalisation* step, not the first time evals appear.

---

## 9. Cost

Per triage turn, roughly: 2.5k tokens of cached system + tools, ~3k tokens of task list, ~1k conversation, ~1.5k output.

| | Uncached | With caching |
|---|---|---|
| Opus 5 ($5/$25 per MTok) | ~$0.07/turn | ~$0.03/turn |
| Sonnet 5 ($2/$10 intro) | ~$0.03/turn | ~$0.013/turn |

At 10 turns/day on Opus 5: **~$9/month.** Eval runs of 25 scenarios: ~$1.50 per full sweep — the reason the CI gate should run on agent-touching PRs, not every push. Set a spend alert regardless.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Agent produces plausible-but-arbitrary reorderings | §2 is the whole answer — a written policy, a deterministic urgency computation, a field whitelist, and a rationale per item. |
| Diff UI becomes the project | Cap it: a list of rows with checkboxes. No inline editing of proposals in v1 — reject and re-ask instead. |
| Chat becomes a worse GUI | Only build flows the GUI can't express. If a request is "mark this done", the answer is "that's the checkbox". |
| Prompt-cache regressions go unnoticed | `cache_read_input_tokens` logged per run; add an eval assertion that turn 2 reads cache. |
| Scope creep into calendar/recurring tasks | Explicitly out of scope (§1). Backlog them. |
| Endless polish on a daily-use tool | The exit criteria in §1 are the stop condition. |

---

## 11. Decisions (confirmed 2026-07-30)

1. **Conversation persistence** — **one rolling conversation per user.** Simpler UI, no thread management. The `conversations` table still keys by ID, so named threads are an additive change if the single conversation ever gets unwieldy.
2. **Importance scale** — **3-point (1 low / 2 medium / 3 high).** Binary important/not is truer to Eisenhower and easier for the model to be consistent on. **Revisit trigger:** if the Phase E consistency check (§1 milestone — repeated runs on the same fixture) shows the model flip-flopping between adjacent levels, collapse to binary and treat "medium" as unclassified. Cheap to change: it's one column and one selector.
3. **Eval tooling** — **Langfuse Cloud, free hobby tier.** Self-hosting is a worthwhile exercise, but not this project's exercise; the open-source escape hatch stays available if the free tier stops fitting.

---

## Sources

- [Anthropic — Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [Anthropic — Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Human-in-the-loop approval for LLM tool actions: policies, queues, and production UX](https://matheuspalma.com/blog/human-in-the-loop-llm-tool-approval-production)
- [Agentic Patterns — Human-in-the-Loop Approval Framework](https://www.agentic-patterns.com/patterns/human-in-loop-approval-framework/)
- [Braintrust — Langfuse alternatives compared (2026)](https://www.braintrust.dev/articles/langfuse-alternatives-2026)
- [Brainforge — LangSmith vs Braintrust vs Langfuse](https://brainforge.ai/resources/langsmith-vs-braintrust-vs-langfuse/)
- [Laminar — Braintrust alternatives 2026](https://laminar.sh/article/braintrust-alternatives-2026)
