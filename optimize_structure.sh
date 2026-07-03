#!/bin/bash
# Memoria 项目结构优化脚本
# 使用方式: ./optimize_structure.sh [--dry-run]

set -e  # 遇到错误立即退出

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查是否为 dry-run 模式
DRY_RUN=false
if [ "$1" == "--dry-run" ]; then
    DRY_RUN=true
    echo -e "${YELLOW}🔍 Dry-run 模式：只显示将要执行的操作，不实际执行${NC}"
    echo ""
fi

echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Memoria 项目结构优化脚本                            ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

# 获取项目根目录
PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo -e "${GREEN}📍 项目根目录: $PROJECT_ROOT${NC}"
echo ""

# 函数：执行或显示命令
execute_or_show() {
    local cmd="$1"
    local desc="$2"
    
    echo -e "${YELLOW}▸ $desc${NC}"
    echo "  命令: $cmd"
    
    if [ "$DRY_RUN" = true ]; then
        echo -e "  ${BLUE}(dry-run: 跳过执行)${NC}"
    else:
        eval "$cmd"
        if [ $? -eq 0 ]; then
            echo -e "  ${GREEN}✓ 完成${NC}"
        else
            echo -e "  ${RED}✗ 失败${NC}"
            return 1
        fi
    fi
    echo ""
}

# 步骤 1: 创建备份
echo -e "${GREEN}═══ 步骤 1: 创建备份 ═══${NC}"
echo ""

BACKUP_FILE="memoria_backup_$(date +%Y%m%d_%H%M%S).tar.gz"
execute_or_show \
    "tar -czf $BACKUP_FILE sqlite_db/ chroma_db/ .env 2>/dev/null || true" \
    "创建数据文件备份: $BACKUP_FILE"

# 步骤 2: 创建新目录结构
echo -e "${GREEN}═══ 步骤 2: 创建新目录结构 ═══${NC}"
echo ""

execute_or_show "mkdir -p docs" "创建 docs/ 目录"
execute_or_show "mkdir -p data/sqlite" "创建 data/sqlite/ 目录"
execute_or_show "mkdir -p data/chroma" "创建 data/chroma/ 目录"
execute_or_show "mkdir -p scripts" "创建 scripts/ 目录"
execute_or_show "touch data/.gitkeep" "创建 data/.gitkeep"

# 步骤 3: 移动文档文件
echo -e "${GREEN}═══ 步骤 3: 移动文档文件 ═══${NC}"
echo ""

if [ -f "CLI_CHAT_GUIDE.md" ]; then
    execute_or_show "mv CLI_CHAT_GUIDE.md docs/" "移动 CLI_CHAT_GUIDE.md"
fi

if [ -f "DISCUSSION_MODE_GUIDE.md" ]; then
    execute_or_show "mv DISCUSSION_MODE_GUIDE.md docs/" "移动 DISCUSSION_MODE_GUIDE.md"
fi

if [ -f "MULTI_CHARACTER_IMPLEMENTATION.md" ]; then
    execute_or_show "mv MULTI_CHARACTER_IMPLEMENTATION.md docs/" "移动 MULTI_CHARACTER_IMPLEMENTATION.md"
fi

if [ -f "PROJECT_STRUCTURE_OPTIMIZATION.md" ]; then
    execute_or_show "mv PROJECT_STRUCTURE_OPTIMIZATION.md docs/" "移动 PROJECT_STRUCTURE_OPTIMIZATION.md"
fi

# 步骤 4: 移动脚本文件
echo -e "${GREEN}═══ 步骤 4: 移动脚本文件 ═══${NC}"
echo ""

if [ -f "chat.sh" ]; then
    execute_or_show "mv chat.sh scripts/" "移动 chat.sh"
    execute_or_show "chmod +x scripts/chat.sh" "设置 chat.sh 可执行权限"
fi

if [ -f "run_all_tests.sh" ]; then
    execute_or_show "mv run_all_tests.sh scripts/run_tests.sh" "移动并重命名 run_all_tests.sh"
    execute_or_show "chmod +x scripts/run_tests.sh" "设置 run_tests.sh 可执行权限"
fi

# 步骤 5: 创建文档索引
echo -e "${GREEN}═══ 步骤 5: 创建文档索引 ═══${NC}"
echo ""

if [ "$DRY_RUN" = false ] && [ ! -f "docs/INDEX.md" ]; then
    cat > docs/INDEX.md << 'EOF'
# Memoria 文档索引

## 📚 核心文档

- [README](../README.md) - 项目主文档
- [多角色对话实现](MULTI_CHARACTER_IMPLEMENTATION.md) - 技术实现细节
- [CLI Chat 使用指南](CLI_CHAT_GUIDE.md) - 命令行工具使用
- [讨论模式指南](DISCUSSION_MODE_GUIDE.md) - 讨论模式详解
- [项目结构优化](PROJECT_STRUCTURE_OPTIMIZATION.md) - 结构优化方案

## 🔧 开发文档

