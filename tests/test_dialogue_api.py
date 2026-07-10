"""
Dialogue API behavior tests.
"""
import sys
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
    monkeypatch.setattr(dialogue.character_loader, "load_character_card", lambda character_id: SimpleNamespace())
    monkeypatch.setattr(dialogue.repository, "get_runtime_state", lambda *args, **kwargs: {"affection_level": 12})
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
    assert res.recovered is False
    assert res.messages == []


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
