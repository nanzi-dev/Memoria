"""
事件系统管理 API

用途：
1. 事件定义的 CRUD 操作
2. 查询事件触发历史
3. 重置事件触发状态（用于调试）
"""

import json
import logging
import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException

from memoria.api.user import require_admin_user_id, require_current_user_id
from memoria.core.cron_schedule import next_cron_run, validate_cron_schedule
from memoria.core.event_schema import (
    TriggerCondition,
    EventEffect,
    TriggerType,
    EffectType,
)
from memoria.core import event_runtime
from memoria.db import repository

logger = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_current_user_id)])


# =========================
# 请求 / 响应模型
# =========================

class TriggerConditionDTO(BaseModel):
    """触发条件 DTO（与 event_schema.TriggerCondition 对齐）"""
    trigger_type: str
    threshold: Optional[float] = None
    comparison: Optional[str] = "gte"
    keywords: Optional[list[str]] = None
    match_mode: Optional[str] = "any"
    crossing: bool = False
    count: Optional[int] = None
    duration_minutes: Optional[int] = None
    schedule: Optional[str] = None
    catch_up_replay_limit: int = Field(default=1, ge=1, le=100)
    mood: Optional[str] = None
    state_field: Optional[str] = None
    event_id: Optional[str] = None
    event_status: Optional[str] = "succeeded"
    min_occurrences: Optional[int] = 1
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    weekdays: Optional[list[int]] = None
    sub_conditions: Optional[list["TriggerConditionDTO"]] = None
    logic_operator: Optional[str] = "and"
    cooldown_hours: Optional[int] = 0


TriggerConditionDTO.model_rebuild()


class EventEffectDTO(BaseModel):
    """事件效果 DTO"""
    effect_type: str
    state_changes: Optional[dict] = None
    unlock_keys: Optional[list[str]] = None
    dialogue_text: Optional[str] = None
    dialogue_action: Optional[str] = None
    memory_text: Optional[str] = None
    memory_importance: Optional[int] = 5
    target_mood: Optional[str] = None
    notification_message: Optional[str] = None
    notification_type: Optional[str] = "info"
    item_id: Optional[str] = None
    quest_id: Optional[str] = None
    target_character_id: Optional[str] = None
    relationship_change: Optional[dict] = None
    next_event_id: Optional[str] = None
    branch_conditions: Optional[list[dict]] = None
    target_session_id: Optional[str] = None
    proactive_character_id: Optional[str] = None
    proactive_prompt: Optional[str] = None
    progress: Optional[float] = None
    progress_delta: Optional[float] = None
    event_status: Optional[str] = None


class EventCreateRequest(BaseModel):
    event_id: str = Field(..., description="事件唯一 ID，建议格式: evt_{character}_{name}")
    event_name: str
    description: Optional[str] = None
    character_id: Optional[str] = None          # None 表示全局事件
    story_id: Optional[str] = None
    trigger_condition: TriggerConditionDTO
    effects: list[EventEffectDTO] = Field(default_factory=list)
    priority: int = 0
    exclusive_group: Optional[str] = None
    exclusive_scope: Literal["turn", "player"] = "turn"
    max_triggers_per_turn: int = Field(3, ge=1, le=20)
    stop_processing: bool = False
    is_active: bool = True
    schedule: Optional[str] = None
    template_id: Optional[str] = None


class EventUpdateRequest(BaseModel):
    event_name: Optional[str] = None
    description: Optional[str] = None
    character_id: Optional[str] = None
    story_id: Optional[str] = None
    trigger_condition: Optional[TriggerConditionDTO] = None
    effects: Optional[list[EventEffectDTO]] = None
    priority: Optional[int] = None
    exclusive_group: Optional[str] = None
    exclusive_scope: Optional[Literal["turn", "player"]] = None
    max_triggers_per_turn: Optional[int] = Field(None, ge=1, le=20)
    stop_processing: Optional[bool] = None
    is_active: Optional[bool] = None
    schedule: Optional[str] = None
    template_id: Optional[str] = None


class EventListItem(BaseModel):
    event_id: str
    event_name: str
    description: Optional[str] = None
    character_id: Optional[str] = None
    story_id: Optional[str] = None
    priority: int
    exclusive_group: Optional[str] = None
    exclusive_scope: Literal["turn", "player"] = "turn"
    max_triggers_per_turn: int = 3
    stop_processing: bool = False
    is_active: bool
    trigger_count: int
    last_triggered_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # 触发类型摘要，方便前端展示
    trigger_type: Optional[str] = None
    schedule: Optional[str] = None
    template_id: Optional[str] = None
    next_run_at: Optional[str] = None
    next_due_real_at: Optional[str] = None
    missed_count: int = 0


class EventDetail(EventListItem):
    trigger_condition: dict
    effects: list[dict]


class TriggerLogItem(BaseModel):
    id: int
    event_id: str
    character_id: str
    player_id: str
    session_id: str
    triggered_at: Optional[str] = None
    effects_applied: Optional[str] = None
    execution_id: Optional[str] = None
    status: Optional[str] = None


class OperationResponse(BaseModel):
    success: bool
    message: str
    event_id: Optional[str] = None
    template_id: Optional[str] = None


class EventTemplateItem(BaseModel):
    template_id: str
    template_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    trigger_config: dict
    effects_config: list[dict]
    metadata: Optional[dict] = None


