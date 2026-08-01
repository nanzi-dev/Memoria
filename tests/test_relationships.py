from __future__ import annotations

import uuid

from sqlalchemy import select

from memoria.db import repository
from memoria.db.models import CharacterRelationshipRevision, RelationshipState


def _user_id() -> str:
    user_id = f"usr_{uuid.uuid4().hex[:10]}"
    repository.create_user(user_id, f"user_{uuid.uuid4().hex[:8]}", "test-hash")
    return user_id


def test_touch_character_relationship_revision_uses_named_params_in_transaction():
    owner_user_id = _user_id()
    character_id_a = f"npc_{uuid.uuid4().hex[:8]}"
    character_id_b = f"npc_{uuid.uuid4().hex[:8]}"

    with repository.db_session() as conn:
        repository._touch_character_relationship_revision(
            conn,
            owner_user_id=owner_user_id,
            character_id_a=character_id_a,
            character_id_b=character_id_b,
            updated_at="2026-01-01T00:00:00+00:00",
        )

    assert repository.get_character_relationship_updated_at(
        owner_user_id,
        character_id_a,
        character_id_b,
    ) == "2026-01-01T00:00:00+00:00"

    with repository.db_session() as conn:
        repository._touch_character_relationship_revision(
            conn,
            owner_user_id=owner_user_id,
            character_id_a=character_id_b,
            character_id_b=character_id_a,
            updated_at="2026-01-02T00:00:00+00:00",
        )

    assert repository.get_character_relationship_updated_at(
        owner_user_id,
        character_id_a,
        character_id_b,
    ) == "2026-01-02T00:00:00+00:00"

    with repository.db_session() as session:
        rows = session.execute(
            select(CharacterRelationshipRevision).where(
                CharacterRelationshipRevision.owner_user_id == owner_user_id,
                (
                    (
                        (CharacterRelationshipRevision.character_id_a == character_id_a)
                        & (CharacterRelationshipRevision.character_id_b == character_id_b)
                    )
                    | (
                        (CharacterRelationshipRevision.character_id_a == character_id_b)
                        & (CharacterRelationshipRevision.character_id_b == character_id_a)
                    )
                ),
            )
        ).scalars().all()

    assert len(rows) == 1
    assert rows[0].updated_at == "2026-01-02T00:00:00+00:00"


def test_sync_runtime_affection_from_player_edge_upserts_affection_level():
    owner_user_id = _user_id()
    player_id = repository.player_node_id(owner_user_id)
    character_id = f"npc_{uuid.uuid4().hex[:8]}"

    with repository.db_session() as conn:
        repository._sync_runtime_affection_from_player_edge(
            conn,
            owner_user_id=owner_user_id,
            character_id_a=player_id,
            character_id_b=character_id,
            affinity=42.0,
            now="2026-01-01T00:00:00+00:00",
        )
        repository._sync_runtime_affection_from_player_edge(
            conn,
            owner_user_id=owner_user_id,
            character_id_a=player_id,
            character_id_b=character_id,
            affinity=87.0,
            now="2026-01-02T00:00:00+00:00",
        )

    with repository.db_session() as session:
        state = session.execute(
            select(RelationshipState).where(
                RelationshipState.character_id == character_id,
                RelationshipState.player_id == owner_user_id,
            )
        ).scalar_one()

    assert state.affection_level == 87.0
    assert state.updated_at == "2026-01-02T00:00:00+00:00"
