"""
事件执行器

用途：
- 执行事件触发后的各种效果
- 支持多种效果类型（状态修改、解锁内容、添加记忆等）
- 返回执行结果供对话流程使用
"""

import json
import logging
from typing import Dict, Any

from app.core.event_schema import (
    EventDefinition,
    EventEffect,
    EventTriggerResult,
    EventContext,
    EffectType,
)
from app.db import repository

logger = logging.getLogger(__name__)


class EventExecutor:
    """事件执行器"""
    
    def __init__(self):
        pass
    
    def execute_event(
        self,
        event: EventDefinition,
        context: EventContext
    ) -> EventTriggerResult:
        """
        执行事件的所有效果
        
        Args:
            event: 事件定义
            context: 事件上下文
        
        Returns:
            事件触发结果
        """
        result = EventTriggerResult(
            event_id=event.event_id,
            event_name=event.event_name,
            triggered=True
        )
        
        # 执行所有效果
        for effect in event.effects:
            try:
                self._execute_single_effect(effect, context, result)
            except Exception as e:
                logger.error(f"执行事件效果失败: {event.event_id}, 效果类型: {effect.effect_type}, 错误: {e}")
        
        # 记录触发日志
        self._log_trigger(event, context, result)
        
        # 更新事件触发计数
        repository.increment_event_trigger_count(event.event_id)
        
        return result
    
    def _execute_single_effect(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """执行单个效果"""
        
        effect_type = effect.effect_type
        effect_name = effect_type.value
        
        # 修改状态
        if effect_type == EffectType.MODIFY_STATE:
            self._apply_state_changes(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 状态已修改")
        
        # 解锁内容
        elif effect_type == EffectType.UNLOCK_CONTENT:
            self._unlock_content(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 内容已解锁")
        
        # 触发对话
        elif effect_type == EffectType.TRIGGER_DIALOGUE:
            self._trigger_dialogue(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 对话已触发")
        
        # 添加记忆
        elif effect_type == EffectType.ADD_MEMORY:
            self._add_memory(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 记忆已添加")
        
        # 改变情绪
        elif effect_type == EffectType.CHANGE_MOOD:
            self._change_mood(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 情绪已改变")
        
        # 通知玩家
        elif effect_type == EffectType.NOTIFY_PLAYER:
            self._notify_player(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 通知已发送")
        
        # 修改关系
        elif effect_type == EffectType.MODIFY_RELATIONSHIP:
            self._modify_relationship(effect, context, result)
            result.effects_applied.append(f"{effect_name}: 关系已修改")
        
        # 其他效果类型（扩展功能）
        elif effect_type in [EffectType.GRANT_ITEM, EffectType.START_QUEST]:
            logger.info(f"效果类型 {effect_type} 暂未实现，跳过")
            result.effects_applied.append(f"{effect_name}: 暂未实现")
        
        else:
            logger.warning(f"未知的效果类型: {effect_type}")
    
    def _apply_state_changes(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """应用状态修改"""
        if not effect.state_changes:
            return
        
        # 记录状态变化到结果
        result.state_changes.update(effect.state_changes)
        
        logger.debug(f"状态变化: {effect.state_changes}")
    
    def _unlock_content(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """解锁内容（标记到上下文中）"""
        if not effect.unlock_keys:
            return
        
        # 将解锁的内容标记记录到结果中
        # 实际解锁逻辑由调用方处理
        for key in effect.unlock_keys:
            if "unlocked_content" not in result.state_changes:
                result.state_changes["unlocked_content"] = []
            result.state_changes["unlocked_content"].append(key)
        
        logger.info(f"内容已解锁: {effect.unlock_keys}")
    
    def _trigger_dialogue(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """触发特定对话"""
        if effect.dialogue_text:
            # 覆盖当前对话
            result.dialogue_override = effect.dialogue_text
            logger.info(f"对话已覆盖: {effect.dialogue_text[:50]}...")
    
    def _add_memory(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """添加长期记忆"""
        if not effect.memory_text:
            return
        
        # 保存到长期记忆
        fact_id = repository.save_long_term_fact(
            character_id=context.character_id,
            player_id=context.player_id,
            fact_text=effect.memory_text,
            importance=effect.memory_importance or 5
        )
        
        logger.info(f"记忆已添加: {effect.memory_text}")
    
    def _change_mood(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """改变角色情绪"""
        if effect.target_mood:
            result.state_changes["current_mood"] = effect.target_mood
            logger.debug(f"情绪改变为: {effect.target_mood}")
    
    def _notify_player(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """通知玩家"""
        if effect.notification_message:
            result.notification = effect.notification_message
            logger.info(f"玩家通知: {effect.notification_message}")
    
    def _modify_relationship(
        self,
        effect: EventEffect,
        context: EventContext,
        result: EventTriggerResult
    ):
        """修改与其他角色的关系"""
        if not effect.target_character_id or not effect.relationship_change:
            return
        
        target_char_id = effect.target_character_id
        rel_changes = effect.relationship_change
        
        # 更新关系亲密度
        if "affinity" in rel_changes:
            affinity_delta = rel_changes["affinity"]
            repository.update_relationship_affinity(
                context.character_id,
                target_char_id,
                affinity_delta
            )
            logger.info(f"角色关系已修改: {context.character_id} <-> {target_char_id}, 亲密度变化: {affinity_delta}")
    
    def _log_trigger(
        self,
        event: EventDefinition,
        context: EventContext,
        result: EventTriggerResult
    ):
        """记录事件触发日志"""
        try:
            # 保存触发记录
            repository.log_event_trigger(
                event_id=event.event_id,
                character_id=context.character_id,
                player_id=context.player_id,
                session_id=context.session_id,
                context_snapshot=context.model_dump_json(),
                effects_applied=json.dumps(result.effects_applied, ensure_ascii=False)
            )
        except Exception as e:
            logger.error(f"记录事件触发日志失败: {e}")


# =========================
# 全局单例
# =========================
_executor_instance = None

def get_event_executor() -> EventExecutor:
    """获取事件执行器单例"""
    global _executor_instance
    if _executor_instance is None:
        _executor_instance = EventExecutor()
    return _executor_instance
