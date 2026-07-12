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
        "group_thread_id": "thread-1",
        "created_at": "2026-01-01T00:00:00+00:00",
        "status": status,
        "is_multi_character": True,
    }


def _participant(character_id, name, join_order=1):
    return {
        "character_id": character_id,
        "name": name,
        "display_name": None,
        "avatar_url": None,
        "join_order": join_order,
        "speak_frequency": 1.0,
        "is_active": True,
        "message_count": 0,
        "last_spoke_at": None,
    }


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


def _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary):
    placeholder_summaries = []
    saved_impressions = []
    monkeypatch.setattr(multi_dialogue.repository, "get_session_summary", lambda session_id: None)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_history",
        lambda session_id, limit_messages=None, created_after=None: [
            {
                "role": "user" if i % 2 == 0 else "assistant",
                "content": f"制定计划 {i}",
                "character_id": None if i % 2 == 0 else "c1",
                "character_name": None if i % 2 == 0 else "角色一",
            }
            for i in range(7)
        ] if limit_messages is None else [],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            {**_participant("c1", "角色一", 1), "display_name": None},
            {**_participant("c2", "角色二", 2), "display_name": "二号"},
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "get_relationship_history_cutoff",
        lambda player_id, character_ids, character_relationships=None: None,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "save_session_summary",
        lambda **kwargs: placeholder_summaries.append(kwargs),
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
        multi_dialogue.multi_character_memory,
        "process_character_impressions",
        lambda **kwargs: saved_impressions.append(kwargs),
    )
    return placeholder_summaries, saved_impressions


@pytest.mark.asyncio
async def test_start_multi_session_rejects_duplicate_group_name(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(multi_dialogue.repository, "is_character_card_active", lambda owner_user_id, character_id: True)
    monkeypatch.setattr(multi_dialogue.repository, "player_group_name_exists", lambda player_id, group_name: True)

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.start_multi_session(
            multi_dialogue.StartMultiSessionRequest(
                player_id="player-1",
                player_name="Player",
                group_name=" 小队 ",
                character_ids=["c1", "c2"],
            ),
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "群聊名称已存在，请换一个名称"


@pytest.mark.asyncio
async def test_start_multi_session_rejects_disabled_character(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(
        multi_dialogue.repository,
        "is_character_card_active",
        lambda owner_user_id, character_id: character_id != "c2",
    )

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.start_multi_session(
            multi_dialogue.StartMultiSessionRequest(
                player_id="player-1",
                player_name="Player",
                group_name="小队",
                character_ids=["c1", "c2"],
            ),
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert "c2" in exc.value.detail


@pytest.mark.asyncio
async def test_end_multi_session_accepts_json_body(monkeypatch):
    from memoria.api import multi_dialogue

    ended = {}
    saved_summary = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _, saved_impressions = _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "end_session",
        lambda session_id: ended.update(session_id=session_id),
    )

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert ended == {"session_id": "session-1"}
    assert saved_summary == {}
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert saved_summary == {
        "session_id": "session-1",
        "character_ids": ["c1", "c2"],
        "player_id": "player-1",
        "summary_text": "玩家和角色一制定了侦查计划。",
        "message_count": 7,
    }
    assert saved_impressions
    assert saved_impressions[0]["session_id"] == "session-1"
    assert saved_impressions[0]["character_ids"] == ["c1", "c2"]
    assert saved_impressions[0]["player_id"] == "player-1"


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

    monkeypatch.setattr(dialogue.repository, "get_session_summary", lambda session_id: None)

    tasks = FakeBackgroundTasks()
    response = dialogue.session_end(
        dialogue.SessionEndRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response.session_id == "session-1"
    assert response.summary is None
    assert response.message_count == 0
    assert ended == {"session_id": "session-1"}
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
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

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert end_called is False
    assert saved_summary == {}
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert saved_summary["summary_text"] == "玩家和角色一制定了侦查计划。"


@pytest.mark.asyncio
async def test_end_multi_session_summary_failure_does_not_block_end(monkeypatch):
    from memoria.api import multi_dialogue

    end_called = False
    placeholder_summaries = []

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _patch_multi_summary(monkeypatch, multi_dialogue, {})

    def fake_save_summary(**kwargs):
        raise RuntimeError("database unavailable")

    def fake_end_session(session_id):
        nonlocal end_called
        end_called = True

    monkeypatch.setattr(multi_dialogue.multi_character_memory, "save_multi_character_summary", fake_save_summary)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "save_session_summary",
        lambda **kwargs: placeholder_summaries.append(kwargs),
    )
    monkeypatch.setattr(multi_dialogue.repository, "end_session", fake_end_session)

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert end_called is True
    assert len(tasks.tasks) == 1
    assert placeholder_summaries == []

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert placeholder_summaries == []


@pytest.mark.asyncio
async def test_end_multi_session_empty_summary_still_processes_impressions(monkeypatch):
    from memoria.api import multi_dialogue

    saved_summary = {}

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    _, saved_impressions = _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "generate_multi_character_summary",
        lambda **kwargs: "  ",
    )
    monkeypatch.setattr(multi_dialogue.repository, "end_session", lambda session_id: None)

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert saved_summary == {}
    assert saved_impressions
    assert saved_impressions[0]["session_id"] == "session-1"
    assert saved_impressions[0]["character_ids"] == ["c1", "c2"]
    assert saved_impressions[0]["player_id"] == "player-1"


@pytest.mark.asyncio
async def test_end_multi_session_skips_summary_when_message_count_not_enough(monkeypatch):
    from memoria.api import multi_dialogue

    ended = {}
    saved_summary = {}
    short_history = [
        {"role": "user", "content": f"消息 {i}", "character_id": None, "character_name": None}
        for i in range(6)
    ]

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id))
    monkeypatch.setattr(multi_dialogue.repository, "get_session_summary", lambda session_id: None)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_history",
        lambda session_id, limit_messages=None: short_history,
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

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert ended == {"session_id": "session-1"}
    assert tasks.tasks == []
    assert saved_summary == {}


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
        lambda session_id, limit_messages=None, created_after=None: long_history,
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "get_relationship_history_cutoff",
        lambda player_id, character_ids, character_relationships=None: None,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            _participant("c2", "角色二", 2),
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
    monkeypatch.setattr(multi_dialogue.repository, "save_session_summary", lambda **kwargs: None)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "end_session",
        lambda session_id: ended.update(session_id=session_id),
    )

    tasks = FakeBackgroundTasks()
    response = await multi_dialogue.end_multi_session(
        multi_dialogue.EndMultiSessionRequest(session_id="session-1"),
        tasks,
        current_user_id="player-1",
    )

    assert response["session_id"] == "session-1"
    assert ended == {"session_id": "session-1"}
    assert summary_calls == []
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert [call["message_count"] for call in summary_calls] == [80, 80, 5, 3]
    assert summary_calls[-1]["session_id"] == "session-1"
    assert saved_summary["summary_text"] == "整场群聊最终摘要"
    assert saved_summary["message_count"] == len(long_history)


