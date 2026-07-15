# Graytide Event-Sourced Reliability Design

## Status

Approved on 2026-07-15. The selected approach is a backward-compatible
event-sourced rewrite for the runtime domains exposed by the Graytide report.

## Objective

Make generated facts, group dialogue, story progress, event effects, knowledge
context, and scheduled triggers explainable and replayable without destroying
existing Memoria data or requiring existing clients to upgrade atomically.

The event ledger is authoritative for new mutations in these domains. Existing
tables remain as synchronous read-model projections while clients migrate.

## Scope

This design addresses every issue listed in
`docs/graytide-implementation-report.md`:

1. Canonical story completion state.
2. Explicit case knowledge in single-character dialogue.
3. Non-destructive `trigger_dialogue` behavior.
4. Verification gates before generated facts become durable memories.
5. One shared claim instead of per-character fan-out.
6. Proactive group dialogue addressed by logical thread.
7. Structured outcomes for empty group responses.
8. Source turn IDs and causal duplicate suppression.
9. Monotonic ordering inside logical group threads.
10. Structured claim correction, retraction, and supersession.
11. Consistent ownership and logging for `time_based` triggers.

It does not convert authentication, character-card administration, or document
storage to event sourcing.

## Architecture

### Event Ledger

Add an append-only `domain_event` table:

| Field | Purpose |
| --- | --- |
| `sequence` | Global monotonically increasing storage cursor |
| `event_id` | Stable UUID used for idempotency and causation |
| `owner_user_id` | Tenant boundary |
| `aggregate_type` | `fact_claim`, `story`, `group_thread`, `event_execution`, or `session_context` |
| `aggregate_id` | Stable domain identity |
| `aggregate_version` | Optimistic-concurrency version within the aggregate |
| `event_type` | Versioned semantic event name |
| `payload` | JSON event data |
| `metadata` | Producer, schema version, and legacy-backfill markers |
| `correlation_id` | End-to-end request or story flow |
| `causation_id` | Event or message that directly caused this event |
| `session_id` | Physical dialogue carrier, when applicable |
| `group_thread_id` | Logical group conversation, when applicable |
| `source_turn_id` | Player/event/autonomous turn that caused output |
| `source_message_id` | Existing message compatibility reference |
| `world_occurred_at` | In-world ordering evidence |
| `recorded_at` | Database commit time |

`UNIQUE(owner_user_id, aggregate_type, aggregate_id, aggregate_version)` prevents
concurrent writers from creating two versions. `event_id` is globally unique.
All event appends and projection updates occur in one database transaction.

### Projection Model

Synchronous projectors update:

- `fact_claim`: active claim state and provenance.
- `story_state`: canonical story status and progress.
- `group_dialogue_turn`: turn outcome and causal origin.
- `short_term_message.thread_seq` and `short_term_message.source_turn_id`.
- `session_story_context`: explicit case/story access for a session.
- Existing `long_term_fact`, `event_context_state`, and inbox/message tables as
  compatibility projections where required.

`projection_checkpoint` records the highest ledger sequence applied by each
rebuildable projector. Runtime writes project synchronously; replay tools can
truncate only the new projection tables and rebuild them from the ledger.

### Event Envelope API

Introduce focused repository APIs instead of letting callers compose SQL:

```python
@dataclass(frozen=True)
class NewDomainEvent:
    owner_user_id: str
    aggregate_type: str
    aggregate_id: str
    event_type: str
    payload: dict[str, Any]
    correlation_id: str | None = None
    causation_id: str | None = None
    session_id: str | None = None
    group_thread_id: str | None = None
    source_turn_id: str | None = None
    source_message_id: int | None = None
    world_occurred_at: str | None = None
    event_id: str | None = None


def append_domain_events(
    conn,
    events: list[NewDomainEvent],
    *,
    expected_versions: dict[tuple[str, str, str], int] | None = None,
) -> list[StoredDomainEvent]:
    ...
```

Callers with an existing transaction pass its connection. Public convenience
wrappers open a transaction for isolated operations.

## Fact Governance

### Claim Lifecycle

Facts are immutable claims with a mutable projection status:

- `candidate`: generated or legacy content without sufficient evidence.
- `verified`: allowed into durable prompts and memory retrieval.
- `retracted`: explicitly withdrawn; never retrieved.
- `superseded`: replaced by a newer claim; never retrieved.

Events:

- `fact.claimed.v1`
- `fact.verified.v1`
- `fact.retracted.v1`
- `fact.superseded.v1`

Every claim records:

- Scope: `character`, `group_thread`, or `story`.
- Normalized text and a stable content hash.
- Source kind: `player_message`, `knowledge_chunk`, `authored_event`,
  `model_inference`, or `legacy`.
- Source IDs, evidence snippets/hashes, and origin character.
- Optional `supersedes_claim_id`.

### Verification Rules

The model may propose claims but may not mark them verified.

A claim is verified only when one of these deterministic rules succeeds:

1. The fact was authored in an enabled event effect.
2. The normalized fact is directly supported by a cited knowledge chunk.
3. The normalized fact is directly supported by the player's source message.
4. An administrator explicitly verifies it.

Unsupported model inference remains `candidate`. High-risk assertions about
identity, signatures, culpability, or definitive agency require two distinct
evidence source IDs.

### Shared Facts

Group extraction writes one `group_thread` or `story` claim. Retrieval composes
verified claims visible to the current character and context. It never copies a
shared claim into every participant's character scope.

Legacy `long_term_fact` rows are preserved. A one-time idempotent backfill emits
`fact.claimed.v1` with source kind `legacy` and status `candidate`; no existing
row is deleted.

