from __future__ import annotations

import json
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier, Lock
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from memoria.core import character_loader, event_runtime, prompt_builder, world_clock
from memoria.core.event_schema import (
    EffectType,
    EventContext,
    EventDefinition,
    EventEffect,
    EventTriggerResult,
    TriggerCondition,
    TriggerType,
)
from memoria.db import repository


UTC = timezone.utc


def _user_id(prefix: str = "clock") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _create_user(prefix: str = "clock") -> str:
    user_id = _user_id(prefix)
    repository.create_user(
        user_id,
        f"{prefix}_{uuid.uuid4().hex[:8]}",
        "test-hash",
    )
    return user_id


def test_world_time_formula_pause_resume_scale_and_sync():
    player_id = _create_user("formula")
    start = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    initial = world_clock.get_clock_snapshot(player_id, real_now=start)
    assert initial.world_now == start
    assert initial.time_scale == 1

    doubled = world_clock.update_clock(player_id, time_scale=2, real_now=start + timedelta(hours=1))
    assert doubled.world_now == start + timedelta(hours=1)
    later = world_clock.get_clock_snapshot(player_id, real_now=start + timedelta(hours=3))
    assert later.world_now == start + timedelta(hours=5)

    paused = world_clock.update_clock(player_id, time_scale=0, real_now=start + timedelta(hours=3))
    frozen = world_clock.get_clock_snapshot(player_id, real_now=start + timedelta(days=2))
    assert paused.world_now == frozen.world_now
    assert frozen.paused

    resumed = world_clock.update_clock(player_id, time_scale=5, real_now=start + timedelta(days=2))
    assert resumed.world_now == frozen.world_now
    synced = world_clock.sync_clock(player_id, real_now=start + timedelta(days=3))
    assert synced.world_now == start + timedelta(days=3)
    assert synced.time_scale == 5


@pytest.mark.parametrize("scale", [-1, 3, 1.5, True])
def test_world_clock_rejects_invalid_scale(scale):
    with pytest.raises(ValueError):
        world_clock.validate_time_scale(scale)


def test_world_clock_rejects_invalid_timezone():
    with pytest.raises(ValueError):
        world_clock.validate_timezone("Mars/Olympus_Mons")


def test_local_time_dst_day_and_week_boundaries():
    player_id = _create_user("dst")
    snapshot = world_clock.WorldClockSnapshot(
        player_id=player_id,
        timezone="America/New_York",
        time_scale=1,
        real_now=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
        world_now=datetime(2026, 3, 8, 7, 30, tzinfo=UTC),
    )
    assert snapshot.local_now.hour == 3
    assert snapshot.local_now.utcoffset() == timedelta(hours=-4)
    assert snapshot.prompt_context()["weekday"] == "星期日"

    monday = world_clock.WorldClockSnapshot(
        player_id=player_id,
        timezone="Asia/Shanghai",
        time_scale=1,
        real_now=datetime(2026, 7, 12, 16, 30, tzinfo=UTC),
        world_now=datetime(2026, 7, 12, 16, 30, tzinfo=UTC),
    )
    context = monday.prompt_context()
    assert context["local_date"] == "2026-07-13"
    assert context["weekday"] == "星期一"


def test_player_local_cron_conversion_handles_dst():
    before_first_fallback = datetime(2026, 11, 1, 4, 59, tzinfo=UTC)
    first = event_runtime.next_cron_run(
        "30 1 * * *",
        before_first_fallback,
        timezone_name="America/New_York",
    )
    second = event_runtime.next_cron_run(
        "30 1 * * *",
        first,
        timezone_name="America/New_York",
    )
    assert first == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert second == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)

    before_spring_gap = datetime(2026, 3, 8, 5, 0, tzinfo=UTC)
    after_gap = event_runtime.next_cron_run(
        "30 2 * * *",
        before_spring_gap,
        timezone_name="America/New_York",
    )
    assert after_gap == datetime(2026, 3, 9, 6, 30, tzinfo=UTC)


def _scheduled_event() -> EventDefinition:
    return EventDefinition(
        event_id="scheduled_event",
        event_name="定时事件",
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.TIME_BASED,
            schedule="*/5 * * * *",
        ),
        effects=[],
    )


