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
        "generate_multi_character_insights",
        lambda **kwargs: {
            "summary": "玩家和角色一制定了侦查计划。",
            "character_impressions": [{
                "observer_id": "c1",
                "target_id": "c2",
                "impression": "角色一认为角色二很可靠",
                "importance": 0.7,
            }],
        },
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "save_multi_character_summary",
        lambda **kwargs: saved_summary.update(kwargs),
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "save_extracted_character_impressions",
        lambda **kwargs: saved_impressions.append(kwargs),
    )
    return placeholder_summaries, saved_impressions


@pytest.mark.asyncio
async def test_multi_dialogue_history_returns_paginated_thread_messages(monkeypatch):
    from memoria.api import multi_dialogue

    requested_page = {}
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: _multi_session(session_id),
    )

    def fake_paginated_history(session_id, offset, limit):
        requested_page.update(session_id=session_id, offset=offset, limit=limit)
        return (
            [
                {
                    "message_id": 21,
                    "session_id": "older-session",
                    "role": "user",
                    "content": "更早的消息",
                    "character_id": None,
                    "character_name": None,
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ],
            True,
        )

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_history_paginated",
        fake_paginated_history,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_sessions",
        lambda session_id: [],
    )

    response = await multi_dialogue.get_multi_dialogue_history(
        "session-1",
        offset=20,
        limit=10,
        current_user_id="player-1",
    )

    assert requested_page == {"session_id": "session-1", "offset": 20, "limit": 10}
    assert response.has_more is True
    assert [message["content"] for message in response.messages] == ["更早的消息"]


@pytest.mark.asyncio
async def test_multi_dialogue_history_uses_incremental_message_id(monkeypatch):
    from memoria.api import multi_dialogue

    requested_page = {}
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: _multi_session(session_id),
    )

    def fake_incremental_history(session_id, after_message_id, limit):
        requested_page.update(
            session_id=session_id,
            after_message_id=after_message_id,
            limit=limit,
        )
        return (
            [
                {
                    "message_id": 42,
                    "session_id": "new-session",
                    "role": "assistant",
                    "content": "增量消息",
                    "character_id": "c2",
                    "character_name": "角色二",
                    "reply_to_message_id": 41,
                    "reply_to_character_id": "c1",
                    "intent": "challenge",
                    "topic": "计划",
                    "trigger_source": "npc_follow_up",
                    "world_created_at": "2026-01-01T01:00:00+00:00",
                }
            ],
            True,
            45,
        )

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_history_after",
        fake_incremental_history,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_multi_character_thread_sessions",
        lambda session_id: [],
    )

    response = await multi_dialogue.get_multi_dialogue_history(
        "session-1",
        offset=99,
        limit=3,
        after_message_id=41,
        current_user_id="player-1",
    )

    assert requested_page == {
        "session_id": "session-1",
        "after_message_id": 41,
        "limit": 3,
    }
    assert response.has_more is True
    assert response.latest_message_id == 45
    assert response.messages[0]["reply_to_message_id"] == 41
    assert response.messages[0]["trigger_source"] == "npc_follow_up"


