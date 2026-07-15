"""
事件运行时集成层。

负责把事件检测、执行、事件链、时间调度、模板库和持久化上下文串起来。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from memoria.core import character_loader, world_clock
from memoria.core.config import configs
from memoria.core.cron_schedule import (
    collect_due_cron_runs,
    next_cron_run,
)
from memoria.core.event_detector import get_event_detector
from memoria.core.event_executor import get_event_executor
from memoria.core.event_schema import (
    EffectType,
    EventContext,
    EventDefinition,
    EventEffect,
    EventTriggerResult,
    TriggerCondition,
    TriggerType,
)
from memoria.db import repository

logger = logging.getLogger(__name__)

MAX_CHAIN_DEPTH = 5


def load_event_definitions(
    owner_user_id: str,
    character_id: str | None = None,
    only_active: bool = True,
) -> list[EventDefinition]:
    """从数据库加载事件定义并转换为 schema 对象。"""
    event_definitions = []
    rows = repository.list_event_definitions(
        owner_user_id=owner_user_id,
        character_id=character_id,
        only_active=only_active,
    )
    for row in rows:
        try:
            event_definitions.append(_event_definition_from_row(row))
        except Exception as e:
            logger.error(f"解析事件定义失败: {row.get('event_id')}, 错误: {e}")
    return event_definitions


def _event_definition_from_row(row: dict[str, Any]) -> EventDefinition:
    return EventDefinition(
        event_id=row["event_id"],
        event_name=row["event_name"],
        description=row.get("description"),
        character_id=row.get("character_id"),
        story_id=row.get("story_id"),
        trigger_condition=json.loads(row["trigger_config"]),
        effects=json.loads(row["effects_config"]),
        priority=row.get("priority", 0),
        exclusive_group=row.get("exclusive_group"),
        max_triggers_per_turn=row.get("max_triggers_per_turn") or 3,
        stop_processing=bool(row.get("stop_processing", 0)),
        is_active=bool(row.get("is_active", 1)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        trigger_count=row.get("trigger_count", 0),
        last_triggered_at=row.get("last_triggered_at"),
        schedule=row.get("schedule"),
        template_id=row.get("template_id"),
    )


def build_event_context(
    *,
    character_id: str,
    player_id: str,
    session_id: str,
    current_affinity: float,
    current_trust: float,
    current_mood: str,
    player_message: str = "",
    npc_response: str | None = None,
    previous_affinity: float | None = None,
    previous_trust: float | None = None,
    affinity_delta: float | None = None,
    trust_delta: float | None = None,
    character_relationships: dict[str, dict] | None = None,
    event_data: dict[str, Any] | None = None,
    last_event_id: str | None = None,
    world_time: str | None = None,
    execution_key: str | None = None,
    trigger_source: str = "dialogue",
    current_user_turn_persisted: bool = False,
) -> EventContext:
    """Build one canonical event context for dialogue, group chat, and schedules."""
    session = repository.get_session(session_id)
    session_turns = repository.get_session_user_turn_count(session_id) if session else 0
    total_turns = repository.count_character_user_turns(player_id, character_id)
    if player_message and not current_user_turn_persisted:
        session_turns += 1
        total_turns += 1

    session_duration_minutes = 0.0
    if session and session.get("created_at"):
        created_at = _parse_iso(session["created_at"])
        if created_at:
            session_duration_minutes = max(
                0.0,
                (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0,
            )

    active_multi_session = repository.get_latest_active_multi_session(player_id)
    if world_time is None:
        world_time = world_clock.get_clock_snapshot(player_id).world_now.isoformat()
    if affinity_delta is None:
        affinity_delta = (
            current_affinity - previous_affinity
            if previous_affinity is not None
            else 0.0
        )
    if trust_delta is None:
        trust_delta = (
            current_trust - previous_trust
            if previous_trust is not None
            else 0.0
        )

    return EventContext(
        character_id=character_id,
        player_id=player_id,
        session_id=session_id,
        current_affinity=current_affinity,
        current_trust=current_trust,
        current_mood=current_mood,
        previous_affinity=previous_affinity,
        previous_trust=previous_trust,
        player_message=player_message,
        npc_response=npc_response,
        dialogue_count=session_turns,
        total_dialogue_count=total_turns,
        session_duration_minutes=session_duration_minutes,
        affinity_delta=affinity_delta,
        trust_delta=trust_delta,
        unlocked_content=repository.list_event_unlocks(player_id, character_id),
        character_relationships=character_relationships or {},
        event_data=event_data or {},
        event_history=repository.list_event_execution_history(player_id, limit=200),
        world_time=world_time,
        last_event_id=last_event_id,
        active_multi_session_id=(
            active_multi_session["session_id"] if active_multi_session else None
        ),
        execution_key=execution_key,
        trigger_source=trigger_source,
    )


def _context_state_for_result(
    event: EventDefinition,
    context: EventContext,
    result: EventTriggerResult,
) -> dict[str, Any]:
    stored = repository.get_event_context_state(
        event.event_id,
        context.character_id,
        context.player_id,
    )
    stored_data: dict[str, Any] = {}
    if stored and stored.get("context_data"):
        try:
            stored_data = json.loads(stored["context_data"])
        except (TypeError, ValueError):
            stored_data = {}

    progress = float((stored or {}).get("progress") or 0.0)
    status = str((stored or {}).get("status") or "active")
    progress_update = result.state_changes.get("event_progress") or {}
    if "progress" in progress_update:
        progress = float(progress_update["progress"])
    if "progress_delta" in progress_update:
        progress += float(progress_update["progress_delta"])
    progress = max(0.0, min(1.0, progress))
    if progress_update.get("status"):
        status = str(progress_update["status"])
    elif progress_update and progress >= 1.0:
        status = "completed"
    elif progress_update and status == "completed" and progress < 1.0:
        status = "active"

    context_data = {
        "event_id": event.event_id,
        "event_name": event.event_name,
        "last_event_id": context.last_event_id,
        "session_id": context.session_id,
        "player_message": context.player_message,
        "npc_response": context.npc_response,
        "current_affinity": context.current_affinity,
        "current_trust": context.current_trust,
        "current_mood": context.current_mood,
        "state_changes": result.state_changes,
        "chained_events": result.chained_events,
        "proactive_dialogues": result.proactive_dialogues,
        "event_data": context.event_data,
        "previous_context": stored_data,
    }
    return {
        "context_data": json.dumps(context_data, ensure_ascii=False),
        "status": status,
        "progress": progress,
    }


def persist_event_context(
    event: EventDefinition,
    context: EventContext,
    result: EventTriggerResult,
) -> None:
    """Legacy standalone persistence wrapper; production uses the batch transaction."""
    state = _context_state_for_result(event, context, result)
    repository.save_event_context_state(
        event_id=event.event_id,
        character_id=context.character_id,
        player_id=context.player_id,
        context_data=state["context_data"],
        status=state["status"],
        progress=state["progress"],
        last_session_id=context.session_id,
    )


def _restore_batch_results(batch: dict[str, Any]) -> list[EventTriggerResult]:
    try:
        stored = json.loads(batch.get("results_data") or "[]")
    except (TypeError, ValueError):
        logger.error("Invalid event batch result payload", extra={"batch": batch})
        return []
    restored = [EventTriggerResult.model_validate(item) for item in stored]
    for result in restored:
        result.status = "skipped"
        result.deduplicated = True
    return restored


def _replay_batch_results(
    player_id: str,
    execution_key: str,
    batch: dict[str, Any],
) -> list[EventTriggerResult]:
    repository.increment_event_execution_batch_deduplicated(
        player_id,
        execution_key,
    )
    return _restore_batch_results(batch)


def _plan_event_chain(
    roots: list[EventDefinition],
    context: EventContext,
    definitions_by_id: dict[str, EventDefinition],
    *,
    enforce_cooldown: bool = False,
) -> tuple[list[EventTriggerResult], list[dict[str, Any]]]:
    return _plan_event_roots(
        [(event, context) for event in roots],
        definitions_by_id,
        enforce_cooldown=enforce_cooldown,
    )


def _plan_event_roots(
    roots: list[tuple[EventDefinition, EventContext]],
    definitions_by_id: dict[str, EventDefinition],
    *,
    enforce_cooldown: bool = False,
) -> tuple[list[EventTriggerResult], list[dict[str, Any]]]:
    executor = get_event_executor()
    results: list[EventTriggerResult] = []
    executions: list[dict[str, Any]] = []
    planned_event_ids: set[str] = set()

    def release_claim(execution: dict[str, Any]) -> None:
        claim_token = execution.get("trigger_claim_token")
        if not claim_token:
            return
        repository.release_event_trigger_guard(
            player_id=execution["player_id"],
            event_id=execution["event_id"],
            character_scope=execution.get("trigger_character_scope") or "",
            claim_token=claim_token,
        )

    def visit(
        event: EventDefinition,
        chain_context: EventContext,
        depth: int,
        path: tuple[str, ...],
    ) -> None:
        if depth > MAX_CHAIN_DEPTH:
            logger.warning("事件链超过最大深度，停止: %s", event.event_id)
            return
        if event.event_id in path:
            logger.warning("检测到事件链循环，停止: %s", event.event_id)
            return
        if event.event_id in planned_event_ids:
            logger.info("同一事件批次跳过重复链节点: %s", event.event_id)
            return
        planned_event_ids.add(event.event_id)

        event_context = chain_context.model_copy(
            update={
                "execution_key": chain_context.execution_key,
                "last_event_id": path[-1] if path else chain_context.last_event_id,
            }
        )
        claim_token = None
        character_scope = event_context.character_id if event.character_id else ""
        if enforce_cooldown:
            claimed_at = datetime.now(timezone.utc)
            claim_token = uuid.uuid4().hex
            claimed = repository.claim_event_trigger_guard(
                player_id=event_context.player_id,
                event_id=event.event_id,
                character_scope=character_scope,
                cooldown_hours=event.trigger_condition.cooldown_hours or 0,
                claim_token=claim_token,
                claimed_at=claimed_at.isoformat(),
                claim_expires_at=(claimed_at + timedelta(minutes=5)).isoformat(),
            )
            if not claimed:
                result = EventTriggerResult(
                    execution_id=uuid.uuid4().hex,
                    execution_key=chain_context.execution_key,
                    event_id=event.event_id,
                    event_name=event.event_name,
                    character_id=event_context.character_id,
                    triggered=False,
                    status="skipped",
                    error="事件已触发或仍在冷却中",
                )
                results.append(result)
                executions.append(
                    executor.build_execution_record(
                        event,
                        event_context,
                        result,
                        {
                            "memories": [],
                            "unlock_keys": [],
                            "inbox_items": [],
                            "proactive_messages": [],
                        },
                    )
                )
                return

        try:
            result, operations = executor.plan_event(
                event,
                event_context,
                execution_key=chain_context.execution_key,
            )
        except Exception:
            if claim_token:
                repository.release_event_trigger_guard(
                    player_id=event_context.player_id,
                    event_id=event.event_id,
                    character_scope=character_scope,
                    claim_token=claim_token,
                )
            raise
        if result.status != "succeeded" and claim_token:
            repository.release_event_trigger_guard(
                player_id=event_context.player_id,
                event_id=event.event_id,
                character_scope=character_scope,
                claim_token=claim_token,
            )
            claim_token = None
        results.append(result)
        executions.append(
            {
                "player_id": event_context.player_id,
                **executor.build_execution_record(
                    event,
                    event_context,
                    result,
                    operations,
                    context_state=(
                        _context_state_for_result(event, event_context, result)
                        if result.status == "succeeded"
                        else None
                    ),
                    trigger_claim_token=claim_token,
                    trigger_character_scope=character_scope,
                ),
            }
        )
        if result.status != "succeeded":
            return
        for next_event_id in result.chained_events:
            next_event = definitions_by_id.get(next_event_id)
            if next_event is None:
                logger.warning("链式事件不存在或不属于当前用户: %s", next_event_id)
                continue
            visit(next_event, event_context, depth + 1, (*path, event.event_id))

    try:
        for root, root_context in roots:
            visit(root, root_context, 0, ())
    except Exception:
        for execution in executions:
            release_claim(execution)
        raise
    return results, executions


def _runtime_state_after_results(
    context: EventContext,
    results: list[EventTriggerResult],
) -> dict[str, Any] | None:
    affinity = context.current_affinity
    trust = context.current_trust
    mood = context.current_mood
    changed = False
    for result in results:
        if result.status != "succeeded":
            continue
        changes = result.state_changes or {}
        if "affection_level" in changes:
            affinity = max(-100, min(100, affinity + float(changes["affection_level"])))
            changed = True
        if "trust_level" in changes:
            trust = max(0, min(100, trust + float(changes["trust_level"])))
            changed = True
        if "current_mood" in changes:
            mood = str(changes["current_mood"])
            changed = True
    if not changed:
        return None
    return {
        "character_id": context.character_id,
        "affection_level": affinity,
        "trust_level": trust,
        "current_mood": mood,
    }


def _runtime_states_after_contexts(
    contexts: list[EventContext],
    results: list[EventTriggerResult],
) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    seen: set[str] = set()
    for context in contexts:
        if context.character_id in seen:
            continue
        seen.add(context.character_id)
        character_results = [
            result
            for result in results
            if result.character_id == context.character_id
        ]
        state = _runtime_state_after_results(context, character_results) or {
            "character_id": context.character_id,
            "affection_level": context.current_affinity,
            "trust_level": context.current_trust,
            "current_mood": context.current_mood,
        }
        states.append(state)
    return states


def _commit_planned_batch(
    context: EventContext,
    results: list[EventTriggerResult],
    executions: list[dict[str, Any]],
    *,
    runtime_states: list[dict[str, Any]] | None = None,
    schedule_completion: dict[str, Any] | None = None,
    dialogue_turn_factory: Callable[[list[EventTriggerResult]], dict] | None = None,
) -> list[EventTriggerResult]:
    results_data = json.dumps(
        [result.model_dump(mode="json") for result in results],
        ensure_ascii=False,
    )
    dialogue_turn = dialogue_turn_factory(results) if dialogue_turn_factory else None
    effective_runtime_states = (
        dialogue_turn.get("runtime_states")
        if dialogue_turn and "runtime_states" in dialogue_turn
        else runtime_states
    )
    try:
        commit = repository.commit_event_execution_batch(
            player_id=context.player_id,
            execution_key=str(context.execution_key),
            trigger_source=context.trigger_source,
            results_data=results_data,
            executions=executions,
            runtime_states=effective_runtime_states,
            schedule_completion=schedule_completion,
            dialogue_turn=dialogue_turn,
        )
    except Exception:
        for execution in executions:
            claim_token = execution.get("trigger_claim_token")
            if claim_token:
                repository.release_event_trigger_guard(
                    player_id=context.player_id,
                    event_id=execution["event_id"],
                    character_scope=execution.get("trigger_character_scope") or "",
                    claim_token=claim_token,
                )
        raise
    if commit["deduplicated"]:
        return _restore_batch_results(commit["batch"])
    get_event_executor()._sync_vector_memories(commit.get("inserted_memories") or [])
    return results


def execute_event_with_chain(
    event: EventDefinition,
    context: EventContext,
    definitions_by_id: dict[str, EventDefinition] | None = None,
    depth: int = 0,
    visited: set[str] | None = None,
) -> list[EventTriggerResult]:
    """Compatibility entry that executes one root and its chain as one batch."""
    del depth, visited
    if definitions_by_id is None:
        definitions_by_id = {
            definition.event_id: definition
            for definition in load_event_definitions(context.player_id, context.character_id)
        }
    definitions_by_id[event.event_id] = event
    execution_key = context.execution_key or (
        f"direct:{context.session_id}:{event.event_id}:{uuid.uuid4().hex}"
    )
    batch_context = context.model_copy(update={"execution_key": execution_key})
    existing = repository.get_event_execution_batch(context.player_id, execution_key)
    if existing:
        return _replay_batch_results(context.player_id, execution_key, existing)
    results, executions = _plan_event_chain(
        [event],
        batch_context,
        definitions_by_id,
    )
    return _commit_planned_batch(
        batch_context,
        results,
        executions,
        runtime_states=[state] if (state := _runtime_state_after_results(batch_context, results)) else [],
    )


def detect_and_execute_events(
    context: EventContext,
    event_definitions: list[EventDefinition] | None = None,
    *,
    runtime_states: list[dict[str, Any]] | None = None,
    schedule_completion: dict[str, Any] | None = None,
    dialogue_turn_factory: Callable[[list[EventTriggerResult]], dict] | None = None,
) -> list[EventTriggerResult]:
    """Detect, plan, and atomically commit one idempotent event batch."""
    execution_key = context.execution_key or (
        f"event:{context.trigger_source}:{context.session_id}:{uuid.uuid4().hex}"
    )
    context = context.model_copy(update={"execution_key": execution_key})
    existing = repository.get_event_execution_batch(context.player_id, execution_key)
    if existing:
        restored = _replay_batch_results(context.player_id, execution_key, existing)
        if not dialogue_turn_factory:
            return restored
        return _commit_planned_batch(
            context,
            restored,
            [],
            runtime_states=runtime_states,
            schedule_completion=schedule_completion,
            dialogue_turn_factory=dialogue_turn_factory,
        )

    definitions = event_definitions or load_event_definitions(context.player_id, context.character_id, only_active=True)
    detector = get_event_detector()
    triggered_events = detector.check_events(context, definitions)
    definitions_by_id = {event.event_id: event for event in definitions}
    results, executions = _plan_event_chain(
        triggered_events,
        context,
        definitions_by_id,
        enforce_cooldown=True,
    )
    for result in results:
        event = definitions_by_id.get(result.event_id)
        if event and event in triggered_events:
            result.condition_trace = [detector.evaluate_event(event, context)["condition"]]

    if runtime_states is None and results:
        state = _runtime_state_after_results(context, results)
        runtime_states = [state] if state else []
    return _commit_planned_batch(
        context,
        results,
        executions,
        runtime_states=runtime_states,
        schedule_completion=schedule_completion,
        dialogue_turn_factory=dialogue_turn_factory,
    )


def detect_and_execute_event_contexts(
    contexts: list[EventContext],
    event_definitions: list[EventDefinition] | None = None,
    *,
    dialogue_turn_factory: Callable[[list[EventTriggerResult]], dict] | None = None,
) -> list[EventTriggerResult]:
    """Execute one group-chat turn across multiple character contexts."""
    if not contexts:
        return []
    player_id = contexts[0].player_id
    execution_key = contexts[0].execution_key or (
        f"event:multi:{contexts[0].session_id}:{uuid.uuid4().hex}"
    )
    normalized_contexts = [
        context.model_copy(
            update={
                "execution_key": execution_key,
                "trigger_source": "multi_dialogue",
            }
        )
        for context in contexts
    ]
    if any(context.player_id != player_id for context in normalized_contexts):
        raise ValueError("group event contexts must belong to one player")

    existing = repository.get_event_execution_batch(player_id, execution_key)
    if existing:
        restored = _replay_batch_results(player_id, execution_key, existing)
        if not dialogue_turn_factory:
            return restored
        return _commit_planned_batch(
            normalized_contexts[0],
            restored,
            [],
            runtime_states=_runtime_states_after_contexts(normalized_contexts, restored),
            dialogue_turn_factory=dialogue_turn_factory,
        )

    definitions = event_definitions or load_event_definitions(
        player_id,
        character_id=None,
        only_active=True,
    )
    definitions_by_id = {event.event_id: event for event in definitions}
    detector = get_event_detector()
    candidates: list[tuple[EventDefinition, EventContext]] = []
    for event in definitions:
        if not event.is_active:
            continue
        scoped_contexts = [
            context
            for context in normalized_contexts
            if event.character_id in {None, context.character_id}
        ]
        for context in scoped_contexts:
            if not detector._check_cooldown(event, context):
                continue
            if detector._check_trigger_condition(event.trigger_condition, context):
                candidates.append((event, context))
                break

    candidates.sort(key=lambda pair: pair[0].priority, reverse=True)
    roots: list[tuple[EventDefinition, EventContext]] = []
    exclusive_groups: set[str] = set()
    turn_limit = min(
        (max(1, event.max_triggers_per_turn or 3) for event, _ in candidates),
        default=3,
    )
    for event, context in candidates:
        if event.exclusive_group and event.exclusive_group in exclusive_groups:
            continue
        if len(roots) >= turn_limit:
            break
        roots.append((event, context))
        if event.exclusive_group:
            exclusive_groups.add(event.exclusive_group)
        if event.stop_processing:
            break

    results, executions = _plan_event_roots(
        roots,
        definitions_by_id,
        enforce_cooldown=True,
    )
    root_contexts = {event.event_id: context for event, context in roots}
    for result in results:
        event = definitions_by_id.get(result.event_id)
        root_context = root_contexts.get(result.event_id)
        if event and root_context:
            result.condition_trace = [
                detector.evaluate_event(event, root_context)["condition"]
            ]

    return _commit_planned_batch(
        normalized_contexts[0],
        results,
        executions,
        runtime_states=_runtime_states_after_contexts(normalized_contexts, results),
        dialogue_turn_factory=dialogue_turn_factory,
    )


def apply_event_results_to_dialogue_state(
    results: list[EventTriggerResult],
    dialogue: str,
    affinity: float,
    trust: float,
    mood: str,
) -> tuple[str, float, float, str, list[dict[str, Any]], str | None]:
    """把事件执行结果合并回对话返回状态。"""
    notification = None
    triggered_info = []

    dialogue_overrides: list[str] = []
    notifications: list[str] = []
    for event_result in results:
        triggered_info.append({
            "event_id": event_result.event_id,
            "event_name": event_result.event_name,
            "character_id": event_result.character_id,
            "execution_id": event_result.execution_id,
            "status": event_result.status,
            "effects": event_result.effects_applied,
            "effect_details": [effect.model_dump(mode="json") for effect in event_result.effects],
            "chained_events": event_result.chained_events,
            "proactive_dialogues": event_result.proactive_dialogues,
            "error": event_result.error,
            "deduplicated": event_result.deduplicated,
        })
        if event_result.status != "succeeded":
            continue
        state_changes = event_result.state_changes or {}
        if "affection_level" in state_changes:
            affinity = max(-100, min(100, affinity + state_changes["affection_level"]))
        if "trust_level" in state_changes:
            trust = max(0, min(100, trust + state_changes["trust_level"]))
        if "current_mood" in state_changes:
            mood = state_changes["current_mood"]
        dialogue_overrides.extend(
            event_result.dialogue_overrides
            or ([event_result.dialogue_override] if event_result.dialogue_override else [])
        )
        notifications.extend(
            item.message for item in event_result.notifications
        )
        if event_result.notification and event_result.notification not in notifications:
            notifications.append(event_result.notification)

    if dialogue_overrides:
        dialogue = "[事件触发] " + "\n".join(dict.fromkeys(dialogue_overrides))
    if notifications:
        notification = "\n".join(dict.fromkeys(notifications))

    return dialogue, affinity, trust, mood, triggered_info, notification


def collect_event_notifications(
    results: list[EventTriggerResult],
) -> list[dict[str, Any]]:
    return [
        notification.model_dump(mode="json")
        for result in results
        if getattr(result, "status", None) == "succeeded"
        for notification in result.notifications
    ]


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def build_time_event_schedule_state(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    base_time: datetime | None = None,
    status: str = "active",
) -> dict[str, Any]:
    """Build a cron schedule state against the player's local world calendar."""
    snapshot = world_clock.get_clock_snapshot(player_id)
    world_base = world_clock.as_utc(base_time or snapshot.world_now)
    next_run = next_cron_run(
        schedule,
        world_base,
        timezone_name=snapshot.timezone,
    )
    next_due_real = world_clock.world_due_to_real(
        next_run,
        snapshot.world_now,
        snapshot.real_now,
        snapshot.time_scale,
    )
    return {
        "event_id": event_id,
        "character_id": character_id,
        "player_id": player_id,
        "schedule": schedule,
        "next_run_at": next_run.isoformat(),
        "next_due_real_at": (
            next_due_real.isoformat() if next_due_real is not None else None
        ),
        "last_checked_at": world_base.isoformat(),
        "status": status,
    }


