# Memoria - 角色模拟系统

基于大语言模型的沉浸式角色扮演对话系统，支持动态记忆管理、情感状态追踪、事件系统和多角色群聊。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

## 核心特性

- **深度角色模拟** - 结构化 JSON 角色卡，多维度性格系统，动态语言风格
- **三层记忆系统** - 短期记忆（8轮窗口）、中期记忆（会话摘要）、长期记忆（RAG向量检索）
- **关系与情感追踪** - 好感度（-100~100）、信任度、情绪实时变化
- **多角色对话** - 2-5个NPC群聊，5种发言策略，讨论模式，角色间互动
- **事件系统** - 好感度/关键词/情绪等多类型触发，丰富事件效果，冷却管理
- **多模型支持** - OpenAI 兼容接口，支持 DeepSeek / Kimi / Qwen 等

## 快速开始

```bash
# 克隆项目
git clone <repository_url>
cd Memoria

# 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp config/.env.example .env
# 编辑 .env，填入 LLM_API_KEY

# 启动服务
uvicorn memoria.main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问:
- API 文档: http://localhost:8000/docs
- CLI 聊天: `python scripts/cli_chat.py`

## 项目结构

```
Memoria/
├── src/memoria/        # 源代码
│   ├── api/            # REST API 端点
│   ├── core/           # 核心业务逻辑
│   ├── db/             # 数据持久化层
│   └── characters/     # 角色卡 JSON 文件
├── tests/              # 测试文件
├── docs/               # 完整文档
├── data/               # 运行时数据（SQLite + ChromaDB）
├── scripts/            # 工具脚本（CLI聊天、测试）
└── config/             # 配置模板
```

## 文档

| 文档 | 内容 |
|------|------|
| [API 文档](docs/API.md) | 完整 REST API 参考（对话、角色卡、事件、关系、多角色） |
| [系统架构](docs/ARCHITECTURE.md) | 架构设计、数据库结构、角色卡规范 |
| [开发路线图](docs/ROADMAP.md) | 已完成和计划中的功能 |
| [故障排查](docs/FAQ.md) | 常见问题和调试技巧 |

## 环境变量

```bash
# LLM API
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-key
LLM_MODEL=deepseek-chat

# 应用配置
DATABASE_PATH=./data/sqlite_db/memoria.db
VECTOR_DB_PATH=./data/chroma_db
SHORT_TERM_MEMORY_TURNS=8
```

## 运行测试

```bash
pip install -e ".[dev]"
PYTHONPATH=src pytest tests/ -v
```

## 许可证

MIT License
