#!/bin/bash
# Memoria 一键启动（Linux / macOS）
# 用法: ./start.sh [--host H] [--port P] [--no-install] [--skip-env]
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "[start] 错误: 未找到 python3，请先安装 Python 3.10+" >&2
    exit 1
fi

exec "$PY" start.py "$@"
