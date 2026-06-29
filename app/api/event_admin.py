"""
事件系统管理 API

用途：
1. 事件定义的 CRUD 操作
2. 查询事件触发历史
3. 重置事件触发状态（用于调试）
"""

import json
import logging
from typing import Optional

from pydantic import BaseModel, Field
from fastapi import APIRouter, HTTPException

from app.core.event_schema import (
    EventDefinition,
    TriggerCondition,
    EventEffect,
    TriggerType,
    EffectType,
)
from app.db import repository

logger = logging.getLogger(__name__)
router = APIRouter()


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
    count: Optional[int] = None
    duration_minutes: Optional[int] = None
    mood: Optional[str] = None
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


class EventCreateRequest(BaseModel):
    event_id: str = Field(..., description="事件唯一 ID，建议格式: evt_{character}_{name}")
    event_name: str
    description: Optional[str] = None
    character_id: Optional[str] = None          # None 表示全局事件
    trigger_condition: TriggerConditionDTO
    effects: list[EventEffectDTO] = Field(default_factory=list)
    priority: int = 0
    is_active: bool = True


class EventUpdateRequest(BaseModel):
    event_name: Optional[str] = None
    description: Optional[str] = None
    trigger_condition: Optional[TriggerConditionDTO] = None
    effects: Optional[list[EventEffectDTO]] = None
    priority: Optional[int] = None
    is_active: Optional[bool] = None


class EventListItem(BaseModel):
    event_id: str
    event_name: str
    description: Optional[str] = None
    character_id: Optional[str] = None
    priority: int
    is_active: bool
    trigger_count: int
    last_triggered_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    # 触发类型摘要，方便前端展示
    trigger_type: Optional[str] = None


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


class OperationResponse(BaseModel):
    success: bool
    message: str
    event_id: Optional[str] = None


# =========================
# 列出事件
# =========================

