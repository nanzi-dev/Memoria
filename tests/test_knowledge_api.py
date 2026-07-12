from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException

from memoria.api import knowledge as knowledge_api
from memoria.api.user import require_current_user_id
from memoria.core.config import configs
from memoria.db import repository


class _FakeVectorStore:
    def __init__(self):
        self.deleted_bases = []
        self.deleted_documents = []

    def delete_knowledge_base(self, owner_user_id, knowledge_base_id):
        self.deleted_bases.append((owner_user_id, knowledge_base_id))

    def delete_document(self, owner_user_id, document_id):
        self.deleted_documents.append((owner_user_id, document_id))


@pytest.fixture
def knowledge_owner(tmp_path, monkeypatch):
    monkeypatch.setattr(configs, "database_url", "")
    monkeypatch.setattr(configs, "database_path", str(tmp_path / "knowledge-api.db"))
    monkeypatch.setattr(
        configs, "knowledge_storage_path", str(tmp_path / "knowledge-files")
    )
    repository.init_db()
    owner_user_id = "usr_knowledge_owner"
    repository.create_user(owner_user_id, "knowledge_owner", "hash")
    return owner_user_id


def test_knowledge_routes_require_authentication():
    assert knowledge_api.router.dependencies
    with pytest.raises(HTTPException) as exc_info:
        require_current_user_id(
            token=None,
            authorization=None,
            cookie_token=None,
        )
    assert exc_info.value.status_code == 401


def test_knowledge_base_crud_bindings_and_owner_isolation(
    knowledge_owner, monkeypatch
):
    owner_user_id = knowledge_owner
    vector_store = _FakeVectorStore()
    monkeypatch.setattr(
        knowledge_api, "get_knowledge_vector_store", lambda: vector_store
    )

    created = knowledge_api.create_knowledge_base(
        knowledge_api.KnowledgeBaseCreate(
            name="城市设定", description="街区与组织"
        ),
        current_user_id=owner_user_id,
    )
    knowledge_base_id = created["knowledge_base_id"]

    listing = knowledge_api.list_knowledge_bases(current_user_id=owner_user_id)
    assert [item["knowledge_base_id"] for item in listing] == [
        knowledge_base_id
    ]

    updated = knowledge_api.update_knowledge_base(
        knowledge_base_id,
        knowledge_api.KnowledgeBaseUpdate(name="新港设定"),
        current_user_id=owner_user_id,
    )
    assert updated["name"] == "新港设定"

    cleared = knowledge_api.update_knowledge_base(
        knowledge_base_id,
        knowledge_api.KnowledgeBaseUpdate(description=None),
        current_user_id=owner_user_id,
    )
    assert cleared["description"] is None

    disabled = knowledge_api.set_knowledge_base_enabled(
        knowledge_base_id,
        knowledge_api.KnowledgeBaseEnabledUpdate(is_enabled=False),
        current_user_id=owner_user_id,
    )
    assert disabled["is_enabled"] == 0

    bindings = knowledge_api.replace_knowledge_bindings(
        knowledge_base_id,
        knowledge_api.KnowledgeBindingsUpdate(
            bindings=[
                knowledge_api.KnowledgeBinding(
                    target_type="global", target_id="ignored"
                )
            ]
        ),
        current_user_id=owner_user_id,
    )
    assert bindings[0]["target_id"] == ""
    listing = knowledge_api.list_knowledge_bases(current_user_id=owner_user_id)
    assert listing[0]["bindings"] == bindings

    foreign = repository.create_knowledge_base("another-owner", "Foreign")
    with pytest.raises(HTTPException) as exc_info:
        knowledge_api.get_knowledge_base(
            foreign["knowledge_base_id"],
            current_user_id=owner_user_id,
        )
    assert exc_info.value.status_code == 404

    deleted = knowledge_api.delete_knowledge_base(
        knowledge_base_id,
        current_user_id=owner_user_id,
    )
    assert deleted.success
    assert vector_store.deleted_bases == [(owner_user_id, knowledge_base_id)]
    assert repository.get_knowledge_base(owner_user_id, knowledge_base_id) is None


class _Upload:
    filename = "district.md"
    content_type = "text/markdown"

    async def read(self, size):
        return b"# District\nOpen at dawn."


class _UnsupportedUpload:
    filename = "district.csv"
    content_type = "text/csv"

    async def read(self, size):
        raise AssertionError("unsupported files must be rejected before reading")


