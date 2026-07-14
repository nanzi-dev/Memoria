"""API-level ownership and data-integrity regression tests."""

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _event_row(character_id="c1"):
    return {
        "event_id": "evt_test",
        "event_name": "Test event",
        "description": None,
        "character_id": character_id,
        "trigger_config": '{"trigger_type":"keyword_match","keywords":["test"]}',
        "effects_config": "[]",
        "priority": 0,
        "is_active": 1,
        "schedule": None,
        "template_id": None,
    }


def test_create_event_rejects_character_not_owned_by_user(monkeypatch):
    from memoria.api import event_admin

    monkeypatch.setattr(event_admin.repository, "get_event_definition", lambda *args: None)
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: pytest.fail("invalid event must not be saved"),
    )

    request = event_admin.EventCreateRequest(
        event_id="evt_test",
        event_name="Test event",
        character_id="foreign-character",
        trigger_condition=event_admin.TriggerConditionDTO(
            trigger_type="keyword_match",
            keywords=["test"],
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.create_event(request, current_user_id="user-1")

    assert exc_info.value.status_code == 404


def test_create_event_uses_condition_schedule_when_top_level_is_blank(monkeypatch):
    from memoria.api import event_admin

    saved = {}
    monkeypatch.setattr(event_admin.repository, "get_event_definition", lambda *args: None)
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "c1"},
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: saved.update(kwargs) or True,
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "build_time_event_schedule_state",
        lambda **kwargs: kwargs,
    )

    response = event_admin.create_event(
        event_admin.EventCreateRequest(
            event_id="evt_scheduled",
            event_name="Scheduled event",
            character_id="c1",
            schedule="   ",
            trigger_condition=event_admin.TriggerConditionDTO(
                trigger_type="time_based",
                schedule="0 9 * * *",
            ),
        ),
        current_user_id="user-1",
    )

    assert response.success is True
    assert saved["schedule"] == "0 9 * * *"
    assert saved["schedule_state"]["schedule"] == "0 9 * * *"
    assert saved["schedule_state"]["status"] == "active"


def test_update_event_persists_changed_character(monkeypatch):
    from memoria.api import event_admin

    saved = {}
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: {
            "character_id": character_id,
        },
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: saved.update(kwargs) or True,
    )

    response = event_admin.update_event(
        "evt_test",
        event_admin.EventUpdateRequest(character_id="c2"),
        current_user_id="user-1",
    )

    assert response.success is True
    assert saved["character_id"] == "c2"


def test_update_event_uses_condition_schedule_when_top_level_is_blank(monkeypatch):
    from memoria.api import event_admin

    saved = {}
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: saved.update(kwargs) or True,
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "build_time_event_schedule_state",
        lambda **kwargs: kwargs,
    )

    response = event_admin.update_event(
        "evt_test",
        event_admin.EventUpdateRequest(
            schedule="",
            trigger_condition=event_admin.TriggerConditionDTO(
                trigger_type="time_based",
                schedule="30 8 * * 1-5",
            ),
        ),
        current_user_id="user-1",
    )

    assert response.success is True
    assert saved["schedule"] == "30 8 * * 1-5"
    assert saved["schedule_state"]["schedule"] == "30 8 * * 1-5"
    assert saved["schedule_state"]["status"] == "active"


def test_update_event_can_clear_character_for_global_event(monkeypatch):
    from memoria.api import event_admin

    saved = {}
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: saved.update(kwargs) or True,
    )

    event_admin.update_event(
        "evt_test",
        event_admin.EventUpdateRequest(character_id=None),
        current_user_id="user-1",
    )

    assert saved["character_id"] is None
    assert saved["schedule_state"] is None


def test_toggle_event_atomically_pauses_definition_and_schedule(monkeypatch):
    from memoria.api import event_admin

    saved = {}
    existing = _event_row()
    existing["schedule"] = "0 9 * * *"
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: existing,
    )
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: saved.update(kwargs) or True,
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "build_time_event_schedule_state",
        lambda **kwargs: kwargs,
    )

    response = event_admin.toggle_event(
        "evt_test",
        active=False,
        current_user_id="user-1",
    )

    assert response.success is True
    assert saved["is_active"] is False
    assert saved["schedule_state"]["status"] == "paused"


