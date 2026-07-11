"""
开发者体验功能测试：回放、性能指标、质量评分。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_performance_snapshot_records_distribution():
    from memoria.core import performance

    performance.reset()
    performance.record("llm.role_turn", 10)
    performance.record("llm.role_turn", 30)

    data = performance.snapshot()

    assert data["llm.role_turn"]["count"] == 2
    assert data["llm.role_turn"]["avg_ms"] == 20
    assert data["llm.role_turn"]["min_ms"] == 10
    assert data["llm.role_turn"]["max_ms"] == 30


def test_replay_builds_step_and_state_timeline():
    from memoria.core import replay

    session = {"session_id": "sid", "player_id": "player"}
    messages = [
        {"message_id": 1, "role": "user", "content": "你好"},
        {
            "message_id": 2,
            "role": "assistant",
            "content": "你好。",
            "affinity_delta": 1,
            "trust_delta": 0,
            "current_affinity": 11,
            "current_trust": 20,
            "current_mood": "happy",
            "action": "greet",
        },
    ]

    data = replay.build_replay(session, messages, step=1)

    assert data["current_step"] == 1
    assert data["total_steps"] == 2
    assert len(data["messages"]) == 1
    assert data["state_tracking_available"] is True
    assert data["state_timeline"][0]["state"]["affinity"] == 11


def test_quality_score_heuristic_returns_scores():
    from memoria.core import quality_scorer

    result = quality_scorer.score_dialogue([
        {"role": "user", "content": "你在做什么？"},
        {"role": "assistant", "content": "[抬头]我在看风。你也听见了吗？"},
    ])

    assert result["method"] == "heuristic"
    assert 0 <= result["character_consistency"] <= 100
    assert 0 <= result["interestingness"] <= 100
    assert 0 <= result["overall"] <= 100
    assert result["reasons"]


def test_developer_replay_requires_owned_session(monkeypatch):
    from memoria.api import developer

    monkeypatch.setattr(
        developer.repository,
        "get_session",
        lambda session_id: {"session_id": session_id, "player_id": "owner"},
    )

    with pytest.raises(HTTPException) as exc:
        developer.replay_session("sid", current_user_id="other")

    assert exc.value.status_code == 403


def test_developer_quality_score_from_session(monkeypatch):
    from memoria.api import developer

    monkeypatch.setattr(
        developer.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "player_id": "owner",
            "character_id": "npc_test",
        },
    )
    monkeypatch.setattr(
        developer.repository,
        "get_session_messages",
        lambda session_id, limit=1000: [
            {"role": "assistant", "content": "今天天气不错。"}
        ],
    )

    result = developer.quality_score(
        developer.QualityScoreRequest(session_id="sid"),
        current_user_id="owner",
    )

    assert result["method"] == "heuristic"
    assert result["overall"] > 0
