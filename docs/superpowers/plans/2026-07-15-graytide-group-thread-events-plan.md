# Graytide Group Thread Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make group dialogue causality, ordering, duplicate suppression, and empty outcomes explicit and replayable across physical sessions.

**Architecture:** A logical group thread is the aggregate. Player, event, and autonomous inputs create turns; posted messages and outcomes append ledger events and synchronously project to existing message history plus new turn metadata.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite/PostgreSQL, React API client compatibility, pytest

---

## File Map

- Create `src/memoria/core/group_turns.py`: turn IDs and outcome types.
- Create `tests/test_group_thread_events.py`: causality, ordering, and outcomes.
- Modify `src/memoria/db/repository.py`: turn schema, thread sequence allocation, projection.
- Modify `src/memoria/core/multi_character_orchestrator.py`: preserve pulse decisions and causal IDs.
- Modify `src/memoria/core/group_dialogue_runtime.py`: autonomous/event turn propagation.
- Modify `src/memoria/api/multi_dialogue.py`: optional structured outcome fields and cursor.
- Modify `web/src/api/memoria.js`: optional thread-sequence cursor.
- Modify `web/src/pages/ChatRoom.jsx`: interpret structured outcomes without replacing current UI flow.
- Modify `tests/test_group_dialogue_pulse.py` and `tests/test_api_models.py`.

### Task 1: Turn and Outcome Types

**Files:**
- Create: `src/memoria/core/group_turns.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing model tests**

Validate that a group turn accepts `player`, `event`, and `autonomous` sources,
and only `responded`, `waiting`, `suppressed`, or `async_pending` terminal
outcomes.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py -v`

Expected: FAIL because `group_turns` does not exist.

- [ ] **Step 3: Implement models**

Add `GroupTurnSource`, `GroupTurnOutcome`, `GroupTurnStart`, and
`GroupTurnResult`. Normalize supplied request IDs; generate UUIDs only when the
caller did not provide one.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 2: Additive Turn and Sequence Schema

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing schema tests**

Insert a logical thread with two physical sessions and assert:

```python
first = repository.start_group_turn(...)
second = repository.start_group_turn(...)
assert first["turn_id"] != second["turn_id"]
assert repository.get_group_turn(first["turn_id"])["status"] == "open"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py::test_group_turns_span_physical_sessions -v`

Expected: FAIL because turn storage does not exist.

- [ ] **Step 3: Add schema**

Add `group_dialogue_turn`, `group_thread_sequence`, optional
`short_term_message.source_turn_id`, and optional
`short_term_message.thread_seq`. Add unique indexes for
`(group_thread_id, thread_seq)` and `(owner_user_id, turn_id)`.

- [ ] **Step 4: Implement turn repository APIs**

Implement start/get/complete operations that append
`group.turn.started.v1`/`group.turn.outcome.v1` and project state in one
transaction. Reusing a request ID returns the existing turn.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 3: Atomic Message Projection and Monotonic Ordering

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_group_thread_events.py`
- Test: `tests/test_repository.py`

- [ ] **Step 1: Write the failing cross-session ordering test**

Create an older physical session after a newer one, insert messages with
deliberately reversed `created_at` values, and assert logical history returns
`thread_seq == [1, 2, 3]`.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py::test_thread_sequence_orders_cross_session_messages -v`

Expected: FAIL because history currently orders by global message ID.

- [ ] **Step 3: Allocate and project sequences**

Within message commit transactions, increment the logical thread sequence,
append `group.message.posted.v1`, and insert the assigned `thread_seq` and
`source_turn_id` into `short_term_message`.

- [ ] **Step 4: Order all logical-history paths**

Update full, limited, paginated, and incremental group history queries to order
by `thread_seq`, with legacy null rows ordered by their deterministic backfill
sequence and message ID as final tie-breaker.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_group_thread_events.py tests/test_repository.py -v`

Expected: PASS.

### Task 4: Legacy Thread-Sequence Backfill

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing non-destructive backfill test**

Create legacy messages across two carrier sessions, run the backfill twice, and
assert stable sequences, unchanged timestamps/content, and one
`group.message.imported.v1` event per message.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py::test_legacy_message_backfill_is_stable -v`

Expected: FAIL because backfill does not exist.

