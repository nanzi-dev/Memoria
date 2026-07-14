"""
事件执行器与检测器深入测试
"""
import pytest, sys, json, uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
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

    def test_time_based_zero_minutes_matches_zero_duration(self):
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import (
            EventContext,
            EventDefinition,
            TriggerCondition,
            TriggerType,
        )

        event = EventDefinition(
            event_id="time_zero",
            event_name="T",
            trigger_condition=TriggerCondition(
                trigger_type=TriggerType.TIME_BASED,
                duration_minutes=0,
                comparison="gte",
            ),
            effects=[],
            is_active=True,
        )
        context = EventContext(
            character_id="c",
            player_id="p",
            session_id="s",
            current_affinity=0,
            current_trust=0,
            current_mood="neutral",
            player_message="",
            dialogue_count=0,
            total_dialogue_count=0,
            session_duration_minutes=0,
        )

        assert EventDetector().check_events(context, [event]) == [event]


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
            effects=[
                EventEffect(effect_type=EffectType.NOTIFY_PLAYER, notification_message="链式事件完成"),
                EventEffect(
                    effect_type=EffectType.UPDATE_EVENT_PROGRESS,
                    progress=1,
                    event_status="completed",
                ),
            ],
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

    def test_branch_event_uses_default_when_no_condition_matches(self):
        from memoria.core.event_executor import EventExecutor
        from memoria.core.event_schema import EventEffect, EffectType, EventTriggerResult

        effect = EventEffect(
            effect_type=EffectType.BRANCH_EVENT,
            next_event_id="fallback",
            branch_conditions=[
                {
                    "event_id": "impossible",
                    "condition": {
                        "trigger_type": "trust_threshold",
                        "threshold": 1000,
                        "comparison": "gte",
                    },
                },
            ],
        )
        result = EventTriggerResult(event_id="branch", event_name="分支", triggered=True)

        EventExecutor()._branch_next_event(effect, self._context(), result)

        assert result.chained_events == ["fallback"]

    def test_cron_helpers(self):
        from datetime import datetime, timezone
        from memoria.core.cron_schedule import cron_matches, next_cron_run

        now = datetime(2026, 7, 10, 14, 30, tzinfo=timezone.utc)
        assert cron_matches("*/5 * * * *", now)
        assert not cron_matches("*/7 * * * *", now)
        assert next_cron_run("*/15 * * * *", now).minute == 45
        sunday = datetime(2026, 7, 12, 9, 0, tzinfo=timezone.utc)
        monday = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
        assert cron_matches("0 9 * * 0", sunday)
        assert cron_matches("0 9 * * 7", sunday)
        assert not cron_matches("0 9 * * 0", monday)

    @pytest.mark.parametrize(
        "schedule",
        [
            "99 * * * *",
            "*/0 * * * *",
            "5-2 * * * *",
            "0 24 * * *",
            "0 0 0 * *",
            "0 0 * 13 *",
            "0 0 * * 8",
            "0,,5 * * * *",
        ],
    )
    def test_cron_helpers_reject_invalid_fields(self, schedule):
        from memoria.core.cron_schedule import validate_cron_schedule

        with pytest.raises(ValueError):
            validate_cron_schedule(schedule)

    def test_delete_event_definition_removes_owned_operational_state(self):
        from memoria.db import repository

        owner_a = f"user_a_{uuid.uuid4().hex[:8]}"
        owner_b = f"user_b_{uuid.uuid4().hex[:8]}"
        event_id = f"ev_delete_{uuid.uuid4().hex[:8]}"

        for owner in (owner_a, owner_b):
            assert repository.save_event_definition(owner, event_id, "Evt", "{}", "[]")
            repository.log_event_trigger(event_id, "c1", owner, "sess", "{}", "[]")
            assert repository.save_event_context_state(
                event_id,
                "c1",
                owner,
                '{"stage": 1}',
            )
            assert repository.save_event_schedule_state(
                event_id,
                "c1",
                owner,
                "0 9 * * *",
                next_run_at="2026-07-15T01:00:00+00:00",
            )

        assert repository.delete_event_definition(owner_a, event_id)
        assert repository.get_event_trigger_history(event_id, player_id=owner_a) == []
        assert repository.get_event_context_state(event_id, "c1", owner_a) is None
        assert repository.get_event_schedule(event_id, "c1", owner_a) is None

        assert repository.get_event_definition(owner_b, event_id) is not None
        assert len(repository.get_event_trigger_history(event_id, player_id=owner_b)) == 1
        assert repository.get_event_context_state(event_id, "c1", owner_b) is not None
        assert repository.get_event_schedule(event_id, "c1", owner_b) is not None

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