@pytest.mark.asyncio
async def test_mark_group_thread_read_handles_not_found_forbidden_and_success(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_latest_group_thread_session",
        lambda group_thread_id: None,
    )
    with pytest.raises(HTTPException) as missing:
        await multi_dialogue.mark_group_thread_read(
            "missing-thread",
            current_user_id="player-1",
        )
    assert missing.value.status_code == 404

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_latest_group_thread_session",
        lambda group_thread_id: _multi_session("session-1"),
    )
    with pytest.raises(HTTPException) as forbidden:
        await multi_dialogue.mark_group_thread_read(
            "thread-1",
            current_user_id="other-player",
        )
    assert forbidden.value.status_code == 403

    marked = {}
    monkeypatch.setattr(
        multi_dialogue.repository,
        "mark_group_thread_notifications_read",
        lambda player_id, group_thread_id: marked.update(
            player_id=player_id,
            group_thread_id=group_thread_id,
        ) or 2,
    )
    response = await multi_dialogue.mark_group_thread_read(
        "thread-1",
        current_user_id="player-1",
    )
    assert marked == {"player_id": "player-1", "group_thread_id": "thread-1"}
    assert response.group_thread_id == "thread-1"
    assert response.marked_read == 2


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
async def test_start_multi_session_rejects_duplicate_characters(monkeypatch):
    from memoria.api import multi_dialogue

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.start_multi_session(
            multi_dialogue.StartMultiSessionRequest(
                player_id="player-1",
                player_name="Player",
                group_name="小队",
                character_ids=["c1", "c1"],
            ),
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "群聊角色不能重复"


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
    assert saved_impressions[0]["player_id"] == "player-1"
    assert saved_impressions[0]["impressions"][0]["observer_id"] == "c1"


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
        "generate_multi_character_insights",
        lambda **kwargs: {
            "summary": "  ",
            "character_impressions": [{
                "observer_id": "c1",
                "target_id": "c2",
                "impression": "角色一认为角色二很可靠",
                "importance": 0.7,
            }],
        },
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
    assert saved_impressions[0]["player_id"] == "player-1"
    assert saved_impressions[0]["impressions"][0]["target_id"] == "c2"


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
    insight_calls = []
    saved_impressions = []
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
        return f"分段摘要 {len(summary_calls)}"

    def fake_generate_insights(**kwargs):
        insight_calls.append({
            "session_id": kwargs["session_id"],
            "summary_message_count": len(kwargs["summary_messages"]),
            "impression_message_count": len(kwargs["impression_messages"]),
        })
        return {
            "summary": "整场群聊最终摘要",
            "character_impressions": [],
        }

    monkeypatch.setattr(multi_dialogue.multi_character_memory, "generate_multi_character_summary", fake_generate_summary)
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "generate_multi_character_insights",
        fake_generate_insights,
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "save_multi_character_summary",
        lambda **kwargs: saved_summary.update(kwargs),
    )
    monkeypatch.setattr(multi_dialogue.repository, "save_session_summary", lambda **kwargs: None)
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "save_extracted_character_impressions",
        lambda **kwargs: saved_impressions.append(kwargs),
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
    assert summary_calls == []
    assert len(tasks.tasks) == 1

    func, args, kwargs = tasks.tasks[0]
    func(*args, **kwargs)
    assert [call["message_count"] for call in summary_calls] == [80, 80, 5]
    assert insight_calls == [{
        "session_id": "session-1",
        "summary_message_count": 3,
        "impression_message_count": 80,
    }]
    assert saved_summary["summary_text"] == "整场群聊最终摘要"
    assert saved_summary["message_count"] == len(long_history)
    assert len(saved_impressions) == 1


def test_multi_summary_reuses_exact_completed_summary(monkeypatch):
    from memoria.api import multi_dialogue

    saved_summary = {}
    _patch_multi_summary(monkeypatch, multi_dialogue, saved_summary)
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_summary",
        lambda session_id: {
            "summary_status": "completed",
            "summary_text": "已有摘要",
            "message_count": 7,
        },
    )
    monkeypatch.setattr(
        multi_dialogue.multi_character_memory,
        "generate_multi_character_insights",
        lambda **kwargs: pytest.fail("exact summary should be reused"),
    )
    multi_dialogue.performance.reset()

    multi_dialogue._save_session_summary_on_end(
        "session-1",
        _multi_session("session-1"),
    )

    assert saved_summary == {}
    assert multi_dialogue.performance.snapshot()["counters"][
        "llm.calls_avoided.summary_reuse"
    ] == 1


def test_multi_summary_regenerates_stale_completed_summary(monkeypatch):
    from memoria.api import multi_dialogue

    saved_summary = {}
    _, saved_impressions = _patch_multi_summary(
        monkeypatch,
        multi_dialogue,
        saved_summary,
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_summary",
        lambda session_id: {
            "summary_status": "completed",
            "summary_text": "旧摘要",
            "message_count": 6,
        },
    )

    multi_dialogue._save_session_summary_on_end(
        "session-1",
        _multi_session("session-1"),
    )

    assert saved_summary["summary_text"] == "玩家和角色一制定了侦查计划。"
    assert saved_summary["message_count"] == 7
    assert len(saved_impressions) == 1


