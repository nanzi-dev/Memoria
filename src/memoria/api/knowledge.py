"""Authenticated management API for independent world knowledge bases."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, Field

from memoria.api.knowledge_models import KnowledgeSource
from memoria.api.user import require_current_user_id
from memoria.core.config import configs
from memoria.core.knowledge_documents import (
    KnowledgeDocumentError,
    validate_document_filename,
    validate_document_size,
)
from memoria.core.knowledge_retriever import retrieve_knowledge
from memoria.core.knowledge_service import (
    process_knowledge_document,
    remove_stored_knowledge_file,
    store_knowledge_file,
)
from memoria.core.knowledge_vector_store import get_knowledge_vector_store
from memoria.db import repository

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/knowledge",
    tags=["knowledge"],
    dependencies=[Depends(require_current_user_id)],
)


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)


class KnowledgeBaseEnabledUpdate(BaseModel):
    is_enabled: bool


class KnowledgeBinding(BaseModel):
    target_type: str
    target_id: str = ""


class KnowledgeBindingsUpdate(BaseModel):
    bindings: list[KnowledgeBinding] = Field(default_factory=list)


class PastedDocumentCreate(BaseModel):
    title: str = Field(default="粘贴文本", min_length=1, max_length=180)
    text: str = Field(min_length=1)


class KnowledgePreviewRequest(BaseModel):
    query: str = Field(min_length=1, max_length=4000)
    character_id: str | None = None
    group_thread_id: str | None = None
    knowledge_base_id: str | None = None


class KnowledgePreviewResponse(BaseModel):
    query_text: str
    sources: list[KnowledgeSource] = Field(default_factory=list)


class OperationResponse(BaseModel):
    success: bool = True


def _clean_required(value: str, field_name: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"{field_name}不能为空")
    return cleaned


def _require_base(owner_user_id: str, knowledge_base_id: str) -> dict:
    knowledge_base = repository.get_knowledge_base(owner_user_id, knowledge_base_id)
    if not knowledge_base:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return knowledge_base


def _require_document(owner_user_id: str, document_id: str) -> dict:
    document = repository.get_knowledge_document(owner_user_id, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="知识文档不存在")
    return document


def _base_detail(owner_user_id: str, knowledge_base_id: str) -> dict:
    knowledge_base = _require_base(owner_user_id, knowledge_base_id)
    return {
        **knowledge_base,
        "bindings": repository.list_knowledge_bindings(
            owner_user_id, knowledge_base_id
        ),
        "documents": repository.list_knowledge_documents(
            owner_user_id, knowledge_base_id
        ),
    }


def _queue_document(
    background_tasks: BackgroundTasks,
    owner_user_id: str,
    document_id: str,
) -> None:
    background_tasks.add_task(
        process_knowledge_document,
        owner_user_id,
        document_id,
    )


@router.get("/bases")
def list_knowledge_bases(
    current_user_id: str = Depends(require_current_user_id),
):
    knowledge_bases = repository.list_knowledge_bases(current_user_id)
    return [
        {
            **knowledge_base,
            "bindings": repository.list_knowledge_bindings(
                current_user_id, knowledge_base["knowledge_base_id"]
            ),
        }
        for knowledge_base in knowledge_bases
    ]


@router.post("/bases", status_code=201)
def create_knowledge_base(
    request: KnowledgeBaseCreate,
    current_user_id: str = Depends(require_current_user_id),
):
    knowledge_base = repository.create_knowledge_base(
        current_user_id,
        _clean_required(request.name, "知识库名称"),
        request.description,
    )
    return {
        **knowledge_base,
        "bindings": [],
        "documents": [],
    }


@router.get("/bases/{knowledge_base_id}")
def get_knowledge_base(
    knowledge_base_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    return _base_detail(current_user_id, knowledge_base_id)


@router.put("/bases/{knowledge_base_id}")
def update_knowledge_base(
    knowledge_base_id: str,
    request: KnowledgeBaseUpdate,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    update = request.model_dump(exclude_unset=True)
    if "name" in update:
        update["name"] = _clean_required(update["name"], "知识库名称")
    repository.update_knowledge_base(
        current_user_id,
        knowledge_base_id,
        **update,
    )
    return _base_detail(current_user_id, knowledge_base_id)


@router.patch("/bases/{knowledge_base_id}/enabled")
def set_knowledge_base_enabled(
    knowledge_base_id: str,
    request: KnowledgeBaseEnabledUpdate,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    return repository.update_knowledge_base(
        current_user_id,
        knowledge_base_id,
        is_enabled=request.is_enabled,
    )


@router.delete("/bases/{knowledge_base_id}", response_model=OperationResponse)
def delete_knowledge_base(
    knowledge_base_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    try:
        deleted = repository.delete_knowledge_base(
            current_user_id, knowledge_base_id
        )
    except Exception as exc:
        logger.exception("删除知识库失败: %s", knowledge_base_id)
        raise HTTPException(status_code=500, detail="删除知识库失败") from exc
    try:
        get_knowledge_vector_store().delete_knowledge_base(
            current_user_id, knowledge_base_id
        )
    except Exception:
        logger.exception("知识库已删除，但向量清理失败: %s", knowledge_base_id)
    for document in (deleted or {}).get("documents", []):
        remove_stored_knowledge_file(document.get("storage_path"))
    return OperationResponse()


@router.put("/bases/{knowledge_base_id}/bindings")
def replace_knowledge_bindings(
    knowledge_base_id: str,
    request: KnowledgeBindingsUpdate,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    try:
        return repository.replace_knowledge_bindings(
            current_user_id,
            knowledge_base_id,
            [binding.model_dump() for binding in request.bindings],
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/binding-targets")
def list_knowledge_binding_targets(
    current_user_id: str = Depends(require_current_user_id),
):
    return repository.list_knowledge_binding_targets(current_user_id)


@router.get("/bases/{knowledge_base_id}/documents")
def list_knowledge_documents(
    knowledge_base_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    return repository.list_knowledge_documents(current_user_id, knowledge_base_id)


@router.post("/bases/{knowledge_base_id}/documents/upload", status_code=202)
async def upload_knowledge_document(
    knowledge_base_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    original_name = Path(file.filename or "").name
    if not original_name:
        raise HTTPException(status_code=400, detail="缺少文件名")
    try:
        validate_document_filename(original_name)
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    data = await file.read(configs.knowledge_upload_max_bytes + 1)
    try:
        validate_document_size(data)
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    storage_path = None
    try:
        storage_path, checksum = store_knowledge_file(data, original_name)
        document = repository.create_knowledge_document(
            current_user_id,
            knowledge_base_id,
            original_name=original_name,
            media_type=file.content_type or "application/octet-stream",
            source_type="upload",
            storage_path=storage_path,
            checksum=checksum,
            byte_size=len(data),
        )
    except ValueError as exc:
        remove_stored_knowledge_file(storage_path)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        remove_stored_knowledge_file(storage_path)
        raise

    _queue_document(background_tasks, current_user_id, document["document_id"])
    return document


@router.post("/bases/{knowledge_base_id}/documents/paste", status_code=202)
def paste_knowledge_document(
    knowledge_base_id: str,
    request: PastedDocumentCreate,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    _require_base(current_user_id, knowledge_base_id)
    title = _clean_required(request.title, "文档标题")
    text = _clean_required(request.text, "文档内容")
    data = text.encode("utf-8")
    try:
        validate_document_size(data)
    except KnowledgeDocumentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    original_name = f"{Path(title).stem or '粘贴文本'}.txt"
    storage_path = None
    try:
        storage_path, checksum = store_knowledge_file(data, original_name)
        document = repository.create_knowledge_document(
            current_user_id,
            knowledge_base_id,
            original_name=original_name,
            media_type="text/plain",
            source_type="pasted_text",
            storage_path=storage_path,
            checksum=checksum,
            byte_size=len(data),
        )
    except Exception:
        remove_stored_knowledge_file(storage_path)
        raise

    _queue_document(background_tasks, current_user_id, document["document_id"])
    return document


@router.delete("/documents/{document_id}", response_model=OperationResponse)
def delete_knowledge_document(
    document_id: str,
    current_user_id: str = Depends(require_current_user_id),
):
    document = _require_document(current_user_id, document_id)
    try:
        repository.delete_knowledge_document(current_user_id, document_id)
    except Exception as exc:
        logger.exception("删除知识文档失败: %s", document_id)
        raise HTTPException(status_code=500, detail="删除知识文档失败") from exc
    try:
        get_knowledge_vector_store().delete_document(current_user_id, document_id)
    except Exception:
        logger.exception("知识文档已删除，但向量清理失败: %s", document_id)
    remove_stored_knowledge_file(document.get("storage_path"))
    return OperationResponse()


@router.post("/documents/{document_id}/retry", status_code=202)
def retry_knowledge_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    current_user_id: str = Depends(require_current_user_id),
):
    document = _require_document(current_user_id, document_id)
    if document["status"] in {"queued", "processing"}:
        raise HTTPException(status_code=409, detail="文档正在处理中")
    queued = repository.update_knowledge_document_status(
        current_user_id,
        document_id,
        "queued",
        error_message=None,
    )
    _queue_document(background_tasks, current_user_id, document_id)
    return queued


@router.post("/preview", response_model=KnowledgePreviewResponse)
def preview_knowledge(
    request: KnowledgePreviewRequest,
    current_user_id: str = Depends(require_current_user_id),
):
    if request.knowledge_base_id:
        _require_base(current_user_id, request.knowledge_base_id)
    targets = repository.list_knowledge_binding_targets(current_user_id)
    if request.character_id and request.character_id not in {
        item["character_id"] for item in targets["characters"]
    }:
        raise HTTPException(status_code=404, detail="角色不存在")
    if request.group_thread_id and request.group_thread_id not in {
        item["group_thread_id"] for item in targets["group_threads"]
    }:
        raise HTTPException(status_code=404, detail="群聊线程不存在")

    result = retrieve_knowledge(
        owner_user_id=current_user_id,
        character_id=request.character_id or "",
        group_thread_id=request.group_thread_id,
        current_message=_clean_required(request.query, "检索内容"),
        recent_history=[],
        preauthorized_knowledge_base_ids=(
            [request.knowledge_base_id] if request.knowledge_base_id else None
        ),
    )
    return KnowledgePreviewResponse(
        query_text=result.query_text,
        sources=result.sources,
    )
