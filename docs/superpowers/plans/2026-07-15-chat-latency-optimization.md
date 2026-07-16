# Chat Latency Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce perceived and tail latency for single and group dialogue by streaming real model output, moving checkpoint memory extraction off the request path, reusing per-turn context, and exposing actionable latency metrics.

**Architecture:** Existing synchronous dialogue endpoints remain compatible. New SSE endpoints bridge the synchronous orchestrators into async FastAPI responses through a thread-safe queue; the LLM client streams structured JSON and incrementally emits only the `dialogue` string while still collecting and validating the final JSON. Checkpoint memory extraction is persisted as leased database jobs and processed by an application-lifespan worker so committed turns return immediately without losing work on restart.

**Tech Stack:** Python 3.10, FastAPI/Starlette `StreamingResponse`, OpenAI-compatible Python client, SQLite, pytest, React 18, Vite, browser Fetch streams, Node test runner.

---

### Task 1: Performance Metric Primitives

**Files:**
- Modify: `src/memoria/core/performance.py`
- Modify: `src/memoria/api/developer.py`
- Test: `tests/test_developer_experience.py`

- [ ] **Step 1: Write failing tests for distributions, counters, and observations**

```python
def test_performance_snapshot_separates_metric_kinds():
    performance.record("dialogue.turn.total", 12.0)
    performance.increment("llm.retry")
    performance.observe("llm.prompt_chars", 450)

    snapshot = performance.snapshot()

    assert snapshot["durations"]["dialogue.turn.total"]["p95_ms"] == 12.0
    assert snapshot["counters"]["llm.retry"] == 1
    assert snapshot["observations"]["llm.prompt_chars"]["max"] == 450
```

- [ ] **Step 2: Verify the tests fail because `increment` and `observe` do not exist**

Run:

```bash
PYTHONPATH=src /home/nanzi/PY3/Memoria/.venv/bin/pytest \
  tests/test_developer_experience.py -q
```

Expected: FAIL on missing metric APIs or the old flat snapshot shape.

- [ ] **Step 3: Implement bounded samples and counters**

Add:

```python
def increment(metric: str, amount: int = 1) -> None: ...
def observe(metric: str, value: float) -> None: ...
def sample_window() -> int: ...
```

Return `durations`, `counters`, and `observations` from `snapshot()`. Keep each duration/observation deque bounded to 200 entries and clear all stores in `reset()`.

- [ ] **Step 4: Expose the real sample-window value from `/developer/performance`**

Return:

```python
{
    "metrics": performance.snapshot(),
    "sample_window": performance.sample_window(),
}
```

- [ ] **Step 5: Run focused tests**

Expected: all developer experience tests pass.

### Task 2: Structured JSON Dialogue Streaming

**Files:**
- Modify: `src/memoria/core/llm_client.py`
- Test: `tests/test_llm_streaming.py`
- Test: `tests/test_memory_extractor.py`

- [ ] **Step 1: Write failing tests for incremental dialogue extraction**

Cover chunks split:

```python
[
    '{"action":"wave","dialogue":"你',
    '好，\\n旅',
    '行者","mood":"warm"}',
]
```

Assert emitted deltas reconstruct `你好，\n旅行者`, escaped quotes/backslashes are decoded once, fields before and after `dialogue` are ignored, and incomplete chunks emit only complete decoded characters.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=src /home/nanzi/PY3/Memoria/.venv/bin/pytest \
  tests/test_llm_streaming.py -q
```

Expected: FAIL because the incremental parser is missing.

- [ ] **Step 3: Implement a focused parser**

Add an internal stateful class with this interface:

```python
class _DialogueJsonStream:
    def feed(self, text: str) -> list[str]: ...
```

It must locate the JSON key `"dialogue"`, enter its string value after `:`, decode valid JSON escapes incrementally, retain incomplete escape sequences between calls, and stop at the unescaped closing quote.

- [ ] **Step 4: Add optional streaming to `call_role_turn`**

Use:

```python
def call_role_turn(
    system_prompt: str,
    history: list[dict],
    model: str | None = None,
    debug: bool = False,
    debug_sink: DebugSink | None = None,
    on_dialogue_delta: Callable[[str], None] | None = None,
) -> dict:
```

When the callback is absent, preserve the existing non-stream request exactly. When present, call the provider with `stream=True`, concatenate `choice.delta.content`, feed chunks into `_DialogueJsonStream`, emit non-empty deltas, and run the existing final parse/repair/plain-text fallback against the concatenated response.

- [ ] **Step 5: Add instrumentation**

Record:

```text
llm.retry
llm.json_repair
llm.response_format_fallback
llm.role_turn.ttft
llm.prompt_chars
llm.output_chars
```

TTFT starts immediately before the provider call and records only when the first dialogue delta is emitted.

- [ ] **Step 6: Verify focused and compatibility tests**

Run:

```bash
PYTHONPATH=src /home/nanzi/PY3/Memoria/.venv/bin/pytest \
  tests/test_llm_streaming.py tests/test_memory_extractor.py \
  tests/test_security_fixes.py -q
