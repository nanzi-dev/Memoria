"""Independent vector collection for world knowledge chunks."""

from __future__ import annotations

import logging
import threading
from typing import Optional

from memoria.core.config import configs
from memoria.core.knowledge_documents import build_chunk_index_text

logger = logging.getLogger(__name__)


class KnowledgeVectorStore:
    collection_name = "knowledge_base_chunks"

    def __init__(self, *, collection=None, embedding_model=None):
        if collection is not None and embedding_model is not None:
            self.collection = collection
            self.embedding_model = embedding_model
            return

        import chromadb
        from chromadb.config import Settings
        from sentence_transformers import SentenceTransformer

        client = chromadb.PersistentClient(
            path=configs.vector_db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True,
                is_persistent=True,
            ),
        )
        self.collection = client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self.embedding_model = SentenceTransformer(configs.embedding_model)

    @property
    def tokenizer(self):
        return getattr(self.embedding_model, "tokenizer", None)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        encoded = self.embedding_model.encode(texts)
        if hasattr(encoded, "tolist"):
            encoded = encoded.tolist()
        if texts and encoded and isinstance(encoded[0], (int, float)):
            return [encoded]
        return encoded

    def upsert_chunks(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        texts = [
            chunk.get("index_text")
            or build_chunk_index_text(
                chunk.get("document_name", ""),
                chunk.get("source_metadata") or {},
                chunk["content"],
            )
            for chunk in chunks
        ]
        self.collection.upsert(
            ids=[chunk["chunk_id"] for chunk in chunks],
            embeddings=self._encode(texts),
            documents=texts,
            metadatas=[
                {
                    "owner_user_id": chunk["owner_user_id"],
                    "knowledge_base_id": chunk["knowledge_base_id"],
                    "document_id": chunk["document_id"],
                    "chunk_id": chunk["chunk_id"],
                }
                for chunk in chunks
            ],
        )

    def search(
        self,
        owner_user_id: str,
        query_text: str,
        *,
        top_k: int,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict]:
        where = {"owner_user_id": owner_user_id}
        if knowledge_base_ids is not None:
            if not knowledge_base_ids:
                return []
            where = {
                "$and": [
                    {"owner_user_id": owner_user_id},
                    {"knowledge_base_id": {"$in": knowledge_base_ids}},
                ]
            }
        result = self.collection.query(
            query_embeddings=self._encode([query_text]),
            n_results=max(1, top_k),
            where=where,
        )
        hits = []
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        for index, chunk_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else 1.0
            hits.append(
                {
                    "chunk_id": chunk_id,
                    "similarity": max(0.0, min(1.0, 1.0 - float(distance))),
                }
            )
        return hits

    def delete_document(self, owner_user_id: str, document_id: str) -> None:
        self.collection.delete(
            where={
                "$and": [
                    {"owner_user_id": owner_user_id},
                    {"document_id": document_id},
                ]
            }
        )

    def delete_knowledge_base(
        self,
        owner_user_id: str,
        knowledge_base_id: str,
    ) -> None:
        self.collection.delete(
            where={
                "$and": [
                    {"owner_user_id": owner_user_id},
                    {"knowledge_base_id": knowledge_base_id},
                ]
            }
        )

    def list_chunk_ids(self) -> set[str]:
        result = self.collection.get(include=["metadatas"])
        return set(result.get("ids") or [])

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        if chunk_ids:
            self.collection.delete(ids=chunk_ids)


_knowledge_vector_store: Optional[KnowledgeVectorStore] = None
_knowledge_vector_store_lock = threading.Lock()


def get_knowledge_vector_store() -> KnowledgeVectorStore:
    global _knowledge_vector_store
    if _knowledge_vector_store is None:
        with _knowledge_vector_store_lock:
            if _knowledge_vector_store is None:
                _knowledge_vector_store = KnowledgeVectorStore()
    return _knowledge_vector_store
