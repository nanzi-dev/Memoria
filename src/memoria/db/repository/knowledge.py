"""Domain repository functions (split from monolith)."""
from __future__ import annotations

# Standard/third-party imports used across repository domains.
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
import sqlite3
import uuid
from typing import Any, Callable
from urllib.parse import urlsplit
import re
from difflib import SequenceMatcher

from memoria.core.config import configs
from memoria.core import performance, tracing
from memoria.core.domain_events import NewDomainEvent, StoredDomainEvent
from memoria.core.fact_claim_policy import (
    ADMIN_VERIFICATION_SOURCE_KIND,
    CLAIM_SOURCE_KINDS,
    clean_source_ids,
    derive_fact_claim_identity,
    evaluate_verification,
    normalize_evidence_entry,
    normalize_fact_text,
)

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover
    psycopg = None
    dict_row = None

logger = logging.getLogger(__name__)

# Import shared helpers / connection / schema. Private names included.
from memoria.db.repository._common import *  # noqa: F403
from memoria.db.repository import _common as _common_mod

# Ensure private helpers from _common are visible as bare names.
for _name, _value in vars(_common_mod).items():
    if _name.startswith('__'):
        continue
    globals().setdefault(_name, _value)
del _name, _value, _common_mod

# =========================
# 世界观知识库
# =========================
_KNOWLEDGE_BINDING_TYPES = {"global", "character", "group_thread"}
_KNOWLEDGE_DOCUMENT_STATUSES = {"queued", "processing", "ready", "failed"}


def create_knowledge_base(
    owner_user_id: str,
    name: str,
    description: str | None = None,
) -> dict:
    knowledge_base_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_base
            (knowledge_base_id, owner_user_id, name, description,
             is_enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                knowledge_base_id,
                owner_user_id,
                name.strip(),
                (description or "").strip() or None,
                now,
                now,
            ),
        )
    return get_knowledge_base(owner_user_id, knowledge_base_id)


def get_knowledge_base(owner_user_id: str, knowledge_base_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id) AS document_count,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id
                      AND d.status = 'ready') AS ready_document_count,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = kb.owner_user_id
                      AND c.knowledge_base_id = kb.knowledge_base_id) AS chunk_count
            FROM knowledge_base kb
            WHERE kb.owner_user_id = ? AND kb.knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchone()
    return _row_to_dict(row)


def list_knowledge_bases(owner_user_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT kb.*,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id) AS document_count,
                   (SELECT COUNT(*) FROM knowledge_document d
                    WHERE d.owner_user_id = kb.owner_user_id
                      AND d.knowledge_base_id = kb.knowledge_base_id
                      AND d.status = 'ready') AS ready_document_count,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = kb.owner_user_id
                      AND c.knowledge_base_id = kb.knowledge_base_id) AS chunk_count
            FROM knowledge_base kb
            WHERE kb.owner_user_id = ?
            ORDER BY kb.updated_at DESC, kb.name ASC
            """,
            (owner_user_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def update_knowledge_base(
    owner_user_id: str,
    knowledge_base_id: str,
    *,
    name: str | None = None,
    description: str | None | object = _UNSET,
    is_enabled: bool | None = None,
) -> dict | None:
    assignments = []
    params: list = []
    if name is not None:
        assignments.append("name = ?")
        params.append(name.strip())
    if description is not _UNSET:
        assignments.append("description = ?")
        params.append(str(description or "").strip() or None)
    if is_enabled is not None:
        assignments.append("is_enabled = ?")
        params.append(1 if is_enabled else 0)
    if not assignments:
        return get_knowledge_base(owner_user_id, knowledge_base_id)

    assignments.append("updated_at = ?")
    params.extend([_now(), owner_user_id, knowledge_base_id])
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE knowledge_base
            SET {", ".join(assignments)}
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            tuple(params),
        )
    return get_knowledge_base(owner_user_id, knowledge_base_id)


def delete_knowledge_base(
    owner_user_id: str,
    knowledge_base_id: str,
) -> dict | None:
    existing = get_knowledge_base(owner_user_id, knowledge_base_id)
    if not existing:
        return None
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, created_at, updated_at)
            VALUES (?, ?, 'knowledge_base', ?, 0, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (cleanup_id, owner_user_id, knowledge_base_id, now, now),
        )
        documents = conn.execute(
            """
            SELECT document_id, storage_path
            FROM knowledge_document
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_document WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_binding WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
        conn.execute(
            "DELETE FROM knowledge_base WHERE owner_user_id = ? AND knowledge_base_id = ?",
            (owner_user_id, knowledge_base_id),
        )
    return {
        "knowledge_base": existing,
        "documents": [dict(row) for row in documents],
        "vector_cleanup_id": get_knowledge_vector_cleanup_id(
            owner_user_id,
            "knowledge_base",
            knowledge_base_id,
        ),
    }


