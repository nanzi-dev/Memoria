#!/bin/bash
# Memoria CLI Chat 快捷启动脚本

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 激活虚拟环境（如果存在）
if [ -d "$PROJECT_DIR/.venv" ]; then
    source "$PROJECT_DIR/.venv/bin/activate"
fi

# 运行 CLI 聊天程序
python "$SCRIPT_DIR/cli_chat.py" "$@"
