"""File persistence and fail-clean indexing for knowledge documents."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
import uuid

from memoria.core.config import configs
from memoria.core.knowledge_documents import chunk_document, extract_document
from memoria.core.knowledge_vector_store import get_knowledge_vector_store
from memoria.db import repository

logger = logging.getLogger(__name__)


def store_knowledge_file(data: bytes, original_name: str) -> tuple[str, str]:
    suffix = Path(original_name or "").suffix.lower()
    storage_root = Path(configs.knowledge_storage_path)
    storage_root.mkdir(parents=True, exist_ok=True)
    path = storage_root / f"{uuid.uuid4()}{suffix}"
    path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest()


def remove_stored_knowledge_file(storage_path: str | None) -> None:
    if not storage_path:
        return
    try:
        path = Path(storage_path)
        root = Path(configs.knowledge_storage_path).resolve()
        resolved = path.resolve()
        if resolved.parent != root:
            logger.warning("拒绝删除知识目录以外的文件: %s", resolved)
            return
        resolved.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("删除知识文档原文件失败: %s", exc)


def retry_knowledge_vector_cleanups(*, vector_store=None) -> dict:
    tasks = repository.list_knowledge_vector_cleanups()
    if not tasks:
        return {"completed": 0, "failed": 0}
    store = vector_store or get_knowledge_vector_store()
    completed = 0
    failed = 0
    for task in tasks:
        try:
            if task["scope_type"] == "document":
                store.delete_document(task["owner_user_id"], task["scope_id"])
            else:
                store.delete_knowledge_base(
                    task["owner_user_id"],
                    task["scope_id"],
                )
            repository.complete_knowledge_vector_cleanup(task["cleanup_id"])
            completed += 1
        except Exception as exc:
            repository.fail_knowledge_vector_cleanup(task["cleanup_id"], str(exc))
            failed += 1
            logger.warning(
                "知识向量清理重试失败: cleanup=%s error=%s",
                task["cleanup_id"],
                exc,
            )
    return {"completed": completed, "failed": failed}


def reconcile_knowledge_vectors(*, vector_store=None) -> dict:
    store = vector_store or get_knowledge_vector_store()
    sql_chunks = repository.list_all_knowledge_chunks_for_indexing()
    by_id = {chunk["chunk_id"]: chunk for chunk in sql_chunks}
    vector_ids = store.list_chunk_ids()
    sql_ids = set(by_id)
    orphan_ids = sorted(vector_ids - sql_ids)
    missing_ids = sorted(sql_ids - vector_ids)
    if orphan_ids:
        store.delete_chunks(orphan_ids)
    if missing_ids:
        store.upsert_chunks([by_id[chunk_id] for chunk_id in missing_ids])
    return {
        "sql_chunks": len(sql_ids),
        "vector_chunks": len(vector_ids),
        "deleted_orphans": len(orphan_ids),
        "restored_missing": len(missing_ids),
    }


def process_knowledge_document(
    owner_user_id: str,
    document_id: str,
    *,
    vector_store=None,
    resume_processing: bool = False,
    expected_status: str | None = None,
    expected_updated_at: str | None = None,
) -> dict:
    document = repository.get_knowledge_document(owner_user_id, document_id)
    if not document:
        raise ValueError("知识文档不存在")
    status = expected_status or document["status"]
    updated_at = expected_updated_at or document["updated_at"]
    if status != "queued" and not (resume_processing and status == "processing"):
        return document
    claimed = repository.claim_knowledge_document_for_processing(
        owner_user_id,
        document_id,
        expected_status=status,
        expected_updated_at=updated_at,
    )
    if not claimed:
        return repository.get_knowledge_document(owner_user_id, document_id) or {}

    try:
        vector_store = vector_store or get_knowledge_vector_store()
        vector_store.delete_document(owner_user_id, document_id)
        repository.clear_knowledge_document_chunks(owner_user_id, document_id)
        storage_path = document.get("storage_path")
        if not storage_path:
            raise ValueError("知识文档缺少存储文件")
        data = Path(storage_path).read_bytes()
        extracted = extract_document(document["original_name"], data)
        chunks = chunk_document(
            extracted,
            document_title=document["original_name"],
            tokenizer=getattr(vector_store, "tokenizer", None),
        )
        if not chunks:
            raise ValueError("文档未生成可检索文本块")
        stored_chunks = repository.replace_knowledge_chunks(
            owner_user_id, document_id, chunks
        )
        if not repository.get_knowledge_document(owner_user_id, document_id):
            vector_store.delete_document(owner_user_id, document_id)
            return {}
        vector_store.upsert_chunks(
            [
                {
                    **chunk,
                    "document_name": document["original_name"],
                }
                for chunk in stored_chunks
            ]
        )
        if not repository.get_knowledge_document(owner_user_id, document_id):
            vector_store.delete_document(owner_user_id, document_id)
            return {}
        return repository.update_knowledge_document_status(
            owner_user_id,
            document_id,
            "ready",
            error_message=None,
            extracted_chars=len(extracted.text),
            page_count=extracted.page_count,
        )
    except Exception as exc:
        if vector_store is not None:
            try:
                vector_store.delete_document(owner_user_id, document_id)
            except Exception as cleanup_exc:
                logger.exception("清理失败知识文档的部分向量时出错")
                repository.enqueue_knowledge_vector_cleanup(
                    owner_user_id,
                    "document",
                    document_id,
                    error=str(cleanup_exc),
                )
        repository.clear_knowledge_document_chunks(owner_user_id, document_id)
        if not repository.get_knowledge_document(owner_user_id, document_id):
            return {}
        logger.warning("知识文档处理失败: document=%s error=%s", document_id, exc)
        return repository.update_knowledge_document_status(
            owner_user_id,
            document_id,
            "failed",
            error_message=str(exc)[:2000],
            extracted_chars=0,
        )
