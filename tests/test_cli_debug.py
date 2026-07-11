"""
CLI 调试模式测试
"""
import importlib.util
from pathlib import Path


def load_cli_chat_module():
    project_root = Path(__file__).resolve().parent.parent
    module_path = project_root / "scripts" / "cli_chat.py"
    spec = importlib.util.spec_from_file_location("cli_chat", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_parses_debug_flag():
    cli_chat = load_cli_chat_module()
    parser = cli_chat.build_parser()

    args = parser.parse_args([
        "--debug",
        "--character-id", "npc_test",
        "--player-id", "player_test",
        "--player-name", "测试者",
    ])

    assert args.debug is True
    assert args.character_id == "npc_test"
    assert args.player_id == "player_test"
    assert args.player_name == "测试者"
