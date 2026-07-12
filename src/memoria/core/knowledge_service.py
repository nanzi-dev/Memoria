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


def process_knowledge_document(
    owner_user_id: str,
    document_id: str,
    *,
    vector_store=None,
) -> dict:
    document = repository.get_knowledge_document(owner_user_id, document_id)
    if not document:
        raise ValueError("知识文档不存在")
    vector_store = vector_store or get_knowledge_vector_store()
    repository.update_knowledge_document_status(
        owner_user_id, document_id, "processing", error_message=None
    )

    try:
        vector_store.delete_document(owner_user_id, document_id)
        repository.clear_knowledge_document_chunks(owner_user_id, document_id)
        storage_path = document.get("storage_path")
        if not storage_path:
            raise ValueError("知识文档缺少存储文件")
        data = Path(storage_path).read_bytes()
        extracted = extract_document(document["original_name"], data)
        chunks = chunk_document(extracted)
        if not chunks:
            raise ValueError("文档未生成可检索文本块")
        stored_chunks = repository.replace_knowledge_chunks(
            owner_user_id, document_id, chunks
        )
        vector_store.upsert_chunks(stored_chunks)
        return repository.update_knowledge_document_status(
            owner_user_id,
            document_id,
            "ready",
            error_message=None,
            extracted_chars=len(extracted.text),
            page_count=extracted.page_count,
        )
    except Exception as exc:
        try:
            vector_store.delete_document(owner_user_id, document_id)
        except Exception:
            logger.exception("清理失败知识文档的部分向量时出错")
        repository.clear_knowledge_document_chunks(owner_user_id, document_id)
        logger.warning("知识文档处理失败: document=%s error=%s", document_id, exc)
        return repository.update_knowledge_document_status(
            owner_user_id,
            document_id,
            "failed",
            error_message=str(exc)[:2000],
            extracted_chars=0,
        )