def register_time_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    base_time: datetime | None = None,
) -> bool:
    """Register a cron schedule against the player's local world calendar."""
    return repository.save_event_schedule_state(
        **build_time_event_schedule_state(
            event_id=event_id,
            character_id=character_id,
            player_id=player_id,
            schedule=schedule,
            base_time=base_time,
        )
    )


def _load_scheduled_event_context(
    event: EventDefinition,
    schedule_state: dict[str, Any],
    world_now: datetime,
) -> EventContext:
    player_id = schedule_state["player_id"]
    character_id = schedule_state["character_id"]
    card = character_loader.load_character_card(character_id, player_id)
    runtime_state = repository.get_runtime_state(character_id, player_id, card)

    stored_context = repository.get_event_context_state(
        event.event_id,
        character_id,
        player_id,
    )
    context_data: dict[str, Any] = {}
    if stored_context and stored_context.get("context_data"):
        try:
            context_data = json.loads(stored_context["context_data"])
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid persisted event context",
                extra={"event_id": event.event_id, "player_id": player_id},
            )

    persisted_session_id = (
        (stored_context or {}).get("last_session_id")
        or context_data.get("session_id")
    )
    session = repository.get_session(persisted_session_id) if persisted_session_id else None
    if session and (
        session.get("player_id") != player_id
        or session.get("status") == "ended"
    ):
        session = None
    if not session:
        session = repository.get_latest_active_session(player_id, character_id)

    session_id = session["session_id"] if session else f"schedule:{event.event_id}"
    event_data = dict(context_data.get("event_data") or {})
    event_data.update({
        "triggered_by": "schedule",
        "scheduled_for": schedule_state["next_run_at"],
        "world_now": world_now.isoformat(),
    })
    return build_event_context(
        character_id=character_id,
        player_id=player_id,
        session_id=session_id,
        current_affinity=runtime_state.get("affection_level", 0),
        current_trust=runtime_state.get("trust_level", 0),
        current_mood=runtime_state.get("current_mood", "neutral"),
        player_message=context_data.get("player_message", ""),
        npc_response=context_data.get("npc_response"),
        character_relationships=context_data.get("character_relationships") or {},
        event_data=event_data,
        last_event_id=context_data.get("last_event_id"),
        world_time=world_now.isoformat(),
        trigger_source="schedule",
        current_user_turn_persisted=True,
    )


