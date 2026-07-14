"""
Dialogue API behavior tests.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def test_session_start_creates_session_without_llm_opening(monkeypatch):
    from memoria.api import dialogue

    created = {}

    monkeypatch.setattr(dialogue.repository, "get_all_player_sessions", lambda player_id: [])
    monkeypatch.setattr(dialogue.repository, "get_latest_active_session", lambda player_id, character_id=None: None)
    monkeypatch.setattr(dialogue.repository, "is_character_card_active", lambda owner_user_id, character_id: True)
    monkeypatch.setattr(dialogue.character_loader, "load_character_card", lambda character_id, owner_user_id=None: SimpleNamespace())
    monkeypatch.setattr(dialogue.repository, "get_runtime_state", lambda *args, **kwargs: {"affection_level": 12})
    world_now = datetime(2026, 7, 14, 8, 30, tzinfo=timezone.utc)
    monkeypatch.setattr(
        dialogue.world_clock,
        "get_clock_snapshot",
        lambda player_id: SimpleNamespace(world_now=world_now),
    )
    monkeypatch.setattr(
        dialogue.repository,
        "create_session",
        lambda session_id, character_id, player_id, player_name: created.update(
            session_id=session_id,
            character_id=character_id,
            player_id=player_id,
            player_name=player_name,
        ),
    )
    monkeypatch.setattr(
        dialogue.orchestrator,
        "start_session",
        lambda *args, **kwargs: pytest.fail("session_start should not block on LLM opening generation"),
    )

    res = dialogue.session_start(
        dialogue.SessionStartRequest(character_id="char-1", player_id="player-1", player_name="Tester"),
        BackgroundTasks(),
        current_user_id="player-1",
    )

    assert res.session_id == created["session_id"]
    assert created["character_id"] == "char-1"
    assert res.opening_line == ""
    assert res.world_created_at == world_now.isoformat()
    assert res.recovered is False
    assert res.messages == []


def test_session_start_rejects_disabled_character_without_existing_session(monkeypatch):
    from memoria.api import dialogue

    monkeypatch.setattr(dialogue.repository, "get_all_player_sessions", lambda player_id: [])
    monkeypatch.setattr(dialogue.repository, "get_latest_active_session", lambda player_id, character_id=None: None)
    monkeypatch.setattr(dialogue.repository, "is_character_card_active", lambda owner_user_id, character_id: False)

    with pytest.raises(HTTPException) as exc_info:
        dialogue.session_start(
            dialogue.SessionStartRequest(character_id="char-1", player_id="player-1", player_name="Tester"),
            BackgroundTasks(),
            current_user_id="player-1",
        )

    assert exc_info.value.status_code == 400
    assert "角色卡已禁用" in exc_info.value.detail


def test_session_start_recovers_latest_message_world_timestamp(monkeypatch):
    from memoria.api import dialogue

    world_created_at = "2026-07-13T21:15:00+00:00"
    monkeypatch.setattr(dialogue.repository, "get_all_player_sessions", lambda player_id: [])
    monkeypatch.setattr(
        dialogue.repository,
        "get_latest_active_session",
        lambda player_id, character_id=None: {"session_id": "session-1"},
    )
    monkeypatch.setattr(
        dialogue,
        "_current_character_state",
        lambda character_id, player_id: (12, 8, "neutral"),
    )
    monkeypatch.setattr(
        dialogue,
        "_messages_for_session",
        lambda session_id: [
            dialogue.HistoryMessage(
                role="assistant",
                content="晚上好。",
                world_created_at=world_created_at,
            )
        ],
    )
    monkeypatch.setattr(
        dialogue.world_clock,
        "get_clock_snapshot",
        lambda player_id: pytest.fail("stored message timestamp should avoid a clock fallback"),
    )

    res = dialogue.session_start(
        dialogue.SessionStartRequest(
            character_id="char-1",
            player_id="player-1",
            player_name="Tester",
        ),
        BackgroundTasks(),
        current_user_id="player-1",
    )

    assert res.recovered is True
    assert res.world_created_at == world_created_at
    assert res.messages[0].world_created_at == world_created_at


def test_dialogue_turn_rejects_disabled_character(monkeypatch):
    from memoria.api import dialogue

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {
            "session_id": session_id,
            "character_id": "char-1",
            "player_id": "player-1",
            "status": "active",
        },
    )
    monkeypatch.setattr(dialogue.repository, "is_character_card_active", lambda owner_user_id, character_id: False)

    with pytest.raises(HTTPException) as exc_info:
        dialogue.dialogue_turn(
            dialogue.DialogueTurnRequest(session_id="session-1", player_message="你好"),
            current_user_id="player-1",
        )

    assert exc_info.value.status_code == 400
    assert "角色卡已禁用" in exc_info.value.detail


def test_session_start_rejects_other_player(monkeypatch):
    from memoria.api import dialogue

    monkeypatch.setattr(dialogue.repository, "get_all_player_sessions", lambda player_id: [])

    with pytest.raises(HTTPException) as exc_info:
        dialogue.session_start(
            dialogue.SessionStartRequest(character_id="char-1", player_id="player-1", player_name="Tester"),
            BackgroundTasks(),
            current_user_id="other-player",
        )

    assert exc_info.value.status_code == 403


def test_generate_session_summary_skips_when_message_count_not_enough(monkeypatch):
    from memoria.api import dialogue

    summarize_called = False
    saved = []
    history = [{"role": "user", "content": f"消息 {i}"} for i in range(6)]

    def fake_summarize_session(messages):
        nonlocal summarize_called
        summarize_called = True
        return "摘要"

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {"session_id": session_id, "character_id": "char-1", "player_id": "player-1"},
    )
    monkeypatch.setattr(dialogue.repository, "get_short_term_history", lambda session_id, limit_turns=1000: history)
    monkeypatch.setattr(dialogue, "summarize_session", fake_summarize_session)
    monkeypatch.setattr(dialogue.repository, "save_session_summary", lambda **kwargs: saved.append(kwargs))

    dialogue._generate_session_summary("session-1")

    assert summarize_called is False
    assert saved == []


def test_generate_session_summary_skips_empty_llm_summary(monkeypatch):
    from memoria.api import dialogue

    saved = []
    history = [{"role": "user", "content": f"消息 {i}"} for i in range(7)]

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {"session_id": session_id, "character_id": "char-1", "player_id": "player-1"},
    )
    monkeypatch.setattr(dialogue.repository, "get_short_term_history", lambda session_id, limit_turns=1000: history)
    monkeypatch.setattr(dialogue, "summarize_session", lambda messages: "  ")
    monkeypatch.setattr(dialogue.repository, "save_session_summary", lambda **kwargs: saved.append(kwargs))

    dialogue._generate_session_summary("session-1")

    assert saved == []


def test_generate_session_summary_saves_completed_non_empty_summary(monkeypatch):
    from memoria.api import dialogue

    saved = {}
    history = [{"role": "user", "content": f"消息 {i}"} for i in range(7)]

    monkeypatch.setattr(
        dialogue.repository,
        "get_session",
        lambda session_id: {"session_id": session_id, "character_id": "char-1", "player_id": "player-1"},
    )
    monkeypatch.setattr(dialogue.repository, "get_short_term_history", lambda session_id, limit_turns=1000: history)
    monkeypatch.setattr(dialogue, "summarize_session", lambda messages: "  有效摘要  ")
    monkeypatch.setattr(dialogue.repository, "save_session_summary", lambda **kwargs: saved.update(kwargs))

    dialogue._generate_session_summary("session-1")

    assert saved == {
        "session_id": "session-1",
        "character_id": "char-1",
        "player_id": "player-1",
        "summary_text": "有效摘要",
        "message_count": 7,
        "summary_status": "completed",
    }
