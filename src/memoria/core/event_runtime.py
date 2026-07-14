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
from typing import Any

from memoria.core import character_loader, world_clock
from memoria.core.config import configs
from memoria.core.cron_schedule import (
    collect_due_cron_runs,
    cron_matches,
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
        trigger_condition=json.loads(row["trigger_config"]),
        effects=json.loads(row["effects_config"]),
        priority=row.get("priority", 0),
        is_active=bool(row.get("is_active", 1)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        trigger_count=row.get("trigger_count", 0),
        last_triggered_at=row.get("last_triggered_at"),
        schedule=row.get("schedule"),
        template_id=row.get("template_id"),
    )


def persist_event_context(event: EventDefinition, context: EventContext, result: EventTriggerResult) -> None:
    """保存事件触发后的上下文进度。"""
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
    }
    progress = min(1.0, float(context.event_data.get("progress", 1.0) or 1.0))
    repository.save_event_context_state(
        event_id=event.event_id,
        character_id=context.character_id,
        player_id=context.player_id,
        context_data=json.dumps(context_data, ensure_ascii=False),
        status="completed" if progress >= 1.0 else "active",
        progress=progress,
        last_session_id=context.session_id,
    )


def execute_event_with_chain(
    event: EventDefinition,
    context: EventContext,
    definitions_by_id: dict[str, EventDefinition] | None = None,
    depth: int = 0,
    visited: set[str] | None = None,
) -> list[EventTriggerResult]:
    """执行事件并按配置继续执行链式事件。"""
    if depth > MAX_CHAIN_DEPTH:
        logger.warning(f"事件链超过最大深度，停止: {event.event_id}")
        return []

    visited = visited or set()
    if event.event_id in visited:
        logger.warning(f"检测到事件链循环，停止: {event.event_id}")
        return []
    visited.add(event.event_id)

    executor = get_event_executor()
    chain_context = context.model_copy(update={"last_event_id": event.event_id})
    result = executor.execute_event(event, chain_context)
    persist_event_context(event, chain_context, result)

    results = [result]
    if not result.chained_events:
        return results

    if definitions_by_id is None:
        definitions_by_id = {
            definition.event_id: definition
            for definition in load_event_definitions(context.player_id, context.character_id)
        }

    for next_event_id in result.chained_events:
        next_event = definitions_by_id.get(next_event_id)
        if not next_event:
            logger.warning(f"链式事件不存在: {next_event_id}")
            continue
        results.extend(
            execute_event_with_chain(
                next_event,
                chain_context,
                definitions_by_id=definitions_by_id,
                depth=depth + 1,
                visited=visited.copy(),
            )
        )
    return results


def detect_and_execute_events(context: EventContext, event_definitions: list[EventDefinition] | None = None) -> list[EventTriggerResult]:
    """检测并执行当前上下文触发的事件。"""
    definitions = event_definitions or load_event_definitions(context.player_id, context.character_id, only_active=True)
    detector = get_event_detector()
    triggered_events = detector.check_events(context, definitions)
    definitions_by_id = {event.event_id: event for event in definitions}

    results = []
    for event in triggered_events:
        results.extend(execute_event_with_chain(event, context, definitions_by_id=definitions_by_id))
    return results


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

    for event_result in results:
        state_changes = event_result.state_changes or {}
        if "affection_level" in state_changes:
            affinity = max(-100, min(100, affinity + state_changes["affection_level"]))
        if "trust_level" in state_changes:
            trust = max(0, min(100, trust + state_changes["trust_level"]))
        if "current_mood" in state_changes:
            mood = state_changes["current_mood"]
        if event_result.dialogue_override and not dialogue.startswith("[事件触发]"):
            dialogue = f"[事件触发] {event_result.dialogue_override}"
        if event_result.notification:
            notification = event_result.notification

        triggered_info.append({
            "event_id": event_result.event_id,
            "event_name": event_result.event_name,
            "effects": event_result.effects_applied,
            "chained_events": event_result.chained_events,
            "proactive_dialogues": event_result.proactive_dialogues,
        })

    return dialogue, affinity, trust, mood, triggered_info, notification


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


