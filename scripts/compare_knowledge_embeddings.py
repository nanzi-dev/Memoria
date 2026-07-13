#!/usr/bin/env python3
"""Compare embedding models on the real knowledge retrieval evaluation set."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.chdir(PROJECT_ROOT)

from memoria.core.knowledge_documents import build_chunk_index_text
from memoria.core.knowledge_retriever import (
    _content_similarity,
    retrieve_knowledge,
)
from memoria.db import repository


DEFAULT_DATASET = PROJECT_ROOT / "tests/fixtures/knowledge_retrieval_zh.json"


class InMemoryEmbeddingStore:
    def __init__(
        self,
        model_path: str,
        chunks: list[dict],
        *,
        query_prefix: str = "",
    ):
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(model_path)
        self.chunks = chunks
        self.query_prefix = query_prefix
        texts = [
            build_chunk_index_text(
                chunk["document_name"],
                chunk.get("source_metadata") or {},
                chunk["content"],
            )
            for chunk in chunks
        ]
        self.embeddings = np.asarray(
            self.model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=False,
            ),
            dtype=np.float32,
        )

    def search(
        self,
        owner_user_id: str,
        query_text: str,
        *,
        top_k: int,
        knowledge_base_ids: list[str] | None = None,
    ) -> list[dict]:
        query_embedding = np.asarray(
            self.model.encode(
                [f"{self.query_prefix}{query_text}"],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0],
            dtype=np.float32,
        )
        similarities = self.embeddings @ query_embedding
        allowed_bases = (
            set(knowledge_base_ids)
            if knowledge_base_ids is not None
            else None
        )
        hits = []
        for index in np.argsort(-similarities):
            chunk = self.chunks[int(index)]
            if chunk["owner_user_id"] != owner_user_id:
                continue
            if (
                allowed_bases is not None
                and chunk["knowledge_base_id"] not in allowed_bases
            ):
                continue
            hits.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "similarity": max(
                        0.0,
                        min(1.0, float(similarities[int(index)])),
                    ),
                }
            )
            if len(hits) >= top_k:
                break
        return hits


def _parse_model(value: str) -> tuple[str, str]:
    label, separator, path = value.partition("=")
    if not separator or not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("模型参数必须使用 label=path 格式")
    return label.strip(), path.strip()


def _parse_assignment(value: str) -> tuple[str, str]:
    label, separator, assigned_value = value.partition("=")
    if not separator or not label.strip():
        raise argparse.ArgumentTypeError("参数必须使用 label=value 格式")
    return label.strip(), assigned_value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="比较嵌入模型的纯向量与混合知识检索质量"
    )
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--model",
        action="append",
        type=_parse_model,
        required=True,
        help="可重复指定，格式为 label=本地模型路径",
    )
    parser.add_argument(
        "--query-prefix",
        action="append",
        type=_parse_assignment,
        default=[],
        help="为指定模型的查询添加前缀，格式为 label=前缀文本",
    )
    return parser


def _load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集必须是非空 JSON 数组")
    return cases


def _rank_expected(
    chunk_ids: list[str],
    chunks_by_id: dict[str, dict],
    expected: str,
) -> int | None:
    return next(
        (
            rank
            for rank, chunk_id in enumerate(chunk_ids, start=1)
            if expected in chunks_by_id[chunk_id]["content"]
        ),
        None,
    )


def evaluate_model(
    *,
    owner_user_id: str,
    knowledge_base_id: str,
    cases: list[dict],
    chunks: list[dict],
    model_path: str,
    query_prefix: str = "",
) -> dict:
    store = InMemoryEmbeddingStore(
        model_path,
        chunks,
        query_prefix=query_prefix,
    )
    chunks_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
    vector_reciprocal_ranks = []
    hybrid_reciprocal_ranks = []
    vector_hits = 0
    hybrid_hits = 0
    table_hits = 0
    table_total = 0
    duplicate_chunks = 0
    returned_chunks = 0

    for case in cases:
        query = str(case["query"])
        expected = str(case["expected"])
        vector_results = store.search(
            owner_user_id,
            query,
            top_k=5,
            knowledge_base_ids=[knowledge_base_id],
        )
        vector_rank = _rank_expected(
            [item["chunk_id"] for item in vector_results],
            chunks_by_id,
            expected,
        )
        if vector_rank is not None:
            vector_hits += 1
        vector_reciprocal_ranks.append(
            1 / vector_rank if vector_rank else 0.0
        )

        result = retrieve_knowledge(
            owner_user_id=owner_user_id,
            character_id="",
            current_message=query,
            recent_history=[],
            preauthorized_knowledge_base_ids=[knowledge_base_id],
            vector_store=store,
        )
        hybrid_rank = next(
            (
                rank
                for rank, chunk in enumerate(result.chunks, start=1)
                if expected in chunk["content"]
            ),
            None,
        )
        if hybrid_rank is not None and hybrid_rank <= 5:
            hybrid_hits += 1
        hybrid_reciprocal_ranks.append(
            1 / hybrid_rank if hybrid_rank else 0.0
        )

        if case.get("table_query"):
            table_total += 1
            if hybrid_rank is not None and hybrid_rank <= 3:
                table_hits += 1
        for index, chunk in enumerate(result.chunks):
            returned_chunks += 1
            if any(
                _content_similarity(
                    chunk["content"],
                    previous["content"],
                )
                >= 0.88
                for previous in result.chunks[:index]
            ):
                duplicate_chunks += 1

    count = len(cases)
    return {
        "vector_recall_at_5": vector_hits / count,
        "vector_mrr_at_5": sum(vector_reciprocal_ranks) / count,
        "hybrid_recall_at_5": hybrid_hits / count,
        "hybrid_mrr": sum(hybrid_reciprocal_ranks) / count,
        "hybrid_table_top_3": (
            table_hits / table_total if table_total else 1.0
        ),
        "hybrid_duplicate_context_ratio": (
            duplicate_chunks / max(1, returned_chunks)
        ),
    }


def main() -> int:
    args = build_parser().parse_args()
    repository.init_db()
    chunks = repository.list_owned_knowledge_chunks_for_bases(
        args.owner_user_id,
        knowledge_base_ids=[args.knowledge_base_id],
    )
    if not chunks:
        print("评测失败: 知识库没有可评测分块", file=sys.stderr)
        return 2
    cases = _load_cases(args.dataset)
    query_prefixes = dict(args.query_prefix)
    model_labels = {label for label, _ in args.model}
    unknown_prefix_labels = sorted(set(query_prefixes) - model_labels)
    if unknown_prefix_labels:
        print(
            "评测失败: 查询前缀引用了未配置模型: "
            + ", ".join(unknown_prefix_labels),
            file=sys.stderr,
        )
        return 2
    results = {}
    for label, model_path in args.model:
        results[label] = evaluate_model(
            owner_user_id=args.owner_user_id,
            knowledge_base_id=args.knowledge_base_id,
            cases=cases,
            chunks=chunks,
            model_path=model_path,
            query_prefix=query_prefixes.get(label, ""),
        )
    print(
        json.dumps(
            {
                "queries": len(cases),
                "chunks": len(chunks),
                "models": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
