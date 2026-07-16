"""
事件执行器与检测器深入测试
"""
from copy import deepcopy

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

    def test_proactive_dialogue_rejects_foreign_group_before_orchestrator(
        self,
        monkeypatch,
    ):
        from memoria.core import event_executor
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

        monkeypatch.setattr(
            event_executor.repository,
            "get_session",
            lambda session_id: {
                "session_id": session_id,
                "player_id": "other-player",
                "is_multi_character": 1,
                "status": "active",
            },
        )
        monkeypatch.setattr(
            MultiCharacterOrchestrator,
            "__init__",
            lambda *args, **kwargs: pytest.fail("foreign session must not be loaded"),
        )

        with pytest.raises(ValueError, match="不属于当前玩家"):
            event_executor.EventExecutor()._plan_npc_proactive_dialogue(
                EventEffect(
                    effect_type=EffectType.NPC_PROACTIVE_DIALOGUE,
                    target_session_id="foreign-session",
                    proactive_character_id="npc-1",
                ),
                self._make_context(player_id="player-1"),
            )

    def test_proactive_dialogue_rejects_character_outside_group(
        self,
        monkeypatch,
    ):
        from memoria.core import event_executor
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

        monkeypatch.setattr(
            event_executor.repository,
            "get_session",
            lambda session_id: {
                "session_id": session_id,
                "player_id": "player-1",
                "is_multi_character": 1,
                "status": "active",
            },
        )
        monkeypatch.setattr(
            event_executor.repository,
            "get_session_participants",
            lambda session_id, only_active=True: [{"character_id": "npc-2"}],
        )
        monkeypatch.setattr(
            MultiCharacterOrchestrator,
            "__init__",
            lambda *args, **kwargs: pytest.fail("invalid participant must not be loaded"),
        )

        with pytest.raises(ValueError, match="不是目标群聊的活跃参与者"):
            event_executor.EventExecutor()._plan_npc_proactive_dialogue(
                EventEffect(
                    effect_type=EffectType.NPC_PROACTIVE_DIALOGUE,
                    target_session_id="owned-session",
                    proactive_character_id="npc-1",
                ),
                self._make_context(player_id="player-1"),
            )

    def test_proactive_dialogue_without_target_prefers_current_group(
        self,
        monkeypatch,
    ):
        from memoria.core import event_executor
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

        sessions = {
            "current-group": {
                "session_id": "current-group",
                "player_id": "player-1",
                "is_multi_character": 1,
                "status": "active",
            },
            "latest-group": {
                "session_id": "latest-group",
                "player_id": "player-1",
                "is_multi_character": 1,
                "status": "active",
            },
        }
        loaded_session_ids = []

        monkeypatch.setattr(
            event_executor.repository,
            "get_session",
            lambda session_id: sessions.get(session_id),
        )
        monkeypatch.setattr(
            MultiCharacterOrchestrator,
            "__init__",
            lambda self, session_id: loaded_session_ids.append(session_id),
        )
        monkeypatch.setattr(
            MultiCharacterOrchestrator,
            "trigger_character_interaction",
            lambda *args, **kwargs: {
                "dialogue": "复盘完成",
                "character_id": "npc-1",
            },
        )

        context = self._make_context(player_id="player-1")
        context.session_id = "current-group"
        context.active_multi_session_id = "latest-group"
        result = event_executor.EventExecutor()._plan_npc_proactive_dialogue(
            EventEffect(effect_type=EffectType.NPC_PROACTIVE_DIALOGUE),
            context,
        )

        assert result["session_id"] == "current-group"
        assert loaded_session_ids == ["current-group"]