@pytest.mark.asyncio
async def test_continue_multi_session_creates_new_active_session_without_reactivating_old(monkeypatch):
    from memoria.api import multi_dialogue

    created = {}
    ended_source = {**_multi_session("old-session", status="ended"), "locale": "en-US"}

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

    def fake_get_or_create_active_multi_character_session(**kwargs):
        created.update(kwargs)
        return (
            {
                "session_id": kwargs["session_id"],
                "player_id": kwargs["player_id"],
                "player_name": kwargs["player_name"],
                "group_name": kwargs["group_name"],
                "group_thread_id": kwargs["group_thread_id"],
                "status": "active",
                "locale": kwargs["locale"],
                "is_multi_character": 1,
            },
            True,
        )

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_or_create_active_multi_character_session",
        fake_get_or_create_active_multi_character_session,
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
    assert created["locale"] == "en-US"
    assert response.locale == "en-US"
    assert ended_source["status"] == "ended"


@pytest.mark.asyncio
async def test_continue_multi_session_reuses_session_created_after_initial_lookup(monkeypatch):
    from memoria.api import multi_dialogue

    ended_source = {**_multi_session("old-session", status="ended"), "locale": "en-US"}
    concurrent_session = {
        **ended_source,
        "session_id": "concurrent-session",
        "status": "active",
        "group_thread_id": "thread-1",
    }
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: ended_source,
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
            _participant("c2", "角色二", 2),
        ],
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_or_create_active_multi_character_session",
        lambda **kwargs: (concurrent_session, False),
    )

    response = await multi_dialogue.continue_multi_session(
        "old-session",
        current_user_id="player-1",
    )

    assert response.session_id == "concurrent-session"
    assert response.status == "active"
    assert response.group_thread_id == "thread-1"
    assert response.locale == "en-US"


@pytest.mark.asyncio
async def test_continue_multi_session_rejects_disabled_participants(monkeypatch):
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

    def fake_get_or_create_active_multi_character_session(**kwargs):
        created.update(kwargs)
        return ({}, True)

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_or_create_active_multi_character_session",
        fake_get_or_create_active_multi_character_session,
    )

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.continue_multi_session(
            "old-session",
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert "c2" in exc.value.detail
    assert created == {}


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

    def fake_get_or_create_active_multi_character_session(**kwargs):
        nonlocal create_called
        create_called = True
        return ({}, True)

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_or_create_active_multi_character_session",
        fake_get_or_create_active_multi_character_session,
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
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            _participant("c2", "角色二", 2),
        ],
    )
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
async def test_multi_dialogue_turn_rejects_disabled_participant(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: _multi_session(session_id),
    )
    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session_participants",
        lambda session_id, only_active=False: [
            _participant("c1", "角色一", 1),
            {**_participant("c2", "角色二", 2), "is_active": False},
        ],
    )
    monkeypatch.setattr(
        multi_dialogue,
        "process_multi_character_turn",
        lambda **kwargs: pytest.fail("disabled participant must block the turn"),
    )

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.multi_dialogue_turn(
            multi_dialogue.MultiDialogueTurnRequest(
                session_id="session-1",
                player_message="继续",
            ),
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert "c2" in exc.value.detail


@pytest.mark.asyncio
async def test_trigger_interaction_rejects_ended_session(monkeypatch):
    from memoria.api import multi_dialogue

    monkeypatch.setattr(
        multi_dialogue.repository,
        "get_session",
        lambda session_id: _multi_session(session_id, status="ended"),
    )

    with pytest.raises(HTTPException) as exc:
        await multi_dialogue.trigger_interaction(
            multi_dialogue.TriggerInteractionRequest(session_id="session-1"),
            current_user_id="player-1",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "会话已结束"


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
