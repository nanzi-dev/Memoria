"""群聊逐消息决策脉冲与长期记忆分发测试。"""

import json
from types import SimpleNamespace
import uuid

import pytest
from pydantic import ValidationError


def _orchestrator():
    from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

    orchestrator = MultiCharacterOrchestrator.__new__(MultiCharacterOrchestrator)
    orchestrator.session_id = "session-1"
    orchestrator.player_id = "player-1"
    orchestrator.player_name = "Player"
    orchestrator.participants = [
        {"character_id": "c1", "message_count": 0},
        {"character_id": "c2", "message_count": 0},
    ]
    orchestrator.character_ids = ["c1", "c2"]
    orchestrator.character_cards = {
        "c1": SimpleNamespace(meta=SimpleNamespace(name="甲", display_name="甲")),
        "c2": SimpleNamespace(meta=SimpleNamespace(name="乙", display_name="乙")),
    }
    orchestrator.last_speaker_id = None
    return orchestrator


def _decision(**updates):
    from memoria.core.multi_character_orchestrator import DialogueDecision

    values = {
        "action": "speak",
        "speaker_id": "c1",
        "reply_to_message_id": 1,
        "intent": "answer",
        "topic": "计划",
    }
    values.update(updates)
    return DialogueDecision(**values)


def _complete_response(character_id: str, dialogue: str) -> dict:
    return {
        "message_id": -2,
        "character_id": character_id,
        "character_name": character_id,
        "dialogue": dialogue,
        "current_affinity": 10,
        "current_trust": 20,
        "current_mood": "neutral",
        "_previous_affinity": 10,
        "_previous_trust": 20,
        "affinity_delta": 0,
        "trust_delta": 0,
    }


def _apply_event_turn(
    orchestrator,
    *,
    player_text: str,
    responses: list[dict],
    request_id: str,
):
    from memoria.core import multi_character_orchestrator

    claim = multi_character_orchestrator.repository.claim_dialogue_turn(
        session_id=orchestrator.session_id,
        request_id=request_id,
        player_id=orchestrator.player_id,
        turn_kind="multi",
    )
    return orchestrator._apply_group_event_results(
        player_text,
        responses,
        clock_snapshot=SimpleNamespace(
            world_now=SimpleNamespace(
                isoformat=lambda: "2026-07-16T12:00:00+08:00"
            )
        ),
        request_id=request_id,
        lease_owner=claim["lease_owner"],
        player_message={
            "message_id": -1,
            "role": "user",
            "content": player_text,
            "world_created_at": "2026-07-16T12:00:00+08:00",
            "trigger_source": "player",
        },
    )


def test_zero_speaker_turn_still_triggers_player_event_and_commits_message(
    monkeypatch,
):
    from memoria.core import multi_character_orchestrator
    from memoria.core.event_schema import TriggerCondition, TriggerType

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"zero-speaker-session-{suffix}"
    orchestrator.player_id = f"zero-speaker-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    event_id = f"zero-speaker-event-{suffix}"
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        event_id,
        "Zero speaker player event",
        TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["保持安静"],
        ).model_dump_json(),
        "[]",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})

    results = _apply_event_turn(
        orchestrator,
        player_text="这轮保持安静",
        responses=[],
        request_id=f"zero-speaker-{suffix}",
    )

    assert [result.event_id for result in results] == [event_id]
    history = multi_character_orchestrator.repository.get_multi_character_thread_history(
        orchestrator.session_id,
        limit_messages=10,
    )
    assert [(message["role"], message["content"]) for message in history] == [
        ("user", "这轮保持安静")
    ]


def test_character_player_event_triggers_when_another_character_responds(
    monkeypatch,
):
    from memoria.core import multi_character_orchestrator
    from memoria.core.event_schema import TriggerCondition, TriggerType

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"nonresponder-session-{suffix}"
    orchestrator.player_id = f"nonresponder-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    event_id = f"nonresponder-event-{suffix}"
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        event_id,
        "Listener player event",
        TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["证人名单"],
        ).model_dump_json(),
        "[]",
        character_id="c2",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})

    results = _apply_event_turn(
        orchestrator,
        player_text="我拿到了证人名单",
        responses=[_complete_response("c1", "我来核对。")],
        request_id=f"nonresponder-{suffix}",
    )

    assert [result.event_id for result in results] == [event_id]
    assert results[0].character_id == "c2"


