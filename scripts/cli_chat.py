#!/usr/bin/env python3
"""Memoria 命令行对话工具。"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
os.chdir(PROJECT_ROOT)

from memoria.core import character_loader, orchestrator
from memoria.db import repository


EXIT_COMMANDS = {"/exit", "/quit", "exit", "quit", "q"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Memoria CLI 聊天工具")
    parser.add_argument(
        "--character-id",
        default="npc_luo_xiaohei",
        help="角色 ID，默认 npc_luo_xiaohei",
    )
    parser.add_argument(
        "--player-id",
        default="cli_player",
        help="玩家 ID，默认 cli_player",
    )
    parser.add_argument(
        "--player-name",
        default="旅行者",
        help="玩家显示名，默认 旅行者",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出 LLM 原始请求/响应和 Prompt 内容到 stderr",
    )
    return parser


def _debug_sink(message: str) -> None:
    print(message, file=sys.stderr)


def _character_label(character_id: str) -> str:
    try:
        card = character_loader.load_character_card(character_id)
        return card.meta.display_name or card.meta.name or character_id
    except Exception:
        return character_id


def run_chat(args: argparse.Namespace) -> int:
    repository.init_db()

    character_label = _character_label(args.character_id)
    session = orchestrator.start_session(
        args.character_id,
        args.player_id,
        args.player_name,
        debug=args.debug,
        debug_sink=_debug_sink if args.debug else None,
    )
    session_id = session["session_id"]

    print(f"会话已开始: {session_id}")
    if session.get("opening_line"):
        print(f"{character_label}: {session['opening_line']}")
    print("输入 /exit 结束。")

    try:
        while True:
            try:
                player_message = input(f"{args.player_name}> ").strip()
            except EOFError:
                print()
                break

            if not player_message:
                continue
            if player_message.lower() in EXIT_COMMANDS:
                break

            result = orchestrator.run_dialogue_turn(
                session_id,
                player_message,
                debug=args.debug,
                debug_sink=_debug_sink if args.debug else None,
            )
            print(f"{character_label}: {result['dialogue']}")
    finally:
        repository.end_session(session_id)
        print(f"会话已结束: {session_id}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return run_chat(args)


if __name__ == "__main__":
    raise SystemExit(main())
