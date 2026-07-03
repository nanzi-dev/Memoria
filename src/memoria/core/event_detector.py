"""
事件检测引擎

用途：
- 检测事件触发条件是否满足
- 支持多种触发类型（好感度、关键词、计数、复合条件等）
- 处理冷却时间和触发次数限制
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List

from memoria.core.event_schema import (
    EventDefinition,
    EventContext,
    TriggerType,
    TriggerCondition,
)
from memoria.db import repository

logger = logging.getLogger(__name__)


class EventDetector:
    """事件检测引擎"""
    
    def __init__(self):
        pass
    
    def check_events(
        self,
        context: EventContext,
        event_definitions: List[EventDefinition]
    ) -> List[EventDefinition]:
        """
        检测哪些事件被触发
        
        Args:
            context: 事件上下文
            event_definitions: 事件定义列表
        
        Returns:
            触发的事件列表（按优先级排序）
        """
        triggered_events = []
        
        for event in event_definitions:
            if not event.is_active:
                continue
            
            # 检查冷却时间
            if not self._check_cooldown(event, context):
                logger.debug(f"事件 {event.event_id} 在冷却中")
                continue
            
            # 检查触发条件
            if self._check_trigger_condition(event.trigger_condition, context):
                triggered_events.append(event)
                logger.info(f"事件触发: {event.event_id} - {event.event_name}")
        
        # 按优先级排序
        triggered_events.sort(key=lambda e: e.priority, reverse=True)
        
        return triggered_events
    
    def _check_cooldown(self, event: EventDefinition, context: EventContext) -> bool:
        """检查事件冷却时间"""
        cooldown_hours = event.trigger_condition.cooldown_hours or 0
        
        # 0 表示只触发一次
        if cooldown_hours == 0:
            # 检查是否已经触发过
            last_trigger = repository.get_last_trigger_time(
                event.event_id,
                context.character_id,
                context.player_id
            )
            if last_trigger:
                return False  # 已触发过，不再触发
        
        # 检查冷却时间
        if cooldown_hours > 0:
            last_trigger = repository.get_last_trigger_time(
                event.event_id,
                context.character_id,
                context.player_id
            )
            if last_trigger:
                last_time = datetime.fromisoformat(last_trigger)
                now = datetime.now(timezone.utc)
                cooldown_delta = timedelta(hours=cooldown_hours)
                
                if now - last_time < cooldown_delta:
                    return False  # 还在冷却中
        
        return True
    
    def _check_trigger_condition(
        self,
        condition: TriggerCondition,
        context: EventContext
    ) -> bool:
        """检查单个触发条件"""
        
        trigger_type = condition.trigger_type
        
        # 好感度阈值
        if trigger_type == TriggerType.AFFINITY_THRESHOLD:
            return self._check_threshold(
                context.current_affinity,
                condition.threshold,
                condition.comparison
            )
        
        # 信任度阈值
        if trigger_type == TriggerType.TRUST_THRESHOLD:
            return self._check_threshold(
                context.current_trust,
                condition.threshold,
                condition.comparison
            )
        
        # 关键词匹配
        if trigger_type == TriggerType.KEYWORD_MATCH:
            return self._check_keyword_match(
                context.player_message,
                condition.keywords,
                condition.match_mode
            )
        
        # 对话次数
        if trigger_type == TriggerType.DIALOGUE_COUNT:
            return self._check_threshold(
                context.total_dialogue_count,
                condition.count,
                condition.comparison
            )
        
        # 基于时间（会话时长）
        if trigger_type == TriggerType.TIME_BASED:
            if condition.duration_minutes:
                return self._check_threshold(
                    context.session_duration_minutes,
                    condition.duration_minutes,
                    condition.comparison
                )
        
        # 情绪匹配
        if trigger_type == TriggerType.MOOD_MATCH:
            return context.current_mood == condition.mood
        
        # 关系变化（扩展功能）
        if trigger_type == TriggerType.RELATIONSHIP_CHANGE:
            # 需要检查与其他角色的关系
            # 暂时返回 False，后续实现
            return False
        
        # 复合条件
        if trigger_type == TriggerType.COMPOSITE:
            return self._check_composite_condition(condition, context)
        
        # 其他类型暂不支持
        logger.warning(f"不支持的触发类型: {trigger_type}")
        return False
    
    def _check_threshold(
        self,
        value: float,
        threshold: float,
        comparison: str = "gte"
    ) -> bool:
        """检查阈值条件"""
        if threshold is None:
            return False
        
        if comparison == "gte" or comparison == ">=":
            return value >= threshold
        elif comparison == "lte" or comparison == "<=":
            return value <= threshold
        elif comparison == "eq" or comparison == "==":
            return value == threshold
        elif comparison == "gt" or comparison == ">":
            return value > threshold
        elif comparison == "lt" or comparison == "<":
            return value < threshold
        else:
            logger.warning(f"未知的比较运算符: {comparison}")
            return False
    
    def _check_keyword_match(
        self,
        text: str,
        keywords: List[str],
        match_mode: str = "any"
    ) -> bool:
        """检查关键词匹配"""
        if not keywords or not text:
            return False
        
        text_lower = text.lower()
        
        if match_mode == "any":
            # 任一关键词匹配即可
            return any(kw.lower() in text_lower for kw in keywords)
        elif match_mode == "all":
            # 所有关键词都要匹配
            return all(kw.lower() in text_lower for kw in keywords)
        else:
            logger.warning(f"未知的匹配模式: {match_mode}")
            return False
    
    def _check_composite_condition(
        self,
        condition: TriggerCondition,
        context: EventContext
    ) -> bool:
        """检查复合条件"""
        if not condition.sub_conditions:
            return False
        
        results = [
            self._check_trigger_condition(sub_cond, context)
            for sub_cond in condition.sub_conditions
        ]
        
        logic_operator = condition.logic_operator or "and"
        
        if logic_operator == "and":
            return all(results)
        elif logic_operator == "or":
            return any(results)
        else:
            logger.warning(f"未知的逻辑运算符: {logic_operator}")
            return False


# =========================
# 全局单例
# =========================
_detector_instance = None

def get_event_detector() -> EventDetector:
    """获取事件检测器单例"""
    global _detector_instance
    if _detector_instance is None:
        _detector_instance = EventDetector()
    return _detector_instance
