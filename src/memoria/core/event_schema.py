"""
事件系统数据结构定义

用途：
- 定义事件的触发条件、执行效果等核心数据结构
- 支持多种触发类型（好感度、关键词、次数等）
- 支持多种效果类型（状态修改、解锁内容、触发剧情等）
"""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# =========================
# 触发器类型
# =========================
class TriggerType(str, Enum):
    """事件触发类型"""
    AFFINITY_THRESHOLD = "affinity_threshold"      # 好感度达到阈值
    TRUST_THRESHOLD = "trust_threshold"            # 信任度达到阈值
    KEYWORD_MATCH = "keyword_match"                # 关键词匹配
    DIALOGUE_COUNT = "dialogue_count"              # 对话次数达到
    TIME_BASED = "time_based"                      # 基于时间（会话时长、真实时间等）
    ITEM_ACQUIRED = "item_acquired"                # 获得特定物品（扩展功能）
    QUEST_COMPLETED = "quest_completed"            # 完成任务（扩展功能）
    RELATIONSHIP_CHANGE = "relationship_change"     # 与其他角色关系变化
    MOOD_MATCH = "mood_match"                      # 特定情绪状态
    COMPOSITE = "composite"                        # 复合条件（多个条件组合）


# =========================
# 触发条件
# =========================
class TriggerCondition(BaseModel):
    """触发条件配置"""
    trigger_type: TriggerType
    
    # 通用参数
    threshold: Optional[float] = None              # 阈值（用于好感度、信任度等）
    comparison: Optional[str] = "gte"              # 比较运算符：gte(>=), lte(<=), eq(==), gt(>), lt(<)
    
    # 关键词匹配
    keywords: Optional[list[str]] = None           # 关键词列表
    match_mode: Optional[str] = "any"              # any（任一匹配）或 all（全部匹配）
    
    # 计数条件
    count: Optional[int] = None                    # 目标计数
    
    # 时间条件
    duration_minutes: Optional[int] = None         # 会话时长（分钟）
    schedule: Optional[str] = None                 # cron 式调度表达式（简化为 5 字段 cron）
    
    # 情绪条件
    mood: Optional[str] = None                     # 目标情绪
    
    # 复合条件
    sub_conditions: Optional[list["TriggerCondition"]] = None  # 子条件列表
    logic_operator: Optional[str] = "and"          # and（全部满足）或 or（任一满足）
    
    # 冷却时间
    cooldown_hours: Optional[int] = 0              # 触发后冷却时间（小时），0 表示只触发一次


# =========================
# 效果类型
# =========================
class EffectType(str, Enum):
    """事件效果类型"""
    MODIFY_STATE = "modify_state"                  # 修改状态（好感度、信任度等）
    UNLOCK_CONTENT = "unlock_content"              # 解锁内容（对话选项、话题等）
    TRIGGER_DIALOGUE = "trigger_dialogue"          # 触发特定对话
    ADD_MEMORY = "add_memory"                      # 添加记忆
    CHANGE_MOOD = "change_mood"                    # 改变情绪
    NOTIFY_PLAYER = "notify_player"                # 通知玩家（UI 提示）
    GRANT_ITEM = "grant_item"                      # 给予物品（扩展功能）
    START_QUEST = "start_quest"                    # 开启任务（扩展功能）
    MODIFY_RELATIONSHIP = "modify_relationship"    # 修改与其他角色的关系
    TRIGGER_EVENT = "trigger_event"                # 触发另一个事件（事件链）
    BRANCH_EVENT = "branch_event"                  # 按上下文分支触发事件
    NPC_PROACTIVE_DIALOGUE = "npc_proactive_dialogue"  # NPC 主动发言（多角色编排器）


