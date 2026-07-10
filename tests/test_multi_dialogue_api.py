"""
Multi-dialogue API behavior tests.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _multi_session(session_id="session-1", status="active"):
    return {
        "session_id": session_id,
        "player_id": "player-1",
        "player_name": "Player",
        "group_name": "小队",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": status,
        "is_multi_character": True,
    }


@pytest.mark.asyncio
async def test_remove_participant_accepts_json_body(monkeypatch):
    from memoria.api import multi_dialogue

    removed = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=True: [
            {"character_id": "c1"},
            {"character_id": "c2"},
            {"character_id": "c3"},
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "remove_participant_from_session",
        lambda session_id, character_id: removed.update(
            session_id=session_id,
            character_id=character_id,
        ) or True,
    )

    response = await multi_dialogue.remove_participant(
        multi_dialogue.RemoveParticipantRequest(session_id="session-1", character_id="c3")
    )

    assert response["success"] is True
    assert removed == {"session_id": "session-1", "character_id": "c3"}


@pytest.mark.asyncio
async def test_update_participant_accepts_frontend_post(monkeypatch):
    from memoria.api import multi_dialogue

    updated = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(
        multi_dialogue.repository,
        "update_participant_frequency",
        lambda session_id, character_id, speak_frequency: updated.update(
            session_id=session_id,
            character_id=character_id,
            speak_frequency=speak_frequency,
        ) or True,
    )

    response = await multi_dialogue.update_participant(
        multi_dialogue.UpdateParticipantRequest(
            session_id="session-1",
            character_id="c2",
            speak_frequency=1.4,
        )
    )

    assert response["success"] is True
    assert updated == {"session_id": "session-1", "character_id": "c2", "speak_frequency": 1.4}


@pytest.mark.asyncio
async def test_end_multi_session_accepts_json_body(monkeypatch):
    from memoria.api import multi_dialogue

    ended = {}
    saved_summary = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_history",
        lambda session_id, limit_messages=None: [
            {"role": "user", "content": "制定计划", "character_id": None, "character_name": None},
            {"role": "assistant", "content": "我负责侦查。", "character_id": "c1", "character_name": "角色一"},
        ] if limit_messages is None else [],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            {"character_id": "c1", "name": "角色一", "display_name": None},
            {"character_id": "c2", "name": "角色二", "display_name": "二号"},
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "generate_multi_character_summary",
        lambda **kwargs: "玩家和角色一制定了侦查计划。",
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "save_multi_character_summary",
        lambda **kwargs: saved_summary.update(kwargs),
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "end_session",
        lambda session_id: ended.update(session_id=session_id),
    )

    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1")
    )

    assert response["session_id"] == "session-1"
    assert ended == {"session_id": "session-1"}
    assert saved_summary == {
        "session_id": "session-1",
        "character_ids": ["c1", "c2"],
        "player_id": "player-1",
        "summary_text": "玩家和角色一制定了侦查计划。",
        "message_count": 2,
    }


@pytest.mark.asyncio
async def test_multi_dialogue_turn_wraps_discussion_response(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(
        multi_dialogue,
        "process_multi_character_turn",
        lambda **kwargs: [
            {
                "character_id": "c1",
                "character_name": "角色一",
                "dialogue": "我负责侦查。",
                "action": "nod",
                "current_affinity": 10,
                "current_mood": "focused",
            },
            {
                "character_id": "c2",
                "character_name": "角色二",
                "dialogue": "我准备装备。",
                "action": "prepare",
                "current_affinity": 8,
                "current_mood": "calm",
            },
        ],
    )

    response = await multi_dialogue.multi_dialogue_turn(
        multi_dialogue.MultiDialogueTurnRequest(
            session_id="session-1",
            player_message="制定计划",
            discussion_mode=True,
            max_responses=2,
        )
    )

    body = response.model_dump()
    assert body["discussion_mode"] is True
    assert body["total_speakers"] == 2
    assert [r["dialogue"] for r in body["responses"]] == ["我负责侦查。", "我准备装备。"]