def _scheduled_context() -> EventContext:
    return EventContext(
        character_id="npc_luo_xiaohei",
        player_id="scheduled_player",
        session_id="schedule:scheduled_event",
        current_affinity=25,
        current_trust=30,
        current_mood="neutral",
        player_message="",
        dialogue_count=0,
        total_dialogue_count=0,
        session_duration_minutes=0,
    )


def test_paused_player_schedule_does_not_trigger(monkeypatch):
    row = {
        "event_id": "scheduled_event",
        "character_id": "npc_luo_xiaohei",
        "player_id": "scheduled_player",
        "schedule": "*/5 * * * *",
        "next_run_at": "2026-07-12T10:00:00+00:00",
    }
    monkeypatch.setattr(event_runtime.repository, "list_active_event_schedules", lambda **kwargs: [row])
    monkeypatch.setattr(
        event_runtime.world_clock,
        "get_clock_snapshot",
        lambda *args, **kwargs: world_clock.WorldClockSnapshot(
            player_id=row["player_id"],
            timezone="UTC",
            time_scale=0,
            real_now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
            world_now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
        ),
    )
    monkeypatch.setattr(
        event_runtime.repository,
        "claim_event_schedule",
        lambda *args, **kwargs: pytest.fail("paused schedule must not be claimed"),
    )
    assert event_runtime.run_due_time_events(
        now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    ) == []


def test_catch_up_runs_once_and_advances_beyond_world_now(monkeypatch):
    world_now = datetime(2026, 7, 12, 12, 2, tzinfo=UTC)
    row = {
        "event_id": "scheduled_event",
        "character_id": "npc_luo_xiaohei",
        "player_id": "scheduled_player",
        "schedule": "*/5 * * * *",
        "next_run_at": "2026-07-12T10:00:00+00:00",
    }
    commits = []
    monkeypatch.setattr(event_runtime.repository, "list_active_event_schedules", lambda **kwargs: [row])
    monkeypatch.setattr(
        event_runtime.world_clock,
        "get_clock_snapshot",
        lambda *args, **kwargs: world_clock.WorldClockSnapshot(
            player_id=row["player_id"],
            timezone="UTC",
            time_scale=10,
            real_now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
            world_now=world_now,
        ),
    )
    monkeypatch.setattr(event_runtime.repository, "claim_event_schedule", lambda *args, **kwargs: True)
    monkeypatch.setattr(event_runtime.repository, "get_event_definition", lambda *args: {"event_id": "scheduled_event"})
    monkeypatch.setattr(event_runtime, "_event_definition_from_row", lambda row: _scheduled_event())
    monkeypatch.setattr(event_runtime, "_load_scheduled_event_context", lambda *args: _scheduled_context())
    result = EventTriggerResult(
        execution_id="scheduled-execution",
        event_id="scheduled_event",
        event_name="定时事件",
        character_id=row["character_id"],
        triggered=True,
    )
    monkeypatch.setattr(event_runtime.repository, "get_event_execution_batch", lambda *args: None)
    monkeypatch.setattr(
        event_runtime,
        "_plan_event_chain",
        lambda *args: ([result], [{
            "execution_id": result.execution_id,
            "status": "succeeded",
            "inbox_items": [],
        }]),
    )
    monkeypatch.setattr(
        event_runtime.repository,
        "commit_event_execution_batch",
        lambda **kwargs: commits.append(kwargs) or {
            "deduplicated": False,
            "inserted_memories": [],
        },
    )

    results = event_runtime.run_due_time_events(
        now=datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    )
    assert len(results) == 1
    assert len(commits) == 1
    assert datetime.fromisoformat(
        commits[0]["schedule_completion"]["next_run_at"]
    ) > world_now
    assert commits[0]["schedule_completion"]["lease_owner"].startswith("scheduler:")