## Story State

`story_state` is the canonical projection:

```text
owner_user_id, story_id, status, progress, version,
started_at, completed_at, failed_at, updated_at, last_event_id
```

Events:

- `story.started.v1`
- `story.progressed.v1`
- `story.completed.v1`
- `story.failed.v1`

Progress is clamped to `[0, 1]`. `completed` forces progress to `1`. Terminal
states reject later progress unless an explicit `story.reopened.v1` event is
added in a future change.

Existing `UPDATE_EVENT_PROGRESS` effects continue updating event-local state.
When an event belongs to a story, the same transaction appends the corresponding
story event. Graytide's final conclusion event completes `graytide`.

A read-only API exposes `GET /stories/{story_id}/state`.

## Group Dialogue Timeline

### Turn Causality

Every input creates a `group_dialogue_turn`:

- `turn_id`: client `request_id` when available, otherwise a UUID.
- `source_kind`: `player`, `event`, or `autonomous`.
- `source_message_id`: player or triggering NPC message.
- `status`: `open`, `responded`, `waiting`, `suppressed`, or `async_pending`.
- `reason`: structured stop reason.

Events:

- `group.turn.started.v1`
- `group.message.posted.v1`
- `group.turn.outcome.v1`

Every assistant message stores `source_turn_id`.

### Logical Ordering

Each logical group thread owns a monotonic `thread_seq`. The sequence is
allocated atomically in the same transaction that appends
`group.message.posted.v1`. History and pagination order by `thread_seq`, then by
message ID only as a legacy tie-breaker.

Existing messages are backfilled deterministically by current message ID within
each logical thread. Their original timestamps remain unchanged.

### Empty Response Contract

`MultiDialogueGroupResponse.responses` remains unchanged. Add optional fields:

```text
turn_id
outcome: responded | waiting | suppressed | async_pending
reason
latest_thread_seq
poll_after_ms
```

Existing clients continue seeing `responses=[]`. Updated clients can distinguish
intentional waiting, duplicate suppression, and delayed autonomous output.

### Duplicate Suppression

Duplicate checks operate across the logical thread and use:

1. Same `source_turn_id`.
2. Same reply target.
3. Same speaker and normalized semantic text.

A suppressed response emits `group.turn.outcome.v1`; it does not silently
disappear.

## Event Runtime

### Dialogue Effects

`TRIGGER_DIALOGUE` gains:

```text
dialogue_mode: append | replace | notification
```

The default is `append`. `append` merges authored event text after the complete
base response, `replace` preserves explicit forced dialogue, and `notification`
creates an inbox/UI notification without changing character speech.

Each applied effect emits `runtime.effect.applied.v1` with the selected mode.

### Proactive Group Dialogue

`NPC_PROACTIVE_DIALOGUE` gains `target_group_thread_id`. Runtime resolution:

1. Resolve the logical thread and verify tenant ownership.
2. Reuse its active physical session when one exists.
3. Otherwise create a continuation carrier with the thread's participants and
   locale.
4. Run through `GroupDialogueRuntime`.
5. Record event execution as correlation and causation metadata.

`target_session_id` remains a compatibility fallback and is translated to its
logical thread.

### Explicit Story Knowledge

Knowledge binding adds `target_type="story"`. Session-start requests accept an
optional `story_id`. Validated associations are projected to
`session_story_context`.

Single and group retrieval receive the session's explicit story IDs. A knowledge
base is visible when bound globally, to the current character, to the current
group thread, or to an attached story. Group-thread knowledge is never exposed
to unrelated single-character sessions.

### Trigger Ownership

Define a routing function:

```python
def trigger_execution_owner(condition: TriggerCondition) -> Literal[
    "dialogue", "scheduler", "unsupported"
]:
    ...
```

- `TIME_BASED` with `duration_minutes` belongs to dialogue detection.
- `TIME_BASED` with only `schedule` belongs to the scheduler.
- Cron-owned conditions return false from dialogue detection with a debug
  delegation log, not an unsupported warning.
- Validation rejects ambiguous time conditions that provide neither field.

Tests provide a trigger-type/entry-point matrix for dialogue and scheduler
execution.

## Compatibility and Migration

- Schema changes are additive.
- Existing API fields retain names and types.
- New API request/response fields are optional.
- Existing event JSON remains valid.
- Existing physical group session IDs continue resolving.
- Existing data is never deleted during initialization or backfill.
- Backfills are idempotent and identified by a migration key.
- SQLite and PostgreSQL paths receive equivalent schema and transaction tests.

## Delivery Boundaries

The implementation is split into three independently testable plans:

1. Event ledger, fact claims, and story state.
2. Group turn causality, thread ordering, and response outcomes.
3. Event effects, proactive logical threads, story knowledge, and trigger
   routing.

Each plan uses red-green-refactor cycles. No production behavior is added before
its regression test has failed for the expected reason.

## Acceptance Criteria

- Every Graytide report issue has a direct regression test.
- New fact, story, group, and runtime mutations append ledger events.
- Rebuilding new projections from the ledger produces equivalent read models.
- Generated unsupported facts cannot enter durable retrieval.
- Shared group facts produce one claim.
- Group history is monotonic across continued physical sessions.
- Empty group responses have a structured outcome.
- Proactive events survive ended physical sessions.
- Story completion is queryable without parsing dialogue.
- Schedule-only `time_based` conditions produce delegation logs, not unsupported
  warnings.
- Full backend tests and frontend build pass without modifying existing Graytide
  data.
