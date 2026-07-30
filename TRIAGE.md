# Triage Policy

The operational definition of "triage" for the todo assistant. This document is the
contract: `backend/app/triage.py` is its executable form, `backend/evals/` grades
against it, and the assistant's system prompt is assembled from it. **Change all
three together.**

Extracted from `AI_ASSISTANT_PLAN.md` §2 so the prompt and the spec cannot drift.

---

## 1. The matrix

Triage means placing every task in an Eisenhower quadrant and proposing the action
that quadrant implies.

### Urgency — derived, never stored

Computed by application code from dates, never by the model:

```
due       = target_date, else end_date, else none
days_left = due - today

urgent = is_focus
         OR (due exists AND days_left <= urgency_horizon_days)   # default 3
```

An undated task is **never** urgent. Overdue tasks (`days_left < 0`) are urgent by
the same rule. The horizon is per-user (`user_planning_preferences.urgency_horizon_days`).

### Importance — stored, user-owned

`todos.importance`: `1` low, `2` medium, `3` high, `NULL` unclassified.

- The user sets it in the task modal.
- The assistant may **propose** a value, with a rationale.
- `NULL` sorts as `2` but is flagged to the assistant as *unclassified* — filling
  those in is one of the most useful things triage does.
- A task is "important" for quadrant purposes only at `3`.

### Quadrants and their actions

| | Important (3) | Not important (1–2) |
|---|---|---|
| **Urgent** | **Q1 — Do.** Keep the date; consider making it the focus task. | **Q3 — Minimise.** Reduce the effort estimate, or batch with similar tasks. |
| **Not urgent** | **Q2 — Schedule.** Give it a `target_date` or a `start_date`/`end_date` block. | **Q4 — Defer or drop.** Push the date out, or propose deletion if also a duplicate. |

Every proposal item must carry its quadrant and a rationale that is consistent with
that quadrant's action.

---

## 2. Writable fields

Enforced by the apply layer, not merely requested in the prompt. Anything outside
this table is rejected before it reaches the database.

| Field | Update | Create | Notes |
|---|:---:|:---:|---|
| `category` | ✅ | ✅ | Must be an existing category for the user, or flagged as new in the rationale |
| `target_date` | ✅ | ✅ | |
| `start_date`, `end_date` | ✅ | ✅ | |
| `estimated_effort` | ✅ | ✅ | May fill when null; may adjust with a rationale |
| `importance` | ✅ | ✅ | |
| `is_focus` | ✅ | ✅ | At most one per user — enforced by the existing router |
| `title`, `description` | ❌ | ✅ | Never silently rewrites an existing task's wording |
| `completed` | ❌ | ❌ | Completion is a statement of fact by the user, never inferred |
| `locked` | ❌ | ❌ | The user's veto — only the user may set it |
| `id`, `user_id`, `created_at`, `updated_at` | ❌ | ❌ | System-owned |

**Deletion** is proposable only for exact or near-exact duplicates, and only when the
rationale cites the surviving task. Everything else is a defer, not a delete.

---

## 3. Guardrails

1. **Locked tasks are read-only.** `locked = true` tasks are returned by read tools
   (the assistant needs them for workload arithmetic) but any proposal item touching
   one is rejected at validation with an explicit error.
2. **No raw SQL tool, ever.** The assistant reaches the database only through the
   typed read tools.
3. **The model proposes; deterministic code validates and applies.** Urgency,
   quadrants, workload sums, capacity checks and date arithmetic all come from
   `app/triage.py`. The model receives them as facts and explains them.
4. **Nothing is applied without explicit user approval.** There is no apply tool.
   Applying is a REST action taken by the user, per item.
5. **Every proposal item carries a rationale.** An item without one is invalid.

---

## 4. Workload arithmetic

Also deterministic (`app/triage.py`):

- A task with a `target_date` consumes its full `estimated_effort` on that day.
- A task with a `start_date`–`end_date` range spreads its estimate evenly across the
  days it spans.
- Completed tasks consume nothing.
- Capacity is `user_planning_preferences.daily_capacity_hours` (default 4.0) on
  workdays, and zero on non-workdays.
- A day is overloaded when scheduled hours exceed capacity; the overage is reported
  as a number, not a judgement.

---

## 5. What triage is not

The assistant declines these, and says why:

- Marking tasks complete — that's the user's checkbox.
- Anything the GUI already does well (create one task, edit one field, toggle done).
- Unlocking or editing locked tasks.
- Deleting anything that isn't a duplicate.
- Inventing categories or dates without saying so in the rationale.