```

Expected: PASS.

### Task 3: Core Event Propagation and Stage Timing

**Files:**
- Modify: `src/memoria/core/orchestrator.py`
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_multi_dialogue_api.py`

- [ ] **Step 1: Write failing tests for event callbacks**

Single chat must emit `stage` updates and `dialogue_delta` before the function returns. Group chat must emit stable `character_started`, per-character deltas, and `character_completed` in generation order.

- [ ] **Step 2: Verify RED**

Expected: callback keyword arguments are rejected by current functions.

- [ ] **Step 3: Add optional event sinks without changing return values**

Use a simple callable:

```python
EventSink = Callable[[str, dict], None]
```

Add `event_sink: EventSink | None = None` to `run_dialogue_turn()` and `process_player_message()`, then propagate through `_generate_group_discussion()`, `run_dialogue_pulse()`, and `_generate_character_response()`.

Before each role call, emit `character_started`. Pass a callback to `call_role_turn()` that emits:

```python
event_sink("dialogue_delta", {"stream_id": stream_id, "delta": delta})
```

After the authoritative response is assembled, emit `character_completed` with the final response payload.

- [ ] **Step 4: Measure request stages**

Add bounded measurements for:

```text
dialogue.turn.total
dialogue.turn.prepare
dialogue.turn.retrieval
dialogue.turn.prompt
dialogue.turn.events
dialogue.turn.commit
multi_dialogue.turn.total
multi_dialogue.character.generate
```

- [ ] **Step 5: Run orchestrator tests**

Expected: existing return contracts and new event ordering tests pass.

### Task 4: Backend SSE Endpoints

**Files:**
- Create: `src/memoria/api/streaming.py`
- Modify: `src/memoria/api/dialogue.py`
- Modify: `src/memoria/api/multi_dialogue.py`
- Test: `tests/test_dialogue_api.py`
- Test: `tests/test_multi_dialogue_api.py`

- [ ] **Step 1: Write failing API tests**

POST to:

```text
/api/v1/dialogue/turn/stream
/api/v1/multi-dialogue/turn/stream
```

Assert `content-type` starts with `text/event-stream`, each frame has `event:` and JSON `data:`, and the final event is `turn_completed`. Assert worker exceptions produce an `error` event rather than a truncated response.

- [ ] **Step 2: Verify RED**

Expected: both routes return 404.

- [ ] **Step 3: Implement the sync-to-async SSE bridge**

Create a helper that:

1. Captures the running event loop.
2. Runs the synchronous turn function through `asyncio.to_thread`.
3. Lets the worker thread enqueue events with `loop.call_soon_threadsafe(queue.put_nowait, event)`.
4. Serializes each event as:

```text
event: dialogue_delta
data: {"stream_id":"...","delta":"..."}

```

5. Always sends one terminal `turn_completed` or `error` event and stops the generator.

- [ ] **Step 4: Preserve authentication, ownership, idempotency, and request models**

Reuse the same request models and authorization dependencies as the existing synchronous endpoints. Do not create a second business-logic implementation.

- [ ] **Step 5: Run focused API tests**

Expected: existing synchronous tests and new stream tests pass.

### Task 5: Frontend SSE Client and Stream State

**Files:**
- Modify: `web/src/api/memoria.js`
- Create: `web/src/utils/dialogueStreamState.js`
- Test: `web/tests/memoriaApi.test.js`
- Create: `web/tests/dialogueStreamState.test.js`

- [ ] **Step 1: Write failing Node tests**

Test an SSE response split across arbitrary byte boundaries, multi-line `data:`, UTF-8 Chinese characters split across chunks, server `error` events, and a final frame without an extra network chunk.

Test stream-state operations:

```javascript
startCharacter(state, event)
appendDialogueDelta(state, event)
completeCharacter(state, event)
reconcileTurn(state, finalResponse)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
cd web && npm test
```

