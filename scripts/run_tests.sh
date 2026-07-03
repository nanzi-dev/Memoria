#!/bin/bash
# Memoria 全量测试执行脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_DIR"

# 激活虚拟环境
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 清除代理环境变量（避免 socks 代理干扰 OpenAI SDK）
unset http_proxy https_proxy all_proxy ALL_PROXY HTTP_PROXY HTTPS_PROXY

echo "========================================"
echo "  Memoria 全量测试"
echo "========================================"
echo ""

# 运行所有测试
PYTHONPATH=src python -m pytest tests/ -v --tb=short "$@"

echo ""
echo "测试完成"