def test_silent_participant_commit_does_not_overwrite_newer_runtime_state(
    monkeypatch,
):
    from memoria.core import event_runtime, multi_character_orchestrator

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"silent-state-session-{suffix}"
    orchestrator.player_id = f"silent-state-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    multi_character_orchestrator.repository.save_runtime_state(
        "c2",
        orchestrator.player_id,
        4,
        5,
        "calm",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    original_detect = event_runtime.detect_and_execute_event_contexts

    def update_silent_state_before_commit(contexts, **kwargs):
        multi_character_orchestrator.repository.save_runtime_state(
            "c2",
            orchestrator.player_id,
            77,
            88,
            "alert",
        )
        return original_detect(contexts, **kwargs)

    monkeypatch.setattr(
        event_runtime,
        "detect_and_execute_event_contexts",
        update_silent_state_before_commit,
    )

    _apply_event_turn(
        orchestrator,
        player_text="继续讨论",
        responses=[_complete_response("c1", "我先说。")],
        request_id=f"silent-state-{suffix}",
    )

    state = multi_character_orchestrator.repository.get_runtime_state(
        "c2",
        orchestrator.player_id,
        orchestrator.character_cards["c2"],
    )
    assert state["affection_level"] == 77
    assert state["trust_level"] == 88
    assert state["current_mood"] == "alert"


def test_silent_participant_event_delta_applies_to_newer_runtime_state(
    monkeypatch,
):
    from memoria.core import event_runtime, multi_character_orchestrator
    from memoria.core.event_schema import (
        EffectType,
        EventEffect,
        TriggerCondition,
        TriggerType,
    )

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"silent-delta-session-{suffix}"
    orchestrator.player_id = f"silent-delta-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    multi_character_orchestrator.repository.save_runtime_state(
        "c2",
        orchestrator.player_id,
        4,
        5,
        "calm",
    )
    effect = EventEffect(
        effect_type=EffectType.MODIFY_STATE,
        state_changes={"trust_level": 3},
    )
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        f"silent-delta-event-{suffix}",
        "Silent participant state event",
        TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["静默状态"],
        ).model_dump_json(),
        json.dumps([effect.model_dump(mode="json")], ensure_ascii=False),
        character_id="c2",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    original_detect = event_runtime.detect_and_execute_event_contexts

    def update_silent_state_before_commit(contexts, **kwargs):
        multi_character_orchestrator.repository.save_runtime_state(
            "c2",
            orchestrator.player_id,
            77,
            88,
            "alert",
        )
        return original_detect(contexts, **kwargs)

    monkeypatch.setattr(
        event_runtime,
        "detect_and_execute_event_contexts",
        update_silent_state_before_commit,
    )

    _apply_event_turn(
        orchestrator,
        player_text="触发静默状态",
        responses=[_complete_response("c1", "我先说。")],
        request_id=f"silent-delta-{suffix}",
    )

    state = multi_character_orchestrator.repository.get_runtime_state(
        "c2",
        orchestrator.player_id,
        orchestrator.character_cards["c2"],
    )
    assert state["affection_level"] == 77
    assert state["trust_level"] == 91
    assert state["current_mood"] == "alert"