def _normalize_knowledge_binding(binding: dict) -> tuple[str, str]:
    target_type = str(binding.get("target_type") or "").strip()
    target_id = str(binding.get("target_id") or "").strip()
    if target_type not in _KNOWLEDGE_BINDING_TYPES:
        raise ValueError(f"不支持的知识库绑定类型: {target_type}")
    if target_type == "global":
        return target_type, ""
    if not target_id:
        raise ValueError(f"{target_type} 绑定必须提供 target_id")
    return target_type, target_id


def _validate_knowledge_binding_target(
    conn,
    owner_user_id: str,
    target_type: str,
    target_id: str,
) -> None:
    if target_type == "global":
        return
    if target_type == "character":
        row = conn.execute(
            """
            SELECT 1 FROM character_card
            WHERE owner_user_id = ? AND character_id = ?
            """,
            (owner_user_id, target_id),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT 1 FROM session
            WHERE player_id = ?
              AND COALESCE(is_multi_character, 0) = 1
              AND COALESCE(group_thread_id, session_id) = ?
            LIMIT 1
            """,
            (owner_user_id, target_id),
        ).fetchone()
    if not row:
        raise ValueError(f"绑定目标不存在或不属于当前用户: {target_type}/{target_id}")


def replace_knowledge_bindings(
    owner_user_id: str,
    knowledge_base_id: str,
    bindings: list[dict],
) -> list[dict]:
    normalized = list(dict.fromkeys(_normalize_knowledge_binding(item) for item in bindings))
    with get_conn() as conn:
        base = conn.execute(
            """
            SELECT 1 FROM knowledge_base
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchone()
        if not base:
            raise ValueError("知识库不存在")

        for target_type, target_id in normalized:
            _validate_knowledge_binding_target(
                conn, owner_user_id, target_type, target_id
            )

        conn.execute(
            """
            DELETE FROM knowledge_binding
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (owner_user_id, knowledge_base_id),
        )
        if normalized:
            conn.executemany(
                """
                INSERT INTO knowledge_binding
                (owner_user_id, knowledge_base_id, target_type, target_id, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (owner_user_id, knowledge_base_id, target_type, target_id, _now())
                    for target_type, target_id in normalized
                ],
            )
        conn.execute(
            """
            UPDATE knowledge_base SET updated_at = ?
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            """,
            (_now(), owner_user_id, knowledge_base_id),
        )
    return list_knowledge_bindings(owner_user_id, knowledge_base_id)


def list_knowledge_bindings(
    owner_user_id: str,
    knowledge_base_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT target_type, target_id, created_at
            FROM knowledge_binding
            WHERE owner_user_id = ? AND knowledge_base_id = ?
            ORDER BY target_type ASC, target_id ASC
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_knowledge_binding_targets(owner_user_id: str) -> dict:
    with get_conn() as conn:
        characters = conn.execute(
            """
            SELECT character_id, COALESCE(display_name, name, character_id) AS name
            FROM character_card
            WHERE owner_user_id = ? AND is_active = 1
            ORDER BY name ASC
            """,
            (owner_user_id,),
        ).fetchall()
        groups = conn.execute(
            """
            SELECT COALESCE(group_thread_id, session_id) AS group_thread_id,
                   MAX(COALESCE(group_name, '未命名群聊')) AS name,
                   MAX(created_at) AS last_active_at
            FROM session
            WHERE player_id = ? AND COALESCE(is_multi_character, 0) = 1
            GROUP BY COALESCE(group_thread_id, session_id)
            ORDER BY last_active_at DESC
            """,
            (owner_user_id,),
        ).fetchall()
    return {
        "characters": [dict(row) for row in characters],
        "group_threads": [dict(row) for row in groups],
    }


def create_knowledge_document(
    owner_user_id: str,
    knowledge_base_id: str,
    *,
    original_name: str,
    media_type: str,
    source_type: str,
    storage_path: str | None,
    checksum: str,
    byte_size: int,
) -> dict:
    if not get_knowledge_base(owner_user_id, knowledge_base_id):
        raise ValueError("知识库不存在")
    document_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_document
            (document_id, owner_user_id, knowledge_base_id, original_name,
             media_type, source_type, storage_path, checksum, byte_size,
             status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
            """,
            (
                document_id,
                owner_user_id,
                knowledge_base_id,
                original_name,
                media_type,
                source_type,
                storage_path,
                checksum,
                byte_size,
                now,
                now,
            ),
        )
    return get_knowledge_document(owner_user_id, document_id)


def get_knowledge_document(owner_user_id: str, document_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.owner_user_id = ? AND d.document_id = ?
            """,
            (owner_user_id, document_id),
        ).fetchone()
    return _row_to_dict(row)


def list_knowledge_documents(
    owner_user_id: str,
    knowledge_base_id: str,
) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.owner_user_id = ? AND d.knowledge_base_id = ?
            ORDER BY d.created_at DESC
            """,
            (owner_user_id, knowledge_base_id),
        ).fetchall()
    return [dict(row) for row in rows]


def list_incomplete_knowledge_documents() -> list[dict]:
    """Return queued or interrupted documents so startup can resume indexing."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT d.*,
                   (SELECT COUNT(*) FROM knowledge_chunk c
                    WHERE c.owner_user_id = d.owner_user_id
                      AND c.document_id = d.document_id) AS chunk_count
            FROM knowledge_document d
            WHERE d.status IN ('queued', 'processing')
            ORDER BY d.created_at ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def claim_knowledge_document_for_processing(
    owner_user_id: str,
    document_id: str,
    *,
    expected_status: str,
    expected_updated_at: str,
) -> bool:
    """Atomically claim a queued or interrupted document for one worker."""
    if expected_status not in {"queued", "processing"}:
        return False
    with get_conn() as conn:
        cursor = conn.execute(
            """
            UPDATE knowledge_document
            SET status = 'processing', error_message = NULL, updated_at = ?
            WHERE owner_user_id = ?
              AND document_id = ?
              AND status = ?
              AND updated_at = ?
            """,
            (
                _now(),
                owner_user_id,
                document_id,
                expected_status,
                expected_updated_at,
            ),
        )
        return cursor.rowcount == 1


def update_knowledge_document_status(
    owner_user_id: str,
    document_id: str,
    status: str,
    *,
    error_message: str | None = None,
    extracted_chars: int | None = None,
    page_count: int | None = None,
) -> dict | None:
    if status not in _KNOWLEDGE_DOCUMENT_STATUSES:
        raise ValueError(f"无效文档状态: {status}")
    assignments = ["status = ?", "error_message = ?", "updated_at = ?"]
    params: list = [status, error_message, _now()]
    if extracted_chars is not None:
        assignments.append("extracted_chars = ?")
        params.append(extracted_chars)
    if page_count is not None:
        assignments.append("page_count = ?")
        params.append(page_count)
    params.extend([owner_user_id, document_id])
    with get_conn() as conn:
        conn.execute(
            f"""
            UPDATE knowledge_document
            SET {", ".join(assignments)}
            WHERE owner_user_id = ? AND document_id = ?
            """,
            tuple(params),
        )
    return get_knowledge_document(owner_user_id, document_id)


def replace_knowledge_chunks(
    owner_user_id: str,
    document_id: str,
    chunks: list[dict],
) -> list[dict]:
    document = get_knowledge_document(owner_user_id, document_id)
    if not document:
        raise ValueError("知识文档不存在")
    now = _now()
    prepared = []
    for index, chunk in enumerate(chunks):
        content = str(chunk.get("content") or "").strip()
        if not content:
            continue
        prepared.append(
            (
                str(chunk.get("chunk_id") or uuid.uuid4()),
                owner_user_id,
                document["knowledge_base_id"],
                document_id,
                int(chunk.get("chunk_index", index)),
                content,
                len(content),
                json.dumps(chunk.get("source_metadata") or {}, ensure_ascii=False),
                now,
            )
        )
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
        if prepared:
            conn.executemany(
                """
                INSERT INTO knowledge_chunk
                (chunk_id, owner_user_id, knowledge_base_id, document_id,
                 chunk_index, content, char_count, source_metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                prepared,
            )
    return list_knowledge_chunks(owner_user_id, document_id)


def list_knowledge_chunks(owner_user_id: str, document_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM knowledge_chunk
            WHERE owner_user_id = ? AND document_id = ?
            ORDER BY chunk_index ASC
            """,
            (owner_user_id, document_id),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def _decode_knowledge_chunk_row(row) -> dict:
    item = dict(row)
    try:
        item["source_metadata"] = json.loads(item.get("source_metadata") or "{}")
    except (TypeError, ValueError):
        item["source_metadata"] = {}
    return item


def clear_knowledge_document_chunks(owner_user_id: str, document_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )


def delete_knowledge_document(
    owner_user_id: str,
    document_id: str,
) -> dict | None:
    document = get_knowledge_document(owner_user_id, document_id)
    if not document:
        return None
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, created_at, updated_at)
            VALUES (?, ?, 'document', ?, 0, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (cleanup_id, owner_user_id, document_id, now, now),
        )
        conn.execute(
            "DELETE FROM knowledge_chunk WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
        conn.execute(
            "DELETE FROM knowledge_document WHERE owner_user_id = ? AND document_id = ?",
            (owner_user_id, document_id),
        )
    return {
        **document,
        "vector_cleanup_id": get_knowledge_vector_cleanup_id(
            owner_user_id,
            "document",
            document_id,
        ),
    }


def get_knowledge_vector_cleanup_id(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
) -> str | None:
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT cleanup_id
            FROM knowledge_vector_cleanup
            WHERE owner_user_id = ? AND scope_type = ? AND scope_id = ?
            """,
            (owner_user_id, scope_type, scope_id),
        ).fetchone()
    return row["cleanup_id"] if row else None


def enqueue_knowledge_vector_cleanup(
    owner_user_id: str,
    scope_type: str,
    scope_id: str,
    *,
    error: str | None = None,
) -> str:
    if scope_type not in {"document", "knowledge_base"}:
        raise ValueError("无效向量清理范围")
    cleanup_id = str(uuid.uuid4())
    now = _now()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO knowledge_vector_cleanup
            (cleanup_id, owner_user_id, scope_type, scope_id,
             attempts, last_error, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(owner_user_id, scope_type, scope_id) DO UPDATE SET
                last_error = excluded.last_error,
                updated_at = excluded.updated_at
            """,
            (
                cleanup_id,
                owner_user_id,
                scope_type,
                scope_id,
                str(error or "")[:2000] or None,
                now,
                now,
            ),
        )
    return (
        get_knowledge_vector_cleanup_id(owner_user_id, scope_type, scope_id)
        or cleanup_id
    )


def list_knowledge_vector_cleanups(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM knowledge_vector_cleanup
            ORDER BY updated_at ASC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def complete_knowledge_vector_cleanup(cleanup_id: str | None) -> None:
    if not cleanup_id:
        return
    with get_conn() as conn:
        conn.execute(
            "DELETE FROM knowledge_vector_cleanup WHERE cleanup_id = ?",
            (cleanup_id,),
        )


def fail_knowledge_vector_cleanup(cleanup_id: str, error: str) -> None:
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE knowledge_vector_cleanup
            SET attempts = attempts + 1, last_error = ?, updated_at = ?
            WHERE cleanup_id = ?
            """,
            (str(error)[:2000], _now(), cleanup_id),
        )


def list_all_knowledge_chunks_for_indexing() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.*, d.original_name AS document_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            WHERE d.status = 'ready'
            ORDER BY c.document_id, c.chunk_index
            """
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def get_authorized_knowledge_chunks(
    owner_user_id: str,
    chunk_ids: list[str],
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[dict]:
    """Revalidate vector hits against current SQL ownership, status and bindings."""
    if not chunk_ids:
        return []
    visibility = ["b.target_type = 'global'"]
    visibility_params: list = []
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        visibility_params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        visibility_params.append(group_thread_id)

    placeholders = ", ".join("?" for _ in chunk_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.chunk_id IN ({placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
              AND EXISTS (
                  SELECT 1 FROM knowledge_binding b
                  WHERE b.owner_user_id = c.owner_user_id
                    AND b.knowledge_base_id = c.knowledge_base_id
                    AND ({" OR ".join(visibility)})
              )
            """,
            tuple([owner_user_id, *chunk_ids, *visibility_params]),
        ).fetchall()
    by_id = {
        row["chunk_id"]: _decode_knowledge_chunk_row(row)
        for row in rows
    }
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


def get_owned_knowledge_chunks(
    owner_user_id: str,
    chunk_ids: list[str],
    *,
    knowledge_base_ids: list[str],
) -> list[dict]:
    """Load ready, enabled chunks from owner-validated knowledge bases."""
    if not chunk_ids or not knowledge_base_ids:
        return []
    chunk_placeholders = ", ".join("?" for _ in chunk_ids)
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.chunk_id IN ({chunk_placeholders})
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
            """,
            tuple([owner_user_id, *chunk_ids, *knowledge_base_ids]),
        ).fetchall()
    by_id = {
        row["chunk_id"]: _decode_knowledge_chunk_row(row)
        for row in rows
    }
    return [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]


def list_authorized_knowledge_chunks(
    owner_user_id: str,
    *,
    knowledge_base_ids: list[str],
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[dict]:
    """List the SQL corpus visible to a dialogue for independent keyword search."""
    if not knowledge_base_ids:
        return []
    visibility = ["b.target_type = 'global'"]
    visibility_params: list = []
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        visibility_params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        visibility_params.append(group_thread_id)
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
              AND EXISTS (
                  SELECT 1 FROM knowledge_binding b
                  WHERE b.owner_user_id = c.owner_user_id
                    AND b.knowledge_base_id = c.knowledge_base_id
                    AND ({" OR ".join(visibility)})
              )
            ORDER BY c.document_id, c.chunk_index
            """,
            tuple(
                [
                    owner_user_id,
                    *knowledge_base_ids,
                    *visibility_params,
                ]
            ),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def list_owned_knowledge_chunks_for_bases(
    owner_user_id: str,
    *,
    knowledge_base_ids: list[str],
) -> list[dict]:
    """List ready chunks in owner-validated bases for admin retrieval preview."""
    if not knowledge_base_ids:
        return []
    base_placeholders = ", ".join("?" for _ in knowledge_base_ids)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, d.original_name AS document_name,
                   kb.name AS knowledge_base_name
            FROM knowledge_chunk c
            INNER JOIN knowledge_document d
              ON d.owner_user_id = c.owner_user_id
             AND d.document_id = c.document_id
            INNER JOIN knowledge_base kb
              ON kb.owner_user_id = c.owner_user_id
             AND kb.knowledge_base_id = c.knowledge_base_id
            WHERE c.owner_user_id = ?
              AND c.knowledge_base_id IN ({base_placeholders})
              AND d.status = 'ready'
              AND kb.is_enabled = 1
            ORDER BY c.document_id, c.chunk_index
            """,
            tuple([owner_user_id, *knowledge_base_ids]),
        ).fetchall()
    return [_decode_knowledge_chunk_row(row) for row in rows]


def get_authorized_knowledge_base_ids(
    owner_user_id: str,
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> list[str]:
    visibility = ["b.target_type = 'global'"]
    params: list = [owner_user_id]
    if character_id:
        visibility.append("(b.target_type = 'character' AND b.target_id = ?)")
        params.append(character_id)
    if group_thread_id:
        visibility.append("(b.target_type = 'group_thread' AND b.target_id = ?)")
        params.append(group_thread_id)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT DISTINCT kb.knowledge_base_id
            FROM knowledge_base kb
            INNER JOIN knowledge_binding b
              ON b.owner_user_id = kb.owner_user_id
             AND b.knowledge_base_id = kb.knowledge_base_id
            INNER JOIN knowledge_document d
              ON d.owner_user_id = kb.owner_user_id
             AND d.knowledge_base_id = kb.knowledge_base_id
            WHERE kb.owner_user_id = ?
              AND kb.is_enabled = 1
              AND d.status = 'ready'
              AND ({" OR ".join(visibility)})
            ORDER BY kb.knowledge_base_id
            """,
            tuple(params),
        ).fetchall()
    return [row["knowledge_base_id"] for row in rows]


def has_authorized_knowledge_bases(
    owner_user_id: str,
    *,
    character_id: str | None = None,
    group_thread_id: str | None = None,
) -> bool:
    return bool(
        get_authorized_knowledge_base_ids(
            owner_user_id,
            character_id=character_id,
            group_thread_id=group_thread_id,
        )
    )