def run_due_time_events(
    now: datetime | None = None,
    limit: int = 50,
    player_id: str | None = None,
    lease_owner: str | None = None,
) -> list[EventTriggerResult]:
    """Execute schedules selected by their indexed real-UTC due instant."""
    real_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    reconcile_event_schedule_due_times(now=real_now, player_id=player_id)
    owner = lease_owner or f"scheduler:{uuid.uuid4().hex}"
    lease_expires_at = real_now + timedelta(
        seconds=configs.world_clock_scheduler_lease_seconds
    )
    rows: list[dict[str, Any]] = []
    after = None
    while True:
        page = repository.list_due_event_schedules(
            real_now.isoformat(),
            limit=limit,
            player_id=player_id,
            after=after,
        )
        rows.extend(page)
        if len(page) < limit:
            break
        last = page[-1]
        after = (
            last["next_due_real_at"],
            last["event_id"],
            last["character_id"],
            last["player_id"],
        )
    results: list[EventTriggerResult] = []

    for schedule_state in rows:
        snapshot = world_clock.get_clock_snapshot(
            schedule_state["player_id"],
            real_now=real_now,
        )
        next_run_at = _parse_iso(schedule_state.get("next_run_at"))
        if snapshot.paused or not next_run_at or next_run_at > snapshot.world_now:
            continue
        if not repository.claim_event_schedule(
            schedule_state["event_id"],
            schedule_state["character_id"],
            schedule_state["player_id"],
            lease_owner=owner,
            lease_expires_at=lease_expires_at.isoformat(),
            real_now_iso=real_now.isoformat(),
            expected_next_run_at=schedule_state["next_run_at"],
            expected_next_due_real_at=schedule_state.get("next_due_real_at"),
        ):
            continue

        try:
            event_row = repository.get_event_definition(
                schedule_state["player_id"],
                schedule_state["event_id"],
            )
            if not event_row:
                raise ValueError("event definition not found")
            event = _event_definition_from_row(event_row)
            if not event.is_active:
                raise ValueError("event definition is inactive")
            replay_runs, due_count, next_run = collect_due_cron_runs(
                schedule_state["schedule"],
                next_run_at,
                snapshot.world_now,
                timezone_name=snapshot.timezone,
                replay_limit=event.trigger_condition.catch_up_replay_limit,
            )
            last_run_at = replay_runs[-1]
            next_due_real = world_clock.world_due_to_real(
                next_run,
                snapshot.world_now,
                real_now,
                snapshot.time_scale,
            )
            missed_count = (
                int(schedule_state.get("missed_count") or 0)
                + due_count
                - len(replay_runs)
            )
            definitions_by_id = {
                definition.event_id: definition
                for definition in load_event_definitions(
                    schedule_state["player_id"],
                    schedule_state["character_id"],
                    only_active=True,
                )
            }
            definitions_by_id[event.event_id] = event

            for index, scheduled_for in enumerate(replay_runs):
                replay_state = {
                    **schedule_state,
                    "next_run_at": scheduled_for.isoformat(),
                }
                context = _load_scheduled_event_context(
                    event,
                    replay_state,
                    scheduled_for,
                )
                execution_key = (
                    f"schedule:{schedule_state['event_id']}:"
                    f"{schedule_state['character_id']}:"
                    f"{schedule_state['player_id']}:"
                    f"{scheduled_for.isoformat()}"
                )
                context = context.model_copy(update={"execution_key": execution_key})
                is_final_replay = index == len(replay_runs) - 1
                schedule_completion = None
                if is_final_replay:
                    schedule_completion = {
                        "event_id": schedule_state["event_id"],
                        "character_id": schedule_state["character_id"],
                        "lease_owner": owner,
                        "last_checked_at": snapshot.world_now.isoformat(),
                        "last_run_at": last_run_at.isoformat(),
                        "next_run_at": next_run.isoformat(),
                        "next_due_real_at": (
                            next_due_real.isoformat()
                            if next_due_real is not None
                            else None
                        ),
                        "missed_count": missed_count,
                    }

                existing = repository.get_event_execution_batch(
                    context.player_id,
                    execution_key,
                )
                if existing:
                    if schedule_completion:
                        commit = repository.commit_event_execution_batch(
                            player_id=context.player_id,
                            execution_key=execution_key,
                            trigger_source=context.trigger_source,
                            results_data=existing.get("results_data") or "[]",
                            executions=[],
                            schedule_completion=schedule_completion,
                        )
                        event_results = _restore_batch_results(commit["batch"])
                    else:
                        event_results = _replay_batch_results(
                            context.player_id,
                            execution_key,
                            existing,
                        )
                    results.extend(event_results)
                    continue

                event_results, executions = _plan_event_chain(
                    [event],
                    context,
                    definitions_by_id,
                )
                failed_executions = [
                    execution
                    for execution in executions
                    if execution["status"] == "failed"
                ]
                if failed_executions:
                    errors = [
                        execution.get("error") or execution["event_id"]
                        for execution in failed_executions
                    ]
                    raise RuntimeError("; ".join(errors))
                for execution in executions:
                    if execution["status"] != "succeeded":
                        continue
                    has_inbox_item = bool(execution.get("inbox_items"))
                    if not has_inbox_item:
                        matching = next(
                            result
                            for result in event_results
                            if result.execution_id == execution["execution_id"]
                        )
                        content_parts = list(matching.dialogue_overrides)
                        content_parts.extend(
                            str(item.get("dialogue") or item.get("content"))
                            for item in matching.proactive_dialogues
                            if item.get("dialogue") or item.get("content")
                        )
                        execution["inbox_items"].append({
                            "title": matching.event_name,
                            "content": "\n".join(dict.fromkeys(content_parts))
                            or f"{matching.event_name} 已触发。",
                            "session_id": (
                                None
                                if context.session_id.startswith("schedule:")
                                else context.session_id
                            ),
                            "payload": matching.model_dump_json(),
                            "world_created_at": scheduled_for.isoformat(),
                        })
                runtime_state = _runtime_state_after_results(context, event_results)
                event_results = _commit_planned_batch(
                    context,
                    event_results,
                    executions,
                    runtime_states=[runtime_state] if runtime_state else [],
                    schedule_completion=schedule_completion,
                )
                results.extend(event_results)
        except Exception as exc:
            repository.fail_event_schedule(
                schedule_state["event_id"],
                schedule_state["character_id"],
                schedule_state["player_id"],
                lease_owner=owner,
                error=str(exc),
                failed_at=snapshot.world_now.isoformat(),
            )
            logger.error(
                "Scheduled event execution failed",
                extra={
                    "event_id": schedule_state.get("event_id"),
                    "character_id": schedule_state.get("character_id"),
                    "player_id": schedule_state.get("player_id"),
                    "next_run_at": schedule_state.get("next_run_at"),
                },
                exc_info=True,
            )

    return results