Expected: imports or new methods are missing.

- [ ] **Step 3: Implement reusable SSE Fetch parsing**

Add a streaming request helper using `response.body.getReader()` and `TextDecoder('utf-8')`. It must preserve decoder state with `{ stream: true }`, split complete SSE frames on blank lines, parse JSON data, dispatch `{ type, data }`, and throw the same normalized API errors used by `request()`.

- [ ] **Step 4: Add API methods**

Add:

```javascript
dialogue.streamMessage(sessionId, playerMessage, requestId, onEvent, options)
multiDialogue.streamDiscussMessage(
  sessionId, playerMessage, maxResponses, requestId, onEvent, options
)
```

Keep `sendMessage()` and `discussMessage()` unchanged as fallbacks.

- [ ] **Step 5: Implement immutable placeholder/reconciliation helpers**

Temporary messages are keyed by `stream_id`. `dialogue_delta` appends text, `character_completed` replaces provisional metadata, and `turn_completed` reconciles placeholders with persisted IDs while removing duplicates.

- [ ] **Step 6: Run Node tests**

Expected: all frontend unit tests pass.

### Task 6: ChatRoom Incremental Rendering

**Files:**
- Modify: `web/src/pages/ChatRoom.jsx`
- Test: `web/tests/dialogueStreamState.test.js`

- [ ] **Step 1: Add a failing reducer-level workflow test**

Simulate two group characters where the first completes while the second is still streaming. Assert the first response remains visible and stable while deltas continue for the second.

- [ ] **Step 2: Verify RED**

Expected: current state utilities cannot represent the workflow.

- [ ] **Step 3: Wire single and group sends to streaming APIs**

On `character_started`, insert a temporary assistant message. On `dialogue_delta`, append to only that `stream_id`. On `character_completed`, preserve visible text and attach final character metadata. On `turn_completed`, replace provisional messages with the authoritative persisted response and update relationships/events/world-clock state using the existing completion path.

- [ ] **Step 4: Handle cancellation and errors**

Use the existing request abort/timeout conventions. Remove incomplete placeholders on error, restore the draft/send state, and fall back to the synchronous endpoint only when streaming is unavailable before any dialogue delta was received.

- [ ] **Step 5: Keep TTS persistence-safe**

Do not start TTS from deltas. Trigger existing autoplay only after reconciliation provides stable persisted message IDs.

- [ ] **Step 6: Run frontend tests and build**

Run:

```bash
cd web && npm test && npm run build
```

Expected: PASS.

### Task 7: Durable Checkpoint Memory Jobs

