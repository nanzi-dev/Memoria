"""
Multi-dialogue API behavior tests.
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

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


def _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary):
    monkeypatch.setattr(multi_dialogue.repository, "get_session_summary", lambda session_id: None)
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
        multi_dialogue.RemoveParticipantRequest(session_id="session-1", character_id="c3"),
        current_user_id="player-1",
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
        ),
        current_user_id="player-1",
    )

    assert response["success"] is True
    assert updated == {"session_id": "session-1", "character_id": "c2", "speak_frequency": 1.4}


@pytest.mark.asyncio
async def test_end_multi_session_accepts_json_body(monkeypatch):
    from memoria.api import multi_dialogue

    ended = {}
    saved_summary = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "end_session",
        lambda session_id: ended.update(session_id=session_id),
    )

    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        current_user_id="player-1",
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


def test_dialogue_end_routes_multi_session_to_group_summary(monkeypatch):
    from memoria.api import dialogue, multi_dialogue

    ended = {}
    saved_summary = {}

    monkeypatch.setattr(dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "end_session",
        lambda session_id: ended.update(session_id=session_id),
    )
    monkeypatch.setattr(
        dialogue.repository,
        "get_session_summary",
        lambda session_id: {"summary_text": saved_summary.get("summary_text", ""), "message_count": saved_summary.get("message_count", 0)},
    )

    response = dialogue.session_end(
        dialogue.SessionEndRequest(session_id="session-1"),
        None,
        current_user_id="player-1",
    )

    assert response.session_id == "session-1"
    assert response.summary == "玩家和角色一制定了侦查计划。"
    assert response.message_count == 2
    assert ended == {"session_id": "session-1"}
    assert saved_summary["summary_text"] == "玩家和角色一制定了侦查计划。"


@pytest.mark.asyncio
async def test_end_multi_session_backfills_summary_when_already_ended(monkeypatch):
    from memoria.api import multi_dialogue

    end_called = False
    saved_summary = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id, status="ended"))
    _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)

    def fake_end_session(session_id):
        nonlocal end_called
        end_called = True

    monkeypatch.setattr(multi_dialogue.repository, "end_session", fake_end_session)

    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert end_called is False
    assert saved_summary["summary_text"] == "玩家和角色一制定了侦查计划。"


@pytest.mark.asyncio
async def test_end_multi_session_fails_when_summary_save_fails(monkeypatch):
    from memoria.api import multi_dialogue

    end_called = False

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _patch_multi_summary(monkeypatch, multi_dialogue, {})

    def fake_save_summary(**kwargs):
        raise RuntimeError("database unavailable")

    def fake_end_session(session_id):
        nonlocal end_called
        end_called = True

    monkeypatch.setattr(multi_dialogue.multi_character_memory, "save_multi_character_summary", fake_save_summary)
    monkeypatch.setattr(multi_dialogue.repository, "end_session", fake_end_session)

    with pytest.raises(HTTPException) as exc_info:
        await multi_dialogue.end_multi_session(
            multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
            current_user_id="player-1",
        )

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "保存多角色摘要失败，会话未结束"
    assert end_called is False


@pytest.mark.asyncio
async def test_end_multi_session_chunks_long_history_before_saving_summary(monkeypatch):
    from memoria.api import multi_dialogue

    ended = {}
    saved_summary = {}
    summary_calls = []
    long_history = [
        {
            "role": "user" if i % 2 == 0 else "assistant",
            "content": f"消息 {i}",
            "character_id": None if i % 2 == 0 else "c1",
            "character_name": None if i % 2 == 0 else "角色一",
        }
        for i in range(multi_dialogue.SUMMARY_CHUNK_MESSAGE_LIMIT * 2 + 5)
    ]

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(multi_dialogue.repository, "get_session_summary", lambda session_id: None)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_history",
        lambda session_id, limit_messages=None: long_history,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            {"character_id": "c1", "name": "角色一", "display_name": None},
            {"character_id": "c2", "name": "角色二", "display_name": None},
        ],
    )

    def fake_generate_summary(**kwargs):
        summary_calls.append({"session_id": kwargs["session_id"], "message_count": len(kwargs["messages"])})
        if ":chunk:" in kwargs["session_id"]:
            return f"分段摘要 {len(summary_calls)}"
        return "整场群聊最终摘要"

    monkeypatch.setattr(multi_dialogue.multi_character_memory, "generate_multi_character_summary", fake_generate_summary)
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
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert ended == {"session_id": "session-1"}
    assert [call["message_count"] for call in summary_calls] == [80, 80, 5, 3]
    assert summary_calls[-1]["session_id"] == "session-1"
    assert saved_summary["summary_text"] == "整场群聊最终摘要"
    assert saved_summary["message_count"] == len(long_history)


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
        ),
        current_user_id="player-1",
    )

    body = response.model_dump()
    assert body["discussion_mode"] is True
    assert body["total_speakers"] == 2
    assert [r["dialogue"] for r in body["responses"]] == ["我负责侦查。", "我准备装备。"]


@pytest.mark.asyncio
async def test_multi_dialogue_turn_rejects_other_player_session(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))

    with pytest.raises(HTTPException) as exc_info:
        await multi_dialogue.multi_dialogue_turn(
            multi_dialogue.MultiDialogueTurnRequest(
                session_id="session-1",
                player_message="制定计划",
                discussion_mode=True,
            ),
            current_user_id="other-player",
        )

    assert exc_info.value.status_code == 403