def test_npc_keyword_event_does_not_use_another_characters_response(monkeypatch):
    from memoria.core import multi_character_orchestrator
    from memoria.core.event_schema import TriggerCondition, TriggerType

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"npc-keyword-session-{suffix}"
    orchestrator.player_id = f"npc-keyword-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    event_id = f"npc-keyword-event-{suffix}"
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        event_id,
        "Listener NPC event",
        TriggerCondition(
            trigger_type=TriggerType.NPC_KEYWORD_MATCH,
            keywords=["内部暗号"],
        ).model_dump_json(),
        "[]",
        character_id="c2",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})

    results = _apply_event_turn(
        orchestrator,
        player_text="继续",
        responses=[_complete_response("c1", "我说出了内部暗号。")],
        request_id=f"npc-keyword-{suffix}",
    )

    assert results == []
    assert multi_character_orchestrator.repository.get_event_trigger_history(
        event_id=event_id,
        player_id=orchestrator.player_id,
    ) == []


def test_repeated_speaker_event_checks_each_response_in_order(monkeypatch):
    from memoria.core import multi_character_orchestrator
    from memoria.core.event_schema import TriggerCondition, TriggerType

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"repeated-speaker-session-{suffix}"
    orchestrator.player_id = f"repeated-speaker-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    event_id = f"repeated-speaker-event-{suffix}"
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        event_id,
        "Repeated speaker NPC event",
        TriggerCondition(
            trigger_type=TriggerType.NPC_KEYWORD_MATCH,
            keywords=["首轮暗号"],
        ).model_dump_json(),
        "[]",
        character_id="c1",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})

    results = _apply_event_turn(
        orchestrator,
        player_text="继续",
        responses=[
            _complete_response("c1", "首轮暗号已经确认。"),
            _complete_response("c2", "我没有补充。"),
            _complete_response("c1", "那就按计划行动。"),
        ],
        request_id=f"repeated-speaker-{suffix}",
    )

    assert [result.event_id for result in results] == [event_id]
    assert results[0].character_id == "c1"