def test_event_commit_rejects_proactive_message_for_foreign_session():
    from memoria.core.event_schema import TriggerCondition, TriggerType
    from memoria.db import repository

    suffix = uuid.uuid4().hex[:8]
    attacker_id = f"attacker_{suffix}"
    victim_id = f"victim_{suffix}"
    event_id = f"event_{suffix}"
    victim_session_id = f"victim_session_{suffix}"
    character_id = f"npc_{suffix}"

    repository.create_user(attacker_id, f"attacker_{suffix}", "test-hash")
    repository.create_user(victim_id, f"victim_{suffix}", "test-hash")
    assert repository.create_multi_character_session(
        session_id=victim_session_id,
        player_id=victim_id,
        player_name="Victim",
        character_ids=[character_id],
    )
    assert repository.save_event_definition(
        owner_user_id=attacker_id,
        event_id=event_id,
        event_name="Foreign proactive message",
        trigger_config=TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["test"],
        ).model_dump_json(),
        effects_config="[]",
    )
    execution = {
        "execution_id": uuid.uuid4().hex,
        "event_id": event_id,
        "character_id": character_id,
        "session_id": f"schedule:{event_id}",
        "status": "succeeded",
        "effects_data": "[]",
        "result_data": "{}",
        "error": None,
        "duration_ms": 1,
        "context_snapshot": "{}",
        "effects_applied": "[]",
        "proactive_messages": [{
            "session_id": victim_session_id,
            "content": "must not be inserted",
            "character_id": character_id,
        }],
    }

    with pytest.raises(RuntimeError, match="proactive dialogue target"):
        repository.commit_event_execution_batch(
            player_id=attacker_id,
            execution_key=f"foreign:{suffix}",
            trigger_source="schedule",
            results_data="[]",
            executions=[execution],
        )

    messages, _ = repository.get_messages_paginated(
        victim_session_id,
        offset=0,
        limit=20,
    )
    assert messages == []


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

    def test_single_event_replay_factory_receives_original_presentation_results(self):
        from memoria.core import event_runtime
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"single_replay_player_{suffix}"
        character_id = f"single_replay_character_{suffix}"
        event_id = f"single_replay_event_{suffix}"
        execution_key = f"single-replay:{suffix}"
        dialogue_override = "重放仍应呈现事件对白。"
        notification = "重放仍应呈现事件通知。"
        context = self._context(
            execution_key=execution_key,
            character_id=character_id,
            player_id=player_id,
        )
        event = self._event(
            event_id,
            [
                EventEffect(
                    effect_type=EffectType.TRIGGER_DIALOGUE,
                    dialogue_text=dialogue_override,
                ),
                EventEffect(
                    effect_type=EffectType.MODIFY_STATE,
                    state_changes={"trust_level": 3},
                ),
                EventEffect(
                    effect_type=EffectType.NOTIFY_PLAYER,
                    notification_message=notification,
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
            character_id=character_id,
        )

        first = event_runtime.detect_and_execute_events(context, [event])
        captured = {}

        def capture_presentation(results):
            (
                captured["dialogue"],
                _,
                captured["trust"],
                _,
                _,
                captured["notification"],
            ) = event_runtime.apply_event_results_to_dialogue_state(
                results,
                "原始回应",
                20,
                30,
                "neutral",
            )
            captured["status"] = results[0].status
            return {}

        replay = event_runtime.detect_and_execute_events(
            context,
            [event],
            dialogue_turn_factory=capture_presentation,
        )

        assert first[0].status == "succeeded"
        assert captured == {
            "dialogue": f"[事件触发] {dialogue_override}",
            "trust": 33,
            "notification": notification,
            "status": "succeeded",
        }
        assert replay[0].status == "skipped"
        assert replay[0].deduplicated is True
        metrics = repository.get_event_execution_metrics(player_id, event_id)
        assert metrics["deduplicated_count"] == 1

    @pytest.mark.parametrize(
        ("turn_kind", "canonical_response", "local_response"),
        [
            (
                "single",
                {
                    "dialogue": "winner single response",
                    "assistant_message_id": 101,
                },
                {
                    "dialogue": "expired loser single response",
                    "assistant_message_id": None,
                },
            ),
            (
                "multi",
                [
                    {
                        "dialogue": "winner group response",
                        "message_id": 202,
                    }
                ],
                [
                    {
                        "dialogue": "expired loser group response",
                        "message_id": -2,
                    }
                ],
            ),
        ],
        ids=["single", "group"],
    )
    def test_commit_race_replaces_factory_response_with_canonical_dialogue(
        self,
        monkeypatch,
        turn_kind,
        canonical_response,
        local_response,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"commit_race_player_{suffix}"
        character_id = f"commit_race_character_{suffix}"
        session_id = f"commit_race_session_{suffix}"
        request_id = f"commit_race_request_{suffix}"
        execution_key = f"commit-race:{suffix}"
        if turn_kind == "multi":
            assert repository.create_multi_character_session(
                session_id,
                player_id,
                "Player",
                [character_id, f"commit_race_peer_{suffix}"],
            )
        else:
            repository.create_session(
                session_id,
                character_id,
                player_id,
                "Player",
            )

        losing_claim = repository.claim_dialogue_turn(
            session_id=session_id,
            request_id=request_id,
            player_id=player_id,
            turn_kind=turn_kind,
        )
        with repository.get_conn() as conn:
            conn.execute(
                """
                UPDATE dialogue_turn
                SET lease_expires_at = '2000-01-01T00:00:00+00:00'
                WHERE session_id = ? AND request_id = ?
                """,
                (session_id, request_id),
            )
        winning_claim = repository.claim_dialogue_turn(
            session_id=session_id,
            request_id=request_id,
            player_id=player_id,
            turn_kind=turn_kind,
        )
        repository.commit_event_execution_batch(
            player_id=player_id,
            execution_key=execution_key,
            trigger_source=(
                "multi_dialogue" if turn_kind == "multi" else "dialogue"
            ),
            results_data="[]",
            executions=[],
            dialogue_turn={
                "session_id": session_id,
                "request_id": request_id,
                "player_id": player_id,
                "lease_owner": winning_claim["lease_owner"],
                "response": deepcopy(canonical_response),
                "runtime_states": [],
                "messages": [],
            },
        )

        monkeypatch.setattr(
            event_runtime.repository,
            "get_event_execution_batch",
            lambda player_id, execution_key: None,
        )
        context = self._context(
            execution_key=execution_key,
            character_id=character_id,
            player_id=player_id,
        ).model_copy(update={"session_id": session_id})
        local_response = deepcopy(local_response)
        turn_holder = {}

        def build_losing_turn(results):
            turn = {
                "session_id": session_id,
                "request_id": request_id,
                "player_id": player_id,
                "lease_owner": losing_claim["lease_owner"],
                "response": local_response,
                "runtime_states": [],
                "messages": [],
            }
            turn_holder["turn"] = turn
            return turn

        if turn_kind == "multi":
            replay = event_runtime.detect_and_execute_event_contexts(
                [context],
                [],
                dialogue_turn_factory=build_losing_turn,
            )
        else:
            replay = event_runtime.detect_and_execute_events(
                context,
                [],
                dialogue_turn_factory=build_losing_turn,
            )

        assert replay == []
        assert turn_holder["turn"]["response"] is local_response
        assert local_response == canonical_response

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
        repository.end_session(first_session_id)
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

    def test_player_exclusive_group_rejects_second_event_across_turns(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"player_scope_{suffix}"
        character_id = f"player_scope_character_{suffix}"
        first = self._event(
            f"player_scope_first_{suffix}",
            [],
            exclusive_group="ending",
            exclusive_scope="player",
        )
        second = self._event(
            f"player_scope_second_{suffix}",
            [],
            exclusive_group="ending",
            exclusive_scope="player",
        )
        for event in (first, second):
            assert repository.save_event_definition(
                owner_user_id=player_id,
                event_id=event.event_id,
                event_name=event.event_name,
                trigger_config=event.trigger_condition.model_dump_json(),
                effects_config="[]",
                exclusive_group=event.exclusive_group,
                exclusive_scope=event.exclusive_scope,
            )

        first_result = event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"player-scope:{suffix}:first",
                character_id=character_id,
                player_id=player_id,
            ),
            [first],
        )[0]
        second_result = event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"player-scope:{suffix}:second",
                character_id=character_id,
                player_id=player_id,
            ),
            [second],
        )[0]

        assert first_result.status == "succeeded"
        assert second_result.status == "skipped"
        assert repository.get_event_exclusive_group_selection(
            player_id,
            "ending",
        )["selected_event_id"] == first.event_id

    def test_selected_event_group_update_releases_old_group_selection(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"updated_group_player_{suffix}"
        character_id = f"updated_group_character_{suffix}"
        old_group = f"old_group_{suffix}"
        new_group = f"new_group_{suffix}"
        selected_event = self._event(
            f"updated_group_selected_{suffix}",
            [],
            exclusive_group=old_group,
            exclusive_scope="player",
        )
        competing_event = self._event(
            f"updated_group_competing_{suffix}",
            [],
            exclusive_group=new_group,
            exclusive_scope="player",
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=selected_event.event_id,
            event_name=selected_event.event_name,
            trigger_config=selected_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=old_group,
            exclusive_scope="player",
        )
        assert event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"updated-group:{suffix}:selected",
                character_id=character_id,
                player_id=player_id,
            ),
            [selected_event],
        )[0].status == "succeeded"

        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=selected_event.event_id,
            event_name=selected_event.event_name,
            trigger_config=selected_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=new_group,
            exclusive_scope="player",
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=competing_event.event_id,
            event_name=competing_event.event_name,
            trigger_config=competing_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=new_group,
            exclusive_scope="player",
        )

        assert repository.get_event_exclusive_group_selection(
            player_id,
            old_group,
        ) is None
        competing_result = event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"updated-group:{suffix}:competing",
                character_id=character_id,
                player_id=player_id,
            ),
            [competing_event],
        )[0]
        assert competing_result.status == "skipped"
        assert repository.get_event_exclusive_group_selection(
            player_id,
            new_group,
        )["selected_event_id"] == selected_event.event_id

    def test_selected_event_scope_update_to_turn_releases_player_selection(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"updated_scope_player_{suffix}"
        character_id = f"updated_scope_character_{suffix}"
        exclusive_group = f"updated_scope_group_{suffix}"
        selected_event = self._event(
            f"updated_scope_selected_{suffix}",
            [],
            exclusive_group=exclusive_group,
            exclusive_scope="player",
        )
        competing_event = self._event(
            f"updated_scope_competing_{suffix}",
            [],
            exclusive_group=exclusive_group,
            exclusive_scope="player",
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=selected_event.event_id,
            event_name=selected_event.event_name,
            trigger_config=selected_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=exclusive_group,
            exclusive_scope="player",
        )
        assert event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"updated-scope:{suffix}:selected",
                character_id=character_id,
                player_id=player_id,
            ),
            [selected_event],
        )[0].status == "succeeded"

        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=selected_event.event_id,
            event_name=selected_event.event_name,
            trigger_config=selected_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=exclusive_group,
            exclusive_scope="turn",
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=competing_event.event_id,
            event_name=competing_event.event_name,
            trigger_config=competing_event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=exclusive_group,
            exclusive_scope="player",
        )

        assert repository.get_event_exclusive_group_selection(
            player_id,
            exclusive_group,
        ) is None
        competing_result = event_runtime.detect_and_execute_events(
            self._context(
                execution_key=f"updated-scope:{suffix}:competing",
                character_id=character_id,
                player_id=player_id,
            ),
            [competing_event],
        )[0]
        assert competing_result.status == "succeeded"
        assert repository.get_event_exclusive_group_selection(
            player_id,
            exclusive_group,
        )["selected_event_id"] == competing_event.event_id

    @pytest.mark.parametrize(
        ("updated_group", "updated_scope"),
        [
            ("new", "player"),
            ("old", "turn"),
        ],
    )
    def test_inflight_exclusive_claim_does_not_select_stale_group_after_update(
        self,
        updated_group,
        updated_scope,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"inflight_update_player_{suffix}"
        character_id = f"inflight_update_character_{suffix}"
        old_group = f"inflight_old_group_{suffix}"
        new_group = f"inflight_new_group_{suffix}"
        event = self._event(
            f"inflight_update_event_{suffix}",
            [],
            exclusive_group=old_group,
            exclusive_scope="player",
        )
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=event.event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=old_group,
            exclusive_scope="player",
        )
        context = self._context(
            execution_key=f"inflight-update:{suffix}",
            character_id=character_id,
            player_id=player_id,
        )
        results, executions = event_runtime._plan_event_roots(
            [(event, context)],
            {event.event_id: event},
            enforce_cooldown=True,
        )
        assert results[0].status == "succeeded"
        assert executions[0]["exclusive_group_claim_token"]

        current_group = new_group if updated_group == "new" else old_group
        assert repository.save_event_definition(
            owner_user_id=player_id,
            event_id=event.event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config="[]",
            exclusive_group=current_group,
            exclusive_scope=updated_scope,
        )
        repository.commit_event_execution_batch(
            player_id=player_id,
            execution_key=context.execution_key,
            trigger_source=context.trigger_source,
            results_data=json.dumps(
                [result.model_dump(mode="json") for result in results],
                ensure_ascii=False,
            ),
            executions=executions,
        )

        assert repository.get_event_exclusive_group_selection(
            player_id,
            old_group,
        ) is None

    def test_turn_exclusive_group_allows_different_event_on_later_turn(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"turn_scope_{suffix}"
        character_id = f"turn_scope_character_{suffix}"
        events = [
            self._event(
                f"turn_scope_{index}_{suffix}",
                [],
                exclusive_group="revelation",
            )
            for index in range(2)
        ]
        for event in events:
            assert event.exclusive_scope == "turn"
            assert repository.save_event_definition(
                owner_user_id=player_id,
                event_id=event.event_id,
                event_name=event.event_name,
                trigger_config=event.trigger_condition.model_dump_json(),
                effects_config="[]",
                exclusive_group=event.exclusive_group,
            )

        results = [
            event_runtime.detect_and_execute_events(
                self._context(
                    execution_key=f"turn-scope:{suffix}:{index}",
                    character_id=character_id,
                    player_id=player_id,
                ),
                [event],
            )[0]
            for index, event in enumerate(events)
        ]

        assert [result.status for result in results] == ["succeeded", "succeeded"]
        assert repository.get_event_exclusive_group_selection(
            player_id,
            "revelation",
        ) is None

    def test_concurrent_player_exclusive_group_commits_only_one_event(
        self,
        monkeypatch,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"concurrent_scope_{suffix}"
        character_id = f"concurrent_scope_character_{suffix}"
        events = [
            self._event(
                f"concurrent_scope_{index}_{suffix}",
                [],
                exclusive_group="ending",
                exclusive_scope="player",
            )
            for index in range(2)
        ]
        for event in events:
            assert repository.save_event_definition(
                owner_user_id=player_id,
                event_id=event.event_id,
                event_name=event.event_name,
                trigger_config=event.trigger_condition.model_dump_json(),
                effects_config="[]",
                exclusive_group=event.exclusive_group,
                exclusive_scope=event.exclusive_scope,
            )

        claim_barrier = Barrier(2)
        original_claim = repository.claim_event_exclusive_group

        def synchronized_claim(**kwargs):
            claim_barrier.wait(timeout=5)
            return original_claim(**kwargs)

        monkeypatch.setattr(
            event_runtime.repository,
            "claim_event_exclusive_group",
            synchronized_claim,
        )

        def run(index):
            return event_runtime.detect_and_execute_events(
                self._context(
                    execution_key=f"concurrent-scope:{suffix}:{index}",
                    character_id=character_id,
                    player_id=player_id,
                ),
                [events[index]],
            )[0]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, range(2)))

        assert sorted(result.status for result in results) == ["skipped", "succeeded"]
        selected = repository.get_event_exclusive_group_selection(
            player_id,
            "ending",
        )
        assert selected["selected_event_id"] in {event.event_id for event in events}
        assert sum(
            len(repository.get_event_trigger_history(
                event_id=event.event_id,
                player_id=player_id,
            ))
            for event in events
        ) == 1

    @pytest.mark.parametrize("failure_point", ["context_state", "execution_record"])
    def test_planning_exception_releases_event_claims(
        self,
        monkeypatch,
        failure_point,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"planning_failure_player_{suffix}"
        character_id = f"planning_failure_character_{suffix}"
        event = self._event(
            f"planning_failure_event_{suffix}",
            [],
            exclusive_group=f"planning_failure_group_{suffix}",
            exclusive_scope="player",
        )
        if failure_point == "context_state":
            monkeypatch.setattr(
                event_runtime,
                "_context_state_for_result",
                Mock(side_effect=RuntimeError("context state failed")),
            )
        else:
            monkeypatch.setattr(
                event_runtime.get_event_executor(),
                "build_execution_record",
                Mock(side_effect=RuntimeError("execution record failed")),
            )

        with pytest.raises(RuntimeError, match="failed"):
            event_runtime.detect_and_execute_events(
                self._context(
                    execution_key=f"planning-failure:{suffix}",
                    character_id=character_id,
                    player_id=player_id,
                ),
                [event],
            )

        with repository.get_conn() as conn:
            trigger_guard = conn.execute(
                """
                SELECT claim_token
                FROM event_trigger_guard
                WHERE player_id = ? AND event_id = ?
                """,
                (player_id, event.event_id),
            ).fetchone()
            exclusive_guard = conn.execute(
                """
                SELECT claim_token, selected_event_id
                FROM event_exclusive_group_guard
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (player_id, event.exclusive_group),
            ).fetchone()

        assert trigger_guard["claim_token"] is None
        assert exclusive_guard["claim_token"] is None
        assert exclusive_guard["selected_event_id"] is None

    def test_exclusive_claim_exception_releases_trigger_claim(
        self,
        monkeypatch,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"exclusive_claim_failure_player_{suffix}"
        character_id = f"exclusive_claim_failure_character_{suffix}"
        event = self._event(
            f"exclusive_claim_failure_event_{suffix}",
            [],
            exclusive_group=f"exclusive_claim_failure_group_{suffix}",
            exclusive_scope="player",
        )
        monkeypatch.setattr(
            event_runtime.repository,
            "claim_event_exclusive_group",
            Mock(side_effect=RuntimeError("exclusive claim failed")),
        )

        with pytest.raises(RuntimeError, match="exclusive claim failed"):
            event_runtime.detect_and_execute_events(
                self._context(
                    execution_key=f"exclusive-claim-failure:{suffix}",
                    character_id=character_id,
                    player_id=player_id,
                ),
                [event],
            )

        with repository.get_conn() as conn:
            trigger_guard = conn.execute(
                """
                SELECT claim_token
                FROM event_trigger_guard
                WHERE player_id = ? AND event_id = ?
                """,
                (player_id, event.event_id),
            ).fetchone()

        assert trigger_guard["claim_token"] is None

    def test_dialogue_turn_factory_exception_releases_event_claims(self):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"dialogue_factory_player_{suffix}"
        character_id = f"dialogue_factory_character_{suffix}"
        event = self._event(
            f"dialogue_factory_event_{suffix}",
            [],
            exclusive_group=f"dialogue_factory_group_{suffix}",
            exclusive_scope="player",
        )

        def fail_dialogue_turn_factory(results):
            raise RuntimeError("dialogue turn factory failed")

        with pytest.raises(RuntimeError, match="dialogue turn factory failed"):
            event_runtime.detect_and_execute_events(
                self._context(
                    execution_key=f"dialogue-factory:{suffix}",
                    character_id=character_id,
                    player_id=player_id,
                ),
                [event],
                dialogue_turn_factory=fail_dialogue_turn_factory,
            )

        with repository.get_conn() as conn:
            trigger_guard = conn.execute(
                """
                SELECT claim_token
                FROM event_trigger_guard
                WHERE player_id = ? AND event_id = ?
                """,
                (player_id, event.event_id),
            ).fetchone()
            exclusive_guard = conn.execute(
                """
                SELECT claim_token, selected_event_id
                FROM event_exclusive_group_guard
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (player_id, event.exclusive_group),
            ).fetchone()

        assert trigger_guard["claim_token"] is None
        assert exclusive_guard["claim_token"] is None
        assert exclusive_guard["selected_event_id"] is None

    @pytest.mark.parametrize("group_context", [False, True])
    def test_condition_trace_exception_releases_event_claims(
        self,
        monkeypatch,
        group_context,
    ):
        from memoria.core import event_runtime
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"trace_failure_player_{suffix}"
        character_id = f"trace_failure_character_{suffix}"
        event = self._event(
            f"trace_failure_event_{suffix}",
            [],
            exclusive_group=f"trace_failure_group_{suffix}",
            exclusive_scope="player",
        )
        context = self._context(
            execution_key=f"trace-failure:{suffix}",
            character_id=character_id,
            player_id=player_id,
        )
        monkeypatch.setattr(
            event_runtime.get_event_detector(),
            "evaluate_event",
            Mock(side_effect=RuntimeError("condition trace failed")),
        )

        with pytest.raises(RuntimeError, match="condition trace failed"):
            if group_context:
                event_runtime.detect_and_execute_event_contexts([context], [event])
            else:
                event_runtime.detect_and_execute_events(context, [event])

        with repository.get_conn() as conn:
            trigger_guard = conn.execute(
                """
                SELECT claim_token
                FROM event_trigger_guard
                WHERE player_id = ? AND event_id = ?
                """,
                (player_id, event.event_id),
            ).fetchone()
            exclusive_guard = conn.execute(
                """
                SELECT claim_token, selected_event_id
                FROM event_exclusive_group_guard
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (player_id, event.exclusive_group),
            ).fetchone()

        assert trigger_guard["claim_token"] is None
        assert exclusive_guard["claim_token"] is None
        assert exclusive_guard["selected_event_id"] is None

    @pytest.mark.parametrize("group_context", [False, True])
    def test_runtime_state_conversion_exception_releases_event_claims(
        self,
        group_context,
    ):
        from memoria.core import event_runtime
        from memoria.core.event_schema import EffectType, EventEffect
        from memoria.db import repository

        suffix = uuid.uuid4().hex[:8]
        player_id = f"state_conversion_player_{suffix}"
        character_id = f"state_conversion_character_{suffix}"
        event = self._event(
            f"state_conversion_event_{suffix}",
            [
                EventEffect(
                    effect_type=EffectType.MODIFY_STATE,
                    state_changes={"trust_level": "not-a-number"},
                )
            ],
            exclusive_group=f"state_conversion_group_{suffix}",
            exclusive_scope="player",
        )
        context = self._context(
            execution_key=f"state-conversion:{suffix}",
            character_id=character_id,
            player_id=player_id,
        )

        with pytest.raises(ValueError, match="could not convert string to float"):
            if group_context:
                event_runtime.detect_and_execute_event_contexts([context], [event])
            else:
                event_runtime.detect_and_execute_events(context, [event])

        with repository.get_conn() as conn:
            trigger_guard = conn.execute(
                """
                SELECT claim_token
                FROM event_trigger_guard
                WHERE player_id = ? AND event_id = ?
                """,
                (player_id, event.event_id),
            ).fetchone()
            exclusive_guard = conn.execute(
                """
                SELECT claim_token, selected_event_id
                FROM event_exclusive_group_guard
                WHERE player_id = ? AND exclusive_group = ?
                """,
                (player_id, event.exclusive_group),
            ).fetchone()

        assert trigger_guard["claim_token"] is None
        assert exclusive_guard["claim_token"] is None
        assert exclusive_guard["selected_event_id"] is None

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