**Files:**
- Modify: `src/memoria/db/repository.py`
- Create: `src/memoria/core/background_jobs.py`
- Modify: `src/memoria/core/orchestrator.py`
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Modify: `src/memoria/main.py`
- Test: `tests/test_repository.py`
- Create: `tests/test_background_jobs.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write failing repository lifecycle tests**

Cover enqueue deduplication, claim lease, expired-lease reclaim, complete, retry with future `available_at`, and terminal failure after the configured attempt count.

- [ ] **Step 2: Verify RED**

Expected: background-job repository operations do not exist.

- [ ] **Step 3: Add schema and atomic operations**

Add `background_job` with:

```text
job_id, job_type, dedupe_key UNIQUE, payload, status, attempts,
available_at, lease_owner, lease_expires_at, last_error,
created_at, updated_at, completed_at
```

Claim inside `BEGIN IMMEDIATE`; select one pending/retry/expired-running job whose `available_at` is due, update its lease and attempts, then commit.

- [ ] **Step 4: Write failing worker tests**

Given a checkpoint payload containing an immutable history snapshot, assert the worker calls `extract_player_memory()`, records generated claims, completes success, and retries transient exceptions without losing the payload.

- [ ] **Step 5: Implement the worker**

Support job types:

```text
single_checkpoint_memory
group_checkpoint_memory
```

Expose a stoppable loop callable from a daemon thread. Poll with a bounded wait, lease jobs, process snapshots, and record errors through repository retry/fail operations.

- [ ] **Step 6: Replace synchronous checkpoint extraction**

After the dialogue transaction commits, enqueue a deduplicated job using session/thread plus checkpoint turn number as the dedupe key. The payload must include the exact history snapshot and IDs needed by extraction and claim recording.

- [ ] **Step 7: Start and stop the worker in FastAPI lifespan**

Initialize after `repository.init_db()`, signal shutdown in `finally`, join with a timeout, and log if it does not stop.

- [ ] **Step 8: Verify repository, worker, and orchestrator tests**

Expected: checkpoint turns return without invoking the light model synchronously, and durable jobs survive a new worker instance.

### Task 8: Group Per-Turn Shared Context

**Files:**
- Modify: `src/memoria/core/multi_character_orchestrator.py`
- Modify: `src/memoria/core/knowledge_retriever.py`
- Test: `tests/test_orchestrator.py`
- Test: `tests/test_multi_dialogue_api.py`

- [ ] **Step 1: Write failing call-count tests**

For one player message producing multiple sequential character responses, assert relationship graph, group thread ID, base DB history, player character, and authorized knowledge-base IDs are each loaded no more than once per applicable scope.

- [ ] **Step 2: Verify RED**

Expected: existing implementation repeats repository calls.

- [ ] **Step 3: Introduce an internal per-turn context**

Build one internal context object at the start of `process_player_message()` containing shared relationships, group thread, player character, base history, and per-character authorized knowledge-base IDs.

- [ ] **Step 4: Reuse staged history**

When `persist_messages=False`, load base DB history once and append staged player/assistant messages locally for each sequential generation step. Preserve ordering and continuity without re-querying unchanged history.

- [ ] **Step 5: Reuse knowledge authorization**

Pass `preauthorized_knowledge_base_ids` into `retrieve_knowledge()` for each character so retrieval does not repeat authorization queries.

- [ ] **Step 6: Verify call-count and behavior tests**

Expected: identical response ordering and persistence with reduced repository-call counts.

### Task 9: Low-Risk Runtime Limits

**Files:**
- Modify: `src/memoria/core/config.py`
- Modify: `src/memoria/core/llm_client.py`
- Modify: `src/memoria/core/orchestrator.py`
- Modify: `config/settings.yaml`
- Test: `tests/test_core.py`
- Test: `tests/test_security_fixes.py`

- [ ] **Step 1: Write failing config tests**

Assert explicit positive values for:

```text
llm_timeout_seconds
light_task_max_output_tokens
max_output_tokens
knowledge_top_k
knowledge_max_chars
short_term_memory_turns
```

Assert invalid zero/negative values produce configuration warnings.

- [ ] **Step 2: Verify RED**

Expected: new settings are absent or hardcoded.

- [ ] **Step 3: Apply conservative defaults**

Use main output limit `400`, light-task output limit `400`, knowledge top-k `4`, injected knowledge chars `4000`, and an explicit chat timeout. Replace the hardcoded single-chat history window with `configs.short_term_memory_turns`.

- [ ] **Step 4: Pass timeout and limits into clients**

Configure both main and light OpenAI-compatible clients with the explicit timeout and replace the hardcoded light-task `max_tokens=800`.

- [ ] **Step 5: Verify focused tests**

Expected: PASS with no change to public API schemas.

### Task 10: End-to-End Verification

**Files:**
- Update only tests or implementation files needed to fix discovered regressions.

- [ ] **Step 1: Run all relevant backend modules**

```bash
PYTHONPATH=src /home/nanzi/PY3/Memoria/.venv/bin/pytest \
  tests/test_llm_streaming.py \
  tests/test_background_jobs.py \
  tests/test_developer_experience.py \
  tests/test_dialogue_api.py \
  tests/test_multi_dialogue_api.py \
  tests/test_orchestrator.py \
  tests/test_repository.py -q
```

- [ ] **Step 2: Run the full backend suite**

```bash
PYTHONPATH=src /home/nanzi/PY3/Memoria/.venv/bin/pytest -q
```

Document the pre-existing missing `examples/graytide/manifest.json` baseline if it remains the only failure.

- [ ] **Step 3: Run frontend verification**

```bash
cd web
npm test
npm run build
```

- [ ] **Step 4: Start the application and exercise both SSE routes**

Verify event ordering, true incremental deltas, terminal completion, stable persisted IDs, group first-character visibility before later characters complete, and `/api/v1/developer/performance` metrics.

- [ ] **Step 5: Confirm branch isolation**

```bash
git -C /home/nanzi/PY3/Memoria status --short --branch
git -C /tmp/memoria-chat-latency status --short --branch
git worktree list
```

The original checkout must remain on `main`; all source changes must exist only on `feat/chat-latency-optimization`.