def reconcile_event_schedule_due_times(
    now: datetime | None = None,
    player_id: str | None = None,
) -> int:
    """Backfill indexed real due times for schedules created by older schemas."""
    real_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = repository.list_event_schedules_missing_due_projection(
        player_id=player_id,
    )
    snapshots: dict[str, world_clock.WorldClockSnapshot] = {}
    updated = 0
    for schedule_state in rows:
        player_id = schedule_state["player_id"]
        snapshot = snapshots.get(player_id)
        if snapshot is None:
            snapshot = world_clock.get_clock_snapshot(player_id, real_now=real_now)
            snapshots[player_id] = snapshot
        if snapshot.paused:
            continue
        next_run_at = _parse_iso(schedule_state.get("next_run_at"))
        if next_run_at is None:
            continue
        next_due_real_at = world_clock.world_due_to_real(
            next_run_at,
            snapshot.world_now,
            real_now,
            snapshot.time_scale,
        )
        if next_due_real_at is None:
            continue
        if repository.set_event_schedule_due_projection(
            schedule_state["event_id"],
            schedule_state["character_id"],
            player_id,
            expected_next_run_at=schedule_state["next_run_at"],
            next_due_real_at=next_due_real_at.isoformat(),
        ):
            updated += 1
    return updated


async def run_world_clock_scheduler() -> None:
    """Run the cancellable background scheduler loop."""
    while True:
        try:
            await asyncio.to_thread(run_due_time_events)
            from memoria.core.group_dialogue_runtime import run_autonomous_group_dialogues

            await asyncio.to_thread(run_autonomous_group_dialogues)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error("World-clock scheduler scan failed", exc_info=True)
        await asyncio.sleep(configs.world_clock_scheduler_interval_seconds)


