# Graytide Event Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the authoritative domain-event ledger plus replayable fact-claim and story-state projections.

**Architecture:** New runtime mutations append immutable events and synchronously update projection tables in the same repository transaction. Existing memory and event-progress tables remain compatibility read models; legacy rows are preserved and backfilled as unverified events.

**Tech Stack:** Python 3.10+, FastAPI, Pydantic v2, SQLite/PostgreSQL repository layer, pytest

---

## File Map

- Create `src/memoria/core/domain_events.py`: typed event envelopes and validation.
- Create `src/memoria/core/fact_claims.py`: deterministic claim verification policy.
- Create `src/memoria/api/story.py`: story-state read API.
- Create `tests/test_domain_events.py`: ledger concurrency, idempotency, and replay.
- Create `tests/test_fact_claims.py`: candidate/verified/retracted behavior and no fan-out.
- Create `tests/test_story_state.py`: story lifecycle and API.
- Modify `src/memoria/db/repository.py`: additive schema, append API, projectors, and backfill.
- Modify `src/memoria/core/memory_extractor.py`: emit candidate claims instead of direct durable facts.
- Modify `src/memoria/core/multi_character_memory.py`: emit one shared claim.
- Modify `src/memoria/core/event_executor.py`: authored memory and story events.
- Modify `src/memoria/core/event_schema.py`: story effect metadata.
- Modify `src/memoria/main.py`: story router.

### Task 1: Typed Event Envelope

**Files:**
- Create: `src/memoria/core/domain_events.py`
- Test: `tests/test_domain_events.py`

- [ ] **Step 1: Write the failing envelope validation test**

```python
def test_new_domain_event_rejects_blank_identity():
    from pydantic import ValidationError
    from memoria.core.domain_events import NewDomainEvent

    with pytest.raises(ValidationError):
        NewDomainEvent(
            owner_user_id="user-1",
            aggregate_type="story",
            aggregate_id="",
            event_type="story.started.v1",
            payload={},
        )
```

- [ ] **Step 2: Run the test and verify RED**

Run: `pytest tests/test_domain_events.py::test_new_domain_event_rejects_blank_identity -v`

Expected: FAIL because `memoria.core.domain_events` does not exist.

- [ ] **Step 3: Implement the event models**

Define `NewDomainEvent` and `StoredDomainEvent` as frozen Pydantic models. Strip
and validate identity fields, default `event_id` to `uuid.uuid4().hex`, and keep
payload/metadata JSON-compatible dictionaries.

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `pytest tests/test_domain_events.py -v`

Expected: PASS.

### Task 2: Append-Only Ledger Schema and Concurrency

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_domain_events.py`

- [ ] **Step 1: Add failing append/idempotency tests**

```python
def test_append_domain_event_assigns_aggregate_versions(test_user):
    first = repository.append_domain_event(_story_event(test_user, "started"))
    second = repository.append_domain_event(_story_event(test_user, "progressed"))
    assert first.aggregate_version == 1
    assert second.aggregate_version == 2


def test_append_domain_event_is_idempotent_by_event_id(test_user):
    event = _story_event(test_user, "started", event_id="stable-event")
    first = repository.append_domain_event(event)
    second = repository.append_domain_event(event)
    assert second.sequence == first.sequence
    assert repository.list_domain_events(test_user, "story", "graytide") == [first]
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_domain_events.py -v`

Expected: FAIL because ledger repository functions and schema do not exist.

- [ ] **Step 3: Add additive schema**

Add `domain_event`, `projection_checkpoint`, and `data_migration` tables plus
indexes for aggregate order, correlation, source turn, and logical group thread.
Use existing repository SQL adaptation helpers so SQLite and PostgreSQL share the
same public API.

- [ ] **Step 4: Implement append/read APIs**

Implement `append_domain_events`, `append_domain_event`, `list_domain_events`,
and `get_domain_event`. Allocate aggregate versions inside the transaction,
return the existing row for duplicate `event_id`, and raise
`DomainEventConcurrencyError` when an expected version differs.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_domain_events.py -v`

