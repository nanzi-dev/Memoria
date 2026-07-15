from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memoria.api.user import _hash_password
from memoria.core.config import configs
from memoria.db import repository
from scripts.seed_graytide_demo import DEFAULT_MODULE_ROOT


def _story_module_api():
    try:
        return importlib.import_module("scripts.seed_story_module")
    except ModuleNotFoundError:
        pytest.fail("scripts.seed_story_module has not been implemented")


@pytest.fixture
def isolated_story_module(tmp_path, monkeypatch):
    database_path = tmp_path / "memoria.db"
    storage_path = tmp_path / "knowledge"
    module_root = tmp_path / "story"
    shutil.copytree(DEFAULT_MODULE_ROOT, module_root)

    manifest_path = module_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_group = manifest.pop("group")
    manifest.update(
        {
            "module_id": "test_story",
            "title": "测试故事模块",
            "demo_username": "test_story_demo",
            "groups": [
                {
                    **legacy_group,
                    "session_id": "test_story_session_one",
                    "thread_id": "test_story_thread_one",
                    "name": "测试故事第一组",
                },
                {
                    "session_id": "test_story_session_two",
                    "thread_id": "test_story_thread_two",
                    "name": "测试故事第二组",
                    "character_ids": legacy_group["character_ids"][:3],
                },
            ],
        }
    )
    for knowledge_base in manifest["knowledge_bases"]:
        for binding in knowledge_base["bindings"]:
            if (
                binding["target_type"] == "group_thread"
                and binding["target_id"] == legacy_group["thread_id"]
            ):
                binding["target_id"] = "test_story_thread_one"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(configs, "database_url", "")
    monkeypatch.setattr(configs, "database_path", str(database_path))
    monkeypatch.setattr(configs, "knowledge_storage_path", str(storage_path))
    monkeypatch.setattr(configs, "vector_db_path", str(tmp_path / "vectors"))
    repository.init_db()
    return module_root


def test_load_story_module_normalizes_legacy_group_without_removing_it(tmp_path):
    api = _story_module_api()
    module_root = tmp_path / "legacy"
    shutil.copytree(DEFAULT_MODULE_ROOT, module_root)

    module = api.load_story_module(module_root)

    assert module["manifest"]["group"]["thread_id"] == (
        "graytide_investigation_thread"
    )
    assert module["manifest"]["groups"] == [module["manifest"]["group"]]


def test_seed_story_module_supports_multiple_groups_and_dynamic_sources(
    isolated_story_module,
):
    api = _story_module_api()

    result = api.seed_story_module(
        isolated_story_module,
        password="Demopass1",
        skip_knowledge_index=True,
    )

    assert result["module_id"] == "test_story"
    assert result["group_thread_ids"] == [
        "test_story_thread_one",
        "test_story_thread_two",
    ]
    assert result["group_thread_id"] == "test_story_thread_one"
    assert result["group_session_ids"] == [
        "test_story_session_one",
        "test_story_session_two",
    ]
    assert result["group_session_id"] == "test_story_session_one"

    owner_user_id = result["user_id"]
    sessions = [
        repository.get_latest_group_thread_session(thread_id)
        for thread_id in result["group_thread_ids"]
    ]
    assert [session["session_id"] for session in sessions] == (
        result["group_session_ids"]
    )
    assert all(session["player_id"] == owner_user_id for session in sessions)

    character_sources = {
        card["source"]
        for card in repository.list_character_cards_from_db(owner_user_id)
    }
    assert character_sources == {"test_story-demo"}

    document_sources = set()
    for knowledge_base in repository.list_knowledge_bases(owner_user_id):
        document_sources.update(
            document["source_type"]
            for document in repository.list_knowledge_documents(
                owner_user_id,
                knowledge_base["knowledge_base_id"],
            )
        )
    assert document_sources == {"test_story-demo"}


