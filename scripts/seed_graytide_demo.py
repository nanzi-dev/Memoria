#!/usr/bin/env python3
"""Backward-compatible CLI wrapper for the Graytide story module."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.seed_story_module import (
    load_story_module,
    reset_story_module,
    seed_story_module,
)

DEFAULT_MODULE_ROOT = REPO_ROOT / "examples" / "graytide"


def load_module(
    module_root: Path = DEFAULT_MODULE_ROOT,
) -> dict[str, Any]:
    return load_story_module(module_root)


def reset_graytide_module(
    owner_user_id: str,
    module: dict,
    *,
    vector_store=None,
) -> None:
    reset_story_module(
        owner_user_id,
        module,
        vector_store=vector_store,
    )


def seed_graytide_demo(
    *,
    password: str | None = None,
    skip_knowledge_index: bool = False,
    reset_module: bool = False,
    module_root: Path = DEFAULT_MODULE_ROOT,
    vector_store=None,
) -> dict[str, Any]:
    return seed_story_module(
        module_root,
        password=password,
        skip_knowledge_index=skip_knowledge_index,
        reset_module=reset_module,
        vector_store=vector_store,
    )


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