Expected: PASS.

### Task 3: Fact Claim Projection

**Files:**
- Create: `src/memoria/core/fact_claims.py`
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_fact_claims.py`

- [ ] **Step 1: Write failing lifecycle tests**

```python
def test_model_inference_stays_candidate(test_user):
    claim = fact_claims.record_claim(
        owner_user_id=test_user,
        scope_type="story",
        scope_id="graytide",
        fact_text="潮声代理在 2003 年使用了印鉴",
        source_kind="model_inference",
    )
    assert claim["status"] == "candidate"
    assert repository.list_verified_fact_claims(test_user, "story", "graytide") == []


def test_retracted_claim_is_removed_from_verified_projection(test_user):
    claim = _record_authored_claim(test_user, "码头封条编号为 GT-7")
    fact_claims.retract_claim(test_user, claim["claim_id"], reason="证据录入错误")
    assert repository.list_verified_fact_claims(test_user, "story", "graytide") == []
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_fact_claims.py -v`

Expected: FAIL because fact-claim APIs do not exist.

- [ ] **Step 3: Add claim schema and projector**

Add `fact_claim` with unique owner/content-hash/scope identity, provenance JSON,
status, source kind, source IDs, supersession link, and ledger version. Project
`fact.claimed.v1`, `fact.verified.v1`, `fact.retracted.v1`, and
`fact.superseded.v1`.

- [ ] **Step 4: Implement deterministic verification**

Implement normalization, content hashing, high-risk term detection, evidence
source counting, and status decisions. Only `authored_event`, direct
player-message support, direct knowledge-chunk support, or admin verification
may emit `fact.verified.v1`.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_fact_claims.py -v`

Expected: PASS.

### Task 4: Replace Generated Long-Term Writes

**Files:**
- Modify: `src/memoria/core/memory_extractor.py`
- Modify: `src/memoria/core/multi_character_memory.py`
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_fact_claims.py`
- Test: `tests/test_memory_extractor.py`

- [ ] **Step 1: Add failing generated-memory tests**

```python
def test_generated_group_fact_is_recorded_once_not_per_character(monkeypatch, group_session):
    _stub_extractor(monkeypatch, ["灯塔记录由潮声代理签署"])
    multi_character_memory.process_dialogue_pulse_memories(
        session_id=group_session,
        recent_messages=[{"role": "assistant", "content": "灯塔记录由潮声代理签署"}],
        character_ids=["a", "b", "c"],
        player_id="user-1",
    )
    claims = repository.list_fact_claims("user-1", "group_thread", "thread-1")
    assert len(claims) == 1
    assert claims[0]["status"] == "candidate"
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_fact_claims.py::test_generated_group_fact_is_recorded_once_not_per_character -v`

Expected: FAIL because current code writes one long-term fact per participant.

- [ ] **Step 3: Route extraction through claims**

Change single-character extraction to character-scoped claims and group
extraction to one logical-thread/story claim. Keep relationship-state updates
unchanged. Stop calling `save_long_term_fact` for unsupported generated facts.

- [ ] **Step 4: Compose verified claims during memory retrieval**

Merge verified character, group-thread, and story claims into prompt memory.
Exclude candidate/retracted/superseded claims. Preserve existing manually saved
facts as a compatibility source until the legacy backfill marker exists.

- [ ] **Step 5: Run focused suites**

Run: `pytest tests/test_fact_claims.py tests/test_memory_extractor.py -v`

Expected: PASS.

### Task 5: Legacy Backfill Without Data Loss

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_domain_events.py`

- [ ] **Step 1: Write failing idempotent backfill test**