class EventTemplateCreateRequest(BaseModel):
    template_id: str
    template_name: str
    category: Optional[str] = None
    description: Optional[str] = None
    trigger_config: TriggerConditionDTO
    effects_config: list[EventEffectDTO] = Field(default_factory=list)
    metadata: Optional[dict] = None


class ScheduleRegisterRequest(BaseModel):
    event_id: str
    character_id: str
    player_id: str
    schedule: str


class ScheduleRunResponse(BaseModel):
    success: bool
    triggered_count: int
    triggered_events: list[dict]


class EventSimulationRequest(BaseModel):
    character_id: Optional[str] = None
    session_id: Optional[str] = None
    player_message: str = Field(default="", max_length=8000)
    npc_response: Optional[str] = None
    current_affinity: Optional[float] = None
    current_trust: Optional[float] = None
    current_mood: Optional[str] = None
    previous_affinity: Optional[float] = None
    previous_trust: Optional[float] = None
    affinity_delta: Optional[float] = None
    trust_delta: Optional[float] = None
    dialogue_count: Optional[int] = None
    total_dialogue_count: Optional[int] = None
    session_duration_minutes: Optional[float] = None
    unlocked_content: Optional[list[str]] = None
    character_relationships: Optional[dict[str, dict]] = None
    event_history: Optional[list[dict]] = None
    world_time: Optional[str] = None
    event_data: dict = Field(default_factory=dict)


class EventSimulationResponse(BaseModel):
    matched: bool
    evaluation: dict
    context: dict
    planned_result: Optional[dict] = None


class EventScheduleItem(BaseModel):
    event_id: str
    character_id: str
    player_id: str
    schedule: str
    last_checked_at: Optional[str] = None
    last_run_at: Optional[str] = None
    next_run_at: Optional[str] = None
    status: str
    lease_owner: Optional[str] = None
    lease_expires_at: Optional[str] = None
    last_error: Optional[str] = None
    last_failed_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class EventMetricsResponse(BaseModel):
    matched_count: int
    succeeded_count: int
    failed_count: int
    partial_count: int
    skipped_count: int
    deduplicated_count: int
    average_duration_ms: float
    last_execution_at: Optional[str] = None
    last_error: Optional[str] = None


class EventContextStateItem(BaseModel):
    event_id: str
    character_id: str
    player_id: str
    context_data: dict
    status: str
    progress: float
    last_session_id: Optional[str] = None
    updated_at: Optional[str] = None


def _require_owned_character(
    current_user_id: str,
    character_id: Optional[str],
) -> Optional[str]:
    """Validate an optional event character and return its normalized ID."""
    normalized_id = str(character_id or "").strip()
    if not normalized_id:
        return None
    character = repository.get_character_card_from_db(
        current_user_id,
        normalized_id,
        include_inactive=True,
    )
    if not character:
        raise HTTPException(status_code=404, detail=f"角色 '{normalized_id}' 不存在")
    return normalized_id


UNIMPLEMENTED_EFFECTS = {
    EffectType.GRANT_ITEM,
    EffectType.START_QUEST,
    EffectType.MODIFY_RELATIONSHIP,
}
UNIMPLEMENTED_TRIGGERS = {
    TriggerType.ITEM_ACQUIRED,
    TriggerType.QUEST_COMPLETED,
    TriggerType.RELATIONSHIP_CHANGE,
}


def sanitize_schedule(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _validate_cron(schedule: str) -> None:
    try:
        validate_cron_schedule(schedule)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"cron 表达式无效: {exc}") from exc