def test_schedule_claim_prevents_stale_second_worker():
    player_id = _create_user("lease")
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    character_id = "npc_luo_xiaohei"
    scheduled_for = "2026-07-12T10:00:00+00:00"
    repository.save_event_schedule_state(
        event_id,
        character_id,
        player_id,
        "*/5 * * * *",
        next_run_at=scheduled_for,
    )
    assert repository.claim_event_schedule(
        event_id,
        character_id,
        player_id,
        lease_owner="worker-a",
        lease_expires_at="2026-07-12T10:02:00+00:00",
        real_now_iso="2026-07-12T10:00:00+00:00",
        expected_next_run_at=scheduled_for,
    )
    assert repository.complete_event_schedule(
        event_id,
        character_id,
        player_id,
        lease_owner="worker-a",
        last_checked_at=scheduled_for,
        last_run_at=scheduled_for,
        next_run_at="2026-07-12T10:05:00+00:00",
    )
    assert not repository.claim_event_schedule(
        event_id,
        character_id,
        player_id,
        lease_owner="worker-b",
        lease_expires_at="2026-07-12T10:02:00+00:00",
        real_now_iso="2026-07-12T10:00:01+00:00",
        expected_next_run_at=scheduled_for,
    )


def test_concurrent_schedulers_execute_due_event_once(monkeypatch):
    player_id = _create_user("concurrent")
    event_id = f"evt_{uuid.uuid4().hex[:8]}"
    character_id = "npc_luo_xiaohei"
    real_now = datetime(2026, 7, 12, 10, 0, tzinfo=UTC)
    scheduled_for = real_now.isoformat()
    row = {
        "event_id": event_id,
        "character_id": character_id,
        "player_id": player_id,
        "schedule": "*/5 * * * *",
        "next_run_at": scheduled_for,
    }
    repository.save_event_schedule_state(
        event_id,
        character_id,
        player_id,
        row["schedule"],
        next_run_at=scheduled_for,
    )

    scan_barrier = Barrier(2)
    execution_lock = Lock()
    execution_count = 0

    def list_schedules(**kwargs):
        scan_barrier.wait(timeout=5)
        return [row]

    original_plan_event_chain = event_runtime._plan_event_chain

    def execute_once(*args):
        nonlocal execution_count
        with execution_lock:
            execution_count += 1
        return original_plan_event_chain(*args)

    monkeypatch.setattr(
        event_runtime.repository,
        "list_active_event_schedules",
        list_schedules,
    )
    monkeypatch.setattr(
        event_runtime.world_clock,
        "get_clock_snapshot",
        lambda *args, **kwargs: world_clock.WorldClockSnapshot(
            player_id=player_id,
            timezone="UTC",
            time_scale=1,
            real_now=real_now,
            world_now=real_now,
        ),
    )
    monkeypatch.setattr(
        event_runtime.repository,
        "get_event_definition",
        lambda *args: {"event_id": event_id},
    )
    monkeypatch.setattr(
        event_runtime,
        "_event_definition_from_row",
        lambda event_row: EventDefinition(
            event_id=event_id,
            event_name="并发定时事件",
            trigger_condition=TriggerCondition(
                trigger_type=TriggerType.TIME_BASED,
                schedule=row["schedule"],
            ),
            effects=[],
        ),
    )
    monkeypatch.setattr(
        event_runtime,
        "_load_scheduled_event_context",
        lambda *args: _scheduled_context().model_copy(
            update={"player_id": player_id}
        ),
    )
    monkeypatch.setattr(event_runtime, "_plan_event_chain", execute_once)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                event_runtime.run_due_time_events,
                now=real_now,
                lease_owner=owner,
            )
            for owner in ("worker-a", "worker-b")
        ]
        scheduler_results = [future.result(timeout=10) for future in futures]

    assert execution_count == 1
    assert sorted(len(results) for results in scheduler_results) == [0, 1]


def test_scheduled_results_persist_state_and_inbox(monkeypatch):
    saved_state = []
    inbox = []
    result = EventTriggerResult(
        event_id="scheduled_event",
        event_name="定时事件",
        triggered=True,
        notification="时间到了",
        state_changes={
            "affection_level": 5,
            "trust_level": 2,
            "current_mood": "happy",
        },
    )
    monkeypatch.setattr(
        event_runtime.repository,
        "save_runtime_state",
        lambda *args: saved_state.append(args),
    )
    monkeypatch.setattr(
        event_runtime.repository,
        "enqueue_player_event",
        lambda *args, **kwargs: inbox.append((args, kwargs)) or 1,
    )
    event_runtime._persist_scheduled_event_results(
        _scheduled_event(),
        _scheduled_context(),
        [result],
        datetime(2026, 7, 12, 12, 0, tzinfo=UTC),
    )
    assert saved_state[0][2:] == (30, 32, "happy")
    assert inbox[0][0][1] == "时间到了"
    assert json.loads(inbox[0][1]["payload"])[0]["event_id"] == "scheduled_event"