def test_paste_upload_retry_and_delete_document(knowledge_owner, monkeypatch):
    owner_user_id = knowledge_owner
    queued = []
    vector_store = _FakeVectorStore()
    monkeypatch.setattr(
        knowledge_api,
        "_queue_document",
        lambda tasks, owner, document_id: queued.append((owner, document_id)),
    )
    monkeypatch.setattr(
        knowledge_api, "get_knowledge_vector_store", lambda: vector_store
    )

    knowledge_base_id = knowledge_api.create_knowledge_base(
        knowledge_api.KnowledgeBaseCreate(name="文档库"),
        current_user_id=owner_user_id,
    )["knowledge_base_id"]

    pasted_document = knowledge_api.paste_knowledge_document(
        knowledge_base_id,
        knowledge_api.PastedDocumentCreate(
            title="城市法则", text="夜间不得进入旧港区。"
        ),
        BackgroundTasks(),
        current_user_id=owner_user_id,
    )
    pasted_path = Path(pasted_document["storage_path"])
    assert pasted_path.read_text(encoding="utf-8") == "夜间不得进入旧港区。"
    assert queued == [(owner_user_id, pasted_document["document_id"])]

    uploaded_document = asyncio.run(
        knowledge_api.upload_knowledge_document(
            knowledge_base_id,
            BackgroundTasks(),
            _Upload(),
            current_user_id=owner_user_id,
        )
    )
    assert uploaded_document["original_name"] == "district.md"
    assert len(queued) == 2

    repository.update_knowledge_document_status(
        owner_user_id,
        uploaded_document["document_id"],
        "failed",
        error_message="embedding failed",
    )
    retried = knowledge_api.retry_knowledge_document(
        uploaded_document["document_id"],
        BackgroundTasks(),
        current_user_id=owner_user_id,
    )
    assert retried["status"] == "queued"
    assert len(queued) == 3

    deleted = knowledge_api.delete_knowledge_document(
        pasted_document["document_id"],
        current_user_id=owner_user_id,
    )
    assert deleted.success
    assert not pasted_path.exists()
    assert vector_store.deleted_documents == [
        (owner_user_id, pasted_document["document_id"])
    ]


def test_upload_rejects_unsupported_suffix_before_storage_or_queue(
    knowledge_owner, monkeypatch
):
    knowledge_base_id = knowledge_api.create_knowledge_base(
        knowledge_api.KnowledgeBaseCreate(name="文档库"),
        current_user_id=knowledge_owner,
    )["knowledge_base_id"]
    monkeypatch.setattr(
        knowledge_api,
        "store_knowledge_file",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not store")),
    )
    monkeypatch.setattr(
        knowledge_api,
        "_queue_document",
        lambda *args: (_ for _ in ()).throw(AssertionError("must not queue")),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            knowledge_api.upload_knowledge_document(
                knowledge_base_id,
                BackgroundTasks(),
                _UnsupportedUpload(),
                current_user_id=knowledge_owner,
            )
        )

    assert exc_info.value.status_code == 400
    assert "仅支持" in exc_info.value.detail


def test_preview_forwards_authenticated_context_and_returns_sources(
    knowledge_owner, monkeypatch
):
    owner_user_id = knowledge_owner
    knowledge_base_id = repository.create_knowledge_base(
        owner_user_id, "World"
    )["knowledge_base_id"]
    calls = []
    source = {
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_name": "World",
        "document_id": "doc-1",
        "document_name": "world.md",
        "chunk_id": "chunk-1",
        "excerpt": "The city gate closes at midnight.",
        "similarity": 0.88,
    }

    def fake_retrieve(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(query_text="当前查询：城门几点关", sources=[source])

    monkeypatch.setattr(knowledge_api, "retrieve_knowledge", fake_retrieve)
    response = knowledge_api.preview_knowledge(
        knowledge_api.KnowledgePreviewRequest(
            query="城门几点关", knowledge_base_id=knowledge_base_id
        ),
        current_user_id=owner_user_id,
    )

    assert response.sources[0].model_dump() == source
    assert calls == [
        {
            "owner_user_id": owner_user_id,
            "character_id": "",
            "group_thread_id": None,
            "current_message": "城门几点关",
            "recent_history": [],
            "knowledge_base_ids": [knowledge_base_id],
        }
    ]
