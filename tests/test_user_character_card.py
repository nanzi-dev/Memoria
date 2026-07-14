from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from memoria.db import repository


def _create_user(prefix: str = "persona") -> tuple[str, str]:
    user_id = f"{prefix}_{uuid.uuid4().hex[:10]}"
    username = f"{prefix}_{uuid.uuid4().hex[:8]}"
    repository.create_user(user_id, username, "test-hash", "female")
    return user_id, username


def test_create_user_creates_default_character_card():
    user_id, username = _create_user()

    card = repository.get_user_character_card(user_id)

    assert card is not None
    assert card["display_name"] == username
    assert card["gender"] == "female"
    assert card["avatar_url"] is None
    assert repository.player_node_id(user_id) == f"player:{user_id}"
    assert repository.is_player_node_id(repository.player_node_id(user_id))


def test_character_card_update_keeps_account_avatar_independent():
    user_id, _ = _create_user()
    repository.update_user_profile(user_id, avatar_url="data:image/png;base64,account")

    card = repository.update_user_character_card(
        user_id,
        {
            "display_name": "星野",
            "avatar_url": "data:image/png;base64,persona",
            "pronouns": "她/她",
            "age": 27,
            "species": "人类",
            "occupation": "档案修复师",
            "appearance": "银灰短发，左眼有一道浅色伤痕。",
            "personality": "谨慎、敏锐，但对弱者温和。",
            "background": "来自旧城区的档案馆。",
            "goals": "找回失落的家族记录。",
        },
    )

    assert card is not None
    assert card["display_name"] == "星野"
    assert card["age"] == 27
    assert repository.get_user_by_id(user_id)["avatar_url"] == "data:image/png;base64,account"
    assert repository.get_user_character_card(user_id)["avatar_url"] == "data:image/png;base64,persona"


def test_runtime_affection_creates_player_edge_without_touching_semantic_revision():
    user_id, _ = _create_user()
    character_id = f"npc_{uuid.uuid4().hex[:8]}"
    repository.save_character_card_to_db(
        user_id,
        character_id,
        json.dumps({"character_id": character_id, "meta": {"name": "守门人"}}),
        name="守门人",
        display_name="守门人",
    )

    repository.save_runtime_state(character_id, user_id, 35, 22, "curious")
    player_id = repository.player_node_id(user_id)
    relationship = repository.get_character_relationship(
        user_id,
        player_id,
        character_id,
    )

    assert relationship is not None
    assert relationship["relationship_type"] == "相识"
    assert relationship["affinity"] == 35
    assert repository.get_character_relationship_updated_at(
        user_id,
        player_id,
        character_id,
    ) is None

    assert repository.save_character_relationship(
        user_id,
        player_id,
        character_id,
        "盟友",
        61,
        "共同守护旧城门",
    )
    revision = repository.get_character_relationship_updated_at(
        user_id,
        player_id,
        character_id,
    )
    with repository.get_conn() as conn:
        runtime = conn.execute(
            """
            SELECT affection_level, trust_level, current_mood
            FROM relationship_state
            WHERE character_id = ? AND player_id = ?
            """,
            (character_id, user_id),
        ).fetchone()
    assert runtime["affection_level"] == 61
    assert runtime["trust_level"] == 22
    assert runtime["current_mood"] == "curious"

    repository.save_runtime_state(character_id, user_id, 72, 29, "warm")
    assert repository.get_character_relationship(
        user_id,
        player_id,
        character_id,
    )["affinity"] == 72
    assert repository.get_character_relationship_updated_at(
        user_id,
        player_id,
        character_id,
    ) == revision


def test_deleting_player_edge_resets_affection_and_next_chat_recreates_it():
    user_id, _ = _create_user()
    character_id = f"npc_{uuid.uuid4().hex[:8]}"
    player_id = repository.player_node_id(user_id)
    repository.save_runtime_state(character_id, user_id, 48, 31, "hopeful")

    assert repository.delete_character_relationship(user_id, player_id, character_id)
    with repository.get_conn() as conn:
        runtime = conn.execute(
            """
            SELECT affection_level, trust_level, current_mood
            FROM relationship_state
            WHERE character_id = ? AND player_id = ?
            """,
            (character_id, user_id),
        ).fetchone()
    assert runtime["affection_level"] == 0
    assert runtime["trust_level"] == 31
    assert runtime["current_mood"] == "hopeful"

    repository.save_runtime_state(character_id, user_id, 4, 31, "hopeful")
    recreated = repository.get_character_relationship(
        user_id,
        player_id,
        character_id,
    )
    assert recreated["relationship_type"] == "相识"
    assert recreated["affinity"] == 4


def test_relationship_validation_rejects_foreign_player_node():
    from memoria.api.relationship import _require_relationship_characters

    with pytest.raises(HTTPException) as exc_info:
        _require_relationship_characters(
            "usr_owner",
            repository.player_node_id("usr_other"),
            "npc",
        )

    assert exc_info.value.status_code == 403


def test_relationship_network_always_contains_isolated_player_node():
    from memoria.api.relationship import get_relationship_network

    user_id, _ = _create_user()
    repository.update_user_character_card(
        user_id,
        {"display_name": "无名旅人", "avatar_url": "data:image/png;base64,role"},
    )

    network = get_relationship_network(current_user_id=user_id)

    assert network.edges == []
    assert len(network.nodes) == 1
    assert network.nodes[0].character_id == repository.player_node_id(user_id)
    assert network.nodes[0].node_type == "player"
    assert network.nodes[0].name == "无名旅人"