def test_atomic_schedule_completion_rolls_back_when_lease_is_lost():
    player_id = _create_user("atomic_lease")
    character_id = "npc_luo_xiaohei"
    event_id = f"atomic_lease_{uuid.uuid4().hex[:8]}"
    execution_key = f"schedule:{event_id}:lost"
    repository.save_event_definition(
        owner_user_id=player_id,
        event_id=event_id,
        event_name="租约回滚",
        trigger_config=TriggerCondition(
            trigger_type=TriggerType.TIME_BASED,
            schedule="*/5 * * * *",
        ).model_dump_json(),
        effects_config="[]",
        character_id=character_id,
        schedule="*/5 * * * *",
    )
    repository.save_runtime_state(character_id, player_id, 10, 20, "neutral")
    execution = {
        "execution_id": uuid.uuid4().hex,
        "event_id": event_id,
        "character_id": character_id,
        "session_id": f"schedule:{event_id}",
        "status": "succeeded",
        "effects_data": "[]",
        "result_data": "{}",
        "error": None,
        "duration_ms": 1,
        "context_snapshot": "{}",
        "effects_applied": "[]",
        "context_state": {
            "context_data": "{}",
            "status": "active",
            "progress": 0.25,
        },
        "memories": [{
            "character_id": character_id,
            "player_id": player_id,
            "fact_text": "租约丢失时不能落库",
            "importance": 5,
        }],
        "unlock_keys": ["lease_unlock"],
        "inbox_items": [{"content": "租约通知"}],
        "proactive_messages": [],
    }

    with pytest.raises(RuntimeError, match="lease was lost"):
        repository.commit_event_execution_batch(
            player_id=player_id,
            execution_key=execution_key,
            trigger_source="schedule",
            results_data="[]",
            executions=[execution],
            runtime_states=[{
                "character_id": character_id,
                "affection_level": 15,
                "trust_level": 20,
                "current_mood": "happy",
            }],
            schedule_completion={
                "event_id": event_id,
                "character_id": character_id,
                "lease_owner": "lost-worker",
                "last_checked_at": "2026-07-14T12:00:00+00:00",
                "last_run_at": "2026-07-14T12:00:00+00:00",
                "next_run_at": "2026-07-14T12:05:00+00:00",
            },
        )

    assert repository.get_event_execution_batch(player_id, execution_key) is None
    assert repository.list_event_execution_history(player_id, event_id=event_id) == []
    assert repository.get_event_trigger_history(event_id=event_id, player_id=player_id) == []
    assert repository.get_long_term_facts(character_id, player_id, 10) == []
    assert repository.list_event_unlocks(player_id, character_id) == []
    assert repository.list_player_event_inbox(player_id) == []
    assert repository.get_event_context_state(event_id, character_id, player_id) is None
    runtime = repository.get_runtime_state(
        character_id,
        player_id,
        character_loader.load_character_card(character_id),
    )
    assert runtime["affection_level"] == 10
    assert runtime["current_mood"] == "neutral"


