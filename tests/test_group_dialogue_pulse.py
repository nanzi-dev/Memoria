"""群聊逐消息决策脉冲与长期记忆分发测试。"""

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
