#!/usr/bin/env python3
"""Seed the isolated Graytide demo module into a Memoria database."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from memoria.api.user import _hash_password, _validate_password
from memoria.core.character_schema import CharacterCard
from memoria.core.event_runtime import register_time_event_schedule
from memoria.core.event_schema import EventDefinition
from memoria.core.knowledge_service import (
    process_knowledge_document,
    remove_stored_knowledge_file,
    store_knowledge_file,
)
from memoria.core.knowledge_vector_store import get_knowledge_vector_store
from memoria.db import repository


DEFAULT_MODULE_ROOT = REPO_ROOT / "examples" / "graytide"
DEMO_USERNAME = "memoria_demo"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(module_root: Path = DEFAULT_MODULE_ROOT) -> dict[str, Any]:
    module_root = Path(module_root).resolve()
    manifest = _read_json(module_root / "manifest.json")
    cards = []
    for path in sorted((module_root / "characters").glob("*.json")):
        raw = _read_json(path)
        cards.append((path, CharacterCard.model_validate(raw), raw))
    events = [
        EventDefinition.model_validate(raw)
        for raw in _read_json(module_root / "events.json")
    ]
    return {
        "root": module_root,
        "manifest": manifest,
        "cards": cards,
        "relationships": _read_json(module_root / "relationships.json"),
        "events": events,
    }


def _deterministic_user_id(username: str) -> str:
    digest = hashlib.sha256(username.encode("utf-8")).hexdigest()[:8]
    return f"usr_{digest}"


def _ensure_demo_user(username: str, password: str | None) -> tuple[dict, bool]:
    existing = repository.get_user_by_username(username)
    if existing:
        return existing, False
    if not password:
        raise ValueError(
            "首次创建 memoria_demo 账户需要 --password 或 MEMORIA_DEMO_PASSWORD"
        )
    _validate_password(password)
    user_id = _deterministic_user_id(username)
    collision = repository.get_user_by_id(user_id)
    if collision and collision.get("username") != username:
        raise RuntimeError(f"演示账户 ID 已被其他用户占用: {user_id}")
    repository.create_user(
        user_id=user_id,
        username=username,
        password_hash=_hash_password(password),
        gender="unknown",
    )
    created = repository.get_user_by_username(username)
    if not created:
        raise RuntimeError("创建演示账户失败")
    return created, True


def _seed_characters(owner_user_id: str, cards: list[tuple]) -> None:
    for _, card, raw in cards:
        success = repository.save_character_card_to_db(
            owner_user_id=owner_user_id,
            character_id=card.character_id,
            card_data_json=json.dumps(raw, ensure_ascii=False, indent=2),
            version=card.version,
            name=card.meta.name,
            display_name=card.meta.display_name,
            source="graytide-demo",
            avatar_url=None,
        )
        if not success:
            raise RuntimeError(f"保存角色卡失败: {card.character_id}")


def _seed_relationships(owner_user_id: str, relationships: list[dict]) -> None:
    for relationship in relationships:
        success = repository.save_character_relationship(
            owner_user_id=owner_user_id,
            character_id_a=relationship["character_id_a"],
            character_id_b=relationship["character_id_b"],
            relationship_type=relationship["relationship_type"],
            affinity=relationship.get("affinity", 0),
            description=relationship.get("description"),
        )
        if not success:
            raise RuntimeError(
                "保存角色关系失败: "
                f"{relationship['character_id_a']}/{relationship['character_id_b']}"
            )


def _ensure_group_session(owner_user_id: str, username: str, group: dict) -> dict:
    thread_id = group["thread_id"]
    existing = repository.get_latest_group_thread_session(thread_id)
    if existing:
        if existing["player_id"] != owner_user_id:
            raise RuntimeError(f"群聊线程 ID 已属于其他用户: {thread_id}")
        repository.end_session(existing["session_id"])
        return existing

    session_collision = repository.get_session(group["session_id"])
    if session_collision:
        raise RuntimeError(f"群聊会话 ID 已存在: {group['session_id']}")
    success = repository.create_multi_character_session(
        session_id=group["session_id"],
        player_id=owner_user_id,
        player_name=username,
        character_ids=group["character_ids"],
        group_name=group["name"],
        group_thread_id=thread_id,
        locale="zh-CN",
    )
    if not success:
        raise RuntimeError("创建灰潮港联合调查群聊失败")
    repository.end_session(group["session_id"])
    created = repository.get_session(group["session_id"])
    if not created:
        raise RuntimeError("创建灰潮港群聊后无法读取会话")
    return created


def _seed_events(owner_user_id: str, events: list[EventDefinition]) -> None:
    for event in events:
        success = repository.save_event_definition(
            owner_user_id=owner_user_id,
            event_id=event.event_id,
            event_name=event.event_name,
            trigger_config=event.trigger_condition.model_dump_json(),
            effects_config=json.dumps(
                [effect.model_dump(mode="json") for effect in event.effects],
                ensure_ascii=False,
            ),
            character_id=event.character_id,
            description=event.description,
            priority=event.priority,
            exclusive_group=event.exclusive_group,
            max_triggers_per_turn=event.max_triggers_per_turn,
            stop_processing=event.stop_processing,
            is_active=event.is_active,
            schedule=event.schedule,
            template_id=event.template_id,
        )
        if not success:
            raise RuntimeError(f"保存事件失败: {event.event_id}")

    for event in events:
        if not event.schedule:
            continue
        if not event.character_id:
            raise RuntimeError(f"定时事件缺少角色: {event.event_id}")
        success = register_time_event_schedule(
            event_id=event.event_id,
            character_id=event.character_id,
            player_id=owner_user_id,
            schedule=event.schedule,
        )
        if not success:
            raise RuntimeError(f"注册事件调度失败: {event.event_id}")
        if not event.is_active:
            repository.set_event_schedule_status(
                event.event_id,
                event.character_id,
                owner_user_id,
                "paused",
            )


def _delete_document(
    owner_user_id: str,
    document: dict,
    *,
    vector_store=None,
) -> None:
    deleted = repository.delete_knowledge_document(
        owner_user_id, document["document_id"]
    )
    if not deleted:
        return
    if vector_store is not None:
        vector_store.delete_document(owner_user_id, document["document_id"])
        repository.complete_knowledge_vector_cleanup(
            deleted.get("vector_cleanup_id")
        )
    remove_stored_knowledge_file(deleted.get("storage_path"))


def _delete_knowledge_base(
    owner_user_id: str,
    knowledge_base: dict,
    *,
    vector_store=None,
) -> None:
    deleted = repository.delete_knowledge_base(
        owner_user_id, knowledge_base["knowledge_base_id"]
    )
    if not deleted:
        return
    if vector_store is not None:
        vector_store.delete_knowledge_base(
            owner_user_id, knowledge_base["knowledge_base_id"]
        )
        repository.complete_knowledge_vector_cleanup(
            deleted.get("vector_cleanup_id")
        )
    for document in deleted.get("documents", []):
        remove_stored_knowledge_file(document.get("storage_path"))


def _find_or_create_base(
    owner_user_id: str,
    definition: dict,
    *,
    vector_store=None,
) -> dict:
    matches = [
        item
        for item in repository.list_knowledge_bases(owner_user_id)
        if item["name"] == definition["name"]
    ]
    if matches:
        knowledge_base = matches[0]
        for duplicate in matches[1:]:
            _delete_knowledge_base(
                owner_user_id, duplicate, vector_store=vector_store
            )
        updated = repository.update_knowledge_base(
            owner_user_id,
            knowledge_base["knowledge_base_id"],
            name=definition["name"],
            description=definition.get("description"),
            is_enabled=True,
        )
        if not updated:
            raise RuntimeError(f"更新知识库失败: {definition['name']}")
        return updated
    return repository.create_knowledge_base(
        owner_user_id,
        definition["name"],
        definition.get("description"),
    )


def _seed_document(
    owner_user_id: str,
    knowledge_base: dict,
    source_path: Path,
    *,
    skip_index: bool,
    vector_store=None,
) -> dict:
    data = source_path.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    documents = repository.list_knowledge_documents(
        owner_user_id, knowledge_base["knowledge_base_id"]
    )
    matches = [
        document
        for document in documents
        if document["original_name"] == source_path.name
    ]
    reusable = next(
        (
            document
            for document in matches
            if document["checksum"] == checksum
            and document.get("storage_path")
            and Path(document["storage_path"]).is_file()
        ),
        None,
    )
    for document in matches:
        if reusable and document["document_id"] == reusable["document_id"]:
            continue
        _delete_document(owner_user_id, document, vector_store=vector_store)

    document = reusable
    if not document:
        storage_path, stored_checksum = store_knowledge_file(data, source_path.name)
        document = repository.create_knowledge_document(
            owner_user_id,
            knowledge_base["knowledge_base_id"],
            original_name=source_path.name,
            media_type="text/markdown",
            source_type="graytide-demo",
            storage_path=storage_path,
            checksum=stored_checksum,
            byte_size=len(data),
        )

    if skip_index or document["status"] == "ready":
        return document
    resume = document["status"] == "processing"
    if document["status"] == "failed":
        _delete_document(owner_user_id, document, vector_store=vector_store)
        return _seed_document(
            owner_user_id,
            knowledge_base,
            source_path,
            skip_index=skip_index,
            vector_store=vector_store,
        )
    indexed = process_knowledge_document(
        owner_user_id,
        document["document_id"],
        vector_store=vector_store,
        resume_processing=resume,
    )
    if indexed.get("status") != "ready":
        raise RuntimeError(
            f"知识文档索引失败: {source_path.name}: "
            f"{indexed.get('error_message') or indexed.get('status')}"
        )
    return indexed


def _seed_knowledge(
    owner_user_id: str,
    module: dict,
    *,
    skip_index: bool,
    vector_store=None,
) -> list[dict]:
    results = []
    for definition in module["manifest"]["knowledge_bases"]:
        knowledge_base = _find_or_create_base(
            owner_user_id, definition, vector_store=vector_store
        )
        repository.replace_knowledge_bindings(
            owner_user_id,
            knowledge_base["knowledge_base_id"],
            definition["bindings"],
        )
        documents = [
            _seed_document(
                owner_user_id,
                knowledge_base,
                module["root"] / relative_path,
                skip_index=skip_index,
                vector_store=vector_store,
            )
            for relative_path in definition["documents"]
        ]
        results.append(
            {
                "knowledge_base_id": knowledge_base["knowledge_base_id"],
                "name": knowledge_base["name"],
                "documents": documents,
            }
        )
    return results


def reset_graytide_module(
    owner_user_id: str,
    module: dict,
    *,
    vector_store=None,
) -> None:
    manifest = module["manifest"]
    knowledge_names = {
        definition["name"] for definition in manifest["knowledge_bases"]
    }
    for knowledge_base in repository.list_knowledge_bases(owner_user_id):
        if knowledge_base["name"] in knowledge_names:
            _delete_knowledge_base(
                owner_user_id, knowledge_base, vector_store=vector_store
            )

    for event in module["events"]:
        repository.delete_event_definition(owner_user_id, event.event_id)
    for relationship in module["relationships"]:
        repository.delete_character_relationship(
            owner_user_id,
            relationship["character_id_a"],
            relationship["character_id_b"],
        )
    for _, card, _ in module["cards"]:
        repository.delete_character_card_from_db(
            owner_user_id, card.character_id, soft_delete=False
        )

    existing = repository.get_latest_group_thread_session(
        manifest["group"]["thread_id"]
    )
    if existing and existing["player_id"] == owner_user_id:
        repository.end_session(existing["session_id"])


def seed_graytide_demo(
    *,
    password: str | None = None,
    skip_knowledge_index: bool = False,
    reset_module: bool = False,
    module_root: Path = DEFAULT_MODULE_ROOT,
    vector_store=None,
) -> dict[str, Any]:
    module = load_module(module_root)
    manifest = module["manifest"]
    username = manifest.get("demo_username") or DEMO_USERNAME
    repository.init_db()
    user, created_user = _ensure_demo_user(username, password)
    owner_user_id = user["user_id"]

    resolved_vector_store = vector_store
    if not skip_knowledge_index and resolved_vector_store is None:
        resolved_vector_store = get_knowledge_vector_store()
    if reset_module:
        reset_graytide_module(
            owner_user_id,
            module,
            vector_store=resolved_vector_store,
        )

    _seed_characters(owner_user_id, module["cards"])
    _seed_relationships(owner_user_id, module["relationships"])
    group_session = _ensure_group_session(
        owner_user_id, username, manifest["group"]
    )
    _seed_events(owner_user_id, module["events"])
    knowledge_bases = _seed_knowledge(
        owner_user_id,
        module,
        skip_index=skip_knowledge_index,
        vector_store=resolved_vector_store,
    )
    return {
        "module_id": manifest["module_id"],
        "username": username,
        "user_id": owner_user_id,
        "created_user": created_user,
        "characters": len(module["cards"]),
        "relationships": len(module["relationships"]),
        "events": len(module["events"]),
        "active_events": sum(event.is_active for event in module["events"]),
        "knowledge_bases": len(knowledge_bases),
        "knowledge_documents": sum(
            len(item["documents"]) for item in knowledge_bases
        ),
        "knowledge_indexed": not skip_knowledge_index,
        "group_session_id": group_session["session_id"],
        "group_thread_id": manifest["group"]["thread_id"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="播种“灰潮港：第十三声钟鸣”演示与压力测试数据。"
    )
    parser.add_argument(
        "--password",
        help="仅在首次创建 memoria_demo 时使用；也可设置 MEMORIA_DEMO_PASSWORD。",
    )
    parser.add_argument(
        "--skip-knowledge-index",
        action="store_true",
        help="创建知识库和排队文档，但不加载本地向量模型。",
    )
    parser.add_argument(
        "--reset-module",
        action="store_true",
        help="先清理当前演示用户下清单列出的灰潮港数据，再重新播种。",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    password = args.password or os.getenv("MEMORIA_DEMO_PASSWORD")
    try:
        result = seed_graytide_demo(
            password=password,
            skip_knowledge_index=args.skip_knowledge_index,
            reset_module=args.reset_module,
        )
    except Exception as exc:
        parser.exit(1, f"灰潮港播种失败: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
