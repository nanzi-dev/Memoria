#!/usr/bin/env python3
"""Evaluate real SQL + Chroma knowledge retrieval against a JSON query set."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.chdir(PROJECT_ROOT)

from memoria.core.knowledge_retriever import _content_similarity, retrieve_knowledge
from memoria.core.knowledge_vector_store import get_knowledge_vector_store
from memoria.db import repository


DEFAULT_DATASET = PROJECT_ROOT / "tests/fixtures/knowledge_retrieval_zh.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="评估真实知识库的中文检索 Recall@5、MRR、表格命中率和重复率"
    )
    parser.add_argument("--owner-user-id", required=True)
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    return parser


def _load_cases(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as file:
        cases = json.load(file)
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集必须是非空 JSON 数组")
    return cases


def evaluate(args: argparse.Namespace) -> dict:
    repository.init_db()
    knowledge_base = repository.get_knowledge_base(
        args.owner_user_id,
        args.knowledge_base_id,
    )
    if not knowledge_base:
        raise ValueError("知识库不存在或不属于指定用户")

    cases = _load_cases(args.dataset)
    store = get_knowledge_vector_store()
    reciprocal_ranks = []
    recall_hits = 0
    table_hits = 0
    table_total = 0
    duplicate_chunks = 0
    returned_chunks = 0
    failures = []

    for case in cases:
        query = str(case["query"])
        expected = str(case["expected"])
        result = retrieve_knowledge(
            owner_user_id=args.owner_user_id,
            character_id="",
            current_message=query,
            recent_history=[],
            preauthorized_knowledge_base_ids=[args.knowledge_base_id],
            vector_store=store,
        )
        rank = next(
            (
                index
                for index, chunk in enumerate(result.chunks, start=1)
                if expected in chunk["content"]
            ),
            None,
        )
        if rank is not None and rank <= 5:
            recall_hits += 1
        reciprocal_ranks.append(1 / rank if rank else 0.0)

        if case.get("table_query"):
            table_total += 1
            if rank is not None and rank <= 3:
                table_hits += 1

        for index, chunk in enumerate(result.chunks):
            returned_chunks += 1
            if any(
                _content_similarity(chunk["content"], previous["content"]) >= 0.88
                for previous in result.chunks[:index]
            ):
                duplicate_chunks += 1

        if rank is None or rank > 5:
            failures.append(
                {
                    "query": query,
                    "expected": expected,
                    "rank": rank,
                    "returned_chunk_ids": [
                        chunk["chunk_id"] for chunk in result.chunks
                    ],
                }
            )

    query_count = len(cases)
    metrics = {
        "queries": query_count,
        "recall_at_5": recall_hits / query_count,
        "mrr": sum(reciprocal_ranks) / query_count,
        "table_top_3": table_hits / table_total if table_total else 1.0,
        "duplicate_context_ratio": duplicate_chunks / max(1, returned_chunks),
        "failures": failures,
    }
    metrics["passed"] = (
        metrics["recall_at_5"] >= 0.90
        and metrics["mrr"] >= 0.80
        and metrics["table_top_3"] == 1.0
        and metrics["duplicate_context_ratio"] < 0.10
    )
    return metrics


def main() -> int:
    args = build_parser().parse_args()
    try:
        metrics = evaluate(args)
    except (OSError, ValueError) as exc:
        print(f"评测失败: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0 if metrics["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