- [API 文档](http://localhost:8000/docs) - FastAPI 自动生成的 API 文档

## 🎯 快速链接

- [快速开始](../README.md#快速开始)
- [API 端点](../README.md#api-文档)
- [多角色对话系统](../README.md#多角色对话系统)

## 📖 使用指南

### 新手入门
1. 阅读 [README](../README.md) 了解项目概况
2. 按照 [快速开始](../README.md#快速开始) 配置环境
3. 使用 [CLI Chat 使用指南](CLI_CHAT_GUIDE.md) 体验对话系统

### 开发者
1. 查看 [项目结构优化](PROJECT_STRUCTURE_OPTIMIZATION.md) 了解目录结构
2. 阅读 [多角色对话实现](MULTI_CHARACTER_IMPLEMENTATION.md) 了解技术细节
3. 访问 [API 文档](http://localhost:8000/docs) 查看接口定义

### 高级功能
- [讨论模式指南](DISCUSSION_MODE_GUIDE.md) - 多角色连续讨论功能
EOF
    echo -e "${GREEN}✓ 创建 docs/INDEX.md${NC}"
    echo ""
else
    echo -e "${BLUE}(docs/INDEX.md 已存在或 dry-run 模式)${NC}"
    echo ""
fi

# 步骤 6: 更新 requirements.txt
echo -e "${GREEN}═══ 步骤 6: 检查 requirements.txt ═══${NC}"
echo ""

if grep -q "overrides" requirements.txt 2>/dev/null; then
    echo -e "${GREEN}✓ overrides 依赖已存在${NC}"
else
    echo -e "${YELLOW}⚠ overrides 依赖缺失${NC}"
    echo "  建议添加: overrides==7.4.0"
    
    if [ "$DRY_RUN" = false ]; then
        read -p "  是否现在添加？(y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            echo "overrides==7.4.0  # 向量存储依赖" >> requirements.txt
            echo -e "${GREEN}✓ 已添加${NC}"
        fi
    fi
fi
echo ""

# 步骤 7: 数据库迁移（可选，需要用户确认）
echo -e "${GREEN}═══ 步骤 7: 数据库迁移（可选）═══${NC}"
echo ""
echo -e "${YELLOW}⚠ 数据库迁移需要修改配置文件和移动数据${NC}"
echo -e "${YELLOW}  建议手动执行以确保数据安全${NC}"
echo ""

if [ "$DRY_RUN" = false ]; then
    read -p "是否现在迁移数据库？(y/n) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo ""
        echo -e "${BLUE}开始数据库迁移...${NC}"
        
        # 移动 SQLite 数据库
        if [ -d "sqlite_db" ] && [ -n "$(ls -A sqlite_db)" ]; then
            execute_or_show "cp -r sqlite_db/* data/sqlite/" "复制 SQLite 数据库"
        fi
        
        # 移动 ChromaDB
        if [ -d "chroma_db" ] && [ -n "$(ls -A chroma_db)" ]; then
            execute_or_show "cp -r chroma_db/* data/chroma/" "复制 ChromaDB"
        fi
        
        echo ""
        echo -e "${YELLOW}⚠ 数据已复制，原目录保留${NC}"
        echo -e "${YELLOW}  验证无误后可手动删除 sqlite_db/ 和 chroma_db/${NC}"
        echo ""
        echo -e "${YELLOW}⚠ 还需要更新 app/core/config.py 中的路径：${NC}"
        echo -e "  database_path: str = \"./data/sqlite/memoria.db\""
        echo -e "  vector_db_path: str = \"./data/chroma\""
        echo ""
    fi
fi

# 步骤 8: 更新 .gitignore
echo -e "${GREEN}═══ 步骤 8: 更新 .gitignore ═══${NC}"
echo ""

if [ -f ".gitignore" ]; then
    if grep -q "data/sqlite" .gitignore 2>/dev/null; then
        echo -e "${GREEN}✓ .gitignore 已包含 data/ 规则${NC}"
    else
        echo -e "${YELLOW}⚠ .gitignore 需要更新${NC}"
        
        if [ "$DRY_RUN" = false ]; then
            read -p "  是否现在更新？(y/n) " -n 1 -r
            echo
            if [[ $REPLY =~ ^[Yy]$ ]]; then
                cat >> .gitignore << 'EOF'

# 数据文件
data/sqlite/*.db
data/chroma/*
!data/.gitkeep
EOF
                echo -e "${GREEN}✓ 已更新 .gitignore${NC}"
            fi
        fi
    fi
else
    echo -e "${RED}✗ .gitignore 文件不存在${NC}"
fi
echo ""

# 总结
echo -e "${BLUE}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     优化完成总结                                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}Dry-run 模式完成！${NC}"
    echo "要实际执行优化，请运行："
    echo "  ./optimize_structure.sh"
else
    echo -e "${GREEN}✓ 项目结构优化完成！${NC}"
    echo ""
    echo "已完成的操作："
    echo "  ✓ 创建备份: $BACKUP_FILE"
    echo "  ✓ 创建 docs/ 目录"
    echo "  ✓ 创建 data/ 目录"
    echo "  ✓ 创建 scripts/ 目录"
    echo "  ✓ 移动文档文件"
    echo "  ✓ 移动脚本文件"
    echo "  ✓ 创建文档索引"
    echo ""
    echo "后续步骤："
    echo "  1. 检查新目录结构是否正确"
    echo "  2. 如果迁移了数据库，更新 app/core/config.py"
    echo "  3. 运行测试验证: ./scripts/run_tests.sh"
    echo "  4. 启动服务器验证: uvicorn app.main:app --reload"
    echo "  5. 验证无误后删除旧目录"
    echo ""
    echo "文档索引: docs/INDEX.md"
fi

echo ""
echo -e "${GREEN}完成！${NC}"