def test_repeated_speaker_event_effects_apply_only_to_matching_response(
    monkeypatch,
):
    from memoria.core import multi_character_orchestrator
    from memoria.core.event_schema import (
        EffectType,
        EventEffect,
        TriggerCondition,
        TriggerType,
    )

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"repeated-effects-session-{suffix}"
    orchestrator.player_id = f"repeated-effects-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    event_id = f"repeated-effects-event-{suffix}"
    effects = [
        EventEffect(
            effect_type=EffectType.TRIGGER_DIALOGUE,
            dialogue_text="仅覆盖命中暗号的回应。",
        ),
        EventEffect(
            effect_type=EffectType.MODIFY_STATE,
            state_changes={"trust_level": 3},
        ),
        EventEffect(
            effect_type=EffectType.NOTIFY_PLAYER,
            notification_message="首轮暗号已确认。",
        ),
    ]
    assert multi_character_orchestrator.repository.save_event_definition(
        orchestrator.player_id,
        event_id,
        "Repeated speaker response-local event",
        TriggerCondition(
            trigger_type=TriggerType.NPC_KEYWORD_MATCH,
            keywords=["首轮暗号"],
        ).model_dump_json(),
        json.dumps(
            [effect.model_dump(mode="json") for effect in effects],
            ensure_ascii=False,
        ),
        character_id="c1",
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    responses = [
        _complete_response("c1", "首轮暗号已经确认。"),
        _complete_response("c2", "我没有补充。"),
        _complete_response("c1", "那就按计划行动。"),
    ]

    _apply_event_turn(
        orchestrator,
        player_text="继续",
        responses=responses,
        request_id=f"repeated-effects-{suffix}",
    )

    assert responses[0]["dialogue"] == "[事件触发] 仅覆盖命中暗号的回应。"
    assert responses[0]["current_trust"] == 23
    assert responses[0]["event_notification"] == "首轮暗号已确认。"
    assert [
        execution["event_id"]
        for execution in responses[0]["event_executions"]
    ] == [event_id]
    assert responses[2]["dialogue"] == "那就按计划行动。"
    assert responses[2]["current_trust"] == 20
    assert responses[2]["event_notification"] is None
    assert responses[2]["event_executions"] == []
    assert responses[2]["event_notifications"] == []


def test_group_event_replay_factory_receives_original_presentation_results():
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
    player_id = f"group-replay-player-{suffix}"
    character_id = f"group-replay-character-{suffix}"
    event_id = f"group-replay-event-{suffix}"
    execution_key = f"group-replay:{suffix}"
    dialogue_override = "重放仍应呈现事件对白。"
    notification = "重放仍应呈现事件通知。"
    event = EventDefinition(
        event_id=event_id,
        event_name="Group replay presentation event",
        character_id=character_id,
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["重放展示"],
        ),
        effects=[
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
        event_id=event.event_id,
        event_name=event.event_name,
        trigger_config=event.trigger_condition.model_dump_json(),
        effects_config=json.dumps(
            [effect.model_dump(mode="json") for effect in event.effects],
            ensure_ascii=False,
        ),
        character_id=character_id,
    )
    context = EventContext(
        character_id=character_id,
        player_id=player_id,
        session_id=f"group-replay-session-{suffix}",
        current_affinity=10,
        current_trust=20,
        current_mood="neutral",
        previous_affinity=10,
        previous_trust=20,
        player_message="请执行重放展示",
        npc_response="原始回应",
        dialogue_count=1,
        total_dialogue_count=1,
        session_duration_minutes=1,
        execution_key=execution_key,
        response_index=2,
    )

    first = event_runtime.detect_and_execute_event_contexts([context], [event])
    captured = {}

    def capture_presentation(results):
        (
            captured["dialogue"],
            captured["affinity"],
            captured["trust"],
            captured["mood"],
            captured["triggered_events"],
            captured["notification"],
        ) = event_runtime.apply_event_results_to_dialogue_state(
            results,
            "原始回应",
            10,
            20,
            "neutral",
        )
        captured["event_executions"] = [
            result.model_dump(mode="json") for result in results
        ]
        captured["event_notifications"] = (
            event_runtime.collect_event_notifications(results)
        )
        return {}

    replay = event_runtime.detect_and_execute_event_contexts(
        [context],
        [event],
        dialogue_turn_factory=capture_presentation,
    )

    assert first[0].status == "succeeded"
    assert captured["dialogue"] == f"[事件触发] {dialogue_override}"
    assert captured["trust"] == 23
    assert captured["notification"] == notification
    assert captured["event_executions"][0]["execution_id"] == first[0].execution_id
    assert captured["event_executions"][0]["response_index"] == 2
    assert captured["event_executions"][0]["status"] == "succeeded"
    assert [
        item["message"] for item in captured["event_notifications"]
    ] == [notification]
    assert replay[0].status == "skipped"
    assert replay[0].deduplicated is True


def test_repeated_speaker_persists_final_response_state(monkeypatch):
    from memoria.core import multi_character_orchestrator

    suffix = uuid.uuid4().hex[:8]
    orchestrator = _orchestrator()
    orchestrator.session_id = f"repeated-state-session-{suffix}"
    orchestrator.player_id = f"repeated-state-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        orchestrator.session_id,
        orchestrator.player_id,
        "Player",
        orchestrator.character_ids,
    )
    monkeypatch.setattr(orchestrator, "_load_all_relationships", lambda: {})
    first_response = _complete_response("c1", "我先提出方案。")
    first_response["current_affinity"] = 11
    first_response["current_trust"] = 21
    final_response = _complete_response("c1", "我修正最终方案。")
    final_response["current_affinity"] = 14
    final_response["current_trust"] = 24
    final_response["current_mood"] = "focused"

    _apply_event_turn(
        orchestrator,
        player_text="继续",
        responses=[
            first_response,
            _complete_response("c2", "我来补充。"),
            final_response,
        ],
        request_id=f"repeated-state-{suffix}",
    )

    state = multi_character_orchestrator.repository.get_runtime_state(
        "c1",
        orchestrator.player_id,
        orchestrator.character_cards["c1"],
    )
    assert state["affection_level"] == 14
    assert state["trust_level"] == 24
    assert state["current_mood"] == "focused"


