"""Tests for the implemented relationship event types."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException

from memoria.api.event_admin import (
    EventEffectDTO,
    TriggerConditionDTO,
    _validate_event_configuration,
)
from memoria.core import event_runtime
from memoria.core.event_detector import EventDetector
from memoria.core.event_schema import (
    EffectType,
    EventContext,
    EventDefinition,
    EventEffect,
    TriggerCondition,
    TriggerType,
)
from memoria.db import repository


def _create_player(player_id: str) -> str:
    repository.create_user(player_id, f"user_{player_id}", "test-hash")
    return player_id


def _save_event(player_id: str, event: EventDefinition) -> None:
    assert repository.save_event_definition(
        owner_user_id=player_id,
        event_id=event.event_id,
        event_name=event.event_name,
        trigger_config=event.trigger_condition.model_dump_json(),
        effects_config=json.dumps(
            [effect.model_dump(mode="json") for effect in event.effects],
            ensure_ascii=False,
        ),
        character_id=event.character_id,
        priority=event.priority,
        is_active=event.is_active,
    )


def _make_context(
    player_id: str, character_id: str = "npc_luo_xiaohei"
) -> EventContext:
    return EventContext(
        character_id=character_id,
        player_id=player_id,
        session_id=f"session:{uuid.uuid4().hex[:8]}",
        current_affinity=10,
        current_trust=10,
        current_mood="neutral",
        player_message="测试",
        dialogue_count=1,
        total_dialogue_count=1,
        session_duration_minutes=0,
    )


def _direct_event(
    event_id: str,
    *,
    character_id: str | None,
    effects: list[EventEffect],
) -> EventDefinition:
    return EventDefinition(
        event_id=event_id,
        event_name=event_id,
        character_id=character_id,
        trigger_condition=TriggerCondition(
            trigger_type=TriggerType.KEYWORD_MATCH,
            keywords=["测试"],
        ),
        effects=effects,
    )


def test_modify_relationship_updates_graph_and_player_edge():
    player_id = _create_player(f"p_rel_{uuid.uuid4().hex[:8]}")
    character_id = "npc_luo_xiaohei"
    npc_target = "npc_wuxian"
    player_node = repository.player_node_id(player_id)

    repository.save_character_relationship(
        player_id,
        character_id,
        npc_target,
        relationship_type="ally",
        affinity=10,
    )
    repository.save_character_relationship(
        player_id,
        player_node,
        character_id,
        relationship_type="acquaintance",
        affinity=20,
    )

    npc_event = _direct_event(
        f"evt_rel_npc_{uuid.uuid4().hex[:8]}",
        character_id=character_id,
        effects=[
            EventEffect(
                effect_type=EffectType.MODIFY_RELATIONSHIP,
                target_character_id=npc_target,
                relationship_change={"affinity_delta": 5, "relationship_type": "rival"},
            )
        ],
    )
    _save_event(player_id, npc_event)
    result = event_runtime.execute_event_with_chain(
        npc_event,
        _make_context(player_id, character_id),
    )[0]
    assert result.status == "succeeded"

    rel = repository.get_character_relationship(player_id, character_id, npc_target)
    assert rel["affinity"] == 15
    assert rel["relationship_type"] == "rival"

    player_event = _direct_event(
        f"evt_rel_player_{uuid.uuid4().hex[:8]}",
        character_id=character_id,
        effects=[
            EventEffect(
                effect_type=EffectType.MODIFY_RELATIONSHIP,
                target_character_id="@player",
                relationship_change={"affinity_delta": -3},
            )
        ],
    )
    _save_event(player_id, player_event)
    event_runtime.execute_event_with_chain(
        player_event,
        _make_context(player_id, character_id),
    )
    rel = repository.get_character_relationship(player_id, player_node, character_id)
    assert rel["affinity"] == 17

    from memoria.core.character_loader import load_character_card

    runtime = repository.get_runtime_state(
        character_id,
        player_id,
        load_character_card(character_id),
    )
    assert runtime["affection_level"] == 17


def test_relationship_change_trigger_checks_graph():
    player_id = _create_player(f"p_rel_trigger_{uuid.uuid4().hex[:8]}")
    character_id = "npc_luo_xiaohei"
    target_id = "npc_wuxian"

    repository.save_character_relationship(
        player_id,
        character_id,
        target_id,
        relationship_type="ally",
        affinity=30,
    )
    event = _direct_event(
        f"evt_rel_trigger_{uuid.uuid4().hex[:8]}",
        character_id=character_id,
        effects=[],
    )
    event.trigger_condition = TriggerCondition(
        trigger_type=TriggerType.RELATIONSHIP_CHANGE,
        target_character_id=target_id,
        state_field="affinity",
        threshold=25,
        comparison="gte",
    )
    assert EventDetector().check_events(_make_context(player_id, character_id), [event])

    event.trigger_condition = TriggerCondition(
        trigger_type=TriggerType.RELATIONSHIP_CHANGE,
        target_character_id=target_id,
        state_field="relationship_type",
        relationship_type="ally",
    )
    assert EventDetector().check_events(_make_context(player_id, character_id), [event])

    event.trigger_condition = TriggerCondition(
        trigger_type=TriggerType.RELATIONSHIP_CHANGE,
        target_character_id=target_id,
        state_field="relationship_type",
        relationship_type="enemy",
    )
    assert not EventDetector().check_events(
        _make_context(player_id, character_id),
        [event],
    )

    # @player 别名解析为当前玩家的 player:<user_id> 节点。
    repository.save_character_relationship(
        player_id,
        repository.player_node_id(player_id),
        character_id,
        relationship_type="friend",
        affinity=40,
    )
    event.trigger_condition = TriggerCondition(
        trigger_type=TriggerType.RELATIONSHIP_CHANGE,
        target_character_id="@player",
        state_field="affinity",
        threshold=35,
        comparison="gte",
    )
    assert EventDetector().check_events(
        _make_context(player_id, character_id),
        [event],
    )


def test_relationship_change_condition_defaults_to_player_edge():
    player_id = _create_player(f"p_rel_default_{uuid.uuid4().hex[:8]}")
    character_id = "npc_luo_xiaohei"
    repository.save_character_relationship(
        player_id,
        repository.player_node_id(player_id),
        character_id,
        relationship_type="friend",
        affinity=40,
    )
    event = _direct_event(
        f"evt_rel_default_{uuid.uuid4().hex[:8]}",
        character_id=character_id,
        effects=[],
    )
    event.trigger_condition = TriggerCondition(
        trigger_type=TriggerType.RELATIONSHIP_CHANGE,
        state_field="affinity",
        threshold=35,
        comparison="gte",
    )
    assert EventDetector().check_events(
        _make_context(player_id, character_id),
        [event],
    )

    condition, effects = _validate_event_configuration(
        TriggerConditionDTO(
            trigger_type="relationship_change",
            state_field="affinity",
            threshold=35,
        ),
        [
            EventEffectDTO(
                effect_type="modify_relationship",
                target_character_id="@player",
                relationship_change={"affinity_delta": 1},
            )
        ],
        player_id,
    )
    assert condition.target_character_id is None
    assert effects[0].target_character_id == "@player"


def test_event_admin_accepts_implemented_relationship_configuration():
    owner_user_id = _create_player(f"p_admin_rel_{uuid.uuid4().hex[:8]}")
    repository.save_character_relationship(
        owner_user_id,
        "npc_luo_xiaohei",
        "npc_wuxian",
        relationship_type="ally",
        affinity=0,
    )
    repository.save_character_card_to_db(
        owner_user_id=owner_user_id,
        character_id="npc_luo_xiaohei",
        card_data_json=json.dumps({"name": "小黑"}),
    )
    repository.save_character_card_to_db(
        owner_user_id=owner_user_id,
        character_id="npc_wuxian",
        card_data_json=json.dumps({"name": "无限"}),
    )

    condition, effects = _validate_event_configuration(
        TriggerConditionDTO(
            trigger_type="relationship_change",
            target_character_id="npc_wuxian",
            state_field="affinity",
            threshold=1,
        ),
        [
            EventEffectDTO(
                effect_type="modify_relationship",
                target_character_id="npc_wuxian",
                relationship_change={"affinity": 1},
            )
        ],
        owner_user_id,
    )
    assert condition.trigger_type == TriggerType.RELATIONSHIP_CHANGE
    assert effects[0].effect_type == EffectType.MODIFY_RELATIONSHIP


def test_event_admin_keeps_reserved_item_and_quest_types_rejected():
    owner_user_id = _create_player(f"p_admin_reserved_{uuid.uuid4().hex[:8]}")
    for trigger in ("item_acquired", "quest_completed"):
        with pytest.raises(HTTPException, match="尚未实现"):
            _validate_event_configuration(
                TriggerConditionDTO(trigger_type=trigger),
                [],
                owner_user_id,
            )
    for effect in ("grant_item", "start_quest"):
        with pytest.raises(HTTPException, match="尚未实现"):
            _validate_event_configuration(
                TriggerConditionDTO(
                    trigger_type="keyword_match",
                    keywords=["测试"],
                ),
                [EventEffectDTO(effect_type=effect)],
                owner_user_id,
            )