# =========================
# 效果配置
# =========================
class EventEffect(BaseModel):
    """事件效果配置"""
    effect_type: EffectType
    
    # 状态修改
    state_changes: Optional[dict[str, Any]] = None  # 例如 {"affection_level": 5, "trust_level": 3}
    
    # 解锁内容
    unlock_keys: Optional[list[str]] = None        # 解锁的内容标识
    
    # 触发对话
    dialogue_text: Optional[str] = None            # 特定对话内容
    dialogue_action: Optional[str] = None          # 对应的动作
    
    # 添加记忆
    memory_text: Optional[str] = None              # 要添加的记忆内容
    memory_importance: Optional[int] = 5           # 记忆重要性
    
    # 改变情绪
    target_mood: Optional[str] = None              # 目标情绪
    
    # 通知玩家
    notification_message: Optional[str] = None     # 通知消息
    notification_type: Optional[str] = "info"      # info, success, warning, error
    
    # 物品和任务（扩展）
    item_id: Optional[str] = None
    quest_id: Optional[str] = None
    
    # 关系修改
    target_character_id: Optional[str] = None      # 目标角色 ID
    relationship_change: Optional[dict[str, Any]] = None  # 关系变化

    # 事件链 / 分支
    next_event_id: Optional[str] = None            # 后续事件 ID
    branch_conditions: Optional[list[dict[str, Any]]] = None  # [{"condition": TriggerCondition, "event_id": "..."}]

    # NPC 主动对话
    target_session_id: Optional[str] = None        # 目标多角色会话；为空时使用当前 session
    proactive_character_id: Optional[str] = None   # 指定主动发言 NPC；为空时自动选择
    proactive_prompt: Optional[str] = None         # 发言提示，默认由多角色编排器生成


# =========================
# 事件定义
# =========================
class EventDefinition(BaseModel):
    """完整的事件定义"""
    event_id: str = Field(..., description="事件唯一标识")
    event_name: str = Field(..., description="事件名称")
    description: Optional[str] = None
    
    # 作用域
    character_id: Optional[str] = None             # 角色专属事件（None 表示全局事件）
    
    # 触发条件
    trigger_condition: TriggerCondition
    
    # 事件效果（可以有多个）
    effects: list[EventEffect] = Field(default_factory=list)
    
    # 优先级
    priority: int = Field(default=0, description="优先级，数字越大越优先")
    
    # 启用状态
    is_active: bool = Field(default=True, description="是否启用")
    
    # 元数据
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    
    # 触发统计
    trigger_count: int = Field(default=0, description="已触发次数")
    last_triggered_at: Optional[str] = None

    # 深度集成元数据
    schedule: Optional[str] = None                 # 时间驱动事件的 cron 式调度
    template_id: Optional[str] = None              # 来源模板 ID


# =========================
# 事件触发结果
# =========================
class EventTriggerResult(BaseModel):
    """事件触发结果"""
    event_id: str
    event_name: str
    triggered: bool = Field(default=False, description="是否成功触发")
    effects_applied: list[str] = Field(default_factory=list, description="已应用的效果列表")
    notification: Optional[str] = None             # 需要显示给玩家的通知
    dialogue_override: Optional[str] = None        # 覆盖的对话内容
    state_changes: dict[str, Any] = Field(default_factory=dict)  # 状态变化
    chained_events: list[str] = Field(default_factory=list)      # 被链式触发的事件 ID
    proactive_dialogues: list[dict[str, Any]] = Field(default_factory=list)  # NPC 主动发言结果


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
    
    # 当前对话
    player_message: str
    npc_response: Optional[str] = None
    
    # 统计信息
    dialogue_count: int                            # 本次会话对话轮数
    total_dialogue_count: int                      # 历史总对话轮数
    session_duration_minutes: float                # 会话时长
    
    # 已解锁内容
    unlocked_content: list[str] = Field(default_factory=list)
    
    # 其他角色关系
    character_relationships: dict[str, dict] = Field(default_factory=dict)

    # 持久化上下文 / 调度信息
    event_data: dict[str, Any] = Field(default_factory=dict)
    last_event_id: Optional[str] = None
    active_multi_session_id: Optional[str] = None


# 更新前向引用
TriggerCondition.model_rebuild()