def test_dialogue_decision_rejects_extra_fields_and_malformed_json():
    from memoria.core.multi_character_orchestrator import MultiCharacterOrchestrator

    with pytest.raises(ValidationError):
        MultiCharacterOrchestrator._parse_dialogue_decision(
            '{"action":"wait","unexpected":true}'
        )
    with pytest.raises(Exception):
        MultiCharacterOrchestrator._parse_dialogue_decision("这不是 JSON")


def test_invalid_decision_json_uses_deterministic_fallback(monkeypatch):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    fallback = _decision(action="wait", speaker_id=None, wait_for_player=True)
    monkeypatch.setattr(
        multi_character_orchestrator.llm_client,
        "call_light_task",
        lambda *args, **kwargs: "invalid",
    )
    monkeypatch.setattr(
        orchestrator,
        "_fallback_dialogue_decision",
        lambda **kwargs: fallback,
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_dialogue_decision_prompt",
        lambda **kwargs: "prompt",
    )

    result = orchestrator._decide_dialogue_action(
        history=[{"message_id": 1, "role": "user", "content": "继续"}],
        trigger_source="player",
        trigger_text="继续",
        trigger_message_id=1,
        initial_speaker_id=None,
        previous_responses=[],
    )

    assert result == fallback


def test_pulse_redecides_after_each_message_and_can_reply_to_npc(monkeypatch):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    histories = iter([
        [{"message_id": 1, "role": "user", "content": "怎么行动？"}],
        [
            {"message_id": 1, "role": "user", "content": "怎么行动？"},
            {
                "message_id": 2,
                "role": "assistant",
                "content": "先侦查。",
                "character_id": "c1",
                "character_name": "甲",
            },
        ],
        [
            {"message_id": 1, "role": "user", "content": "怎么行动？"},
            {
                "message_id": 2,
                "role": "assistant",
                "content": "先侦查。",
                "character_id": "c1",
                "character_name": "甲",
            },
            {
                "message_id": 3,
                "role": "assistant",
                "content": "我补充路线。",
                "character_id": "c2",
                "character_name": "乙",
            },
        ],
    ])
    decisions = iter([
        _decision(speaker_id="c1", reply_to_message_id=1),
        _decision(
            speaker_id="c2",
            reply_to_message_id=2,
            reply_to_character_id="c1",
            intent="agree",
        ),
        _decision(
            speaker_id="c1",
            reply_to_message_id=3,
            reply_to_character_id="c2",
            intent="challenge",
        ),
    ])
    generated = []

    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: next(histories),
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_group_thread_id",
        lambda session_id: "thread-1",
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "save_group_dialogue_state",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        orchestrator,
        "_decide_dialogue_action",
        lambda **kwargs: next(decisions),
    )

    def generate(character_id, player_message, **kwargs):
        generated.append({
            "character_id": character_id,
            "target": kwargs["target_message"]["message_id"],
            "trigger_source": kwargs["trigger_source"],
        })
        return {
            "message_id": len(generated) + 1,
            "character_id": character_id,
            "character_name": "甲" if character_id == "c1" else "乙",
            "dialogue": f"reply-{len(generated)}",
        }

    monkeypatch.setattr(orchestrator, "_generate_character_response", generate)

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="player",
        trigger_text="怎么行动？",
        trigger_message_id=1,
        max_messages=5,
        clock_snapshot=SimpleNamespace(world_now=SimpleNamespace(isoformat=lambda: "now")),
    )

    assert [response["character_id"] for response in responses] == ["c1", "c2", "c1"]
    assert generated == [
        {"character_id": "c1", "target": 1, "trigger_source": "player"},
        {"character_id": "c2", "target": 2, "trigger_source": "npc_follow_up"},
        {"character_id": "c1", "target": 3, "trigger_source": "npc_follow_up"},
    ]


