#!/bin/bash
# Memoria CLI Chat 快捷启动脚本

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 激活虚拟环境（如果存在）
if [ -d "$SCRIPT_DIR/.venv" ]; then
    source "$SCRIPT_DIR/.venv/bin/activate"
fi

# 运行 CLI 聊天程序
python "$SCRIPT_DIR/app/scripts/cli_chat.py" "$@"