def test_unimplemented_scheduled_effect_rolls_back_all_side_effects():
    player_id = _create_user("side_effects")
    character_id = "npc_luo_xiaohei"
    target_character_id = "npc_wuxian"
    event = EventDefinition(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        event_name="完整副作用",
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.TIME_BASED,
            schedule="0 * * * *",
        ),
        effects=[
            EventEffect(
                effect_type=EffectType.MODIFY_STATE,
                state_changes={"affection_level": 5, "trust_level": 2},
            ),
            EventEffect(
                effect_type=EffectType.CHANGE_MOOD,
                target_mood="happy",
            ),
            EventEffect(
                effect_type=EffectType.ADD_MEMORY,
                memory_text="定时事件留下了一段清晰的记忆。",
                memory_importance=8,
            ),
            EventEffect(
                effect_type=EffectType.MODIFY_RELATIONSHIP,
                target_character_id=target_character_id,
                relationship_change={"affinity": 4},
            ),
            EventEffect(
                effect_type=EffectType.NOTIFY_PLAYER,
                notification_message="定时事件已经完成",
            ),
        ],
    )
    context = EventContext(
        character_id=character_id,
        player_id=player_id,
        session_id=f"schedule:{event.event_id}",
        current_affinity=25,
        current_trust=30,
        current_mood="neutral",
        player_message="",
        dialogue_count=0,
        total_dialogue_count=0,
        session_duration_minutes=0,
    )
    repository.save_character_relationship(
        player_id,
        character_id,
        target_character_id,
        relationship_type="ally",
        affinity=10,
    )
    repository.save_runtime_state(character_id, player_id, 25, 30, "neutral")

    results = event_runtime.execute_event_with_chain(event, context)
    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].triggered is False

    from memoria.core import character_loader

    runtime_state = repository.get_runtime_state(
        character_id,
        player_id,
        character_loader.load_character_card(character_id),
    )
    assert runtime_state["affection_level"] == 25
    assert runtime_state["trust_level"] == 30
    assert runtime_state["current_mood"] == "neutral"
    assert "定时事件留下了一段清晰的记忆。" not in repository.get_long_term_facts(
        character_id,
        player_id,
        limit=10,
    )
    relationship = repository.get_character_relationship(
        player_id,
        character_id,
        target_character_id,
    )
    assert relationship["affinity"] == 10
    inbox = repository.list_player_event_inbox(player_id)
    assert inbox == []
    assert repository.get_event_trigger_history(
        event_id=event.event_id,
        player_id=player_id,
    ) == []


def test_single_and_group_prompts_share_world_context():
    from memoria.core import character_loader

    card = character_loader.load_character_card("npc_luo_xiaohei")
    context = world_clock.WorldClockSnapshot(
        player_id="prompt-player",
        timezone="Asia/Shanghai",
        time_scale=2,
        real_now=datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
        world_now=datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
    ).prompt_context(datetime(2026, 7, 12, 2, 0, tzinfo=UTC))
    state = {
        "affection_level": 0,
        "trust_level": 10,
        "current_mood": "neutral",
        "known_player_facts": [],
    }
    single = prompt_builder.build_system_prompt(card, state, "玩家", time_context=context)
    group = prompt_builder.build_multi_character_system_prompt(
        card,
        state,
        "玩家",
        [],
        time_context=context,
    )
    for expected in ("2026-07-12", "12:00:00", "Asia/Shanghai", "2x", "2 小时"):
        assert expected in single
        assert expected in group