def test_seed_and_reset_preserve_unrelated_same_name_knowledge_base(
    isolated_story_module,
):
    api = _story_module_api()
    module = api.load_story_module(isolated_story_module)
    repository.create_user(
        "usr_existing_story",
        "test_story_demo",
        _hash_password("Existingpass1"),
    )
    definition = module["manifest"]["knowledge_bases"][0]
    unrelated_base = repository.create_knowledge_base(
        "usr_existing_story",
        definition["name"],
        "unrelated same-name base",
    )
    repository.replace_knowledge_bindings(
        "usr_existing_story",
        unrelated_base["knowledge_base_id"],
        [{"target_type": "global", "target_id": ""}],
    )
    unrelated_document = repository.create_knowledge_document(
        "usr_existing_story",
        unrelated_base["knowledge_base_id"],
        original_name="unrelated.md",
        media_type="text/markdown",
        source_type="unrelated-source",
        storage_path=None,
        checksum="unrelated-checksum",
        byte_size=10,
    )

    result = api.seed_story_module(
        isolated_story_module,
        skip_knowledge_index=True,
    )
    owner_user_id = result["user_id"]
    same_name_bases = [
        base
        for base in repository.list_knowledge_bases(owner_user_id)
        if base["name"] == definition["name"]
    ]
    assert len(same_name_bases) == 2
    module_base = next(
        base
        for base in same_name_bases
        if any(
            document["source_type"] == "test_story-demo"
            for document in repository.list_knowledge_documents(
                owner_user_id,
                base["knowledge_base_id"],
            )
        )
    )
    assert module_base["knowledge_base_id"] != unrelated_base["knowledge_base_id"]

    api.reset_story_module(owner_user_id, module)

    assert repository.get_knowledge_base(
        owner_user_id,
        unrelated_base["knowledge_base_id"],
    )
    assert repository.get_knowledge_document(
        owner_user_id,
        unrelated_document["document_id"],
    )
    assert {
        (binding["target_type"], binding["target_id"])
        for binding in repository.list_knowledge_bindings(
            owner_user_id,
            unrelated_base["knowledge_base_id"],
        )
    } == {("global", "")}
    assert not repository.get_knowledge_base(
        owner_user_id,
        module_base["knowledge_base_id"],
    )


def test_seed_and_reset_preserve_unrelated_content_in_mixed_base(
    isolated_story_module,
):
    api = _story_module_api()
    module = api.load_story_module(isolated_story_module)
    result = api.seed_story_module(
        isolated_story_module,
        password="Demopass1",
        skip_knowledge_index=True,
    )
    owner_user_id = result["user_id"]
    definition = module["manifest"]["knowledge_bases"][0]
    mixed_base = next(
        base
        for base in repository.list_knowledge_bases(owner_user_id)
        if base["name"] == definition["name"]
    )
    unrelated_document = repository.create_knowledge_document(
        owner_user_id,
        mixed_base["knowledge_base_id"],
        original_name="unrelated.md",
        media_type="text/markdown",
        source_type="unrelated-source",
        storage_path=None,
        checksum="mixed-unrelated-checksum",
        byte_size=10,
    )
    existing_bindings = repository.list_knowledge_bindings(
        owner_user_id,
        mixed_base["knowledge_base_id"],
    )
    unrelated_binding = {
        "target_type": "character",
        "target_id": module["cards"][0][1].character_id,
    }
    repository.replace_knowledge_bindings(
        owner_user_id,
        mixed_base["knowledge_base_id"],
        [
            *existing_bindings,
            unrelated_binding,
        ],
    )

    api.seed_story_module(
        isolated_story_module,
        skip_knowledge_index=True,
    )
    assert repository.get_knowledge_document(
        owner_user_id,
        unrelated_document["document_id"],
    )
    bindings_before_reset = repository.list_knowledge_bindings(
        owner_user_id,
        mixed_base["knowledge_base_id"],
    )
    assert (
        unrelated_binding["target_type"],
        unrelated_binding["target_id"],
    ) in {
        (binding["target_type"], binding["target_id"])
        for binding in bindings_before_reset
    }

    api.reset_story_module(owner_user_id, module)

    assert repository.get_knowledge_base(
        owner_user_id,
        mixed_base["knowledge_base_id"],
    )
    assert repository.get_knowledge_document(
        owner_user_id,
        unrelated_document["document_id"],
    )
    assert {
        (binding["target_type"], binding["target_id"])
        for binding in repository.list_knowledge_bindings(
            owner_user_id,
            mixed_base["knowledge_base_id"],
        )
    } == {
        (binding["target_type"], binding["target_id"])
        for binding in bindings_before_reset
    }
    assert all(
        document["source_type"] != "test_story-demo"
        for document in repository.list_knowledge_documents(
            owner_user_id,
            mixed_base["knowledge_base_id"],
        )
    )


def test_reset_ends_latest_session_for_each_manifest_thread(
    isolated_story_module,
):
    api = _story_module_api()
    module = api.load_story_module(isolated_story_module)
    result = api.seed_story_module(
        isolated_story_module,
        password="Demopass1",
        skip_knowledge_index=True,
    )
    owner_user_id = result["user_id"]
    group = module["manifest"]["groups"][0]
    continuation_session_id = "test_story_session_one_continuation"
    assert repository.create_multi_character_session(
        session_id=continuation_session_id,
        player_id=owner_user_id,
        player_name=result["username"],
        character_ids=group["character_ids"],
        group_name=group["name"],
        group_thread_id=group["thread_id"],
    )
    other_user_id = "usr_story_session_competitor"
    repository.create_user(
        other_user_id,
        "story_session_competitor",
        _hash_password("Otherpass1"),
    )
    _, other_card, other_raw = module["cards"][0]
    assert repository.save_character_card_to_db(
        owner_user_id=other_user_id,
        character_id=other_card.character_id,
        card_data_json=json.dumps(other_raw, ensure_ascii=False),
        version=other_card.version,
        name=other_card.meta.name,
        display_name=other_card.meta.display_name,
        source="other-user-fixture",
    )
    competing_session_id = "zz_story_competing_owner_session"
    assert repository.create_multi_character_session(
        session_id=competing_session_id,
        player_id=other_user_id,
        player_name="story_session_competitor",
        character_ids=[other_card.character_id],
        group_name="其他用户同线程群聊",
        group_thread_id=group["thread_id"],
    )
    assert repository.get_latest_group_thread_session(group["thread_id"])[
        "session_id"
    ] == competing_session_id

    api.reset_story_module(owner_user_id, module)

    assert repository.get_session(continuation_session_id)["status"] == "ended"
    assert repository.get_session(competing_session_id)["status"] == "active"