def _validate_condition_semantics(
    condition: TriggerCondition,
    current_user_id: str,
) -> None:
    if condition.trigger_type in UNIMPLEMENTED_TRIGGERS:
        raise HTTPException(
            status_code=400,
            detail=f"触发类型 {condition.trigger_type.value} 尚未实现，不能保存",
        )
    if condition.comparison not in {"gte", ">=", "lte", "<=", "eq", "==", "gt", ">", "lt", "<"}:
        raise HTTPException(status_code=400, detail="比较运算符无效")
    if condition.trigger_type in {TriggerType.KEYWORD_MATCH, TriggerType.NPC_KEYWORD_MATCH}:
        if not any(str(keyword or "").strip() for keyword in condition.keywords or []):
            raise HTTPException(status_code=400, detail="关键词触发条件至少需要一个非空关键词")
        if condition.match_mode not in {"any", "all", "exact", "whole_word", "regex"}:
            raise HTTPException(status_code=400, detail="关键词匹配模式无效")
        if condition.match_mode == "regex":
            try:
                for pattern in condition.keywords or []:
                    re.compile(pattern)
            except re.error as exc:
                raise HTTPException(status_code=400, detail=f"关键词正则表达式无效: {exc}") from exc
    if condition.trigger_type in {TriggerType.AFFINITY_THRESHOLD, TriggerType.TRUST_THRESHOLD, TriggerType.STATE_DELTA}:
        if condition.threshold is None:
            raise HTTPException(status_code=400, detail="阈值触发条件必须提供 threshold")
    if condition.trigger_type == TriggerType.DIALOGUE_COUNT:
        if condition.count is None or condition.count < 0:
            raise HTTPException(status_code=400, detail="对话次数条件必须提供非负 count")
    if condition.trigger_type == TriggerType.TIME_BASED:
        if condition.duration_minutes is None and not condition.schedule:
            raise HTTPException(status_code=400, detail="时间条件必须提供 duration_minutes 或 schedule")
        if condition.duration_minutes is not None and condition.duration_minutes < 0:
            raise HTTPException(status_code=400, detail="duration_minutes 不能为负数")
    if condition.trigger_type == TriggerType.MOOD_MATCH and not str(condition.mood or "").strip():
        raise HTTPException(status_code=400, detail="情绪条件必须提供 mood")
    if condition.trigger_type == TriggerType.STATE_DELTA and condition.state_field not in {"affinity", "trust"}:
        raise HTTPException(status_code=400, detail="状态变化条件的 state_field 必须为 affinity 或 trust")
    if condition.trigger_type == TriggerType.EVENT_HISTORY:
        if not condition.event_id or not repository.get_event_definition(current_user_id, condition.event_id):
            raise HTTPException(status_code=400, detail="事件历史条件引用了不存在的当前用户事件")
        if condition.event_status not in {"succeeded", "failed", "partial", "skipped"}:
            raise HTTPException(status_code=400, detail="事件历史状态无效")
    if condition.trigger_type == TriggerType.WORLD_TIME_WINDOW:
        if not condition.time_window_start or not condition.time_window_end:
            raise HTTPException(status_code=400, detail="世界时间窗口需要开始和结束时间")
        try:
            datetime.strptime(condition.time_window_start, "%H:%M")
            datetime.strptime(condition.time_window_end, "%H:%M")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="世界时间窗口必须使用 HH:MM") from exc
        if any(day < 0 or day > 6 for day in condition.weekdays or []):
            raise HTTPException(status_code=400, detail="weekdays 必须位于 0 到 6")
    if condition.trigger_type == TriggerType.COMPOSITE:
        if not condition.sub_conditions:
            raise HTTPException(status_code=400, detail="复合条件至少需要一个子条件")
        if condition.logic_operator not in {"and", "or"}:
            raise HTTPException(status_code=400, detail="复合条件逻辑运算符必须为 and 或 or")
    if condition.schedule:
        _validate_cron(condition.schedule)
    for child in condition.sub_conditions or []:
        _validate_condition_semantics(child, current_user_id)


def _validate_effect_semantics(
    effect: EventEffect,
    current_user_id: str,
) -> None:
    if effect.effect_type in UNIMPLEMENTED_EFFECTS:
        raise HTTPException(
            status_code=400,
            detail=f"效果 {effect.effect_type.value} 尚未实现，不能保存",
        )
    if effect.effect_type == EffectType.MODIFY_STATE:
        if not effect.state_changes:
            raise HTTPException(status_code=400, detail="修改状态效果必须提供 state_changes")
        unknown = set(effect.state_changes) - {"affection_level", "trust_level", "current_mood"}
        if unknown:
            raise HTTPException(status_code=400, detail=f"不支持的状态字段: {', '.join(sorted(unknown))}")
    if effect.effect_type == EffectType.UNLOCK_CONTENT and not any(
        str(key or "").strip() for key in effect.unlock_keys or []
    ):
        raise HTTPException(status_code=400, detail="解锁内容效果至少需要一个 unlock_key")
    if effect.effect_type == EffectType.TRIGGER_DIALOGUE and not str(effect.dialogue_text or "").strip():
        raise HTTPException(status_code=400, detail="触发对话效果必须提供 dialogue_text")
    if effect.effect_type == EffectType.ADD_MEMORY and not str(effect.memory_text or "").strip():
        raise HTTPException(status_code=400, detail="添加记忆效果必须提供 memory_text")
    if effect.effect_type == EffectType.CHANGE_MOOD and not str(effect.target_mood or "").strip():
        raise HTTPException(status_code=400, detail="改变情绪效果必须提供 target_mood")
    if effect.effect_type == EffectType.NOTIFY_PLAYER and not str(effect.notification_message or "").strip():
        raise HTTPException(status_code=400, detail="通知效果必须提供 notification_message")
    referenced_events: list[str] = []
    if effect.effect_type == EffectType.TRIGGER_EVENT and effect.next_event_id:
        referenced_events.append(effect.next_event_id)
    if effect.effect_type == EffectType.BRANCH_EVENT:
        if effect.next_event_id:
            referenced_events.append(effect.next_event_id)
        referenced_events.extend(
            str(branch.get("event_id") or "") for branch in effect.branch_conditions or []
        )
    for event_id in referenced_events:
        if not event_id or not repository.get_event_definition(current_user_id, event_id):
            raise HTTPException(status_code=400, detail=f"引用事件 '{event_id}' 不存在或不属于当前用户")
    if effect.effect_type == EffectType.BRANCH_EVENT and not effect.branch_conditions:
        raise HTTPException(status_code=400, detail="分支事件效果必须提供 branch_conditions")
    if effect.effect_type == EffectType.BRANCH_EVENT:
        for branch in effect.branch_conditions or []:
            condition_data = branch.get("condition")
            if not condition_data:
                raise HTTPException(status_code=400, detail="分支事件缺少 condition")
            try:
                branch_condition = TriggerCondition.model_validate(condition_data)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"分支条件无效: {exc}") from exc
            _validate_condition_semantics(branch_condition, current_user_id)
    for character_id in (effect.target_character_id, effect.proactive_character_id):
        if character_id:
            _require_owned_character(current_user_id, character_id)
    if (
        effect.effect_type == EffectType.NPC_PROACTIVE_DIALOGUE
        and effect.target_session_id
    ):
        target_session = repository.get_session(effect.target_session_id)
        if (
            not target_session
            or target_session.get("player_id") != current_user_id
            or not target_session.get("is_multi_character")
            or target_session.get("status") == "ended"
        ):
            raise HTTPException(
                status_code=404,
                detail="NPC 主动对白目标群聊不存在或不属于当前用户",
            )
        if effect.proactive_character_id:
            participant_ids = {
                item["character_id"]
                for item in repository.get_session_participants(
                    effect.target_session_id,
                    only_active=True,
                )
            }
            if effect.proactive_character_id not in participant_ids:
                raise HTTPException(
                    status_code=400,
                    detail="主动发言角色不是目标群聊的活跃参与者",
                )
    if effect.effect_type == EffectType.UPDATE_EVENT_PROGRESS:
        if effect.event_status and effect.event_status not in {"pending", "active", "completed", "failed"}:
            raise HTTPException(status_code=400, detail="事件进度状态无效")
        if effect.progress is not None and not 0 <= effect.progress <= 1:
            raise HTTPException(status_code=400, detail="事件进度必须位于 0 到 1")


