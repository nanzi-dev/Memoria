"""
事件系统数据结构定义

用途：
- 定义事件的触发条件、执行效果等核心数据结构
- 支持多种触发类型（好感度、关键词、次数等）
- 支持多种效果类型（状态修改、解锁内容、触发剧情等）
"""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# =========================
# 触发器类型
# =========================
class TriggerType(str, Enum):
    """事件触发类型"""

    AFFINITY_THRESHOLD = "affinity_threshold"  # 好感度达到阈值
    TRUST_THRESHOLD = "trust_threshold"  # 信任度达到阈值
    KEYWORD_MATCH = "keyword_match"  # 关键词匹配
    DIALOGUE_COUNT = "dialogue_count"  # 对话次数达到
    TIME_BASED = "time_based"  # 基于时间（会话时长、真实时间等）
    ITEM_ACQUIRED = "item_acquired"  # 获得特定物品（枚举保留）
    QUEST_COMPLETED = "quest_completed"  # 完成任务（枚举保留）
    RELATIONSHIP_CHANGE = "relationship_change"  # 与其他角色关系变化
    MOOD_MATCH = "mood_match"  # 特定情绪状态
    NPC_KEYWORD_MATCH = "npc_keyword_match"  # NPC 回复关键词匹配
    STATE_DELTA = "state_delta"  # 好感度/信任度变化量
    EVENT_HISTORY = "event_history"  # 历史事件执行状态
    WORLD_TIME_WINDOW = "world_time_window"  # 玩家世界时间窗口
    COMPOSITE = "composite"  # 复合条件（多个条件组合）


# =========================
# 触发条件
# =========================
class TriggerCondition(BaseModel):
    """触发条件配置"""

    trigger_type: TriggerType

    # 通用参数
    threshold: float | None = None  # 阈值（用于好感度、信任度等）
    comparison: str | None = "gte"  # 比较运算符：gte(>=), lte(<=), eq(==), gt(>), lt(<)

    # 关键词匹配
    keywords: list[str] | None = None  # 关键词列表
    match_mode: str | None = "any"  # any（任一匹配）或 all（全部匹配）
    crossing: bool = False  # 仅在本轮跨过阈值时触发

    # 跨角色聚合
    aggregation: Literal["any", "all", "count"] = "any"
    min_characters: int | None = None  # count 聚合需要的最少满足角色数
    character_ids: list[str] | None = None  # 参与聚合的角色；空列表表示当前参与角色

    # 计数条件
    count: int | None = None  # 目标计数

    # 时间条件
    duration_minutes: int | None = None  # 会话时长（分钟）
    schedule: str | None = None  # cron 式调度表达式（简化为 5 字段 cron）
    catch_up_replay_limit: int = Field(default=1, ge=1, le=100)

    # 情绪条件
    mood: str | None = None  # 目标情绪

    # 状态变化量 / 事件历史 / 世界时间窗口
    state_field: str | None = None  # affinity / trust / relationship_type
    event_id: str | None = None  # 依赖的历史事件 ID
    event_status: str | None = "succeeded"  # 依赖事件状态
    min_occurrences: int | None = 1  # 最少历史执行次数
    time_window_start: str | None = None  # HH:MM
    time_window_end: str | None = None  # HH:MM
    weekdays: list[int] | None = None  # 0=Monday ... 6=Sunday

    # 关系变化条件
    target_character_id: str | None = None  # 关系变化条件的另一端角色（可为 @player）
    relationship_type: str | None = None  # 需要匹配的关系类型（可选）

    # 复合条件
    sub_conditions: list["TriggerCondition"] | None = None  # 子条件列表
    logic_operator: str | None = "and"  # and（全部满足）或 or（任一满足）

    # 冷却时间
    cooldown_hours: int | None = 0  # 触发后冷却时间（小时），0 表示只触发一次


# =========================
# 效果类型
# =========================
class EffectType(str, Enum):
    """事件效果类型"""

    MODIFY_STATE = "modify_state"  # 修改状态（好感度、信任度等）
    UNLOCK_CONTENT = "unlock_content"  # 解锁内容（对话选项、话题等）
    TRIGGER_DIALOGUE = "trigger_dialogue"  # 触发特定对话
    ADD_MEMORY = "add_memory"  # 添加记忆
    CHANGE_MOOD = "change_mood"  # 改变情绪
    NOTIFY_PLAYER = "notify_player"  # 通知玩家（UI 提示）
    GRANT_ITEM = "grant_item"  # 给予物品（枚举保留）
    START_QUEST = "start_quest"  # 开启任务（枚举保留）
    MODIFY_RELATIONSHIP = "modify_relationship"  # 修改与其他角色的关系
    TRIGGER_EVENT = "trigger_event"  # 触发另一个事件（事件链）
    BRANCH_EVENT = "branch_event"  # 按上下文分支触发事件
    NPC_PROACTIVE_DIALOGUE = "npc_proactive_dialogue"  # NPC 主动发言（多角色编排器）
    UPDATE_EVENT_PROGRESS = "update_event_progress"  # 更新多阶段事件状态/进度