def test_seed_and_reset_are_idempotent_and_owner_scoped(isolated_story_module):
    api = _story_module_api()
    module = api.load_story_module(isolated_story_module)
    first = api.seed_story_module(
        isolated_story_module,
        password="Demopass1",
        skip_knowledge_index=True,
    )
    second = api.seed_story_module(
        isolated_story_module,
        skip_knowledge_index=True,
    )
    owner_user_id = first["user_id"]

    assert second["created_user"] is False
    assert second["group_thread_ids"] == first["group_thread_ids"]
    assert len(repository.list_character_cards_from_db(owner_user_id)) == 8
    assert len(repository.list_all_character_relationships(owner_user_id)) == 26
    assert len(
        repository.list_event_definitions(owner_user_id, only_active=False)
    ) == 24
    assert len(repository.list_knowledge_bases(owner_user_id)) == 4

    unrelated_character_id = "unrelated_character"
    assert repository.save_character_card_to_db(
        owner_user_id=owner_user_id,
        character_id=unrelated_character_id,
        card_data_json="{}",
        version="1.0.0",
        name="Unrelated",
        display_name="无关角色",
        source="unrelated-fixture",
    )
    unrelated_base = repository.create_knowledge_base(
        owner_user_id,
        "无关知识库",
        "reset isolation fixture",
    )
    unrelated_session_id = "unrelated_session"
    unrelated_thread_id = "unrelated_thread"
    assert repository.create_multi_character_session(
        session_id=unrelated_session_id,
        player_id=owner_user_id,
        player_name=first["username"],
        character_ids=[unrelated_character_id],
        group_name="无关群聊",
        group_thread_id=unrelated_thread_id,
    )

    other_user_id = "usr_story_other"
    repository.create_user(
        other_user_id,
        "story_other",
        _hash_password("Otherpass1"),
    )
    _, other_card, other_raw = module["cards"][0]
    assert repository.save_character_card_to_db(
        owner_user_id=other_user_id,
        character_id=other_card.character_id,
        card_data_json=json.dumps(other_raw, ensure_ascii=False),
        version=other_card.version,
        name=other_card.meta.name,
        display_name=other_card.meta.display_name,
        source="other-user-fixture",
    )
    first_group = module["manifest"]["groups"][0]
    assert repository.create_multi_character_session(
        session_id="other_user_colliding_session",
        player_id=other_user_id,
        player_name="story_other",
        character_ids=[other_card.character_id],
        group_name="其他用户同线程群聊",
        group_thread_id=first_group["thread_id"],
    )

    api.reset_story_module(owner_user_id, module)

    assert repository.get_character_card_from_db(
        owner_user_id,
        unrelated_character_id,
    )
    assert repository.get_knowledge_base(
        owner_user_id,
        unrelated_base["knowledge_base_id"],
    )
    assert repository.get_session(unrelated_session_id)["status"] == "active"
    assert repository.get_character_card_from_db(
        other_user_id,
        other_card.character_id,
    )
    assert repository.get_session("other_user_colliding_session")[
        "status"
    ] == "active"
    assert all(
        repository.get_session(group["session_id"])["status"]
        == "ended"
        for group in module["manifest"]["groups"]
    )
    assert not any(
        card["character_id"].startswith("graytide_")
        for card in repository.list_character_cards_from_db(owner_user_id)
    )
    assert repository.list_event_definitions(
        owner_user_id,
        only_active=False,
    ) == []


def test_generic_cli_help_and_errors_are_module_specific(
    isolated_story_module,
    monkeypatch,
    capsys,
):
    api = _story_module_api()
    help_text = api.build_parser().format_help()
    assert "module_root" in help_text
    assert "--password" in help_text
    assert "--skip-knowledge-index" in help_text
    assert "--reset-module" in help_text
    assert "Graytide" not in help_text
    assert "灰潮港" not in help_text

    (isolated_story_module / "player_character.json").unlink()
    monkeypatch.setattr(
        sys,
        "argv",
        ["seed_story_module.py", str(isolated_story_module)],
    )
    with pytest.raises(SystemExit) as exc_info:
        api.main()
    assert exc_info.value.code == 1
    error = capsys.readouterr().err
    assert "测试故事模块" in error
    assert "test_story" in error
    assert "灰潮港" not in error