def _validate_event_configuration(
    trigger_condition: TriggerConditionDTO,
    effects: list[EventEffectDTO],
    current_user_id: str,
) -> tuple[TriggerCondition, list[EventEffect]]:
    try:
        condition = TriggerCondition.model_validate(trigger_condition.model_dump())
        parsed_effects = [EventEffect.model_validate(effect.model_dump()) for effect in effects]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"配置校验失败: {exc}") from exc
    _validate_condition_semantics(condition, current_user_id)
    for effect in parsed_effects:
        _validate_effect_semantics(effect, current_user_id)
    return condition, parsed_effects


def _build_definition_schedule_state(
    *,
    event_id: str,
    character_id: str | None,
    player_id: str,
    schedule: str | None,
    is_active: bool = True,
) -> dict | None:
    if not schedule:
        return None
    if not character_id:
        raise HTTPException(status_code=400, detail="定时事件必须绑定角色")
    _validate_cron(schedule)
    return event_runtime.build_time_event_schedule_state(
        event_id=event_id,
        character_id=character_id,
        player_id=player_id,
        schedule=schedule,
        status="active" if is_active else "paused",
    )


# =========================
# 列出事件
# =========================

@router.get("/admin/events", response_model=list[EventListItem])
def list_events(
    character_id: Optional[str] = None,
    only_active: bool = False,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    列出事件定义列表

    - character_id: 过滤某角色专属事件（同时返回全局事件）
    - only_active: 是否仅返回启用事件
    """
    try:
        rows = repository.list_event_definitions(
            owner_user_id=current_user_id,
            character_id=character_id,
            only_active=only_active,
        )
        schedules_by_event: dict[str, list[dict]] = {}
        for schedule_state in repository.list_event_schedules_for_player(
            current_user_id
        ):
            schedules_by_event.setdefault(schedule_state["event_id"], []).append(
                schedule_state
            )
        result = []
        for r in rows:
            try:
                trigger_cfg = json.loads(r["trigger_config"])
                trigger_type = trigger_cfg.get("trigger_type")
            except Exception:
                trigger_type = None

            event_schedules = schedules_by_event.get(r["event_id"], [])
            event_schedules.sort(
                key=lambda item: (
                    item.get("next_due_real_at") is None,
                    item.get("next_due_real_at") or item.get("next_run_at") or "",
                )
            )
            next_schedule = event_schedules[0] if event_schedules else {}

            result.append(EventListItem(
                event_id=r["event_id"],
                event_name=r["event_name"],
                description=r.get("description"),
                character_id=r.get("character_id"),
                story_id=r.get("story_id"),
                priority=r.get("priority", 0),
                exclusive_group=r.get("exclusive_group"),
                exclusive_scope=r.get("exclusive_scope") or "turn",
                max_triggers_per_turn=r.get("max_triggers_per_turn") or 3,
                stop_processing=bool(r.get("stop_processing", 0)),
                is_active=bool(r.get("is_active", 1)),
                trigger_count=r.get("trigger_count", 0),
                last_triggered_at=r.get("last_triggered_at"),
                created_at=r.get("created_at"),
                updated_at=r.get("updated_at"),
                trigger_type=trigger_type,
                schedule=r.get("schedule"),
                template_id=r.get("template_id"),
                next_run_at=next_schedule.get("next_run_at"),
                next_due_real_at=next_schedule.get("next_due_real_at"),
                missed_count=sum(
                    int(item.get("missed_count") or 0)
                    for item in event_schedules
                ),
            ))
        return result
    except Exception as e:
        logger.error(f"列出事件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# 获取事件详情
# =========================

@router.get("/admin/events/{event_id}", response_model=EventDetail)
def get_event(
    event_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """获取单个事件的完整定义"""
    row = repository.get_event_definition(current_user_id, event_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    try:
        trigger_cfg = json.loads(row["trigger_config"])
        effects_cfg = json.loads(row["effects_config"])
        trigger_type = trigger_cfg.get("trigger_type")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析事件配置失败: {e}")

    return EventDetail(
        event_id=row["event_id"],
        event_name=row["event_name"],
        description=row.get("description"),
        character_id=row.get("character_id"),
        story_id=row.get("story_id"),
        priority=row.get("priority", 0),
        exclusive_group=row.get("exclusive_group"),
        exclusive_scope=row.get("exclusive_scope") or "turn",
        max_triggers_per_turn=row.get("max_triggers_per_turn") or 3,
        stop_processing=bool(row.get("stop_processing", 0)),
        is_active=bool(row.get("is_active", 1)),
        trigger_count=row.get("trigger_count", 0),
        last_triggered_at=row.get("last_triggered_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        trigger_type=trigger_type,
        schedule=row.get("schedule"),
        template_id=row.get("template_id"),
        trigger_condition=trigger_cfg,
        effects=effects_cfg,
    )


# =========================
# 创建事件
# =========================

@router.post("/admin/events", response_model=OperationResponse)
def create_event(
    req: EventCreateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    创建事件定义

    trigger_condition 和 effects 均在运行时通过 Pydantic 校验，
    以 JSON 字符串形式存储于数据库。
    """
    # 检查 ID 是否已存在
    existing = repository.get_event_definition(current_user_id, req.event_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"事件 '{req.event_id}' 已存在，请使用更新接口",
        )

    character_id = _require_owned_character(current_user_id, req.character_id)

    _validate_event_configuration(
        req.trigger_condition,
        req.effects,
        current_user_id,
    )
    schedule = sanitize_schedule(req.schedule) or sanitize_schedule(
        req.trigger_condition.schedule
    )
    if schedule:
        _validate_cron(schedule)
        if not character_id:
            raise HTTPException(status_code=400, detail="定时事件必须绑定角色")

    trigger_json = req.trigger_condition.model_dump_json()
    effects_json = json.dumps(
        [e.model_dump() for e in req.effects], ensure_ascii=False
    )

    schedule_state = _build_definition_schedule_state(
        event_id=req.event_id,
        character_id=character_id,
        player_id=current_user_id,
        schedule=schedule,
        is_active=req.is_active,
    )
    success = repository.save_event_definition_with_schedule(
        owner_user_id=current_user_id,
        event_id=req.event_id,
        event_name=req.event_name,
        trigger_config=trigger_json,
        effects_config=effects_json,
        schedule_state=schedule_state,
        character_id=character_id,
        story_id=req.story_id,
        description=req.description,
        priority=req.priority,
        exclusive_group=req.exclusive_group,
        exclusive_scope=req.exclusive_scope,
        max_triggers_per_turn=req.max_triggers_per_turn,
        stop_processing=req.stop_processing,
        is_active=req.is_active,
        schedule=schedule,
        template_id=req.template_id,
    )

    if not success:
        raise HTTPException(status_code=500, detail="保存事件到数据库失败")

    return OperationResponse(
        success=True,
        message=f"事件 '{req.event_id}' 创建成功",
        event_id=req.event_id,
    )


# =========================
# 更新事件
# =========================

@router.put("/admin/events/{event_id}", response_model=OperationResponse)
def update_event(
    event_id: str,
    req: EventUpdateRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    更新事件定义（仅更新传入的字段，未传入的保持原值）
    """
    existing = repository.get_event_definition(current_user_id, event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    # 合并字段
    event_name = req.event_name or existing["event_name"]
    description = req.description if req.description is not None else existing.get("description")
    priority = req.priority if req.priority is not None else existing.get("priority", 0)
    exclusive_group = (
        req.exclusive_group
        if "exclusive_group" in req.model_fields_set
        else existing.get("exclusive_group")
    )
    exclusive_scope = req.exclusive_scope or existing.get("exclusive_scope") or "turn"
    max_triggers_per_turn = (
        req.max_triggers_per_turn
        if req.max_triggers_per_turn is not None
        else existing.get("max_triggers_per_turn") or 3
    )
    stop_processing = (
        req.stop_processing
        if req.stop_processing is not None
        else bool(existing.get("stop_processing", 0))
    )
    is_active = req.is_active if req.is_active is not None else bool(existing.get("is_active", 1))
    schedule = (
        sanitize_schedule(req.schedule)
        or sanitize_schedule(
            req.trigger_condition.schedule if req.trigger_condition else None
        )
        if "schedule" in req.model_fields_set
        else existing.get("schedule")
    )
    template_id = (
        req.template_id
        if "template_id" in req.model_fields_set
        else existing.get("template_id")
    )
    character_id = existing.get("character_id")
    if "character_id" in req.model_fields_set:
        character_id = _require_owned_character(current_user_id, req.character_id)
    story_id = (
        req.story_id
        if "story_id" in req.model_fields_set
        else existing.get("story_id")
    )

    condition_dto = req.trigger_condition or TriggerConditionDTO.model_validate_json(
        existing["trigger_config"]
    )
    effects_dto = req.effects
    if effects_dto is None:
        effects_dto = [
            EventEffectDTO.model_validate(item)
            for item in json.loads(existing["effects_config"])
        ]
    _validate_event_configuration(condition_dto, effects_dto, current_user_id)
    trigger_json = condition_dto.model_dump_json()
    effects_json = json.dumps(
        [effect.model_dump() for effect in effects_dto],
        ensure_ascii=False,
    )
    if schedule:
        _validate_cron(schedule)
        if not character_id:
            raise HTTPException(status_code=400, detail="定时事件必须绑定角色")

    schedule_state = _build_definition_schedule_state(
        event_id=event_id,
        character_id=character_id,
        player_id=current_user_id,
        schedule=schedule,
        is_active=is_active,
    )
    success = repository.save_event_definition_with_schedule(
        owner_user_id=current_user_id,
        event_id=event_id,
        event_name=event_name,
        trigger_config=trigger_json,
        effects_config=effects_json,
        schedule_state=schedule_state,
        character_id=character_id,
        story_id=story_id,
        description=description,
        priority=priority,
        exclusive_group=exclusive_group,
        exclusive_scope=exclusive_scope,
        max_triggers_per_turn=max_triggers_per_turn,
        stop_processing=stop_processing,
        is_active=is_active,
        schedule=schedule,
        template_id=template_id,
    )

    if not success:
        raise HTTPException(status_code=500, detail="更新事件失败")

    return OperationResponse(
        success=True,
        message=f"事件 '{event_id}' 更新成功",
        event_id=event_id,
    )


# =========================
# 删除事件
# =========================

@router.delete("/admin/events/{event_id}", response_model=OperationResponse)
def delete_event(
    event_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """永久删除事件定义及其触发记录（不可恢复）"""
    existing = repository.get_event_definition(current_user_id, event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    success = repository.delete_event_definition(current_user_id, event_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除事件失败")

    return OperationResponse(
        success=True,
        message=f"事件 '{event_id}' 已删除",
        event_id=event_id,
    )


# =========================
# 启用 / 禁用事件
# =========================

@router.post("/admin/events/{event_id}/toggle", response_model=OperationResponse)
def toggle_event(
    event_id: str,
    active: bool,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    切换事件启用状态

    - active=true  → 启用
    - active=false → 禁用（不删除数据，对话流程中自动跳过）
    """
    existing = repository.get_event_definition(current_user_id, event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    character_id = existing.get("character_id")
    schedule = existing.get("schedule")
    schedule_state = _build_definition_schedule_state(
        event_id=event_id,
        character_id=character_id,
        player_id=current_user_id,
        schedule=schedule,
        is_active=active,
    )
    success = repository.save_event_definition_with_schedule(
        owner_user_id=current_user_id,
        event_id=event_id,
        event_name=existing["event_name"],
        trigger_config=existing["trigger_config"],
        effects_config=existing["effects_config"],
        schedule_state=schedule_state,
        character_id=character_id,
        description=existing.get("description"),
        priority=existing.get("priority", 0),
        exclusive_group=existing.get("exclusive_group"),
        exclusive_scope=existing.get("exclusive_scope") or "turn",
        max_triggers_per_turn=existing.get("max_triggers_per_turn") or 3,
        stop_processing=bool(existing.get("stop_processing", 0)),
        is_active=active,
        schedule=schedule,
        template_id=existing.get("template_id"),
    )

    if not success:
        raise HTTPException(status_code=500, detail="切换事件状态失败")

    status_text = "已启用" if active else "已禁用"
    return OperationResponse(
        success=True,
        message=f"事件 '{event_id}' {status_text}",
        event_id=event_id,
    )


# =========================
# 查询触发历史
# =========================

@router.get("/admin/events/{event_id}/history", response_model=list[TriggerLogItem])
def get_trigger_history(
    event_id: str,
    character_id: Optional[str] = None,
    player_id: Optional[str] = None,
    limit: int = 50,
    current_user_id: str = Depends(require_current_user_id),
):
    """查询指定事件的触发历史记录"""
    if player_id and player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的事件历史")
    rows = repository.get_event_trigger_history(
        event_id=event_id,
        character_id=character_id,
        player_id=current_user_id,
        limit=limit,
    )
    return [TriggerLogItem(**r) for r in rows]


@router.get("/admin/events/history/all", response_model=list[TriggerLogItem])
def get_all_trigger_history(
    character_id: Optional[str] = None,
    player_id: Optional[str] = None,
    limit: int = 100,
    current_user_id: str = Depends(require_current_user_id),
):
    """查询所有事件的触发历史（可按角色/玩家过滤）"""
    if player_id and player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的事件历史")
    rows = repository.get_event_trigger_history(
        character_id=character_id,
        player_id=current_user_id,
        limit=limit,
    )
    return [TriggerLogItem(**r) for r in rows]


# =========================
# 重置触发记录（调试用）
# =========================

@router.delete("/admin/events/{event_id}/history", response_model=OperationResponse)
def reset_trigger_history(
    event_id: str,
    character_id: str,
    player_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    """
    删除指定事件对某玩家的触发记录

    用途：开发调试时重置一次性事件的触发状态，使其可以再次触发。
    生产环境慎用。
    """
    if player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的事件历史")
    count = repository.delete_trigger_history(event_id, character_id, player_id)
    return OperationResponse(
        success=True,
        message=f"已清除 {count} 条触发记录",
        event_id=event_id,
    )


# =========================
# 事件深度集成：模板 / 调度 / 上下文
# =========================

@router.get("/admin/event-templates", response_model=list[EventTemplateItem])
def list_event_templates(
    category: Optional[str] = None,
    current_user_id: str = Depends(require_current_user_id),
):
    """列出内置和已保存的事件模板。"""
    event_runtime.ensure_default_event_templates()
    rows = repository.list_event_templates(category=category)
    result = []
    for row in rows:
        try:
            trigger_config = json.loads(row["trigger_config"])
            effects_config = json.loads(row["effects_config"])
            metadata = json.loads(row["metadata"]) if row.get("metadata") else None
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"解析事件模板失败: {e}")
        result.append(EventTemplateItem(
            template_id=row["template_id"],
            template_name=row["template_name"],
            category=row.get("category"),
            description=row.get("description"),
            trigger_config=trigger_config,
            effects_config=effects_config,
            metadata=metadata,
        ))
    return result


@router.post("/admin/event-templates", response_model=OperationResponse)
def create_event_template(
    req: EventTemplateCreateRequest,
    current_user_id: str = Depends(require_admin_user_id),
):
    """创建或更新系统事件模板。仅作为开发维护 API 使用。"""
    _validate_event_configuration(
        req.trigger_config,
        req.effects_config,
        current_user_id,
    )

    success = repository.save_event_template(
        template_id=req.template_id,
        template_name=req.template_name,
        category=req.category,
        description=req.description,
        trigger_config=req.trigger_config.model_dump_json(),
        effects_config=json.dumps([e.model_dump() for e in req.effects_config], ensure_ascii=False),
        metadata=json.dumps(req.metadata, ensure_ascii=False) if req.metadata is not None else None,
    )
    if not success:
        raise HTTPException(status_code=500, detail="保存事件模板失败")

    return OperationResponse(
        success=True,
        message=f"事件模板 '{req.template_id}' 已保存",
        template_id=req.template_id,
    )


@router.delete("/admin/event-templates/{template_id}", response_model=OperationResponse)
def delete_event_template(
    template_id: str,
    current_user_id: str = Depends(require_admin_user_id),
):
    """删除系统事件模板。仅作为开发维护 API 使用。"""
    existing = repository.get_event_template(template_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件模板 '{template_id}' 不存在")

    success = repository.delete_event_template(template_id)
    if not success:
        raise HTTPException(status_code=500, detail="删除事件模板失败")

    return OperationResponse(
        success=True,
        message=f"事件模板 '{template_id}' 已删除",
        template_id=template_id,
    )


@router.post("/admin/events/schedules", response_model=OperationResponse)
def register_event_schedule(
    req: ScheduleRegisterRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    """注册一个时间驱动事件调度。schedule 使用 5 字段 cron 表达式。"""
    if req.player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的事件调度")
    existing = repository.get_event_definition(current_user_id, req.event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{req.event_id}' 不存在")
    character_id = _require_owned_character(current_user_id, req.character_id)
    if not character_id:
        raise HTTPException(status_code=400, detail="定时事件必须绑定角色")
    event_character_id = existing.get("character_id")
    if event_character_id and event_character_id != character_id:
        raise HTTPException(
            status_code=400,
            detail="角色专属事件只能注册到事件定义绑定的角色",
        )
    _validate_cron(req.schedule)

    try:
        success = event_runtime.register_time_event_schedule(
            event_id=req.event_id,
            character_id=character_id,
            player_id=req.player_id,
            schedule=req.schedule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"注册调度失败: {exc}") from exc
    except Exception as exc:
        logger.exception("注册事件调度失败", extra={"event_id": req.event_id})
        raise HTTPException(status_code=500, detail="注册事件调度失败") from exc
    if not success:
        raise HTTPException(status_code=500, detail="注册事件调度失败")

    return OperationResponse(
        success=True,
        message="事件调度已注册",
        event_id=req.event_id,
    )


@router.get("/admin/event-schedules", response_model=list[EventScheduleItem])
def list_event_schedules(
    event_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 200,
    current_user_id: str = Depends(require_current_user_id),
):
    if status and status not in {"active", "paused"}:
        raise HTTPException(status_code=400, detail="调度状态必须为 active 或 paused")
    return [
        EventScheduleItem(**row)
        for row in repository.list_event_schedules(
            current_user_id,
            event_id=event_id,
            status=status,
            limit=limit,
        )
    ]


@router.post(
    "/admin/event-schedules/{event_id}/{character_id}/pause",
    response_model=OperationResponse,
)
def pause_event_schedule(
    event_id: str,
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    if not repository.get_event_definition(current_user_id, event_id):
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")
    if not repository.set_event_schedule_status(
        event_id,
        character_id,
        current_user_id,
        "paused",
    ):
        raise HTTPException(status_code=404, detail="事件调度不存在")
    return OperationResponse(success=True, message="事件调度已暂停", event_id=event_id)


@router.post(
    "/admin/event-schedules/{event_id}/{character_id}/resume",
    response_model=OperationResponse,
)
def resume_event_schedule(
    event_id: str,
    character_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    schedule_state = repository.get_event_schedule(
        event_id,
        character_id,
        current_user_id,
    )
    if not schedule_state:
        raise HTTPException(status_code=404, detail="事件调度不存在")
    snapshot = event_runtime.world_clock.get_clock_snapshot(current_user_id)
    try:
        next_run_at = next_cron_run(
            schedule_state["schedule"],
            snapshot.world_now,
            timezone_name=snapshot.timezone,
        ).isoformat()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"无法恢复调度: {exc}") from exc
    if not repository.set_event_schedule_status(
        event_id,
        character_id,
        current_user_id,
        "active",
        next_run_at=next_run_at,
    ):
        raise HTTPException(status_code=404, detail="事件调度不存在")
    return OperationResponse(success=True, message="事件调度已恢复", event_id=event_id)


@router.get("/admin/event-metrics", response_model=EventMetricsResponse)
def get_event_metrics(
    event_id: Optional[str] = None,
    current_user_id: str = Depends(require_current_user_id),
):
    if event_id and not repository.get_event_definition(current_user_id, event_id):
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")
    return EventMetricsResponse(
        **repository.get_event_execution_metrics(current_user_id, event_id)
    )


@router.get("/admin/events/{event_id}/executions")
def list_event_executions(
    event_id: str,
    limit: int = 100,
    current_user_id: str = Depends(require_current_user_id),
):
    if not repository.get_event_definition(current_user_id, event_id):
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")
    return repository.list_event_execution_history(
        current_user_id,
        event_id=event_id,
        limit=limit,
    )


@router.post(
    "/admin/events/{event_id}/simulate",
    response_model=EventSimulationResponse,
)
def simulate_event(
    event_id: str,
    req: EventSimulationRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    row = repository.get_event_definition(current_user_id, event_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")
    event = event_runtime._event_definition_from_row(row)
    character_id = _require_owned_character(
        current_user_id,
        req.character_id or event.character_id,
    )
    if not character_id:
        raise HTTPException(status_code=400, detail="模拟全局事件时必须提供 character_id")

    session_id = req.session_id or f"simulate:{event_id}"
    state = repository.get_event_context_state(
        event_id,
        character_id,
        current_user_id,
    )
    context = event_runtime.build_event_context(
        character_id=character_id,
        player_id=current_user_id,
        session_id=session_id,
        current_affinity=(
            req.current_affinity if req.current_affinity is not None else 0.0
        ),
        current_trust=(
            req.current_trust if req.current_trust is not None else 0.0
        ),
        current_mood=req.current_mood or "neutral",
        previous_affinity=req.previous_affinity,
        previous_trust=req.previous_trust,
        affinity_delta=req.affinity_delta,
        trust_delta=req.trust_delta,
        player_message=req.player_message,
        npc_response=req.npc_response,
        character_relationships=req.character_relationships,
        event_data={
            **(json.loads(state["context_data"]) if state and state.get("context_data") else {}),
            **req.event_data,
        },
        world_time=req.world_time,
        trigger_source="simulation",
        current_user_turn_persisted=True,
    )
    updates = {}
    for key in (
        "dialogue_count",
        "total_dialogue_count",
        "session_duration_minutes",
        "unlocked_content",
        "event_history",
    ):
        value = getattr(req, key)
        if value is not None:
            updates[key] = value
    if updates:
        context = context.model_copy(update=updates)

    evaluation = event_runtime.get_event_detector().evaluate_event(event, context)
    planned_result = None
    if evaluation["matched"]:
        result, _ = event_runtime.get_event_executor().plan_event(
            event,
            context,
            execution_key=f"simulation:{event_id}",
        )
        planned_result = result.model_dump(mode="json")
    return EventSimulationResponse(
        matched=evaluation["matched"],
        evaluation=evaluation,
        context=context.model_dump(mode="json"),
        planned_result=planned_result,
    )


@router.post("/admin/events/schedules/run-due", response_model=ScheduleRunResponse)
def run_due_event_schedules(
    limit: int = 50,
    current_user_id: str = Depends(require_current_user_id),
):
    """手动检查并执行到期的时间驱动事件。"""
    try:
        results = event_runtime.run_due_time_events(limit=limit, player_id=current_user_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行调度失败: {e}")

    return ScheduleRunResponse(
        success=True,
        triggered_count=len(results),
        triggered_events=[
            {
                "event_id": r.event_id,
                "event_name": r.event_name,
                "effects": r.effects_applied,
                "chained_events": r.chained_events,
                "proactive_dialogues": r.proactive_dialogues,
            }
            for r in results
        ],
    )


@router.get("/admin/event-context", response_model=list[EventContextStateItem])
def list_event_context_states(
    character_id: Optional[str] = None,
    player_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    current_user_id: str = Depends(require_current_user_id),
):
    """查询跨会话持久化的事件上下文。"""
    if player_id and player_id != current_user_id:
        raise HTTPException(status_code=403, detail="无权访问该玩家的事件上下文")
    rows = repository.list_event_context_states(
        character_id=character_id,
        player_id=current_user_id,
        status=status,
        limit=limit,
    )
    result = []
    for row in rows:
        try:
            context_data = json.loads(row["context_data"])
        except Exception:
            context_data = {}
        result.append(EventContextStateItem(
            event_id=row["event_id"],
            character_id=row["character_id"],
            player_id=row["player_id"],
            context_data=context_data,
            status=row.get("status") or "active",
            progress=float(row.get("progress") or 0.0),
            last_session_id=row.get("last_session_id"),
            updated_at=row.get("updated_at"),
        ))
    return result
