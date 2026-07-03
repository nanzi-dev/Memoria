"""
事件执行器与检测器深入测试
"""
import pytest, sys, json, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from unittest.mock import Mock, patch, MagicMock

class TestEventExecutorEffects:
    def _make_context(self, **kw):
        from memoria.core.event_schema import EventContext
        d = {"character_id":"c","player_id":"p","session_id":"s",
             "current_affinity":50,"current_trust":30,"current_mood":"happy",
             "player_message":"","dialogue_count":1,"total_dialogue_count":10,
             "session_duration_minutes":5}
        d.update(kw)
        return EventContext(**d)

    def _make_event(self, eid, tc, effects):
        from memoria.core.event_schema import EventDefinition, TriggerCondition, TriggerType
        return EventDefinition(event_id=eid,event_name="T",trigger_condition=tc,
                               effects=effects,priority=1,is_active=True)

    def test_execute_modify_state(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.MODIFY_STATE,
                          state_changes={"affection_level":5,"trust_level":3})
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e1",tc,[eff]),ctx)
        assert result.triggered
        assert any("modify_state" in e.lower() for e in result.effects_applied)

    def test_execute_notify_player(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.NOTIFY_PLAYER,
                          notification_message="测试通知")
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e2",tc,[eff]),ctx)
        assert result.notification == "测试通知"

    def test_execute_change_mood(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.CHANGE_MOOD,target_mood="sad")
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e3",tc,[eff]),ctx)
        assert result.state_changes.get("current_mood") == "sad"

    def test_execute_trigger_dialogue(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.TRIGGER_DIALOGUE,
                          dialogue_text="你好！")
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e4",tc,[eff]),ctx)
        assert result.dialogue_override == "你好！"

    def test_execute_unlock_content(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.UNLOCK_CONTENT,
                          unlock_keys=["quest_intro"])
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e5",tc,[eff]),ctx)
        assert "quest_intro" in result.state_changes.get("unlocked_content",[])

    def test_execute_add_memory(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        eff = EventEffect(effect_type=EffectType.ADD_MEMORY,
                          memory_text="test_memory",memory_importance=8)
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e6",tc,[eff]),ctx)
        assert any("add_memory" in e.lower() for e in result.effects_applied)

    def test_multiple_effects(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (TriggerCondition,TriggerType,
            EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        effects = [
            EventEffect(effect_type=EffectType.MODIFY_STATE,
                        state_changes={"affection_level":3}),
            EventEffect(effect_type=EffectType.NOTIFY_PLAYER,
                        notification_message="完成！"),
            EventEffect(effect_type=EffectType.CHANGE_MOOD,target_mood="excited"),
        ]
        ctx = self._make_context()
        result = exe.execute_event(self._make_event("e7",tc,effects),ctx)
        assert result.triggered
        assert len(result.effects_applied) == 3
        assert result.notification == "完成！"
        assert result.state_changes.get("current_mood") == "excited"

    def test_inactive_event_not_executed(self):
        from memoria.core.event_executor import get_event_executor
        from memoria.core.event_schema import (EventDefinition,TriggerCondition,
            TriggerType,EventEffect,EffectType)
        exe = get_event_executor()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=0)
        event = EventDefinition(event_id="inactive",event_name="T",
                                trigger_condition=tc,effects=[],is_active=False)
        ctx = self._make_context()
        from memoria.core.event_detector import EventDetector
        det = EventDetector()
        triggered = det.check_events(ctx,[event])
        assert len(triggered) == 0


class TestEventDetectorMore:
    def test_keyword_case_insensitive(self):
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import (EventDefinition,TriggerCondition,
            TriggerType)
        det = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.KEYWORD_MATCH,
                              keywords=["HELLO"],match_mode="any")
        event = EventDefinition(event_id="kw",event_name="T",
                                trigger_condition=tc,effects=[],is_active=True)
        from memoria.core.event_schema import EventContext
        ctx = EventContext(character_id="c",player_id="p",session_id="s",
                           current_affinity=0,current_trust=0,current_mood="neutral",
                           player_message="hello world",dialogue_count=1,
                           total_dialogue_count=1,session_duration_minutes=1)
        triggered = det.check_events(ctx,[event])
        assert len(triggered) == 1

    def test_affinity_eq_comparison(self):
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import (EventDefinition,TriggerCondition,
            TriggerType)
        det = EventDetector()
        tc = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,
                              threshold=50,comparison="eq")
        event = EventDefinition(event_id="eq",event_name="T",
                                trigger_condition=tc,effects=[],is_active=True)
        from memoria.core.event_schema import EventContext
        ctx = EventContext(character_id="c",player_id="p",session_id="s",
                           current_affinity=50,current_trust=0,current_mood="neutral",
                           player_message="",dialogue_count=1,total_dialogue_count=1,
                           session_duration_minutes=1)
        triggered = det.check_events(ctx,[event])
        assert len(triggered) == 1

    def test_gt_lt_comparisons(self):
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import (EventDefinition,TriggerCondition,
            TriggerType,EventContext)
        det = EventDetector()
        ctx = EventContext(character_id="c",player_id="p",session_id="s",
                           current_affinity=50,current_trust=0,current_mood="neutral",
                           player_message="",dialogue_count=1,total_dialogue_count=1,
                           session_duration_minutes=1)
        tc_gt = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=40,comparison="gt")
        triggered_gt = det.check_events(ctx,[EventDefinition(event_id="gt",event_name="T",trigger_condition=tc_gt,effects=[],is_active=True)])
        assert len(triggered_gt)==1
        tc_lt = TriggerCondition(trigger_type=TriggerType.AFFINITY_THRESHOLD,threshold=60,comparison="lt")
        triggered_lt = det.check_events(ctx,[EventDefinition(event_id="lt",event_name="T",trigger_condition=tc_lt,effects=[],is_active=True)])
        assert len(triggered_lt)==1
