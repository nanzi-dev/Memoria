from __future__ import annotations

import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoria.api.event_admin import (
    UNIMPLEMENTED_EFFECTS,
    UNIMPLEMENTED_TRIGGERS,
    _validate_condition_semantics,
    _validate_effect_semantics,
)
from memoria.api.user import _hash_password
from memoria.core.config import configs
from memoria.core.event_schema import EffectType, TriggerType
from memoria.core.knowledge_documents import chunk_document, extract_document
from memoria.db import repository
from scripts.seed_graytide_demo import (
    DEFAULT_MODULE_ROOT,
    build_parser,
    load_module,
    seed_graytide_demo,
)


class FakeKnowledgeVectorStore:
    tokenizer = None

    def __init__(self):
        self.chunks: dict[str, dict] = {}
        self.deleted_documents: list[tuple[str, str]] = []
        self.deleted_bases: list[tuple[str, str]] = []

    def delete_document(self, owner_user_id, document_id):
        self.deleted_documents.append((owner_user_id, document_id))
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk["document_id"] != document_id
        }

    def delete_knowledge_base(self, owner_user_id, knowledge_base_id):
        self.deleted_bases.append((owner_user_id, knowledge_base_id))
        self.chunks = {
            chunk_id: chunk
            for chunk_id, chunk in self.chunks.items()
            if chunk["knowledge_base_id"] != knowledge_base_id
        }

    def upsert_chunks(self, chunks):
        for chunk in chunks:
            self.chunks[chunk["chunk_id"]] = dict(chunk)


@pytest.fixture
def isolated_graytide(tmp_path, monkeypatch):
    database_path = tmp_path / "memoria.db"
    storage_path = tmp_path / "knowledge"
    module_root = tmp_path / "graytide"
    shutil.copytree(DEFAULT_MODULE_ROOT, module_root)
    monkeypatch.setattr(configs, "database_url", "")
    monkeypatch.setattr(configs, "database_path", str(database_path))
    monkeypatch.setattr(configs, "knowledge_storage_path", str(storage_path))
    monkeypatch.setattr(configs, "vector_db_path", str(tmp_path / "vectors"))
    repository.init_db()
    return module_root


def _counts(owner_user_id: str) -> dict[str, int]:
    with repository.get_conn() as conn:
        tables = {
            "characters": "character_card",
            "relationships": "character_relationship",
            "events": "event_definition",
            "knowledge_bases": "knowledge_base",
            "knowledge_documents": "knowledge_document",
            "knowledge_chunks": "knowledge_chunk",
        }
        return {
            key: conn.execute(
                f"SELECT COUNT(*) AS count FROM {table} WHERE owner_user_id = ?",
                (owner_user_id,),
            ).fetchone()["count"]
            for key, table in tables.items()
        }


def _knowledge_state(owner_user_id: str) -> tuple[dict[str, str], dict[str, dict]]:
    base_ids = {}
    documents = {}
    for knowledge_base in repository.list_knowledge_bases(owner_user_id):
        base_ids[knowledge_base["name"]] = knowledge_base["knowledge_base_id"]
        for document in repository.list_knowledge_documents(
            owner_user_id, knowledge_base["knowledge_base_id"]
        ):
            documents[document["original_name"]] = document
    return base_ids, documents


def test_graytide_static_content_is_coherent():
    module = load_module()
    manifest = module["manifest"]
    character_ids = {card.character_id for _, card, _ in module["cards"]}
    event_ids = {event.event_id for event in module["events"]}

    assert len(character_ids) == 8
    assert len(module["relationships"]) == 18
    assert len(module["events"]) == 24
    assert sum(event.is_active for event in module["events"]) == 20
    assert len(manifest["knowledge_bases"]) == 4
    assert sum(len(item["documents"]) for item in manifest["knowledge_bases"]) == 8
    assert set(manifest["group"]["character_ids"]) == character_ids

    relationship_pairs = set()
    for relationship in module["relationships"]:
        left = relationship["character_id_a"]
        right = relationship["character_id_b"]
        assert left in character_ids
        assert right in character_ids
        assert left != right
        assert -100 <= relationship["affinity"] <= 100
        pair = tuple(sorted((left, right)))
        assert pair not in relationship_pairs
        relationship_pairs.add(pair)

    disabled_extension_count = 0
    for event in module["events"]:
        if event.character_id:
            assert event.character_id in character_ids
        if event.trigger_condition.event_id:
            assert event.trigger_condition.event_id in event_ids
        if event.trigger_condition.trigger_type in UNIMPLEMENTED_TRIGGERS:
            assert not event.is_active
            disabled_extension_count += 1
        for effect in event.effects:
            if effect.next_event_id:
                assert effect.next_event_id in event_ids
            if effect.target_character_id:
                assert effect.target_character_id in character_ids
            if effect.proactive_character_id:
                assert effect.proactive_character_id in character_ids
            if effect.effect_type in UNIMPLEMENTED_EFFECTS:
                assert not event.is_active
    assert disabled_extension_count == 3
    assert {
        TriggerType.KEYWORD_MATCH,
        TriggerType.NPC_KEYWORD_MATCH,
        TriggerType.TRUST_THRESHOLD,
        TriggerType.AFFINITY_THRESHOLD,
        TriggerType.DIALOGUE_COUNT,
        TriggerType.TIME_BASED,
        TriggerType.MOOD_MATCH,
        TriggerType.STATE_DELTA,
        TriggerType.EVENT_HISTORY,
        TriggerType.WORLD_TIME_WINDOW,
        TriggerType.COMPOSITE,
    }.issubset({event.trigger_condition.trigger_type for event in module["events"]})
    assert {
        EffectType.ADD_MEMORY,
        EffectType.MODIFY_STATE,
        EffectType.UNLOCK_CONTENT,
        EffectType.TRIGGER_EVENT,
        EffectType.NPC_PROACTIVE_DIALOGUE,
        EffectType.UPDATE_EVENT_PROGRESS,
    }.issubset(
        {effect.effect_type for event in module["events"] for effect in event.effects}
    )

    document_names = set()
    for knowledge_base in manifest["knowledge_bases"]:
        for relative_path in knowledge_base["documents"]:
            path = module["root"] / relative_path
            extracted = extract_document(path.name, path.read_bytes())
            assert chunk_document(extracted, document_title=path.name)
            document_names.add(path.name)
    evaluations = json.loads(
        (module["root"] / "retrieval_eval.json").read_text(encoding="utf-8")
    )
    assert len(evaluations) == 10
    for evaluation in evaluations:
        assert evaluation["expected_facts"]
        assert set(evaluation["expected_documents"]).issubset(document_names)
    assert "--skip-knowledge-index" in build_parser().format_help()