def register_time_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    base_time: datetime | None = None,
) -> bool:
    """Register a cron schedule against the player's local world calendar."""
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
    return repository.save_event_schedule_state(
        event_id=event_id,
        character_id=character_id,
        player_id=player_id,
        schedule=schedule,
        next_run_at=next_run.isoformat(),
        next_due_real_at=(
            next_due_real.isoformat() if next_due_real is not None else None
        ),
        last_checked_at=world_base.isoformat(),
        status="active",
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

    active_multi_session = repository.get_latest_active_multi_session(player_id)
    session_id = session["session_id"] if session else f"schedule:{event.event_id}"
    messages = repository.get_session_messages(session_id) if session else []
    dialogue_count = sum(1 for message in messages if message.get("role") == "user")

    session_duration_minutes = 0.0
    if session and session.get("created_at"):
        created_at = _parse_iso(session["created_at"])
        if created_at:
            session_duration_minutes = max(
                0.0,
                (datetime.now(timezone.utc) - created_at).total_seconds() / 60.0,
            )

    event_data = dict(context_data.get("event_data") or {})
    event_data.update({
        "triggered_by": "schedule",
        "scheduled_for": schedule_state["next_run_at"],
        "world_now": world_now.isoformat(),
    })
    return EventContext(
        character_id=character_id,
        player_id=player_id,
        session_id=session_id,
        current_affinity=runtime_state.get("affection_level", 0),
        current_trust=runtime_state.get("trust_level", 0),
        current_mood=runtime_state.get("current_mood", "neutral"),
        player_message=context_data.get("player_message", ""),
        npc_response=context_data.get("npc_response"),
        dialogue_count=dialogue_count,
        total_dialogue_count=dialogue_count,
        session_duration_minutes=session_duration_minutes,
        unlocked_content=context_data.get("unlocked_content") or [],
        character_relationships=context_data.get("character_relationships") or {},
        event_data=event_data,
        last_event_id=context_data.get("last_event_id"),
        active_multi_session_id=(
            active_multi_session["session_id"] if active_multi_session else None
        ),
    )


def _persist_scheduled_event_results(
    event: EventDefinition,
    context: EventContext,
    results: list[EventTriggerResult],
    world_now: datetime,
) -> None:
    _, affinity, trust, mood, _, notification = apply_event_results_to_dialogue_state(
        results,
        "",
        context.current_affinity,
        context.current_trust,
        context.current_mood,
    )
    repository.save_runtime_state(
        context.character_id,
        context.player_id,
        affinity,
        trust,
        mood,
    )

    messages: list[str] = []
    if notification:
        messages.append(notification)
    for result in results:
        if result.dialogue_override:
            messages.append(result.dialogue_override)
        for proactive in result.proactive_dialogues:
            if isinstance(proactive, dict):
                text = proactive.get("dialogue") or proactive.get("content")
                if text:
                    messages.append(str(text))
    content = "\n".join(dict.fromkeys(messages)) or f"{event.event_name} 已触发。"
    repository.enqueue_player_event(
        context.player_id,
        content,
        event_id=event.event_id,
        character_id=context.character_id,
        session_id=(
            None if context.session_id.startswith("schedule:") else context.session_id
        ),
        title=event.event_name,
        payload=json.dumps(
            [result.model_dump(mode="json") for result in results],
            ensure_ascii=False,
        ),
        world_created_at=world_now.isoformat(),
    )


def run_due_time_events(
    now: datetime | None = None,
    limit: int = 50,
    player_id: str | None = None,
    lease_owner: str | None = None,
) -> list[EventTriggerResult]:
    """Execute schedules selected by their indexed real-UTC due instant."""
    real_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
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
            for scheduled_for in replay_runs:
                replay_state = {
                    **schedule_state,
                    "next_run_at": scheduled_for.isoformat(),
                }
                context = _load_scheduled_event_context(
                    event,
                    replay_state,
                    scheduled_for,
                )
                event_results = execute_event_with_chain(event, context)
                _persist_scheduled_event_results(
                    event,
                    context,
                    event_results,
                    scheduled_for,
                )
                results.extend(event_results)

            next_due_real = world_clock.world_due_to_real(
                next_run,
                snapshot.world_now,
                real_now,
                snapshot.time_scale,
            )
            if not repository.complete_event_schedule(
                schedule_state["event_id"],
                schedule_state["character_id"],
                schedule_state["player_id"],
                lease_owner=owner,
                last_checked_at=snapshot.world_now.isoformat(),
                last_run_at=last_run_at.isoformat(),
                next_run_at=next_run.isoformat(),
                next_due_real_at=(
                    next_due_real.isoformat() if next_due_real is not None else None
                ),
                missed_count=(
                    int(schedule_state.get("missed_count") or 0)
                    + due_count
                    - len(replay_runs)
                ),
            ):
                raise RuntimeError("schedule lease was lost before completion")
        except Exception:
            repository.release_event_schedule(
                schedule_state["event_id"],
                schedule_state["character_id"],
                schedule_state["player_id"],
                lease_owner=owner,
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


def reconcile_event_schedule_due_times(now: datetime | None = None) -> int:
    """Backfill indexed real due times for schedules created by older schemas."""
    real_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = repository.list_event_schedules_missing_due_projection()
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
