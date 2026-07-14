"""离线自主群聊运行时测试。"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace


UTC = timezone.utc


def _snapshot(now, *, world_now=None, paused=False):
    from memoria.core.world_clock import WorldClockSnapshot

    return WorldClockSnapshot(
        player_id="player-1",
        timezone="UTC",
        time_scale=0 if paused else 1,
        real_now=now,
        world_now=world_now or now,
    )


def test_ordinary_pulse_due_enforces_pause_cooldowns_and_daily_budget():
    from memoria.core import group_dialogue_runtime

    now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    state = {
        "last_autonomous_pulse_at": (now - timedelta(minutes=3)).isoformat(),
        "last_autonomous_world_at": (now - timedelta(minutes=21)).isoformat(),
        "daily_message_date": now.date().isoformat(),
        "daily_message_count": 23,
    }

    assert group_dialogue_runtime._ordinary_pulse_due(state, _snapshot(now)) is True
    assert group_dialogue_runtime._ordinary_pulse_due(
        state,
        _snapshot(now, paused=True),
    ) is False
    assert group_dialogue_runtime._ordinary_pulse_due(
        {**state, "last_autonomous_pulse_at": (now - timedelta(seconds=30)).isoformat()},
        _snapshot(now),
    ) is False
    assert group_dialogue_runtime._ordinary_pulse_due(
        {
            **state,
            "last_autonomous_world_at": (now - timedelta(minutes=5)).isoformat(),
        },
        _snapshot(now),
    ) is False
    assert group_dialogue_runtime._ordinary_pulse_due(
        {**state, "daily_message_count": 24},
        _snapshot(now),
    ) is False


def test_pulse_does_not_run_when_lease_claim_fails(monkeypatch):
    from memoria.core import group_dialogue_runtime

    now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "get_group_dialogue_state",
        lambda thread_id: {"group_thread_id": thread_id, "player_id": "player-1"},
    )
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "get_latest_group_thread_session",
        lambda thread_id: {"session_id": "session-1", "status": "active"},
    )
    monkeypatch.setattr(group_dialogue_runtime, "_active_character_ids", lambda session: ["c1", "c2"])
    monkeypatch.setattr(
        group_dialogue_runtime.world_clock,
        "get_clock_snapshot",
        lambda player_id, real_now: _snapshot(now),
    )
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "claim_group_dialogue_state",
        lambda *args, **kwargs: False,
    )

    result = group_dialogue_runtime.run_group_dialogue_pulse(
        "thread-1",
        trigger_source="event",
        trigger_text="敌军逼近",
        explicit_event=True,
        now=now,
    )

    assert result == []


def test_ended_thread_creates_carrier_session_and_persists_notification(monkeypatch):
    from memoria.core import group_dialogue_runtime

    now = datetime(2026, 1, 2, 12, 0, tzinfo=UTC)
    state = {
        "group_thread_id": "thread-1",
        "player_id": "player-1",
        "daily_message_date": now.date().isoformat(),
        "daily_message_count": 0,
    }
    latest_session = {
        "session_id": "ended-session",
        "status": "ended",
        "player_id": "player-1",
        "player_name": "Player",
        "group_name": "行动组",
    }
    created = {}
    completed = {}
    notified = {}

    monkeypatch.setattr(group_dialogue_runtime.repository, "get_group_dialogue_state", lambda thread_id: state)
    monkeypatch.setattr(group_dialogue_runtime.repository, "get_latest_group_thread_session", lambda thread_id: latest_session)
    monkeypatch.setattr(group_dialogue_runtime, "_active_character_ids", lambda session: ["c1", "c2"])
    monkeypatch.setattr(
        group_dialogue_runtime.world_clock,
        "get_clock_snapshot",
        lambda player_id, real_now: _snapshot(now),
    )
    monkeypatch.setattr(group_dialogue_runtime.repository, "claim_group_dialogue_state", lambda *args, **kwargs: True)

    def create_session(**kwargs):
        created.update(kwargs)
        return True

    monkeypatch.setattr(group_dialogue_runtime.repository, "create_multi_character_session", create_session)
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "get_session",
        lambda session_id: {
            **latest_session,
            "session_id": session_id,
            "status": "active",
            "group_thread_id": "thread-1",
        },
    )
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "complete_group_dialogue_pulse",
        lambda group_thread_id, **kwargs: completed.update(
            group_thread_id=group_thread_id,
            **kwargs,
        ) or True,
    )
    monkeypatch.setattr(
        group_dialogue_runtime.repository,
        "upsert_group_message_notification",
        lambda player_id, group_thread_id, session_id, new_message_count, **kwargs: notified.update(
            player_id=player_id,
            group_thread_id=group_thread_id,
            session_id=session_id,
            new_message_count=new_message_count,
            **kwargs,
        ) or 1,
    )

    class FakeOrchestrator:
        def __init__(self, session_id):
            self.session_id = session_id
            self.last_pulse_state = {}

        def run_dialogue_pulse(self, **kwargs):
            assert kwargs["max_messages"] == 3
            assert kwargs["extract_memory"] is True
            assert kwargs["persist_state"] is False
            self.last_pulse_state = {
                "current_topic": "敌军逼近",
                "last_speaker_id": "c1",
                "waiting_for_player": True,
            }
            return [
                {"message_id": 10, "character_id": "c1", "dialogue": "准备迎敌。"},
                {"message_id": 11, "character_id": "c2", "dialogue": "我守后方。"},
            ]

    monkeypatch.setattr(group_dialogue_runtime, "MultiCharacterOrchestrator", FakeOrchestrator)

    responses = group_dialogue_runtime.run_group_dialogue_pulse(
        "thread-1",
        trigger_source="event",
        trigger_text="敌军逼近",
        explicit_event=True,
        now=now,
        lease_owner="worker-1",
    )

    assert len(responses) == 2
    assert created["group_thread_id"] == "thread-1"
    assert created["character_ids"] == ["c1", "c2"]
    assert completed["lease_owner"] == "worker-1"
    assert completed["autonomous_message_count"] == 0
    assert completed["waiting_for_player"] is True
    assert notified["new_message_count"] == 2
    assert notified["group_thread_id"] == "thread-1"