def test_register_event_schedule_rejects_unknown_character(monkeypatch):
    from memoria.api import event_admin

    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "register_time_event_schedule",
        lambda **kwargs: pytest.fail("invalid schedule must not be registered"),
    )

    request = event_admin.ScheduleRegisterRequest(
        event_id="evt_test",
        character_id="missing",
        player_id="user-1",
        schedule="0 9 * * *",
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.register_event_schedule(request, current_user_id="user-1")

    assert exc_info.value.status_code == 404


@pytest.mark.parametrize("schedule", ["99 * * * *", "*/0 * * * *"])
def test_register_event_schedule_rejects_invalid_cron(monkeypatch, schedule):
    from memoria.api import event_admin

    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "c1"},
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "register_time_event_schedule",
        lambda **kwargs: pytest.fail("invalid cron must not be registered"),
    )

    request = event_admin.ScheduleRegisterRequest(
        event_id="evt_test",
        character_id="c1",
        player_id="user-1",
        schedule=schedule,
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.register_event_schedule(request, current_user_id="user-1")

    assert exc_info.value.status_code == 400


def test_register_event_schedule_rejects_mismatched_event_character(monkeypatch):
    from memoria.api import event_admin

    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(character_id="c1"),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: {
            "character_id": character_id,
        },
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "register_time_event_schedule",
        lambda **kwargs: pytest.fail("mismatched character must not be registered"),
    )

    request = event_admin.ScheduleRegisterRequest(
        event_id="evt_test",
        character_id="c2",
        player_id="user-1",
        schedule="0 9 * * *",
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.register_event_schedule(request, current_user_id="user-1")

    assert exc_info.value.status_code == 400


def test_register_event_schedule_reports_repository_failure(monkeypatch):
    from memoria.api import event_admin

    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "c1"},
    )
    monkeypatch.setattr(
        event_admin.event_runtime,
        "register_time_event_schedule",
        lambda **kwargs: False,
    )

    request = event_admin.ScheduleRegisterRequest(
        event_id="evt_test",
        character_id="c1",
        player_id="user-1",
        schedule="0 9 * * *",
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.register_event_schedule(request, current_user_id="user-1")

    assert exc_info.value.status_code == 500


def test_event_simulation_plans_without_committing(monkeypatch):
    from memoria.api import event_admin

    row = _event_row(character_id="c1")
    row["effects_config"] = (
        '[{"effect_type":"notify_player","notification_message":"planned"}]'
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: row,
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_character_card_from_db",
        lambda *args, **kwargs: {"character_id": "c1"},
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_context_state",
        lambda *args: None,
    )
    monkeypatch.setattr(
        event_admin.repository,
        "commit_event_execution_batch",
        lambda **kwargs: pytest.fail("simulation must not commit event effects"),
    )

    result = event_admin.simulate_event(
        "evt_test",
        event_admin.EventSimulationRequest(
            character_id="c1",
            player_message="test",
            current_affinity=10,
            current_trust=20,
        ),
        current_user_id="user-1",
    )

    assert result.matched is True
    assert result.planned_result["notifications"][0]["message"] == "planned"
    assert result.planned_result["status"] == "succeeded"


@pytest.mark.parametrize(
    ("trigger", "effects", "expected_detail"),
    [
        (
            {"trigger_type": "keyword_match", "keywords": ["["] , "match_mode": "regex"},
            [],
            "正则表达式无效",
        ),
        (
            {"trigger_type": "item_acquired"},
            [],
            "尚未实现",
        ),
        (
            {"trigger_type": "keyword_match", "keywords": ["test"]},
            [{"effect_type": "grant_item", "item_id": "item-1"}],
            "尚未实现",
        ),
    ],
)
def test_create_event_rejects_invalid_or_unimplemented_configuration(
    monkeypatch,
    trigger,
    effects,
    expected_detail,
):
    from memoria.api import event_admin

    monkeypatch.setattr(event_admin.repository, "get_event_definition", lambda *args: None)
    monkeypatch.setattr(
        event_admin.repository,
        "save_event_definition_with_schedule",
        lambda **kwargs: pytest.fail("invalid event must not be saved"),
    )
    request = event_admin.EventCreateRequest(
        event_id="evt_invalid",
        event_name="Invalid event",
        trigger_condition=event_admin.TriggerConditionDTO(**trigger),
        effects=[event_admin.EventEffectDTO(**effect) for effect in effects],
    )

    with pytest.raises(HTTPException) as exc_info:
        event_admin.create_event(request, current_user_id="user-1")

    assert exc_info.value.status_code == 400
    assert expected_detail in exc_info.value.detail


def test_schedule_pause_resume_and_delete_lifecycle(monkeypatch):
    from memoria.api import event_admin

    statuses = []
    deleted = []
    schedule_state = {
        "event_id": "evt_test",
        "character_id": "c1",
        "player_id": "user-1",
        "schedule": "0 9 * * *",
        "status": "active",
    }
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_definition",
        lambda *args: _event_row(),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "get_event_schedule",
        lambda *args: schedule_state,
    )
    monkeypatch.setattr(
        event_admin.repository,
        "set_event_schedule_status",
        lambda event_id, character_id, player_id, status, **kwargs: (
            statuses.append((status, kwargs.get("next_run_at"))) or True
        ),
    )
    monkeypatch.setattr(
        event_admin.repository,
        "delete_event_definition",
        lambda owner_user_id, event_id: (
            deleted.append((owner_user_id, event_id)) or True
        ),
    )

    paused = event_admin.pause_event_schedule("evt_test", "c1", "user-1")
    resumed = event_admin.resume_event_schedule("evt_test", "c1", "user-1")
    removed = event_admin.delete_event("evt_test", current_user_id="user-1")

    assert paused.success and resumed.success and removed.success
    assert statuses[0] == ("paused", None)
    assert statuses[1][0] == "active"
    assert statuses[1][1]
    assert deleted == [("user-1", "evt_test")]