def test_pulse_persists_each_reply_once_for_next_decision(monkeypatch):
    from memoria.core import multi_character_orchestrator

    suffix = uuid.uuid4().hex[:8]
    session_id = f"pulse-session-{suffix}"
    player_id = f"pulse-player-{suffix}"
    assert multi_character_orchestrator.repository.create_multi_character_session(
        session_id,
        player_id,
        "Player",
        ["c1", "c2"],
    )
    player_message_id = (
        multi_character_orchestrator.repository.append_multi_character_message(
            session_id,
            role="user",
            content="怎么行动？",
            trigger_source="player",
        )
    )

    orchestrator = _orchestrator()
    orchestrator.session_id = session_id
    orchestrator.player_id = player_id
    observed_histories = []

    def decide(**kwargs):
        history = kwargs["history"]
        observed_histories.append([message["content"] for message in history])
        if len(observed_histories) == 1:
            return _decision(
                speaker_id="c1",
                reply_to_message_id=player_message_id,
            )
        if len(observed_histories) == 2:
            return _decision(
                speaker_id="c2",
                reply_to_message_id=history[-1]["message_id"],
                reply_to_character_id="c1",
                intent="agree",
            )
        return _decision(action="wait", speaker_id=None)

    def generate(character_id, _player_message, **kwargs):
        decision = kwargs["decision"]
        return {
            "character_id": character_id,
            "character_name": "甲" if character_id == "c1" else "乙",
            "dialogue": "先侦查。" if character_id == "c1" else "我补充路线。",
            "world_created_at": "2026-01-01T08:00:00+00:00",
            "reply_to_message_id": decision.reply_to_message_id,
            "reply_to_character_id": decision.reply_to_character_id,
            "intent": decision.intent,
            "topic": decision.topic,
            "trigger_source": kwargs["trigger_source"],
        }

    monkeypatch.setattr(orchestrator, "_decide_dialogue_action", decide)
    monkeypatch.setattr(orchestrator, "_generate_character_response", generate)

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="player",
        trigger_text="怎么行动？",
        trigger_message_id=player_message_id,
        max_messages=3,
        persist_state=False,
        clock_snapshot=SimpleNamespace(
            world_now=SimpleNamespace(
                isoformat=lambda: "2026-01-01T08:00:00+00:00"
            )
        ),
    )

    history = multi_character_orchestrator.repository.get_multi_character_history(
        session_id,
        limit_messages=None,
    )
    assert observed_histories == [
        ["怎么行动？"],
        ["怎么行动？", "先侦查。"],
        ["怎么行动？", "先侦查。", "我补充路线。"],
    ]
    assert [message["content"] for message in history] == observed_histories[-1]
    assert len({response["message_id"] for response in responses}) == 2
    assert history[-1]["reply_to_message_id"] == responses[0]["message_id"]


def test_unpersisted_pulse_uses_staged_messages_for_next_decision(monkeypatch):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    observed_histories = []

    def decide(**kwargs):
        history = kwargs["history"]
        observed_histories.append([dict(message) for message in history])
        if len(observed_histories) == 1:
            return _decision(speaker_id="c1", reply_to_message_id=1)
        if len(observed_histories) == 2:
            return _decision(
                speaker_id="c2",
                reply_to_message_id=history[-1]["message_id"],
                reply_to_character_id="c1",
            )
        return _decision(action="wait", speaker_id=None)

    def generate(character_id, _player_message, **kwargs):
        decision = kwargs["decision"]
        return {
            "character_id": character_id,
            "character_name": "甲" if character_id == "c1" else "乙",
            "dialogue": "先侦查。" if character_id == "c1" else "我补充路线。",
            "reply_to_message_id": decision.reply_to_message_id,
            "reply_to_character_id": decision.reply_to_character_id,
            "intent": decision.intent,
            "topic": decision.topic,
            "trigger_source": kwargs["trigger_source"],
        }

    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [
            {"message_id": 1, "role": "user", "content": "怎么行动？"}
        ],
    )
    monkeypatch.setattr(orchestrator, "_decide_dialogue_action", decide)
    monkeypatch.setattr(orchestrator, "_generate_character_response", generate)

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="event",
        trigger_text="怎么行动？",
        max_messages=3,
        persist_state=False,
        persist_messages=False,
        clock_snapshot=SimpleNamespace(world_now=SimpleNamespace(isoformat=lambda: "now")),
    )

    assert [response["message_id"] for response in responses] == [-1, -2]
    assert responses[1]["reply_to_message_id"] == -1
    assert [message["content"] for message in observed_histories[1]] == [
        "怎么行动？",
        "先侦查。",
    ]
    assert observed_histories[1][-1]["message_id"] == -1
    assert [message["content"] for message in observed_histories[2]] == [
        "怎么行动？",
        "先侦查。",
        "我补充路线。",
    ]