def test_group_orchestrator_paths_share_clock_snapshot_with_prompt_and_messages(monkeypatch):
    from memoria.core import multi_character_orchestrator

    character_id = "npc_luo_xiaohei"
    snapshot = world_clock.WorldClockSnapshot(
        player_id="group-player",
        timezone="Asia/Shanghai",
        time_scale=2,
        real_now=datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
        world_now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
    )
    card = SimpleNamespace(
        meta=SimpleNamespace(name="小黑", display_name="小黑"),
        action_vocabulary=SimpleNamespace(default_action="idle"),
    )
    orchestrator = multi_character_orchestrator.MultiCharacterOrchestrator.__new__(
        multi_character_orchestrator.MultiCharacterOrchestrator
    )
    orchestrator.session_id = "group-session"
    orchestrator.player_id = snapshot.player_id
    orchestrator.player_name = "玩家"
    orchestrator.character_ids = [character_id]
    orchestrator.character_cards = {character_id: card}
    orchestrator._checkpoint_memory_ready = True
    orchestrator._checkpoint_memory_fact = None
    orchestrator._load_all_relationships = lambda: {}
    orchestrator._load_runtime_state_for_prompt = lambda *args, **kwargs: {
        "affection_level": 10,
        "trust_level": 20,
        "current_mood": "neutral",
    }
    orchestrator._load_memory_context = lambda *args, **kwargs: []
    orchestrator._format_history_for_llm = lambda *args, **kwargs: []

    prompts = []
    saved_messages = []
    knowledge_queries = []
    monkeypatch.setattr(
        multi_character_orchestrator.multi_character_memory,
        "get_relationship_history_cutoff",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_last_character_interaction_world_at",
        lambda *args, **kwargs: datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_multi_character_thread_history",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "get_group_thread_id",
        lambda session_id: "thread-1",
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "save_runtime_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        multi_character_orchestrator.repository,
        "append_multi_character_message",
        lambda *args, **kwargs: saved_messages.append((args, kwargs)) or len(saved_messages),
    )
    monkeypatch.setattr(
        multi_character_orchestrator.prompt_builder,
        "build_multi_character_system_prompt",
        lambda *args, **kwargs: prompts.append(kwargs) or "group prompt",
    )
    monkeypatch.setattr(
        multi_character_orchestrator.llm_client,
        "call_role_turn",
        lambda *args, **kwargs: {
            "dialogue": "现在出发。",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
        },
    )

    def fake_retrieve_knowledge(**kwargs):
        knowledge_queries.append(kwargs)
        return SimpleNamespace(prompt_section="相关知识", sources=[{"document_id": "doc-1"}])

    monkeypatch.setattr(
        multi_character_orchestrator,
        "retrieve_knowledge",
        fake_retrieve_knowledge,
    )

    opening = orchestrator._generate_opening(character_id, clock_snapshot=snapshot)
    response = orchestrator._generate_character_response(
        character_id,
        "我们去哪里？",
        clock_snapshot=snapshot,
    )

    assert opening["dialogue"] == "现在出发。"
    assert response["dialogue"] == "现在出发。"
    assert prompts[0]["is_opening"] is True
    assert prompts[0]["time_context"] == prompts[1]["time_context"]
    assert prompts[0]["time_context"]["last_interaction_elapsed"] == "2 小时"
    assert prompts[1]["knowledge_context"] == "相关知识"
    assert knowledge_queries[0]["current_message"] == "我们去哪里？"
    assert [message[1]["world_created_at"] for message in saved_messages] == [
        snapshot.world_now.isoformat(),
        snapshot.world_now.isoformat(),
    ]