class TestEventReliability:
    def _context(self, *, execution_key=None, character_id=None, player_id=None):
        from memoria.core.event_schema import EventContext

        suffix = uuid.uuid4().hex[:8]
        return EventContext(
            character_id=character_id or f"reliable_character_{suffix}",
            player_id=player_id or f"reliable_player_{suffix}",
            session_id=f"reliable_session_{suffix}",
            current_affinity=20,
            current_trust=30,
            current_mood="neutral",
            previous_affinity=18,
            previous_trust=29,
            player_message="触发可靠性事件",
            npc_response="NPC 提到了可靠性",
            dialogue_count=1,
            total_dialogue_count=1,
            session_duration_minutes=1,
            execution_key=execution_key,
        )

    def _event(self, event_id, effects, **updates):
        from memoria.core.event_schema import EventDefinition, TriggerCondition, TriggerType

        return EventDefinition(
            event_id=event_id,
            event_name=event_id,
            trigger_condition=TriggerCondition(
                trigger_type=TriggerType.KEYWORD_MATCH,
                keywords=["可靠性"],
            ),
            effects=effects,
            **updates,
        )

    def test_replay_execution_key_applies_side_effects_once(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"replay_player_{suffix}"
        character_id = f"replay_character_{suffix}"
        event_id = f"replay_event_{suffix}"
        execution_key = f"replay:{suffix}"
        context = self._context(
            execution_key=execution_key,
            character_id=character_id,
            player_id=player_id,
        )
        event = self._event(event_id, [
            EventEffect(
                effect_type=EffectType.MODIFY_STATE,
                state_changes={"affection_level": 4},
            ),
            EventEffect(
                effect_type=EffectType.ADD_MEMORY,
                memory_text=f"唯一记忆 {suffix}",
            ),
            EventEffect(
                effect_type=EffectType.UNLOCK_CONTENT,
                unlock_keys=[f"unlock_{suffix}"],
            ),
            EventEffect(
                effect_type=EffectType.NOTIFY_PLAYER,
                notification_message=f"唯一通知 {suffix}",
            ),
            EventEffect(
                effect_type=EffectType.UPDATE_EVENT_PROGRESS,
                progress=0.5,
                event_status="active",
            ),
        ])
        repository.save_event_definition(
            owner_user_id=player_id,
            event_id=event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config=json.dumps(
                [effect.model_dump(mode="json") for effect in event.effects],
                ensure_ascii=False,
            ),
        )

        first = event_runtime.detect_and_execute_events(context, [event])
        second = event_runtime.detect_and_execute_events(context, [event])

        assert first[0].status == "succeeded"
        assert second[0].status == "skipped"
        assert second[0].deduplicated is True
        assert repository.get_long_term_facts(character_id, player_id, 10).count(
            f"唯一记忆 {suffix}"
        ) == 1
        assert repository.list_event_unlocks(player_id, character_id) == [
            f"unlock_{suffix}"
        ]
        assert len(repository.list_player_event_inbox(player_id)) == 1
        assert len(repository.get_event_trigger_history(event_id=event_id, player_id=player_id)) == 1
        assert repository.get_event_context_state(event_id, character_id, player_id)[
            "progress"
        ] == 0.5
        metrics = repository.get_event_execution_metrics(player_id, event_id)
        assert metrics["succeeded_count"] == 1
        assert metrics["deduplicated_count"] == 1

    @pytest.mark.parametrize("cooldown_hours", [0, 2])
    def test_concurrent_once_or_cooldown_event_commits_side_effects_once(
        self,
        monkeypatch,
        cooldown_hours,
    ):
        from memoria.core import event_runtime
        from memoria.core.event_schema import (
            EffectType,
            EventDefinition,
            EventEffect,
            TriggerCondition,
            TriggerType,
        )
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"guard_player_{suffix}"
        character_id = f"guard_character_{suffix}"
        event_id = f"guard_event_{suffix}"
        memory_text = f"并发唯一记忆 {suffix}"
        unlock_key = f"guard_unlock_{suffix}"
        event = EventDefinition(
            event_id=event_id,
            event_name="并发触发保护",
            trigger_condition=TriggerCondition(
                trigger_type=TriggerType.KEYWORD_MATCH,
                keywords=["可靠性"],
                cooldown_hours=cooldown_hours,
            ),
            effects=[
                EventEffect(
                    effect_type=EffectType.ADD_MEMORY,
                    memory_text=memory_text,
                ),
                EventEffect(
                    effect_type=EffectType.UNLOCK_CONTENT,
                    unlock_keys=[unlock_key],
                ),
                EventEffect(
                    effect_type=EffectType.NOTIFY_PLAYER,
                    notification_message=f"并发唯一通知 {suffix}",
                ),
            ],
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config=json.dumps(
                [effect.model_dump(mode="json") for effect in event.effects],
                ensure_ascii=False,
            ),
        )

        claim_barrier = Barrier(2)
        original_claim = repository.claim_event_trigger_guard

        def synchronized_claim(**kwargs):
            claim_barrier.wait(timeout=5)
            return original_claim(**kwargs)

        monkeypatch.setattr(
            event_runtime.repository,
            "claim_event_trigger_guard",
            synchronized_claim,
        )

        def run(execution_key):
            context = self._context(
                execution_key=execution_key,
                character_id=character_id,
                player_id=player_id,
            )
            return event_runtime.detect_and_execute_events(context, [event])[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(run, f"guard:{suffix}:{index}")
                for index in range(2)
            ]
            results = [future.result(timeout=10) for future in futures]

        assert sorted(result.status for result in results) == ["skipped", "succeeded"]
        assert repository.get_long_term_facts(character_id, player_id, 10).count(
            memory_text
        ) == 1
        assert repository.list_event_unlocks(player_id, character_id) == [unlock_key]
        assert len(repository.list_player_event_inbox(player_id)) == 1
        assert len(
            repository.get_event_trigger_history(
                event_id=event_id,
                player_id=player_id,
            )
        ) == 1

    def test_failed_effect_rolls_back_every_planned_side_effect(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"rollback_player_{suffix}"
        character_id = f"rollback_character_{suffix}"
        event_id = f"rollback_event_{suffix}"
        context = self._context(character_id=character_id, player_id=player_id)
        event = self._event(event_id, [
            EventEffect(
                effect_type=EffectType.MODIFY_STATE,
                state_changes={"affection_level": 5},
            ),
            EventEffect(
                effect_type=EffectType.ADD_MEMORY,
                memory_text=f"不应出现的记忆 {suffix}",
            ),
            EventEffect(
                effect_type=EffectType.UNLOCK_CONTENT,
                unlock_keys=[f"blocked_{suffix}"],
            ),
            EventEffect(
                effect_type=EffectType.NOTIFY_PLAYER,
                notification_message=f"不应出现的通知 {suffix}",
            ),
            EventEffect(effect_type=EffectType.GRANT_ITEM, item_id="missing-system"),
        ])
        repository.save_runtime_state(character_id, player_id, 20, 30, "neutral")
        repository.save_event_definition(
            owner_user_id=player_id,
            event_id=event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config=json.dumps(
                [effect.model_dump(mode="json") for effect in event.effects],
                ensure_ascii=False,
            ),
        )

        result = event_runtime.detect_and_execute_events(context, [event])[0]

        assert result.status == "failed"
        assert result.triggered is False
        assert result.state_changes == {}
        assert repository.get_long_term_facts(character_id, player_id, 10) == []
        assert repository.list_event_unlocks(player_id, character_id) == []
        assert repository.list_player_event_inbox(player_id) == []
        assert repository.get_event_trigger_history(event_id=event_id, player_id=player_id) == []
        assert repository.get_event_context_state(event_id, character_id, player_id) is None
        runtime = repository.get_runtime_state(character_id, player_id, MagicMock())
        assert runtime["affection_level"] == 20
        assert repository.get_event_definition(player_id, event_id)["trigger_count"] == 0

    def test_turn_limit_is_the_strictest_matching_event_limit(self):
        from memoria.core.event_detector import EventDetector

        context = self._context()
        events = [
            self._event(f"limit_{index}", [], priority=10 - index, max_triggers_per_turn=limit)
            for index, limit in enumerate([1, 20, 20])
        ]
        assert [event.event_id for event in EventDetector().check_events(context, events)] == [
            "limit_0"
        ]

    def test_new_condition_sources_and_conflict_rules(self):
        from memoria.core.event_detector import EventDetector
        from memoria.core.event_schema import EventDefinition, TriggerCondition, TriggerType

        context = self._context().model_copy(update={
            "previous_affinity": 49,
            "current_affinity": 51,
            "affinity_delta": 2,
            "event_history": [{"event_id": "prerequisite", "status": "succeeded"}],
            "world_time": "2026-07-14T23:30:00+08:00",
        })
        conditions = [
            TriggerCondition(
                trigger_type=TriggerType.AFFINITY_THRESHOLD,
                threshold=50,
                crossing=True,
            ),
            TriggerCondition(
                trigger_type=TriggerType.NPC_KEYWORD_MATCH,
                keywords=[r"NPC\s+提到了"],
                match_mode="regex",
            ),
            TriggerCondition(
                trigger_type=TriggerType.STATE_DELTA,
                state_field="affinity",
                threshold=2,
            ),
            TriggerCondition(
                trigger_type=TriggerType.EVENT_HISTORY,
                event_id="prerequisite",
                min_occurrences=1,
            ),
            TriggerCondition(
                trigger_type=TriggerType.WORLD_TIME_WINDOW,
                time_window_start="22:00",
                time_window_end="01:00",
                weekdays=[1],
            ),
        ]
        detector = EventDetector()
        for index, condition in enumerate(conditions):
            event = EventDefinition(
                event_id=f"condition_{index}",
                event_name="condition",
                trigger_condition=condition,
                effects=[],
            )
            assert detector.check_events(context, [event]) == [event]

    def test_canonical_context_counts_single_and_group_turns(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"context_player_{suffix}"
        character_id = f"context_character_{suffix}"
        other_character_id = f"context_other_{suffix}"
        first_session_id = f"context_single_a_{suffix}"
        second_session_id = f"context_single_b_{suffix}"
        group_session_id = f"context_group_{suffix}"

        repository.create_session(first_session_id, character_id, player_id, "Player")
        repository.append_short_term_message(first_session_id, "user", "one")
        repository.append_short_term_message(first_session_id, "assistant", "reply")
        repository.append_short_term_message(first_session_id, "user", "two")
        repository.create_session(second_session_id, character_id, player_id, "Player")
        repository.append_short_term_message(second_session_id, "user", "three")
        assert repository.create_multi_character_session(
            group_session_id,
            player_id,
            "Player",
            [character_id, other_character_id],
        )
        repository.append_multi_character_message(group_session_id, "user", "four")
        repository.append_multi_character_message(group_session_id, "user", "five")

        persisted = event_runtime.build_event_context(
            character_id=character_id,
            player_id=player_id,
            session_id=group_session_id,
            current_affinity=0,
            current_trust=0,
            current_mood="neutral",
            player_message="five",
            current_user_turn_persisted=True,
        )
        pending = event_runtime.build_event_context(
            character_id=character_id,
            player_id=player_id,
            session_id=group_session_id,
            current_affinity=0,
            current_trust=0,
            current_mood="neutral",
            player_message="six",
            current_user_turn_persisted=False,
        )

        assert persisted.dialogue_count == 2
        assert persisted.total_dialogue_count == 5
        assert pending.dialogue_count == 3
        assert pending.total_dialogue_count == 6
        assert repository.count_character_user_turns(player_id, other_character_id) == 2

    def test_group_contexts_apply_scope_conflicts_and_structured_results(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import (
            EffectType,
            EventContext,
            EventDefinition,
            EventEffect,
            TriggerCondition,
            TriggerType,
        )
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"group_player_{suffix}"
        session_id = f"group_session_{suffix}"
        character_a = f"group_a_{suffix}"
        character_b = f"group_b_{suffix}"
        execution_key = f"group:{suffix}"

        def context(character_id):
            return EventContext(
                character_id=character_id,
                player_id=player_id,
                session_id=session_id,
                current_affinity=10,
                current_trust=10,
                current_mood="neutral",
                player_message="群聊触发",
                dialogue_count=1,
                total_dialogue_count=1,
                session_duration_minutes=1,
                execution_key=execution_key,
            )

        def event(event_id, *, character_id=None, priority=0, **updates):
            return EventDefinition(
                event_id=event_id,
                event_name=event_id,
                character_id=character_id,
                trigger_condition=TriggerCondition(
                    trigger_type=TriggerType.KEYWORD_MATCH,
                    keywords=["群聊"],
                ),
                effects=[
                    EventEffect(
                        effect_type=EffectType.NOTIFY_PLAYER,
                        notification_message=f"{event_id}-notice-a",
                    ),
                    EventEffect(
                        effect_type=EffectType.NOTIFY_PLAYER,
                        notification_message=f"{event_id}-notice-b",
                    ),
                    EventEffect(
                        effect_type=EffectType.TRIGGER_DIALOGUE,
                        dialogue_text=f"{event_id}-dialogue-a",
                    ),
                    EventEffect(
                        effect_type=EffectType.TRIGGER_DIALOGUE,
                        dialogue_text=f"{event_id}-dialogue-b",
                    ),
                ],
                priority=priority,
                **updates,
            )

        global_event = event(f"global_{suffix}", priority=30)
        character_event = event(
            f"character_{suffix}",
            character_id=character_b,
            priority=20,
            exclusive_group="story",
        )
        excluded_by_group = event(
            f"excluded_{suffix}",
            character_id=character_b,
            priority=10,
            exclusive_group="story",
        )
        excluded_by_limit = event(
            f"limit_{suffix}",
            character_id=character_a,
            priority=5,
            max_triggers_per_turn=2,
        )
        definitions = [
            global_event,
            character_event,
            excluded_by_group,
            excluded_by_limit,
        ]
        for definition in definitions:
            repository.save_event_definition(
                owner_user_id=player_id,
                event_id=definition.event_id,
                event_name=definition.event_name,
                character_id=definition.character_id,
                trigger_config=definition.trigger_condition.model_dump_json(),
                effects_config=json.dumps(
                    [effect.model_dump(mode="json") for effect in definition.effects],
                    ensure_ascii=False,
                ),
                priority=definition.priority,
                exclusive_group=definition.exclusive_group,
                max_triggers_per_turn=definition.max_triggers_per_turn,
                stop_processing=definition.stop_processing,
            )

        results = event_runtime.detect_and_execute_event_contexts(
            [context(character_a), context(character_b)],
            definitions,
        )

        assert [result.event_id for result in results] == [
            global_event.event_id,
            character_event.event_id,
        ]
        assert [result.character_id for result in results] == [character_a, character_b]
        for result in results:
            assert [item.message for item in result.notifications] == [
                f"{result.event_id}-notice-a",
                f"{result.event_id}-notice-b",
            ]
            assert result.dialogue_overrides == [
                f"{result.event_id}-dialogue-a",
                f"{result.event_id}-dialogue-b",
            ]
        assert len(repository.get_event_trigger_history(
            event_id=global_event.event_id,
            player_id=player_id,
        )) == 1
        assert repository.get_event_execution_metrics(
            player_id,
            global_event.event_id,
        )["succeeded_count"] == 1

    def test_group_contexts_persist_base_state_without_event_matches(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import EventContext
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"group_state_player_{suffix}"
        session_id = f"group_state_session_{suffix}"
        character_a = f"group_state_a_{suffix}"
        character_b = f"group_state_b_{suffix}"
        contexts = [
            EventContext(
                character_id=character_a,
                player_id=player_id,
                session_id=session_id,
                current_affinity=14,
                current_trust=23,
                current_mood="happy",
                player_message="no event",
                dialogue_count=1,
                total_dialogue_count=1,
                session_duration_minutes=1,
                execution_key=f"group-state:{suffix}",
            ),
            EventContext(
                character_id=character_b,
                player_id=player_id,
                session_id=session_id,
                current_affinity=-7,
                current_trust=41,
                current_mood="worried",
                player_message="no event",
                dialogue_count=1,
                total_dialogue_count=1,
                session_duration_minutes=1,
                execution_key=f"group-state:{suffix}",
            ),
        ]

        assert event_runtime.detect_and_execute_event_contexts(contexts, []) == []

        with repository.get_conn() as conn:
            rows = conn.execute(
                """
                SELECT character_id, affection_level, trust_level, current_mood
                FROM relationship_state
                WHERE player_id = ?
                ORDER BY character_id
                """,
                (player_id,),
            ).fetchall()
        assert [dict(row) for row in rows] == [
            {
                "character_id": character_a,
                "affection_level": 14.0,
                "trust_level": 23.0,
                "current_mood": "happy",
            },
            {
                "character_id": character_b,
                "affection_level": -7.0,
                "trust_level": 41.0,
                "current_mood": "worried",
            },
        ]

    def test_group_context_stop_processing_uses_priority_order(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import (
            EventContext,
            EventDefinition,
            TriggerCondition,
            TriggerType,
        )

        suffix = uuid.uuid4().hex[:8]
        context = EventContext(
            character_id=f"stop_character_{suffix}",
            player_id=f"stop_player_{suffix}",
            session_id=f"stop_session_{suffix}",
            current_affinity=0,
            current_trust=0,
            current_mood="neutral",
            player_message="stop",
            dialogue_count=1,
            total_dialogue_count=1,
            session_duration_minutes=1,
            execution_key=f"stop:{suffix}",
        )
        condition = TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["stop"],
        )
        first = EventDefinition(
            event_id=f"stop_first_{suffix}",
            event_name="first",
            trigger_condition=condition,
            effects=[],
            priority=20,
            stop_processing=True,
        )
        second = EventDefinition(
            event_id=f"stop_second_{suffix}",
            event_name="second",
            trigger_condition=condition,
            effects=[],
            priority=10,
        )

        results = event_runtime.detect_and_execute_event_contexts(
            [context],
            [second, first],
        )

        assert [result.event_id for result in results] == [first.event_id]
