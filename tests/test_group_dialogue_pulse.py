"""群聊逐消息决策脉冲与长期记忆分发测试。"""

from types import SimpleNamespace

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


def test_dialogue_pulse_memory_secret_is_not_broadcast(monkeypatch):
    from memoria.core import multi_character_memory

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

    secret_recipients = {
        character_id
        for character_id, fact, _ in long_term
        if fact == "甲持有密钥"
    }
    player_fact_recipients = {
        character_id
        for character_id, fact, _ in long_term
        if fact == "玩家来自北境"
    }
    assert secret_recipients == {"c1", "c2"}
    assert player_fact_recipients == {"c1", "c2", "c3"}
    assert group_memories[0]["participants"] == ["c1", "c2", "c3"]
    assert len(shared_memories) == 3
