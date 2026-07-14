from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import fastapi.dependencies.utils
import fastapi.routing
import httpx
import pytest
from fastapi import FastAPI

from memoria.api import dialogue as dialogue_api
from memoria.api import event_admin as event_admin_api
from memoria.api import multi_dialogue as multi_dialogue_api
from memoria.core import character_loader
from memoria.core import multi_character_orchestrator
from memoria.core import orchestrator
from memoria.core import vector_memory
from memoria.db import repository


UTC = timezone.utc


class _EmptyVectorStore:
    def search_similar_memories(self, **_kwargs):
        return []


def _character_card(character_id: str, name: str) -> dict:
    return {
        "character_id": character_id,
        "version": "1.0.0",
        "meta": {"name": name, "display_name": name},
        "identity": {
            "age": "unknown",
            "gender": "unknown",
            "occupation": "tester",
            "race_or_species": "human",
            "appearance": "plain",
        },
        "personality": {},
        "speech_style": {"tone_register": "plain", "vocabulary_notes": ""},
        "background": {"story_bio": ""},
        "goals_and_motivations": {},
        "interaction_rules": {},
        "action_vocabulary": {"default_action": "neutral"},
        "runtime_state_schema": {
            "current_mood": {
                "emotions": ["neutral", "happy"],
                "default_mood": "neutral",
            },
        },
        "safety_constraints": {},
    }


def _create_identity(prefix: str) -> tuple[str, dict[str, str]]:
    suffix = uuid.uuid4().hex[:10]
    player_id = f"{prefix}_player_{suffix}"
    repository.create_user(player_id, f"{prefix}_user_{suffix}", "test-hash")
    token = f"{prefix}_token_{uuid.uuid4().hex}"
    repository.create_auth_token(
        token,
        player_id,
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
    )
    return player_id, {"Authorization": f"Bearer {token}"}


def _save_character(player_id: str, character_id: str, name: str) -> None:
    card = _character_card(character_id, name)
    assert repository.save_character_card_to_db(
        player_id,
        character_id,
        json.dumps(card),
        name=name,
        display_name=name,
    )
    character_loader.load_character_card.cache_clear()


def _app(*routers) -> FastAPI:
    app = FastAPI()
    for router in routers:
        app.include_router(router, prefix="/api/v1")
    return app


def _event_payload(
    *,
    event_id: str,
    character_id: str | None,
    keyword: str,
    notification: str,
    state_changes: dict,
    schedule: str | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "event_name": f"E2E {event_id}",
        "character_id": character_id,
        "trigger_condition": {
            "trigger_type": "time_based" if schedule else "keyword_match",
            "keywords": None if schedule else [keyword],
            "duration_minutes": 0 if schedule else None,
            "schedule": schedule,
            "cooldown_hours": 0,
        },
        "effects": [
            {
                "effect_type": "modify_state",
                "state_changes": state_changes,
            },
            {
                "effect_type": "notify_player",
                "notification_message": notification,
            },
        ],
        "schedule": schedule,
    }


def _install_inline_fastapi(monkeypatch) -> None:
    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(fastapi.routing, "run_in_threadpool", run_inline)
    monkeypatch.setattr(
        fastapi.dependencies.utils,
        "run_in_threadpool",
        run_inline,
    )


