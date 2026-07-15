# Graytide Runtime Projections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Project event effects, proactive logical-thread dialogue, explicit story knowledge, and trigger ownership from the domain ledger.

**Architecture:** Event execution planning remains pure. The transaction appends runtime domain events and applies dialogue, story, knowledge, and group-thread projections atomically. Existing event JSON and session-based callers remain valid.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, repository transactions, pytest

---

## File Map

- Create `src/memoria/core/trigger_routing.py`: trigger-owner matrix.
- Create `tests/test_runtime_projections.py`: dialogue effects and proactive thread execution.
- Modify `src/memoria/core/event_schema.py`: dialogue mode, story ID, logical thread target.
- Modify `src/memoria/core/event_executor.py`: event operations instead of direct session orchestration.
- Modify `src/memoria/core/event_runtime.py`: event-ledger commit and group runtime dispatch.
- Modify `src/memoria/core/group_dialogue_runtime.py`: ensure active carrier for logical thread.
- Modify `src/memoria/core/orchestrator.py`: dialogue-effect composition.
- Modify `src/memoria/core/knowledge_retriever.py`: story bindings.
- Modify `src/memoria/db/repository.py`: session-story context and binding queries.
- Modify `src/memoria/api/dialogue.py` and `src/memoria/api/multi_dialogue.py`: optional story context.
- Modify Graytide event definitions in their current source file.
- Modify `tests/test_knowledge_base.py`, `tests/test_events.py`, and `tests/test_world_clock.py`.

### Task 1: Dialogue Effect Modes

**Files:**
- Modify: `src/memoria/core/event_schema.py`
- Modify: `src/memoria/core/event_executor.py`
- Modify: `src/memoria/core/event_runtime.py`
- Modify: `src/memoria/core/orchestrator.py`
- Test: `tests/test_runtime_projections.py`

- [ ] **Step 1: Write failing composition tests**

Test that `append` preserves the full base reply and appends authored text,
`replace` returns only authored text, and `notification` preserves the base
reply while creating an event notification.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_runtime_projections.py -v`

Expected: FAIL because `dialogue_mode` is absent and current runtime replaces the
base response.

- [ ] **Step 3: Extend effect schema**

Add `dialogue_mode: Literal["append", "replace", "notification"] = "append"`.
Keep existing serialized effects valid through the default.

- [ ] **Step 4: Plan typed dialogue operations**

Replace the bare `dialogue_overrides` queue with ordered operations containing
mode, text, effect index, and event ID. Emit `runtime.effect.applied.v1` payloads
from the same operation data.

- [ ] **Step 5: Compose at runtime**

Apply operations in effect order after base generation. Append with one newline
boundary, replace only when explicit, and convert notification mode to the
existing inbox/notification projection.

- [ ] **Step 6: Run and verify GREEN**

Run: `pytest tests/test_runtime_projections.py tests/test_events.py -v`

Expected: PASS.

### Task 2: Logical-Thread Proactive Dialogue

**Files:**
- Modify: `src/memoria/core/event_schema.py`
- Modify: `src/memoria/core/event_executor.py`
- Modify: `src/memoria/core/event_runtime.py`
- Modify: `src/memoria/core/group_dialogue_runtime.py`
- Test: `tests/test_runtime_projections.py`

- [ ] **Step 1: Write failing ended-session regression test**

Create a logical group thread whose last carrier session is ended. Execute an
`NPC_PROACTIVE_DIALOGUE` effect targeting the logical thread. Assert a new active
carrier is created and its first assistant message has the event execution's
correlation/source turn.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_runtime_projections.py::test_proactive_dialogue_continues_ended_logical_thread -v`

Expected: FAIL with `NPC 主动对白目标不是可用群聊`.

- [ ] **Step 3: Extend schema and planning**

Add optional `target_group_thread_id`. Planning records a proactive-group
operation without constructing `MultiCharacterOrchestrator`.

- [ ] **Step 4: Ensure an active carrier**

Implement `ensure_active_group_thread_session(owner_user_id, group_thread_id)`.
Reuse an active session or create a continuation from the latest participant
set, locale, player name, and group name.

- [ ] **Step 5: Execute through GroupDialogueRuntime**

After the event batch commits, invoke the explicit event pulse with correlation
and causation IDs. Append `group.turn.started.v1` and resulting message/outcome
events. Preserve `target_session_id` by resolving it to its thread first.

- [ ] **Step 6: Run and verify GREEN**

Run: `pytest tests/test_runtime_projections.py tests/test_group_dialogue_pulse.py -v`

Expected: PASS.

### Task 3: Explicit Story Knowledge Context

**Files:**
- Modify: `src/memoria/db/repository.py`
- Modify: `src/memoria/core/knowledge_retriever.py`
- Modify: `src/memoria/core/orchestrator.py`
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Modify: `src/memoria/api/dialogue.py`
- Modify: `src/memoria/api/multi_dialogue.py`
- Test: `tests/test_knowledge_base.py`
- Test: `tests/test_dialogue_api.py`

- [ ] **Step 1: Write failing authorization tests**