def _relationship_request(character_id_a="c1", character_id_b="c2"):
    from memoria.api import relationship

    return relationship.RelationshipCreateRequest(
        character_id_a=character_id_a,
        character_id_b=character_id_b,
        relationship_type="friend",
        affinity=20,
    )


def test_create_relationship_rejects_self_relationship():
    from memoria.api import relationship

    with pytest.raises(HTTPException) as exc_info:
        relationship.create_relationship(
            _relationship_request("c1", "c1"),
            current_user_id="user-1",
        )

    assert exc_info.value.status_code == 400


def test_create_relationship_rejects_missing_character(monkeypatch):
    from memoria.api import relationship

    monkeypatch.setattr(
        relationship.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: (
            {"character_id": character_id} if character_id == "c1" else None
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        relationship.create_relationship(
            _relationship_request(),
            current_user_id="user-1",
        )

    assert exc_info.value.status_code == 404


def test_create_relationship_returns_conflict_for_duplicate(monkeypatch):
    from memoria.api import relationship

    monkeypatch.setattr(
        relationship.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: {
            "character_id": character_id,
        },
    )
    monkeypatch.setattr(
        relationship.repository,
        "get_character_relationship",
        lambda *args: {"id": 1},
    )

    with pytest.raises(HTTPException) as exc_info:
        relationship.create_relationship(
            _relationship_request(),
            current_user_id="user-1",
        )

    assert exc_info.value.status_code == 409


def test_delete_relationship_returns_not_found_when_absent(monkeypatch):
    from memoria.api import relationship

    monkeypatch.setattr(
        relationship.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: {
            "character_id": character_id,
        },
    )
    monkeypatch.setattr(
        relationship.repository,
        "get_character_relationship",
        lambda *args: None,
    )
    monkeypatch.setattr(
        relationship.repository,
        "delete_character_relationship",
        lambda *args: pytest.fail("missing relationship must not be deleted"),
    )

    with pytest.raises(HTTPException) as exc_info:
        relationship.delete_relationship("c1", "c2", current_user_id="user-1")

    assert exc_info.value.status_code == 404


def test_batch_relationship_success_reflects_actual_writes(monkeypatch):
    from memoria.api import relationship

    monkeypatch.setattr(
        relationship.repository,
        "get_character_card_from_db",
        lambda owner_user_id, character_id, include_inactive=False: {
            "character_id": character_id,
        },
    )
    monkeypatch.setattr(
        relationship.repository,
        "get_character_relationship",
        lambda *args: None,
    )
    monkeypatch.setattr(
        relationship.repository,
        "save_character_relationship",
        lambda **kwargs: True,
    )

    mixed = relationship.batch_create_relationships(
        [_relationship_request(), _relationship_request("c3", "c3")],
        current_user_id="user-1",
    )
    all_invalid = relationship.batch_create_relationships(
        [_relationship_request("c3", "c3")],
        current_user_id="user-1",
    )

    assert mixed.success is True
    assert "成功 1 条，失败 1 条" in mixed.message
    assert all_invalid.success is False
