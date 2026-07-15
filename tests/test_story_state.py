from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import fastapi.dependencies.utils
import fastapi.routing
import httpx
import pytest
from fastapi import FastAPI

from memoria.db import repository


UTC = timezone.utc


def _create_identity(prefix: str) -> tuple[str, dict[str, str]]:
    suffix = uuid.uuid4().hex[:10]
    user_id = f"{prefix}_{suffix}"
    repository.create_user(
        user_id,
        f"{prefix}_user_{suffix}",
        "test-hash",
    )
    token = f"{prefix}_token_{uuid.uuid4().hex}"
    repository.create_auth_token(
        token,
        user_id,
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    return user_id, {"Authorization": f"Bearer {token}"}


def _install_inline_fastapi(monkeypatch) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", run_inline)
    monkeypatch.setattr(
        fastapi.dependencies.utils,
        "run_in_threadpool",
        run_inline,
    )


@pytest.fixture
def test_user():
    user_id, _headers = _create_identity("story")
    return user_id


def test_story_lifecycle_projects_canonical_state(test_user):
    repository.append_story_event(
        test_user,
        "graytide",
        "story.started.v1",
        {"progress": -0.25},
    )
    progressed = repository.append_story_event(
        test_user,
        "graytide",
        "story.progressed.v1",
        {"progress_delta": 1.5},
    )

    assert progressed["status"] == "active"
    assert progressed["progress"] == 1.0
    assert progressed["ledger_version"] == 2

    completed = repository.append_story_event(
        test_user,
        "graytide",
        "story.completed.v1",
        {"reason": "final_conclusion"},
    )

    assert completed["owner_user_id"] == test_user
    assert completed["story_id"] == "graytide"
    assert completed["status"] == "completed"
    assert completed["progress"] == 1.0
    assert completed["terminal_reason"] == "final_conclusion"
    assert completed["ledger_version"] == 3
    assert completed["completed_at"] is not None
    assert completed["failed_at"] is None


def test_event_effects_project_fact_and_story_atomically():
    from memoria.core.event_executor import EventExecutor
    from memoria.core.event_schema import (
        EffectType,
        EventContext,
        EventDefinition,
        EventEffect,
        TriggerCondition,
        TriggerType,
    )

    user_id, _headers = _create_identity("story_event")
    suffix = uuid.uuid4().hex[:10]
    story_id = f"graytide-{suffix}"
    memory_text = f"灯塔账册确认潮汐钟由港务局维护 {suffix}"
    event = EventDefinition(
        event_id=f"graytide_finale_{suffix}",
        event_name="灰潮终局",
        story_id=story_id,
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["终局"],
        ),
        effects=[
            EventEffect(
                effect_type=EffectType.ADD_MEMORY,
                memory_text=memory_text,
            ),
            EventEffect(
                effect_type=EffectType.UPDATE_EVENT_PROGRESS,
                progress=1.0,
                event_status="completed",
            ),
        ],
    )
    context = EventContext(
        character_id=f"archivist-{suffix}",
        player_id=user_id,
        session_id=f"session-{suffix}",
        current_affinity=0,
        current_trust=0,
        current_mood="neutral",
        player_message="终局",
        dialogue_count=1,
        total_dialogue_count=1,
        session_duration_minutes=1,
        execution_key=f"story-event:{suffix}",
    )

    result = EventExecutor().execute_event(event, context)

    assert result.status == "succeeded"
    claims = repository.list_fact_claims(
        user_id,
        scope_type="story",
        scope_id=story_id,
    )
    assert len(claims) == 1
    assert claims[0]["fact_text"] == memory_text
    assert claims[0]["source_kind"] == "authored_event"
    assert claims[0]["status"] == "verified"

    state = repository.get_story_state(user_id, story_id)
    assert state["status"] == "completed"
    assert state["progress"] == 1.0

    fact_events = repository.list_domain_events(
        user_id,
        "fact_claim",
        claims[0]["claim_id"],
    )
    story_events = repository.list_domain_events(
        user_id,
        "story",
        story_id,
    )
    assert fact_events
    assert [event.event_type for event in story_events] == [
        "story.started.v1",
        "story.completed.v1",
    ]
    assert {
        event.correlation_id
        for event in [*fact_events, *story_events]
    } == {result.execution_id}


