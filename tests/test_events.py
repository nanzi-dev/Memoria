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


class TestEventDeepIntegration:
    def _context(self):
        from memoria.core.event_schema import EventContext
        return EventContext(
            character_id="chain_c",
            player_id="chain_p",
            session_id="chain_s",
            current_affinity=70,
            current_trust=80,
            current_mood="neutral",
            player_message="线索出现了",
            dialogue_count=1,
            total_dialogue_count=1,
            session_duration_minutes=1,
        )

    def test_execute_event_chain_persists_context(self):
        import uuid
        from memoria.core import event_runtime
        from memoria.core.event_schema import (
            EffectType,
            EventDefinition,
            EventEffect,
            TriggerCondition,
            TriggerType,
        )
        suffix = uuid.uuid4().hex[:8]
        first_id = f"chain_first_{suffix}"
        second_id = f"chain_second_{suffix}"

        first = EventDefinition(
            event_id=first_id,
            event_name="第一段",
            trigger_condition=TriggerCondition(trigger_type=TriggerType.KEYWORD_MATCH, keywords=["线索"]),
            effects=[EventEffect(effect_type=EffectType.TRIGGER_EVENT, next_event_id=second_id)],
        )
        second = EventDefinition(
            event_id=second_id,
            event_name="第二段",
            trigger_condition=TriggerCondition(trigger_type=TriggerType.KEYWORD_MATCH, keywords=["不会出现"]),
            effects=[EventEffect(effect_type=EffectType.NOTIFY_PLAYER, notification_message="链式事件完成")],
        )

        results = event_runtime.detect_and_execute_events(self._context(), [first, second])
        assert [r.event_id for r in results] == [first_id, second_id]

        from memoria.db import repository
        state = repository.get_event_context_state(second_id, "chain_c", "chain_p")
        assert state is not None
        assert state["status"] == "completed"

    def test_branch_event_selects_matching_branch(self):
        from memoria.core.event_executor import EventExecutor
        from memoria.core.event_schema import EventEffect, EffectType, TriggerType

        effect = EventEffect(
            effect_type=EffectType.BRANCH_EVENT,
            branch_conditions=[
                {"event_id": "low", "condition": {"trigger_type": "trust_threshold", "threshold": 10, "comparison": "lt"}},
                {"event_id": "high", "condition": {"trigger_type": "trust_threshold", "threshold": 50, "comparison": "gte"}},
            ],
        )
        from memoria.core.event_schema import EventTriggerResult
        result = EventTriggerResult(event_id="branch", event_name="分支", triggered=True)
        EventExecutor()._branch_next_event(effect, self._context(), result)
        assert result.chained_events == ["high"]

    def test_cron_helpers(self):
        from datetime import datetime, timezone
        from memoria.core import event_runtime

        now = datetime(2026, 7, 10, 14, 30, tzinfo=timezone.utc)
        assert event_runtime.cron_matches("*/5 * * * *", now)
        assert not event_runtime.cron_matches("*/7 * * * *", now)
        assert event_runtime.next_cron_run("*/15 * * * *", now).minute == 45
        sunday = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
        monday = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
        assert event_runtime.cron_matches("0 9 * * 0", sunday)
        assert event_runtime.cron_matches("0 9 * * 7", sunday)
        assert not event_runtime.cron_matches("0 9 * * 0", monday)

    def test_default_templates_are_created(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        count = event_runtime.ensure_default_event_templates()
        templates = repository.list_event_templates()
        ids = {t["template_id"] for t in templates}
        assert count >= 3
        assert "tpl_affinity_milestone" in ids
        assert "tpl_story_keyword_node" in ids

    def test_event_template_admin_create_and_delete(self):
        from memoria.api import event_admin
        from memoria.db import repository

        tid = "tpl_api_dev_test"
        req = event_admin.EventTemplateCreateRequest(
            template_id=tid,
            template_name="开发测试模板",
            category="dev",
            description="dev template",
            trigger_config=event_admin.TriggerConditionDTO(
                trigger_type="keyword_match",
                keywords=["dev"],
                match_mode="any",
            ),
            effects_config=[
                event_admin.EventEffectDTO(
                    effect_type="notify_player",
                    notification_message="dev ok",
                )
            ],
            metadata={"dev": True},
        )

        created = event_admin.create_event_template(req, current_user_id="test-user")
        assert created.success is True
        assert created.template_id == tid
        assert repository.get_event_template(tid) is not None

        deleted = event_admin.delete_event_template(tid, current_user_id="test-user")
        assert deleted.success is True
        assert repository.get_event_template(tid) is None
