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
        "save_event_definition",
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
        "save_event_definition",
        lambda **kwargs: saved.update(kwargs) or True,
    )

    response = event_admin.update_event(
        "evt_test",
        event_admin.EventUpdateRequest(character_id="c2"),
        current_user_id="user-1",
    )

    assert response.success is True
    assert saved["character_id"] == "c2"


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
        "save_event_definition",
        lambda **kwargs: saved.update(kwargs) or True,
    )

    event_admin.update_event(
        "evt_test",
        event_admin.EventUpdateRequest(character_id=None),
        current_user_id="user-1",
    )

    assert saved["character_id"] is None


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