def test_single_dialogue_uses_elapsed_world_time_and_shared_message_timestamp(
    monkeypatch,
):
    from memoria.core import orchestrator

    player_id = _create_user("single_elapsed")
    character_id = "npc_luo_xiaohei"
    session_id = f"single_{uuid.uuid4().hex}"
    repository.create_session(session_id, character_id, player_id, "玩家")
    snapshot = world_clock.WorldClockSnapshot(
        player_id=player_id,
        timezone="Asia/Shanghai",
        time_scale=2,
        real_now=datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
        world_now=datetime(2026, 7, 12, 6, 0, tzinfo=UTC),
    )
    captured_time_context = []
    saved_messages = []
    card = SimpleNamespace(
        action_vocabulary=SimpleNamespace(
            default_action="idle",
            greeting_actions=[],
            farewell_actions=[],
            agreement_actions=[],
            disagreement_actions=[],
            emotional_reactions=[],
        ),
        runtime_state_schema=SimpleNamespace(
            current_mood=SimpleNamespace(emotions=["neutral"])
        ),
    )

    monkeypatch.setattr(
        orchestrator.world_clock,
        "get_clock_snapshot",
        lambda *args, **kwargs: snapshot,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_last_character_interaction_world_at",
        lambda *args, **kwargs: datetime(2026, 7, 12, 4, 0, tzinfo=UTC),
    )
    monkeypatch.setattr(
        orchestrator.character_loader,
        "load_character_card",
        lambda *args, **kwargs: card,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_runtime_state",
        lambda *args, **kwargs: {
            "affection_level": 10,
            "trust_level": 20,
            "current_mood": "neutral",
            "known_player_facts": [],
        },
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_short_term_history",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "get_recent_summaries",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator,
        "_load_single_character_prompt_context",
        lambda *args, **kwargs: {
            "known_player_facts": [],
            "cross_mode_memories": [],
            "relationship_graph_lines": [],
            "character_relationships": {},
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "retrieve_knowledge",
        lambda **kwargs: SimpleNamespace(prompt_section="", sources=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "_build_system_prompt",
        lambda *args, **kwargs: captured_time_context.append(
            kwargs["time_context"]
        )
        or "single prompt",
    )
    monkeypatch.setattr(
        orchestrator.llm_client,
        "call_role_turn",
        lambda *args, **kwargs: {
            "dialogue": "我记得。",
            "action": "idle",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
        },
    )
    monkeypatch.setattr(
        orchestrator.event_runtime,
        "detect_and_execute_events",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "save_runtime_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "append_short_term_message",
        lambda *args, **kwargs: saved_messages.append((args, kwargs))
        or len(saved_messages),
    )
    monkeypatch.setattr(
        orchestrator.repository,
        "is_long_term_memory_checkpoint",
        lambda *args, **kwargs: False,
    )

    result = orchestrator.run_dialogue_turn(session_id, "还记得上次吗？")

    assert result["dialogue"] == "我记得。"
    assert captured_time_context[0]["last_interaction_elapsed"] == "2 小时"
    assert [message[1]["world_created_at"] for message in saved_messages] == [
        snapshot.world_now.isoformat(),
        snapshot.world_now.isoformat(),
    ]


def test_single_and_group_messages_store_same_world_timestamp():
    player_id = _create_user("messages")
    world_created_at = "2026-07-12T08:30:00+00:00"
    single_session = f"single_{uuid.uuid4().hex}"
    group_session = f"group_{uuid.uuid4().hex}"
    repository.create_session(single_session, "npc_luo_xiaohei", player_id, "玩家")
    repository.create_multi_character_session(
        group_session,
        player_id,
        "玩家",
        ["npc_luo_xiaohei"],
        group_name="测试群",
    )
    repository.append_short_term_message(
        single_session,
        "assistant",
        "单聊",
        world_created_at=world_created_at,
    )
    repository.append_multi_character_message(
        group_session,
        "assistant",
        "群聊",
        character_id="npc_luo_xiaohei",
        world_created_at=world_created_at,
    )
    with repository.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT world_created_at
            FROM short_term_message
            WHERE session_id IN (?, ?)
            ORDER BY id
            """,
            (single_session, group_session),
        ).fetchall()
    assert [row["world_created_at"] for row in rows] == [
        world_created_at,
        world_created_at,
    ]


def test_world_clock_api_auth_isolation_and_inbox_ownership():
    from memoria.api import user as user_api

    player_a = _create_user("api_a")
    player_b = _create_user("api_b")
    token_a = f"token_{uuid.uuid4().hex}"
    token_b = f"token_{uuid.uuid4().hex}"
    expires_at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    repository.create_auth_token(token_a, player_a, expires_at)
    repository.create_auth_token(token_b, player_b, expires_at)

    with pytest.raises(HTTPException) as unauthorized:
        user_api.require_current_user_id(
            token=None,
            authorization=None,
            cookie_token=None,
        )
    assert unauthorized.value.status_code == 401
    assert user_api.require_current_user_id(
        token=None,
        authorization=f"Bearer {token_a}",
        cookie_token=None,
    ) == player_a
    assert user_api.require_current_user_id(
        token=None,
        authorization=f"Bearer {token_b}",
        cookie_token=None,
    ) == player_b

    updated = user_api.put_world_clock(
        user_api.UpdateWorldClockRequest(
            timezone="Asia/Shanghai",
            time_scale=0,
        ),
        user_id=player_a,
    )
    assert updated.paused is True
    other = user_api.get_world_clock(user_id=player_b)
    assert other.time_scale == 1

    inbox_id = repository.enqueue_player_event(
        player_a,
        "仅玩家 A 可见",
    )
    with pytest.raises(HTTPException) as not_found:
        user_api.read_event_inbox_item(inbox_id, user_id=player_b)
    assert not_found.value.status_code == 404
    listed = user_api.get_event_inbox(
        unread_only=True,
        limit=50,
        user_id=player_a,
    )
    assert any(item["id"] == inbox_id for item in listed)
    assert user_api.read_event_inbox_item(
        inbox_id,
        user_id=player_a,
    ).success is True