DEFAULT_EVENT_TEMPLATES = [
    {
        "template_id": "tpl_affinity_milestone",
        "template_name": "好感度里程碑",
        "category": "relationship",
        "description": "当玩家与 NPC 的好感度达到指定阈值时通知玩家并记录记忆。",
        "trigger_condition": TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD, threshold=50),
        "effects": [
            EventEffect(effect_type=EffectType.NOTIFY_PLAYER, notification_message="关系出现了新的变化。"),
            EventEffect(effect_type=EffectType.ADD_MEMORY, memory_text="玩家与我的关系进入了新的阶段。", memory_importance=7),
        ],
        "metadata": {"threshold_editable": True},
    },
    {
        "template_id": "tpl_trust_milestone",
        "template_name": "信任度里程碑",
        "category": "relationship",
        "description": "当信任度达到阈值后解锁更深入的话题。",
        "trigger_condition": TriggerCondition(trigger_type=TriggerType.TRUST_THRESHOLD, threshold=60),
        "effects": [
            EventEffect(effect_type=EffectType.UNLOCK_CONTENT, unlock_keys=["deep_trust_topic"]),
            EventEffect(effect_type=EffectType.NOTIFY_PLAYER, notification_message="新的信任话题已解锁。"),
        ],
        "metadata": {"threshold_editable": True},
    },
    {
        "template_id": "tpl_story_keyword_node",
        "template_name": "关键剧情节点",
        "category": "story",
        "description": "玩家提到关键字时推进剧情，并可通过 next_event_id 接续事件链。",
        "trigger_condition": TriggerCondition(trigger_type=TriggerType.KEYWORD_MATCH, keywords=["线索"], match_mode="any"),
        "effects": [
            EventEffect(effect_type=EffectType.TRIGGER_DIALOGUE, dialogue_text="这件事不能再拖了，我们得继续查下去。"),
        ],
        "metadata": {"keywords_editable": True},
    },
]


def ensure_default_event_templates() -> int:
    """写入内置 RPG 事件模板。"""
    count = 0
    for template in DEFAULT_EVENT_TEMPLATES:
        ok = repository.save_event_template(
            template_id=template["template_id"],
            template_name=template["template_name"],
            category=template["category"],
            description=template["description"],
            trigger_config=template["trigger_condition"].model_dump_json(),
            effects_config=json.dumps([e.model_dump() for e in template["effects"]], ensure_ascii=False),
            metadata=json.dumps(template["metadata"], ensure_ascii=False),
        )
        if ok:
            count += 1
    return count
