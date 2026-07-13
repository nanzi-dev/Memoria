"""
事件检测引擎

用途：
- 检测事件触发条件是否满足
- 支持多种触发类型（好感度、关键词、计数、复合条件等）
- 处理冷却时间和触发次数限制
"""

import logging
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, List

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
        matched_events = []
        
        for event in event_definitions:
            if not event.is_active:
                continue
            
            # 检查冷却时间
            if not self._check_cooldown(event, context):
                logger.debug(f"事件 {event.event_id} 在冷却中")
                continue
            
            # 检查触发条件
            if self._check_trigger_condition(event.trigger_condition, context):
                matched_events.append(event)
                logger.info(f"事件触发: {event.event_id} - {event.event_name}")
        
        # 按优先级排序
        matched_events.sort(key=lambda e: e.priority, reverse=True)

        triggered_events = []
        exclusive_groups: set[str] = set()
        turn_limit = min(
            (max(1, event.max_triggers_per_turn or 3) for event in matched_events),
            default=3,
        )
        for event in matched_events:
            if event.exclusive_group and event.exclusive_group in exclusive_groups:
                continue
            if len(triggered_events) >= turn_limit:
                break
            triggered_events.append(event)
            if event.exclusive_group:
                exclusive_groups.add(event.exclusive_group)
            if event.stop_processing:
                break

        return triggered_events
    
    def _check_cooldown(self, event: EventDefinition, context: EventContext) -> bool:
        """检查事件冷却时间"""
        cooldown_hours = event.trigger_condition.cooldown_hours or 0
        cooldown_character_id = context.character_id if event.character_id else None
        
        # 0 表示只触发一次
        if cooldown_hours == 0:
            # 检查是否已经触发过
            last_trigger = repository.get_last_trigger_time(
                event.event_id,
                cooldown_character_id,
                context.player_id
            )
            if last_trigger:
                return False  # 已触发过，不再触发
        
        # 检查冷却时间
        if cooldown_hours > 0:
            last_trigger = repository.get_last_trigger_time(
                event.event_id,
                cooldown_character_id,
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
            if condition.crossing:
                return self._check_threshold_crossing(
                    context.previous_affinity,
                    context.current_affinity,
                    condition.threshold,
                    condition.comparison,
                )
            return self._check_threshold(
                context.current_affinity,
                condition.threshold,
                condition.comparison
            )
        
        # 信任度阈值
        if trigger_type == TriggerType.TRUST_THRESHOLD:
            if condition.crossing:
                return self._check_threshold_crossing(
                    context.previous_trust,
                    context.current_trust,
                    condition.threshold,
                    condition.comparison,
                )
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

        if trigger_type == TriggerType.NPC_KEYWORD_MATCH:
            return self._check_keyword_match(
                context.npc_response or "",
                condition.keywords,
                condition.match_mode,
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
            if condition.duration_minutes is not None:
                return self._check_threshold(
                    context.session_duration_minutes,
                    condition.duration_minutes,
                    condition.comparison
                )
        
        # 情绪匹配
        if trigger_type == TriggerType.MOOD_MATCH:
            return context.current_mood == condition.mood

        if trigger_type == TriggerType.STATE_DELTA:
            value = (
                context.affinity_delta
                if condition.state_field == "affinity"
                else context.trust_delta
                if condition.state_field == "trust"
                else None
            )
            return value is not None and self._check_threshold(
                value,
                condition.threshold,
                condition.comparison,
            )

        if trigger_type == TriggerType.EVENT_HISTORY:
            occurrences = sum(
                1
                for item in context.event_history
                if item.get("event_id") == condition.event_id
                and (
                    not condition.event_status
                    or item.get("status") == condition.event_status
                )
            )
            return occurrences >= int(condition.min_occurrences or 1)

        if trigger_type == TriggerType.WORLD_TIME_WINDOW:
            return self._check_world_time_window(condition, context)
        
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
        
        cleaned_keywords = [kw.strip() for kw in keywords if kw and kw.strip()]
        if not cleaned_keywords:
            return False

        if match_mode == "any":
            # 任一关键词匹配即可
            return any(kw.lower() in text_lower for kw in cleaned_keywords)
        elif match_mode == "all":
            # 所有关键词都要匹配
            return all(kw.lower() in text_lower for kw in cleaned_keywords)
        elif match_mode == "exact":
            return any(text_lower.strip() == kw.lower() for kw in cleaned_keywords)
        elif match_mode == "whole_word":
            return any(
                re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", text, flags=re.IGNORECASE)
                for kw in cleaned_keywords
            )
        elif match_mode == "regex":
            return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in cleaned_keywords)
        else:
            logger.warning(f"未知的匹配模式: {match_mode}")
            return False

    def _check_threshold_crossing(
        self,
        previous: float | None,
        current: float,
        threshold: float | None,
        comparison: str = "gte",
    ) -> bool:
        if previous is None or threshold is None:
            return False
        if comparison in {"gte", ">=", "gt", ">"}:
            return not self._check_threshold(previous, threshold, comparison) and self._check_threshold(
                current, threshold, comparison
            )
        if comparison in {"lte", "<=", "lt", "<"}:
            return not self._check_threshold(previous, threshold, comparison) and self._check_threshold(
                current, threshold, comparison
            )
        return previous != threshold and current == threshold

    def _check_world_time_window(
        self,
        condition: TriggerCondition,
        context: EventContext,
    ) -> bool:
        if not context.world_time or not condition.time_window_start or not condition.time_window_end:
            return False
        try:
            world_datetime = datetime.fromisoformat(context.world_time.replace("Z", "+00:00"))
            start = time.fromisoformat(condition.time_window_start)
            end = time.fromisoformat(condition.time_window_end)
        except ValueError:
            return False
        if condition.weekdays is not None and world_datetime.weekday() not in condition.weekdays:
            return False
        current = world_datetime.timetz().replace(tzinfo=None)
        if start <= end:
            return start <= current <= end
        return current >= start or current <= end

    def evaluate_event(self, event: EventDefinition, context: EventContext) -> dict[str, Any]:
        """返回模拟接口使用的条件判定轨迹。"""
        cooldown_ok = event.is_active and self._check_cooldown(event, context)
        condition_trace = self._evaluate_condition(event.trigger_condition, context)
        return {
            "event_id": event.event_id,
            "event_name": event.event_name,
            "active": event.is_active,
            "cooldown_passed": cooldown_ok,
            "matched": bool(event.is_active and cooldown_ok and condition_trace["matched"]),
            "condition": condition_trace,
        }

    def _evaluate_condition(
        self,
        condition: TriggerCondition,
        context: EventContext,
    ) -> dict[str, Any]:
        children = [
            self._evaluate_condition(child, context)
            for child in condition.sub_conditions or []
        ]
        return {
            "trigger_type": condition.trigger_type.value,
            "matched": self._check_trigger_condition(condition, context),
            "config": condition.model_dump(mode="json", exclude_none=True),
            "children": children,
        }
    
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