def test_graytide_seed_is_idempotent_replaceable_and_isolated(isolated_graytide):
    module = load_module(isolated_graytide)
    other_user_id = "usr_other_graytide"
    repository.create_user(
        other_user_id,
        "graytide_other",
        _hash_password("Otherpass1"),
    )
    _, other_card, other_raw = module["cards"][0]
    assert repository.save_character_card_to_db(
        other_user_id,
        other_card.character_id,
        json.dumps(other_raw, ensure_ascii=False),
        version=other_card.version,
        name=other_card.meta.name,
        display_name=other_card.meta.display_name,
        source="isolation-fixture",
    )

    vector_store = FakeKnowledgeVectorStore()
    first = seed_graytide_demo(
        password="Demopass1",
        module_root=isolated_graytide,
        vector_store=vector_store,
    )
    owner_user_id = first["user_id"]
    assert first["created_user"] is True
    assert _counts(owner_user_id) == {
        "characters": 8,
        "relationships": 18,
        "events": 24,
        "knowledge_bases": 4,
        "knowledge_documents": 8,
        "knowledge_chunks": len(vector_store.chunks),
    }
    assert _counts(owner_user_id)["knowledge_chunks"] > 8
    first_base_ids, first_documents = _knowledge_state(owner_user_id)
    assert all(document["status"] == "ready" for document in first_documents.values())

    for event in module["events"]:
        if not event.is_active:
            continue
        _validate_condition_semantics(event.trigger_condition, owner_user_id)
        for effect in event.effects:
            _validate_effect_semantics(effect, owner_user_id)

    second = seed_graytide_demo(
        module_root=isolated_graytide,
        vector_store=vector_store,
    )
    second_base_ids, second_documents = _knowledge_state(owner_user_id)
    assert second["created_user"] is False
    assert second_base_ids == first_base_ids
    assert {
        name: document["document_id"]
        for name, document in second_documents.items()
    } == {
        name: document["document_id"]
        for name, document in first_documents.items()
    }
    assert _counts(owner_user_id)["events"] == 24

    changed_path = isolated_graytide / "knowledge" / "city_and_geography.md"
    changed_path.write_text(
        changed_path.read_text(encoding="utf-8")
        + "\n\n## 测试附记\n\n蓝灯压力罐编号为 GT-13。\n",
        encoding="utf-8",
    )
    old_document_id = first_documents["city_and_geography.md"]["document_id"]
    seed_graytide_demo(
        module_root=isolated_graytide,
        vector_store=vector_store,
    )
    _, changed_documents = _knowledge_state(owner_user_id)
    changed_document = changed_documents["city_and_geography.md"]
    assert changed_document["document_id"] != old_document_id
    assert (owner_user_id, old_document_id) in vector_store.deleted_documents
    assert changed_document["status"] == "ready"
    assert _counts(owner_user_id)["knowledge_documents"] == 8

    reset_result = seed_graytide_demo(
        module_root=isolated_graytide,
        vector_store=vector_store,
        reset_module=True,
    )
    assert reset_result["group_thread_id"] == "graytide_investigation_thread"
    assert _counts(owner_user_id)["characters"] == 8
    assert _counts(owner_user_id)["events"] == 24
    assert repository.get_character_card_from_db(
        other_user_id,
        other_card.character_id,
        include_inactive=True,
    )

    binding_types = set()
    binding_targets = set()
    for knowledge_base in repository.list_knowledge_bases(owner_user_id):
        for binding in repository.list_knowledge_bindings(
            owner_user_id, knowledge_base["knowledge_base_id"]
        ):
            binding_types.add(binding["target_type"])
            binding_targets.add((binding["target_type"], binding["target_id"]))
    assert binding_types == {"global", "character", "group_thread"}
    assert (
        "group_thread",
        "graytide_investigation_thread",
    ) in binding_targets