@pytest.mark.asyncio
async def test_continue_multi_session_creates_new_active_session_without_reactivating_old(monkeypatch):
    from memoria.api import multi_dialogue

    created = {}
    ended_source = _multi_session("old-session", status="ended")

    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: ended_source)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_sessions",
        lambda session_id: [
            {
                "session_id": "old-session",
                "status": "ended",
                "group_name": "小队",
                "group_thread_id": "thread-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:10:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            _participant("c2", "角色二", 2),
        ],
    )

    def fake_create_multi_character_session(**kwargs):
        created.update(kwargs)
        return True

    monkeypatch.setattr(
        multi_dialogue.repository,
        "create_multi_character_session",
        fake_create_multi_character_session,
    )

    response = await multi_dialogue.continue_multi_session(
        "old-session",
        current_user_id="player-1",
    )

    assert response.status == "active"
    assert response.session_id != "old-session"
    assert response.group_name == "小队"
    assert response.group_thread_id == "thread-1"
    assert created["group_thread_id"] == "thread-1"
    assert created["group_name"] == "小队"
    assert created["character_ids"] == ["c1", "c2"]
    assert ended_source["status"] == "ended"


@pytest.mark.asyncio
async def test_continue_multi_session_keeps_disabled_participants(monkeypatch):
    from memoria.api import multi_dialogue

    created = {}
    disabled_participant = {**_participant("c2", "角色二", 2), "is_active": False}

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: _multi_session("old-session", status="ended"),
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_sessions",
        lambda session_id: [
            {
                "session_id": "old-session",
                "status": "ended",
                "group_name": "小队",
                "group_thread_id": "thread-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:10:00+00:00",
            }
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            disabled_participant,
        ],
    )

    def fake_create_multi_character_session(**kwargs):
        created.update(kwargs)
        return True

    monkeypatch.setattr(
        multi_dialogue.repository,
        "create_multi_character_session",
        fake_create_multi_character_session,
    )

    response = await multi_dialogue.continue_multi_session(
        "old-session",
        current_user_id="player-1",
    )

    assert response.status == "active"
    assert created["character_ids"] == ["c1", "c2"]
    assert any(p.character_id == "c2" and not p.is_active for p in response.participants)


@pytest.mark.asyncio
async def test_continue_multi_session_reuses_existing_active_thread_session(monkeypatch):
    from memoria.api import multi_dialogue

    create_called = False
    monkeypatch.setattr(multi_dialogue.repository, "get_session", lambda session_id: _multi_session(session_id, status="ended"))
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_sessions",
        lambda session_id: [
            {
                "session_id": "old-session",
                "status": "ended",
                "group_name": "小队",
                "group_thread_id": "thread-1",
                "created_at": "2026-01-01T00:00:00+00:00",
                "ended_at": "2026-01-01T00:10:00+00:00",
            },
            {
                "session_id": "active-session",
                "status": "active",
                "group_name": "小队",
                "group_thread_id": "thread-1",
                "created_at": "2026-01-01T00:11:00+00:00",
                "ended_at": None,
            },
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            _participant("c2", "角色二", 2),
        ],
    )

    def fake_create_multi_character_session(**kwargs):
        nonlocal create_called
        create_called = True
        return True

    monkeypatch.setattr(
        multi_dialogue.repository,
        "create_multi_character_session",
        fake_create_multi_character_session,
    )

    response = await multi_dialogue.continue_multi_session(
        "old-session",
        current_user_id="player-1",
    )

    assert response.session_id == "active-session"
    assert response.status == "active"
    assert response.group_thread_id == "thread-1"
    assert create_called is False


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
