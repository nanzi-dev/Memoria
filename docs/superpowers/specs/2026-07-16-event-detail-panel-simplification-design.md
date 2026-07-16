# Event Detail Panel Simplification Design

## Goal

Reduce the amount of technical configuration shown in the event archive's
right-hand detail panel while preserving the current layout, event management
actions, and access to the full event editor.

This change applies only to the detail panel on `/events`. The full editor at
`/events/:eventId` remains unchanged and continues to expose every event
setting.

## Chosen Approach

Use a lightly simplified version of the existing detail panel:

- Preserve the current header, overview strip, section order, and visual style.
- Keep information that helps a user identify an event and understand its
  behavior at a glance.
- Remove raw field dumps, internal field labels, repeated values, and empty
  configuration rows.
- Keep all existing edit, enable/disable, delete, refresh, loading, and error
  behavior.

No backend or API changes are required.

## Display Rules

### Header and Overview

Keep:

- Event name and active state.
- Event description.
- Event ID.
- Edit, enable/disable, and delete actions.
- Priority, cumulative trigger count, localized trigger type, and per-turn
  trigger limit.

### Trigger Configuration

Keep:

- The existing natural-language trigger description, limited to two visible
  lines.
- Bound character, with global events labeled as such.
- Exclusive group only when one is configured.
- Post-match processing only when it differs from the normal/default behavior.

Hide:

- The duplicated raw trigger type value.
- The complete `trigger_condition` field table.
- Internal field names such as `trigger_type`, `comparison`, and
  `catch_up_replay_limit`.
- Raw arrays, object serialization, and JSON-like values.
- Rows whose only value is an unset placeholder.

### Time-Based Schedule

For time-based events, keep:

- Next scheduled world time when available.
- Estimated real time when available, or the paused-world-time state when
  scheduling is paused.
- Missed-trigger count only when greater than zero.

Hide:

- Raw schedule expressions.
- World timezone and time-scale diagnostics.
- Empty or not-yet-calculated rows.

### Execution Effects

Keep one compact entry per effect:

- Localized effect name.
- One human-readable action summary:
  - State changes: number of state values adjusted.
  - Content unlock: number of entries unlocked.
  - Dialogue, memory, notification, chained-event, and proactive-dialogue
    effects: a plain-language statement of the action without reproducing the
    configured text or internal target ID.
  - Mood change: target mood when configured.
  - Branch event: number of configured branches.
  - Progress update: whether progress is set directly or adjusted relatively.
- Unknown effect types use the neutral label `其他效果` without dumping their
  properties.

Hide:

- Raw `effect_type` values.
- Generic record-field dumps.
- Internal object keys and serialized arrays or objects.
- Empty effect properties.

Effect order remains unchanged.

### Run Records

Keep:

- Last triggered time when available.
- Last updated time when available.
- Creation time when available.
- Template only when the event uses one.

Do not render rows for missing optional values.

## Behavior and Data Flow

`EventList` continues to load the selected event through the existing detail
API. `EventDetailPanel` receives the same event object and callbacks as before;
only its presentation logic changes.

Loading skeletons, error recovery, selection behavior, and all event actions
remain unchanged. The empty-detail copy will describe the panel as an event
summary rather than promising full technical configuration.

## Testing

Add focused frontend coverage for the event detail panel:

- Raw condition-field rendering and internal labels are absent.
- Optional rows are conditionally displayed only when meaningful.
- Trigger and effect information is rendered as concise, localized text.
- Edit, enable/disable, delete, and refresh contracts remain intact.

Run the focused test, the frontend test suite, and the production build before
completion.

## Out of Scope

- Changes to the full event editor.
- Backend schema or API response changes.
- Changes to event creation, update, triggering, or scheduling behavior.
- A new expandable technical-details control in the list page.
- Broader redesign of the event archive workspace.

## Acceptance Criteria

- The `/events` right-hand panel is visibly shorter and easier to scan.
- No raw condition table, internal field names, or JSON-like values are shown.
- Empty optional metadata does not occupy space.
- Users can still understand the trigger, effects, schedule, and recent event
  activity at a glance.
- Existing management actions and full-editor navigation continue to work.