- [ ] **Step 3: Implement idempotent backfill**

Group rows by tenant and logical thread, sort by existing message ID, assign
sequences, and emit deterministic imported event IDs. Record migration key
`2026-07-15-group-thread-sequence-backfill`.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 5: Preserve Pulse Decisions and Source Turns

**Files:**
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Modify: `src/memoria/core/group_dialogue_runtime.py`
- Test: `tests/test_group_dialogue_pulse.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing causal propagation tests**

Assert all synchronous responses share the player's turn ID, and a delayed
autonomous response caused by that turn retains the same `source_turn_id`.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_dialogue_pulse.py -v`

Expected: FAIL because pulse results do not expose a source turn.

- [ ] **Step 3: Thread the causal ID**

Add `source_turn_id` to `run_dialogue_pulse`,
`_generate_character_response`, staged messages, autonomous state/hooks, and
repository commit calls. Persist the last pulse decision instead of discarding
it after returning only the response list.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_group_dialogue_pulse.py tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 6: Structured Empty Outcomes

**Files:**
- Modify: `src/memoria/api/multi_dialogue.py`
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Test: `tests/test_api_models.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing API contract tests**

For a wait decision assert:

```python
body = response.json()
assert body["responses"] == []
assert body["outcome"] == "waiting"
assert body["reason"] == "wait_for_player"
assert body["turn_id"]
```

For duplicate suppression assert `outcome == "suppressed"`. For a queued
autonomous continuation assert `outcome == "async_pending"`.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_api_models.py tests/test_group_thread_events.py -v`

Expected: FAIL because response fields and turn outcomes do not exist.

- [ ] **Step 3: Extend response model**

Add optional `turn_id`, `outcome`, `reason`, `latest_thread_seq`, and
`poll_after_ms` to `MultiDialogueGroupResponse`. Keep `responses` and
`total_speakers` unchanged.

- [ ] **Step 4: Complete every turn explicitly**

Map pulse state to structured outcomes, append the outcome event, and return the
projection from the route. A non-empty response always uses `responded`.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_api_models.py tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 7: Causal Duplicate Suppression

**Files:**
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing logical-thread duplicate test**

Post a response in carrier session A, continue the thread in session B, then
attempt a near-duplicate from the same speaker and source turn. Assert no second
message is inserted and the turn outcome is `suppressed`.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py::test_duplicate_suppression_crosses_carrier_sessions -v`

Expected: FAIL because duplicate lookup filters by physical session.

- [ ] **Step 3: Query logical-thread candidates**

Replace session-local duplicate SQL with a tenant/thread join. Prefer exact
source-turn and reply-target matches before normalized-text similarity.

- [ ] **Step 4: Emit suppression outcome**

Append `group.turn.outcome.v1` with reason `duplicate_response`; retain the
existing message as evidence but do not map the new temporary ID to it as if it
were newly posted.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_group_thread_events.py -v`

Expected: PASS.

### Task 8: API Cursor and Frontend Compatibility

**Files:**
- Modify: `src/memoria/api/multi_dialogue.py`
- Modify: `web/src/api/memoria.js`
- Modify: `web/src/pages/ChatRoom.jsx`
- Test: `web/tests/memoriaApi.test.js`
- Test: `tests/test_group_thread_events.py`

- [ ] **Step 1: Write failing cursor tests**

Assert `after_thread_seq` returns only later logical messages and response
metadata includes `latest_thread_seq`. Assert the old `after_message_id` path
still returns valid results.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_group_thread_events.py -v && cd web && npm test -- --run web/tests/memoriaApi.test.js`

Expected: FAIL because the sequence cursor is absent.

- [ ] **Step 3: Add optional cursor**

Accept `after_thread_seq` in group history, prefer it when present, and retain
`after_message_id` as compatibility fallback.

- [ ] **Step 4: Update frontend polling**

Track `latest_thread_seq` when present. Render no explanatory feature copy; use
existing pending state for `async_pending`, stop typing indicators for
`waiting`, and silently ignore `suppressed`.

- [ ] **Step 5: Run phase verification**

Run: `pytest tests/test_group_thread_events.py tests/test_group_dialogue_pulse.py tests/test_api_models.py -v && cd web && npm test -- --run && npm run build`

Expected: PASS.