Create two legacy `long_term_fact` rows, run
`backfill_legacy_long_term_fact_events()` twice, and assert there are exactly two
`fact.claimed.v1` events, both `candidate`, while both legacy rows still exist.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_domain_events.py::test_legacy_fact_backfill_is_idempotent_and_non_destructive -v`

Expected: FAIL because the backfill does not exist.

- [ ] **Step 3: Implement the migration**

Use `data_migration.migration_key =
'2026-07-15-long-term-fact-event-backfill'`. Emit deterministic event IDs from
the legacy row ID and mark metadata with `legacy_backfill=true`. Never update or
delete the source rows.

- [ ] **Step 4: Run and verify GREEN**

Run: `pytest tests/test_domain_events.py -v`

Expected: PASS.

### Task 6: Canonical Story State

**Files:**
- Modify: `src/memoria/db/repository.py`
- Create: `src/memoria/api/story.py`
- Modify: `src/memoria/main.py`
- Test: `tests/test_story_state.py`

- [ ] **Step 1: Write failing lifecycle and API tests**

```python
def test_story_completion_is_queryable_without_dialogue(test_user, client):
    repository.append_story_event(test_user, "graytide", "story.started.v1", {})
    repository.append_story_event(
        test_user, "graytide", "story.completed.v1", {"reason": "final_conclusion"}
    )
    response = client.get("/stories/graytide/state", headers=_auth(test_user))
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["progress"] == 1.0
```

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_story_state.py -v`

Expected: FAIL because story projection and router do not exist.

- [ ] **Step 3: Add story projector and transition rules**

Add `story_state`; project started, progressed, completed, and failed events.
Clamp progress and reject progress events after terminal state.

- [ ] **Step 4: Add read API**

Implement authenticated `GET /stories/{story_id}/state`; return 404 when no
story aggregate exists and enforce `owner_user_id`.

- [ ] **Step 5: Run and verify GREEN**

Run: `pytest tests/test_story_state.py -v`

Expected: PASS.

### Task 7: Event-Authored Facts and Story Progress

**Files:**
- Modify: `src/memoria/core/event_schema.py`
- Modify: `src/memoria/core/event_executor.py`
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_events.py`
- Test: `tests/test_story_state.py`

- [ ] **Step 1: Write failing atomic projection test**

Build an event with `ADD_MEMORY`, `story_id="graytide"`, and
`UPDATE_EVENT_PROGRESS(event_status="completed")`. Assert one verified
`authored_event` claim and a completed story projection are committed with the
same event-execution correlation ID.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_story_state.py::test_event_effects_project_fact_and_story_atomically -v`

Expected: FAIL because event commits do not append domain events.

- [ ] **Step 3: Extend schemas and operation planning**

Add optional `story_id` to `EventDefinition` and claim/story event operations to
the executor plan. Build domain events without committing them during planning.

- [ ] **Step 4: Commit ledger and projections atomically**

Extend `commit_event_execution_batch` so event-trigger logs, authored facts,
story state, and ledger records share one transaction. Roll back all projections
if any effect fails.

- [ ] **Step 5: Run focused suites**

Run: `pytest tests/test_events.py tests/test_story_state.py tests/test_event_e2e.py -v`

Expected: PASS.

### Task 8: Projection Replay

**Files:**
- Modify: `src/memoria/db/repository.py`
- Test: `tests/test_domain_events.py`

- [ ] **Step 1: Write failing replay equivalence test**

Capture fact and story projection rows, clear only those new projection tables,
run `rebuild_domain_projections(owner_user_id)`, and assert normalized rows equal
the captured rows.

- [ ] **Step 2: Run and verify RED**

Run: `pytest tests/test_domain_events.py::test_replay_rebuilds_fact_and_story_projections -v`

Expected: FAIL because replay does not exist.

- [ ] **Step 3: Implement deterministic replay**

Read ledger events by global sequence, dispatch pure projector functions, and
advance per-projector checkpoints. Reject unknown major event versions with a
clear exception.

- [ ] **Step 4: Run phase verification**

Run: `pytest tests/test_domain_events.py tests/test_fact_claims.py tests/test_story_state.py tests/test_memory_extractor.py tests/test_events.py -v`

Expected: PASS.