# =========================
# 效果配置
# =========================
class EventEffect(BaseModel):
    """事件效果配置"""

    effect_type: EffectType

    # 状态修改
    state_changes: dict[str, Any] | None = (
        None  # 例如 {"affection_level": 5, "trust_level": 3}
    )

    # 解锁内容
    unlock_keys: list[str] | None = None  # 解锁的内容标识

    # 触发对话
    dialogue_text: str | None = None  # 特定对话内容
    dialogue_action: str | None = None  # 对应的动作

    # 添加记忆
    memory_text: str | None = None  # 要添加的记忆内容
    memory_importance: int | None = 5  # 记忆重要性

    # 改变情绪
    target_mood: str | None = None  # 目标情绪

    # 通知玩家
    notification_message: str | None = None  # 通知消息
    notification_type: str | None = "info"  # info, success, warning, error

    # 物品和任务（枚举保留，暂不开放执行）
    item_id: str | None = None
    quest_id: str | None = None

    # 关系修改
    target_character_id: str | None = None  # 目标角色 ID
    relationship_change: dict[str, Any] | None = None  # 关系变化

    # 事件链 / 分支
    next_event_id: str | None = None  # 后续事件 ID
    branch_conditions: list[dict[str, Any]] | None = (
        None  # [{"condition": TriggerCondition, "event_id": "..."}]
    )

    # NPC 主动对话
    target_session_id: str | None = None  # 目标多角色会话；为空时使用当前 session
    proactive_character_id: str | None = None  # 指定主动发言 NPC；为空时自动选择
    proactive_prompt: str | None = None  # 发言提示，默认由多角色编排器生成

    # 多阶段事件进度
    progress: float | None = None  # 直接设置进度（0.0 ~ 1.0）
    progress_delta: float | None = None  # 在当前进度上增减
    event_status: str | None = None  # pending / active / completed / failed


# =========================
# 事件定义
# =========================
class EventDefinition(BaseModel):
    """完整的事件定义"""

    event_id: str = Field(..., description="事件唯一标识")
    event_name: str = Field(..., description="事件名称")
    description: str | None = None

    # 作用域
    character_id: str | None = None  # 角色专属事件（None 表示全局事件）
    story_id: str | None = None  # 所属剧情聚合（None 表示不更新剧情状态）

    # 触发条件
    trigger_condition: TriggerCondition

    # 事件效果（可以有多个）
    effects: list[EventEffect] = Field(default_factory=list)

    # 优先级
    priority: int = Field(default=0, description="优先级，数字越大越优先")
    exclusive_group: str | None = None  # 同一轮同组只执行最高优先级事件
    exclusive_scope: Literal["turn", "player"] = "turn"
    max_triggers_per_turn: int = Field(default=3, ge=1, le=20)
    stop_processing: bool = False  # 触发后停止处理后续普通事件

    # 启用状态
    is_active: bool = Field(default=True, description="是否启用")

    # 元数据
    created_at: str | None = None
    updated_at: str | None = None

    # 触发统计
    trigger_count: int = Field(default=0, description="已触发次数")
    last_triggered_at: str | None = None

    # 深度集成元数据
    schedule: str | None = None  # 时间驱动事件的 cron 式调度
    template_id: str | None = None  # 来源模板 ID


# =========================
# 事件触发结果
# =========================
class EventTriggerResult(BaseModel):
    """事件触发结果"""

    event_id: str
    event_name: str
    character_id: str | None = None
    response_index: int | None = None
    triggered: bool = Field(default=False, description="是否成功触发")
    effects_applied: list[str] = Field(
        default_factory=list, description="已应用的效果列表"
    )
    notification: str | None = None  # 需要显示给玩家的通知
    dialogue_override: str | None = None  # 覆盖的对话内容
    state_changes: dict[str, Any] = Field(default_factory=dict)  # 状态变化
    chained_events: list[str] = Field(default_factory=list)  # 被链式触发的事件 ID
    proactive_dialogues: list[dict[str, Any]] = Field(
        default_factory=list
    )  # NPC 主动发言结果

    # 新执行契约；上面的字段保留一个兼容周期。
    execution_id: str | None = None
    execution_key: str | None = None
    status: str = "succeeded"  # succeeded / partial / failed / skipped
    effects: list["EffectExecutionDetail"] = Field(default_factory=list)
    notifications: list["EventNotification"] = Field(default_factory=list)
    dialogue_overrides: list[str] = Field(default_factory=list)
    error: str | None = None
    deduplicated: bool = False
    duration_ms: float = 0.0
    condition_trace: list[dict[str, Any]] = Field(default_factory=list)


class EffectExecutionDetail(BaseModel):
    """单个效果的可审计执行结果。"""

    index: int
    effect_type: str
    status: str = "succeeded"  # succeeded / failed / skipped / planned
    message: str | None = None
    error: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)


class EventNotification(BaseModel):
    """可返回给客户端或写入玩家收件箱的结构化通知。"""

    event_id: str
    message: str
    notification_type: str = "info"
    title: str | None = None


# =========================
# 事件上下文
# =========================
class EventContext(BaseModel):
    """事件检测上下文（传递给检测引擎的信息）"""

    character_id: str
    player_id: str
    session_id: str

    # 当前状态
    current_affinity: float
    current_trust: float
    current_mood: str
    previous_affinity: float | None = None
    previous_trust: float | None = None

    # 当前对话
    player_message: str
    npc_response: str | None = None

    # 统计信息
    dialogue_count: int  # 本次会话对话轮数
    total_dialogue_count: int  # 历史总对话轮数
    session_duration_minutes: float  # 会话时长
    affinity_delta: float = 0.0
    trust_delta: float = 0.0

    # 已解锁内容
    unlocked_content: list[str] = Field(default_factory=list)

    # 其他角色关系
    character_relationships: dict[str, dict] = Field(default_factory=dict)

    # 持久化上下文 / 调度信息
    event_data: dict[str, Any] = Field(default_factory=dict)
    event_history: list[dict[str, Any]] = Field(default_factory=list)
    world_time: str | None = None
    world_timezone: str | None = None
    last_event_id: str | None = None
    active_multi_session_id: str | None = None
    execution_key: str | None = None
    trigger_source: str = "dialogue"
    response_index: int | None = None


# 更新前向引用
TriggerCondition.model_rebuild()
EventTriggerResult.model_rebuild()