@pytest.mark.parametrize(
    ("decisions", "expected_count", "waiting_for_player"),
    [
        ([_decision(action="wait", speaker_id=None)], 0, True),
        ([_decision(wait_for_player=True)], 1, True),
    ],
)
def test_pulse_stops_on_wait_or_wait_for_player(
    monkeypatch,
    decisions,
    expected_count,
    waiting_for_player,
):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    generated = []
    decision_iter = iter(decisions)
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [
            {"message_id": 1, "role": "user", "content": "继续"}
        ],
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_group_thread_id",
        lambda session_id: "thread-1",
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "save_group_dialogue_state",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        orchestrator,
        "_decide_dialogue_action",
        lambda **kwargs: next(decision_iter),
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_response",
        lambda *args, **kwargs: generated.append(True) or {
            "message_id": 2,
            "character_id": "c1",
            "character_name": "甲",
            "dialogue": "等你回应。",
        },
    )

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="player",
        trigger_text="继续",
        trigger_message_id=1,
        max_messages=3,
        clock_snapshot=SimpleNamespace(world_now=SimpleNamespace(isoformat=lambda: "now")),
    )

    assert len(responses) == expected_count
    assert len(generated) == expected_count
    assert orchestrator.last_pulse_state["waiting_for_player"] is waiting_for_player


def test_pulse_suppresses_repeated_generated_dialogue(monkeypatch):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    decisions = iter([
        _decision(speaker_id="c1", reply_to_message_id=1),
        _decision(speaker_id="c1", reply_to_message_id=1),
    ])
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [
            {"message_id": 1, "role": "user", "content": "继续"}
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_decide_dialogue_action",
        lambda **kwargs: next(decisions),
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_response",
        lambda *args, **kwargs: {
            "character_id": "c1",
            "character_name": "甲",
            "dialogue": "我们先去北门侦查。",
            "reply_to_message_id": 1,
        },
    )

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="event",
        trigger_text="继续",
        max_messages=2,
        persist_state=False,
        persist_messages=False,
        clock_snapshot=SimpleNamespace(world_now=SimpleNamespace(isoformat=lambda: "now")),
    )

    assert [response["dialogue"] for response in responses] == ["我们先去北门侦查。"]
    assert orchestrator.last_pulse_state["waiting_for_player"] is True


def test_pulse_suppresses_duplicate_from_recent_history(monkeypatch):
    from memoria.core import multi_character_orchestrator

    orchestrator = _orchestrator()
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [
            {"message_id": 1, "role": "user", "content": "继续"},
            {
                "message_id": 2,
                "role": "assistant",
                "character_id": "c1",
                "content": "我们先去北门侦查。",
            },
        ],
    )
    monkeypatch.setattr(
        orchestrator,
        "_decide_dialogue_action",
        lambda **kwargs: _decision(speaker_id="c1", reply_to_message_id=1),
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_response",
        lambda *args, **kwargs: {
            "character_id": "c1",
            "character_name": "甲",
            "dialogue": "我们先去北门侦查！",
            "reply_to_message_id": 1,
        },
    )

    responses = orchestrator.run_dialogue_pulse(
        trigger_source="player",
        trigger_text="继续",
        max_messages=1,
        persist_state=False,
        persist_messages=False,
        clock_snapshot=SimpleNamespace(world_now=SimpleNamespace(isoformat=lambda: "now")),
    )

    assert responses == []
    assert orchestrator.last_pulse_state["waiting_for_player"] is True