Bind a knowledge base to story `graytide`. Assert a single-character session
with `story_id="graytide"` retrieves it, while another session for the same
character without that context does not. Assert unrelated group-thread bindings
remain inaccessible.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_knowledge_base.py tests/test_dialogue_api.py -v`

Expected: FAIL because story bindings and session context do not exist.

- [ ] **Step 3: Add additive context schema**

Add `session_story_context(owner_user_id, session_id, story_id, attached_at,
source_event_id)` and allow `knowledge_binding.target_type="story"`.

- [ ] **Step 4: Extend start requests**

Add optional `story_id` to single and group start requests. Validate story
ownership/existence, append `session.context.attached.v1`, and project the
association.

- [ ] **Step 5: Extend retrieval**

Pass explicit story IDs from session context into `retrieve_knowledge`; update
binding queries to union global, character, group-thread, and story visibility
without broadening any existing scope.

- [ ] **Step 6: Run and verify GREEN**

Run: `pytest tests/test_knowledge_base.py tests/test_dialogue_api.py tests/test_orchestrator.py -v`

Expected: PASS.

### Task 4: Trigger Ownership Matrix

**Files:**
- Create: `src/memoria/core/trigger_routing.py`
- Modify: `src/memoria/core/event_detector.py`
- Modify: `src/memoria/core/event_runtime.py`
- Test: `tests/test_world_clock.py`
- Test: `tests/test_events.py`

- [ ] **Step 1: Write failing routing matrix tests**

Parametrize every `TriggerType` against dialogue and scheduler entry points.
Specifically assert schedule-only `TIME_BASED` is scheduler-owned,
duration-only `TIME_BASED` is dialogue-owned, and schedule-only detection emits
no warning containing `不支持`.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_events.py tests/test_world_clock.py -v`

Expected: FAIL because schedule-only `TIME_BASED` falls through to the
unsupported warning.

- [ ] **Step 3: Implement routing**

Return `dialogue`, `scheduler`, or `unsupported` from one pure function.
Composite conditions remain dialogue-owned while recursively validating their
children.

- [ ] **Step 4: Use routing at both entry points**

Dialogue detection logs scheduler delegation at debug level with event ID and
entry point. Scheduler ignores non-scheduler conditions without warning.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_events.py tests/test_world_clock.py -v`

Expected: PASS.

### Task 5: Graytide Story Projection Configuration

**Files:**
- Modify: the source file located by `codegraph explore "graytide final conclusion event definition"`
- Test: `tests/test_graytide_demo.py`
- Test: `tests/test_story_state.py`

- [ ] **Step 1: Write failing configuration tests**

Assert all Graytide mainline events declare `story_id="graytide"`, the final
conclusion completes the story, and proactive group effects target the logical
thread rather than a stale carrier session.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_graytide_demo.py tests/test_story_state.py -v`

Expected: FAIL because story metadata and logical targets are absent.

- [ ] **Step 3: Update authored definitions**

Add story metadata and explicit dialogue modes. Do not change lore text,
thresholds, or evidence content unrelated to the report.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_graytide_demo.py tests/test_story_state.py -v`

Expected: PASS.

### Task 6: Runtime Projection Replay and Audit

**Files:**
- Modify: `src/memoria/db/repository.py`
- Modify: `src/memoria/core/event_runtime.py`
- Test: `tests/test_runtime_projections.py`
- Test: `tests/test_event_e2e.py`

- [ ] **Step 1: Write failing audit-correlation test**

Execute a Graytide event and assert its trigger, effects, story transition,
authored claims, group turn, and messages can all be queried by one correlation
ID with correct causation links.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_runtime_projections.py::test_event_correlation_reconstructs_runtime_outcome -v`

Expected: FAIL because existing records are not joined by a domain-event
correlation.

- [ ] **Step 3: Add audit query**

Implement `list_domain_events_by_correlation(owner_user_id, correlation_id)` and
ensure every runtime operation carries the execution ID through append and
projection calls.

- [ ] **Step 4: Verify rollback**

Add a failing-effect case and assert no domain event or projection remains when
the event batch transaction rolls back.

- [ ] **Step 5: Run phase verification**

Run: `pytest tests/test_runtime_projections.py tests/test_event_e2e.py tests/test_events.py tests/test_world_clock.py tests/test_knowledge_base.py tests/test_graytide_demo.py -v`

Expected: PASS.

### Task 7: Full Verification and Report Update

**Files:**
- Modify: `docs/graytide-implementation-report.md`

- [ ] **Step 1: Run backend verification**

Run: `source .venv/bin/activate && pytest`

Expected: all tests PASS.

- [ ] **Step 2: Run frontend verification**

Run: `cd web && npm test -- --run && npm run build`

Expected: tests and production build PASS.

- [ ] **Step 3: Run non-destructive data audit**

Record row counts for existing Graytide sessions, messages, events, knowledge
documents, and legacy facts before and after initialization. Assert no count
decreases and no existing content/timestamp changes.

- [ ] **Step 4: Update implementation report**

For each numbered issue, link the implementing test and describe the event,
projection, and compatibility behavior. Keep original observations intact and
add a dated remediation section.

- [ ] **Step 5: Review final diff**

Run: `git diff --check && git status --short`

Expected: no whitespace errors; only intended source, tests, and documentation
are modified. Existing untracked `data/` and Graytide playthrough evidence remain
untouched.