@router.get("/admin/events", response_model=list[EventListItem])
def list_events(
    character_id: Optional[str] = None,
    only_active: bool = False,
):
    """
    列出事件定义列表

    - character_id: 过滤某角色专属事件（同时返回全局事件）
    - only_active: 是否仅返回启用事件
    """
    try:
        rows = repository.list_event_definitions(
            character_id=character_id,
            only_active=only_active,
        )
        result = []
        for r in rows:
            try:
                trigger_cfg = json.loads(r["trigger_config"])
                trigger_type = trigger_cfg.get("trigger_type")
            except Exception:
                trigger_type = None

            result.append(EventListItem(
                event_id=r["event_id"],
                event_name=r["event_name"],
                description=r.get("description"),
                character_id=r.get("character_id"),
                priority=r.get("priority", 0),
                is_active=bool(r.get("is_active", 1)),
                trigger_count=r.get("trigger_count", 0),
                last_triggered_at=r.get("last_triggered_at"),
                created_at=r.get("created_at"),
                updated_at=r.get("updated_at"),
                trigger_type=trigger_type,
            ))
        return result
    except Exception as e:
        logger.error(f"列出事件失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =========================
# 获取事件详情
# =========================

@router.get("/admin/events/{event_id}", response_model=EventDetail)
def get_event(event_id: str):
    """获取单个事件的完整定义"""
    row = repository.get_event_definition(event_id)
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
        priority=row.get("priority", 0),
        is_active=bool(row.get("is_active", 1)),
        trigger_count=row.get("trigger_count", 0),
        last_triggered_at=row.get("last_triggered_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
        trigger_type=trigger_type,
        trigger_condition=trigger_cfg,
        effects=effects_cfg,
    )


# =========================
# 创建事件
# =========================

@router.post("/admin/events", response_model=OperationResponse)
def create_event(req: EventCreateRequest):
    """
    创建事件定义

    trigger_condition 和 effects 均在运行时通过 Pydantic 校验，
    以 JSON 字符串形式存储于数据库。
    """
    # 检查 ID 是否已存在
    existing = repository.get_event_definition(req.event_id)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"事件 '{req.event_id}' 已存在，请使用更新接口",
        )

    # 将 DTO 转为 event_schema 对象进行深度校验
    try:
        TriggerCondition.model_validate(req.trigger_condition.model_dump())
        for eff in req.effects:
            EventEffect.model_validate(eff.model_dump())
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"配置校验失败: {e}")

    trigger_json = req.trigger_condition.model_dump_json()
    effects_json = json.dumps(
        [e.model_dump() for e in req.effects], ensure_ascii=False
    )

    success = repository.save_event_definition(
        event_id=req.event_id,
        event_name=req.event_name,
        trigger_config=trigger_json,
        effects_config=effects_json,
        character_id=req.character_id,
        description=req.description,
        priority=req.priority,
        is_active=req.is_active,
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
def update_event(event_id: str, req: EventUpdateRequest):
    """
    更新事件定义（仅更新传入的字段，未传入的保持原值）
    """
    existing = repository.get_event_definition(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    # 合并字段
    event_name = req.event_name or existing["event_name"]
    description = req.description if req.description is not None else existing.get("description")
    priority = req.priority if req.priority is not None else existing.get("priority", 0)
    is_active = req.is_active if req.is_active is not None else bool(existing.get("is_active", 1))

    if req.trigger_condition is not None:
        try:
            TriggerCondition.model_validate(req.trigger_condition.model_dump())
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"触发条件校验失败: {e}")
        trigger_json = req.trigger_condition.model_dump_json()
    else:
        trigger_json = existing["trigger_config"]

    if req.effects is not None:
        try:
            for eff in req.effects:
                EventEffect.model_validate(eff.model_dump())
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"效果配置校验失败: {e}")
        effects_json = json.dumps(
            [e.model_dump() for e in req.effects], ensure_ascii=False
        )
    else:
        effects_json = existing["effects_config"]

    success = repository.save_event_definition(
        event_id=event_id,
        event_name=event_name,
        trigger_config=trigger_json,
        effects_config=effects_json,
        character_id=existing.get("character_id"),
        description=description,
        priority=priority,
        is_active=is_active,
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
def delete_event(event_id: str):
    """永久删除事件定义及其触发记录（不可恢复）"""
    existing = repository.get_event_definition(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    success = repository.delete_event_definition(event_id)
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
def toggle_event(event_id: str, active: bool):
    """
    切换事件启用状态

    - active=true  → 启用
    - active=false → 禁用（不删除数据，对话流程中自动跳过）
    """
    existing = repository.get_event_definition(event_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"事件 '{event_id}' 不存在")

    success = repository.save_event_definition(
        event_id=event_id,
        event_name=existing["event_name"],
        trigger_config=existing["trigger_config"],
        effects_config=existing["effects_config"],
        character_id=existing.get("character_id"),
        description=existing.get("description"),
        priority=existing.get("priority", 0),
        is_active=active,
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
):
    """查询指定事件的触发历史记录"""
    rows = repository.get_event_trigger_history(
        event_id=event_id,
        character_id=character_id,
        player_id=player_id,
        limit=limit,
    )
    return [TriggerLogItem(**r) for r in rows]


@router.get("/admin/events/history/all", response_model=list[TriggerLogItem])
def get_all_trigger_history(
    character_id: Optional[str] = None,
    player_id: Optional[str] = None,
    limit: int = 100,
):
    """查询所有事件的触发历史（可按角色/玩家过滤）"""
    rows = repository.get_event_trigger_history(
        character_id=character_id,
        player_id=player_id,
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
):
    """
    删除指定事件对某玩家的触发记录

    用途：开发调试时重置一次性事件的触发状态，使其可以再次触发。
    生产环境慎用。
    """
    count = repository.delete_trigger_history(event_id, character_id, player_id)
    return OperationResponse(
        success=True,
        message=f"已清除 {count} 条触发记录",
        event_id=event_id,
    )