"""
事件运行时集成层。

负责把事件检测、执行、事件链、时间调度、模板库和持久化上下文串起来。
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

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


def load_event_definitions(character_id: str | None = None, only_active: bool = True) -> list[EventDefinition]:
    """从数据库加载事件定义并转换为 schema 对象。"""
    event_definitions = []
    rows = repository.list_event_definitions(character_id=character_id, only_active=only_active)
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
        definitions_by_id = {definition.event_id: definition for definition in load_event_definitions(context.character_id)}

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
    definitions = event_definitions or load_event_definitions(context.character_id, only_active=True)
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


def _field_matches(value: int, field: str, min_value: int, max_value: int) -> bool:
    field = (field or "*").strip()
    if field == "*":
        return True
    allowed: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            allowed.update(range(min_value, max_value + 1, step))
        elif "-" in part:
            start, end = [int(x) for x in part.split("-", 1)]
            allowed.update(range(max(min_value, start), min(max_value, end) + 1))
        else:
            allowed.add(int(part))
    return value in allowed


def _cron_weekday(when: datetime) -> int:
    """Return cron weekday where Sunday is 0, Monday is 1, ... Saturday is 6."""
    return (when.weekday() + 1) % 7


def _weekday_field_matches(weekday: int, field: str) -> bool:
    field = (field or "*").strip()
    if field == "*":
        return True

    allowed: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            allowed.update(range(0, 7, step))
        elif "-" in part:
            raw_start, raw_end = [int(x) for x in part.split("-", 1)]
            start = 0 if raw_start == 7 else raw_start
            end = 0 if raw_end == 7 else raw_end
            if raw_end == 7 and start > 0:
                allowed.update(range(start, 7))
                allowed.add(0)
            elif start <= end:
                allowed.update(range(max(0, start), min(6, end) + 1))
            else:
                allowed.update(range(start, 7))
                allowed.update(range(0, end + 1))
        else:
            value = int(part)
            allowed.add(0 if value == 7 else value)
    return weekday in allowed


def cron_matches(schedule: str, when: datetime) -> bool:
    """检查 5 字段 cron 是否匹配当前分钟。"""
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("cron 表达式必须是 5 字段: minute hour day month weekday")
    return (
        _field_matches(when.minute, parts[0], 0, 59)
        and _field_matches(when.hour, parts[1], 0, 23)
        and _field_matches(when.day, parts[2], 1, 31)
        and _field_matches(when.month, parts[3], 1, 12)
        and _weekday_field_matches(_cron_weekday(when), parts[4])
    )


def next_cron_run(schedule: str, after: datetime | None = None, max_minutes: int = 366 * 24 * 60) -> datetime:
    """计算下一次 cron 命中时间，分钟级精度。"""
    cursor = after or datetime.now(timezone.utc)
    cursor = cursor.astimezone(timezone.utc).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(max_minutes):
        if cron_matches(schedule, cursor):
            return cursor
        cursor += timedelta(minutes=1)
    raise ValueError(f"无法在搜索窗口内计算下一次 cron: {schedule}")


def register_time_event_schedule(
    event_id: str,
    character_id: str,
    player_id: str,
    schedule: str,
    base_time: datetime | None = None,
) -> bool:
    """注册或更新时间驱动事件调度。"""
    next_run = next_cron_run(schedule, base_time)
    return repository.save_event_schedule_state(
        event_id=event_id,
        character_id=character_id,
        player_id=player_id,
        schedule=schedule,
        next_run_at=next_run.isoformat(),
        last_checked_at=(base_time or datetime.now(timezone.utc)).isoformat(),
        status="active",
    )


def run_due_time_events(now: datetime | None = None, limit: int = 50) -> list[EventTriggerResult]:
    """检查并执行到期的时间驱动事件。"""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(second=0, microsecond=0)
    rows = repository.list_due_event_schedules(now.isoformat(), limit=limit)
    results: list[EventTriggerResult] = []

    for schedule_state in rows:
        event_row = repository.get_event_definition(schedule_state["event_id"])
        if not event_row:
            continue
        try:
            event = _event_definition_from_row(event_row)
            if not event.is_active:
                continue
            context = EventContext(
                character_id=schedule_state["character_id"],
                player_id=schedule_state["player_id"],
                session_id=schedule_state.get("last_session_id") or f"schedule:{event.event_id}",
                current_affinity=0,
                current_trust=0,
                current_mood="neutral",
                player_message="",
                npc_response=None,
                dialogue_count=0,
                total_dialogue_count=0,
                session_duration_minutes=0,
                event_data={"triggered_by": "schedule"},
            )
            results.extend(execute_event_with_chain(event, context))
            next_run = next_cron_run(schedule_state["schedule"], now)
            repository.save_event_schedule_state(
                event_id=schedule_state["event_id"],
                character_id=schedule_state["character_id"],
                player_id=schedule_state["player_id"],
                schedule=schedule_state["schedule"],
                last_checked_at=now.isoformat(),
                last_run_at=now.isoformat(),
                next_run_at=next_run.isoformat(),
                status="active",
            )
        except Exception as e:
            logger.error(f"执行定时事件失败: {schedule_state.get('event_id')}, 错误: {e}", exc_info=True)

    return results


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