def test_dialogue_pulse_memory_secret_is_not_broadcast(monkeypatch):
    from memoria.core import memory_extractor, multi_character_memory

    claims = []
    long_term = []
    group_memories = []
    shared_memories = []
    monkeypatch.setattr(
        multi_character_memory,
        "extract_dialogue_pulse_memories",
        lambda recent_messages, character_ids: {
            "player_facts": ["玩家来自北境"],
            "shared_facts": ["众人决定夜间出发"],
            "secret_facts": [
                {"fact": "甲持有密钥", "allowed_character_ids": ["c1", "c2"]}
            ],
        },
    )
    monkeypatch.setattr(
        multi_character_memory.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "player_id": "player-1",
            "group_thread_id": "thread-1",
            "story_id": "story-1",
            "is_multi_character": 1,
        },
    )
    monkeypatch.setattr(
        memory_extractor,
        "record_generated_memory_claim",
        lambda **kwargs: claims.append(kwargs) or {
            **kwargs,
            "status": "candidate",
            "source_kind": "model_inference",
        },
        raising=False,
    )
    monkeypatch.setattr(
        multi_character_memory.repository,
        "save_long_term_fact",
        lambda character_id, player_id, fact, importance=5: long_term.append(
            (character_id, fact, importance)
        ),
    )
    monkeypatch.setattr(
        multi_character_memory.repository,
        "save_group_memory",
        lambda **kwargs: group_memories.append(kwargs),
    )
    monkeypatch.setattr(
        multi_character_memory.repository,
        "save_shared_memory",
        lambda **kwargs: shared_memories.append(kwargs),
    )
    multi_character_memory.process_dialogue_pulse_memories(
        session_id="session-1",
        recent_messages=[{"role": "assistant", "content": "密谈"}],
        character_ids=["c1", "c2", "c3"],
        player_id="player-1",
    )

    assert long_term == []
    assert group_memories == []
    assert shared_memories == []
    assert claims == [
        {
            "owner_user_id": "player-1",
            "scope_type": "group_thread",
            "scope_id": "thread-1",
            "fact_text": "玩家来自北境",
            "source_ids": ["session:session-1"],
            "provenance": {
                "memory_kind": "player_fact",
                "session_id": "session-1",
            },
        },
        {
            "owner_user_id": "player-1",
            "scope_type": "group_thread",
            "scope_id": "thread-1",
            "fact_text": "众人决定夜间出发",
            "source_ids": ["session:session-1"],
            "provenance": {
                "memory_kind": "shared_fact",
                "session_id": "session-1",
            },
        },
        {
            "owner_user_id": "player-1",
            "scope_type": "group_thread",
            "scope_id": "thread-1",
            "fact_text": "甲持有密钥",
            "source_ids": ["session:session-1"],
            "provenance": {
                "memory_kind": "secret_fact",
                "session_id": "session-1",
                "allowed_character_ids": ["c1", "c2"],
            },
        },
    ]
def test_dialogue_pulse_does_not_duplicate_character_impression_writes(monkeypatch):
    from memoria.core import multi_character_memory
    from memoria.db import repository

    player_id = f"pulse-player-{uuid.uuid4().hex}"
    monkeypatch.setattr(
        multi_character_memory.llm_client,
        "call_light_task",
        lambda *args, **kwargs: (
            '{"player_facts":[],"shared_facts":[],"secret_facts":[],'
            '"character_impressions":[{"observer_id":"c1","target_id":"c2",'
            '"impression":"c1认为c2值得信任","importance":0.9}]}'
        ),
    )

    extracted = multi_character_memory.process_dialogue_pulse_memories(
        session_id=f"pulse-impression-{uuid.uuid4().hex}",
        recent_messages=[
            {
                "role": "assistant",
                "character_id": "c1",
                "character_name": "甲",
                "content": "我现在相信乙的判断。",
            }
        ],
        character_ids=["c1", "c2"],
        player_id=player_id,
    )

    assert set(extracted) == {"player_facts", "shared_facts", "secret_facts"}
    assert repository.get_shared_memories(
        player_id,
        "c1",
        "c2",
        limit=5,
    ) == []