def test_event_effect_commit_failure_rolls_back_all_projections(monkeypatch):
    from memoria.core.event_executor import EventExecutor
    from memoria.core.event_schema import (
        EffectType,
        EventContext,
        EventDefinition,
        EventEffect,
        TriggerCondition,
        TriggerType,
    )

    user_id, _headers = _create_identity("story_event_rollback")
    suffix = uuid.uuid4().hex[:10]
    story_id = f"graytide-rollback-{suffix}"
    character_id = f"archivist-rollback-{suffix}"
    event_id = f"graytide_rollback_{suffix}"
    memory_text = f"这条记忆必须随故事投影失败一起回滚 {suffix}"
    event = EventDefinition(
        event_id=event_id,
        event_name="灰潮回滚验证",
        story_id=story_id,
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["回滚"],
        ),
        effects=[
            EventEffect(
                effect_type=EffectType.ADD_MEMORY,
                memory_text=memory_text,
            ),
            EventEffect(
                effect_type=EffectType.UPDATE_EVENT_PROGRESS,
                progress=1.0,
                event_status="completed",
            ),
        ],
    )
    context = EventContext(
        character_id=character_id,
        player_id=user_id,
        session_id=f"session-rollback-{suffix}",
        current_affinity=0,
        current_trust=0,
        current_mood="neutral",
        player_message="回滚",
        dialogue_count=1,
        total_dialogue_count=1,
        session_duration_minutes=1,
        execution_key=f"story-event-rollback:{suffix}",
    )

    def fail_story_projection(*args, **kwargs):
        raise RuntimeError("forced story projection failure")

    monkeypatch.setattr(
        repository,
        "_apply_story_update_in_transaction",
        fail_story_projection,
    )

    with pytest.raises(RuntimeError, match="forced story projection failure"):
        EventExecutor().execute_event(event, context)

    assert repository.get_long_term_facts(character_id, user_id, 10) == []
    assert repository.list_fact_claims(user_id, "story", story_id) == []
    assert repository.get_story_state(user_id, story_id) is None
    assert repository.list_domain_events(user_id, "story", story_id) == []
    assert repository.get_event_trigger_history(
        event_id=event_id,
        player_id=user_id,
    ) == []


@pytest.mark.parametrize(
    ("terminal_event_type", "terminal_status"),
    [
        ("story.completed.v1", "completed"),
        ("story.failed.v1", "failed"),
    ],
)
def test_story_progress_is_rejected_after_terminal_state(
    test_user,
    terminal_event_type,
    terminal_status,
):
    story_id = f"graytide-{terminal_status}"
    repository.append_story_event(
        test_user,
        story_id,
        "story.started.v1",
        {},
    )
    repository.append_story_event(
        test_user,
        story_id,
        terminal_event_type,
        {"reason": "terminal"},
    )

    with pytest.raises(repository.StoryStateTransitionError):
        repository.append_story_event(
            test_user,
            story_id,
            "story.progressed.v1",
            {"progress": 0.5},
        )

    state = repository.get_story_state(test_user, story_id)
    assert state["status"] == terminal_status
    assert repository.list_domain_events(
        test_user,
        "story",
        story_id,
    )[-1].event_type == terminal_event_type


@pytest.mark.asyncio
async def test_story_state_api_requires_auth_and_returns_not_found(monkeypatch):
    from memoria.api import story as story_api

    _install_inline_fastapi(monkeypatch)
    user_id, headers = _create_identity("story_api_missing")
    app = FastAPI()
    app.include_router(story_api.router, prefix="/api/v1")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        assert (
            await client.get("/api/v1/stories/graytide/state")
        ).status_code == 401
        response = await client.get(
            "/api/v1/stories/graytide/state",
            headers=headers,
        )

    assert response.status_code == 404
    assert repository.get_story_state(user_id, "graytide") is None


@pytest.mark.asyncio
async def test_story_completion_is_queryable_without_dialogue(monkeypatch):
    from memoria.api import story as story_api

    _install_inline_fastapi(monkeypatch)
    user_id, headers = _create_identity("story_api_complete")
    repository.append_story_event(
        user_id,
        "graytide",
        "story.started.v1",
        {},
    )
    repository.append_story_event(
        user_id,
        "graytide",
        "story.completed.v1",
        {"reason": "final_conclusion"},
    )
    app = FastAPI()
    app.include_router(story_api.router, prefix="/api/v1")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/v1/stories/graytide/state",
            headers=headers,
        )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["progress"] == 1.0
    assert response.json()["terminal_reason"] == "final_conclusion"


@pytest.mark.asyncio
async def test_story_state_api_enforces_owner_user_id(monkeypatch):
    from memoria.api import story as story_api

    _install_inline_fastapi(monkeypatch)
    owner_user_id, _owner_headers = _create_identity("story_owner")
    other_user_id, other_headers = _create_identity("story_other")
    repository.append_story_event(
        owner_user_id,
        "graytide",
        "story.started.v1",
        {"progress": 0.4},
    )
    app = FastAPI()
    app.include_router(story_api.router, prefix="/api/v1")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get(
            "/api/v1/stories/graytide/state",
            headers=other_headers,
        )

    assert response.status_code == 404
    assert repository.get_story_state(other_user_id, "graytide") is None