@pytest.mark.asyncio
async def test_single_dialogue_http_event_execution_persists_to_database(monkeypatch):
    _install_inline_fastapi(monkeypatch)
    monkeypatch.setattr(vector_memory, "get_vector_store", lambda: _EmptyVectorStore())
    monkeypatch.setattr(
        orchestrator.llm_client,
        "call_role_turn",
        lambda **_kwargs: {
            "dialogue": "single response",
            "action": "neutral",
            "affinity_delta": 0,
            "trust_delta": 0,
            "mood_after": "neutral",
        },
    )
    player_id, headers = _create_identity("single_e2e")
    suffix = uuid.uuid4().hex[:8]
    character_id = f"single_character_{suffix}"
    session_id = f"single_session_{suffix}"
    event_id = f"single_event_{suffix}"
    keyword = f"single-keyword-{suffix}"
    notification = f"single notification {suffix}"
    _save_character(player_id, character_id, "Single Character")
    repository.create_session(session_id, character_id, player_id, "Player")

    app = _app(event_admin_api.router, dialogue_api.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/admin/events",
            headers=headers,
            json=_event_payload(
                event_id=event_id,
                character_id=character_id,
                keyword=keyword,
                notification=notification,
                state_changes={"affection_level": 4},
            ),
        )
        assert created.status_code == 200, created.text

        response = await client.post(
            "/api/v1/dialogue/turn",
            headers=headers,
            json={
                "session_id": session_id,
                "player_message": f"please trigger {keyword}",
                "request_id": f"single-request-{suffix}",
            },
        )
        replay = await client.post(
            "/api/v1/dialogue/turn",
            headers=headers,
            json={
                "session_id": session_id,
                "player_message": f"please trigger {keyword}",
                "request_id": f"single-request-{suffix}",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_affinity"] == 4
    assert body["event_executions"][0]["event_id"] == event_id
    assert body["event_executions"][0]["status"] == "succeeded"
    assert [item["message"] for item in body["event_notifications"]] == [notification]
    assert replay.status_code == 200, replay.text
    replay_body = replay.json()
    assert replay_body == body

    runtime = repository.get_runtime_state(
        character_id,
        player_id,
        character_loader.load_character_card(character_id, player_id),
    )
    assert runtime["affection_level"] == 4
    assert len(repository.get_event_trigger_history(event_id=event_id, player_id=player_id)) == 1
    assert [item["content"] for item in repository.list_player_event_inbox(player_id)] == [
        notification
    ]
    assert [
        message["role"]
        for message in repository.get_short_term_history(session_id, limit_turns=2)
    ] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_group_dialogue_http_event_execution_persists_to_database(monkeypatch):
    _install_inline_fastapi(monkeypatch)

    def generate_response(
        self,
        character_id,
        _player_message,
        **_kwargs,
    ):
        return {
            "character_id": character_id,
            "character_name": self.character_cards[character_id].meta.display_name,
            "dialogue": "group response",
            "action": "neutral",
            "affinity_delta": 0,
            "trust_delta": 1,
            "current_affinity": 0,
            "current_trust": 11,
            "current_mood": "neutral",
            "knowledge_sources": [],
            "_previous_affinity": 0,
            "_previous_trust": 10,
        }

    monkeypatch.setattr(
        multi_character_orchestrator.MultiCharacterOrchestrator,
        "_generate_character_response",
        generate_response,
    )
    player_id, headers = _create_identity("group_e2e")
    suffix = uuid.uuid4().hex[:8]
    character_ids = [f"group_character_a_{suffix}", f"group_character_b_{suffix}"]
    session_id = f"group_session_{suffix}"
    event_id = f"group_event_{suffix}"
    keyword = f"group-keyword-{suffix}"
    notification = f"group notification {suffix}"
    for index, character_id in enumerate(character_ids):
        _save_character(player_id, character_id, f"Group Character {index}")
    assert repository.create_multi_character_session(
        session_id,
        player_id,
        "Player",
        character_ids,
    )

    app = _app(event_admin_api.router, multi_dialogue_api.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/admin/events",
            headers=headers,
            json=_event_payload(
                event_id=event_id,
                character_id=None,
                keyword=keyword,
                notification=notification,
                state_changes={"trust_level": 3},
            ),
        )
        assert created.status_code == 200, created.text

        response = await client.post(
            "/api/v1/multi-dialogue/turn",
            headers=headers,
            json={
                "session_id": session_id,
                "player_message": f"please trigger {keyword}",
                "discussion_mode": False,
                "request_id": f"group-request-{suffix}",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    speaker_id = body["character_id"]
    assert body["current_trust"] == 14
    assert body["event_executions"][0]["event_id"] == event_id
    assert body["event_executions"][0]["status"] == "succeeded"
    assert [item["message"] for item in body["event_notifications"]] == [notification]

    runtime = repository.get_runtime_state(
        speaker_id,
        player_id,
        character_loader.load_character_card(speaker_id, player_id),
    )
    assert runtime["trust_level"] == 14
    assert len(repository.get_event_trigger_history(event_id=event_id, player_id=player_id)) == 1
    assert [item["content"] for item in repository.list_player_event_inbox(player_id)] == [
        notification
    ]
    history = repository.get_multi_character_history(session_id, limit_messages=10)
    assert [message["role"] for message in history] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_scheduled_event_http_execution_persists_and_advances_schedule(monkeypatch):
    _install_inline_fastapi(monkeypatch)
    player_id, headers = _create_identity("schedule_e2e")
    suffix = uuid.uuid4().hex[:8]
    character_id = f"schedule_character_{suffix}"
    event_id = f"schedule_event_{suffix}"
    notification = f"schedule notification {suffix}"
    _save_character(player_id, character_id, "Schedule Character")

    app = _app(event_admin_api.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        created = await client.post(
            "/api/v1/admin/events",
            headers=headers,
            json=_event_payload(
                event_id=event_id,
                character_id=character_id,
                keyword="",
                notification=notification,
                state_changes={"affection_level": 7},
                schedule="* * * * *",
            ),
        )
        assert created.status_code == 200, created.text

        due_at = (datetime.now(UTC) - timedelta(minutes=2)).replace(
            second=0,
            microsecond=0,
        )
        assert repository.save_event_schedule_state(
            event_id=event_id,
            character_id=character_id,
            player_id=player_id,
            schedule="* * * * *",
            next_run_at=due_at.isoformat(),
            status="active",
        )

        response = await client.post(
            "/api/v1/admin/events/schedules/run-due",
            headers=headers,
        )
        replay = await client.post(
            "/api/v1/admin/events/schedules/run-due",
            headers=headers,
        )

    assert response.status_code == 200, response.text
    assert response.json()["triggered_count"] == 1
    assert response.json()["triggered_events"][0]["event_id"] == event_id
    assert replay.status_code == 200, replay.text
    assert replay.json()["triggered_count"] == 0

    runtime = repository.get_runtime_state(
        character_id,
        player_id,
        character_loader.load_character_card(character_id, player_id),
    )
    assert runtime["affection_level"] == 7
    assert len(repository.get_event_trigger_history(event_id=event_id, player_id=player_id)) == 1
    assert [item["content"] for item in repository.list_player_event_inbox(player_id)] == [
        notification
    ]
    schedule = repository.get_event_schedule(event_id, character_id, player_id)
    assert schedule["last_run_at"] is not None
    assert datetime.fromisoformat(schedule["next_run_at"]) > due_at
    assert schedule["lease_owner"] is None
