# Memoria - 角色模拟系统

一个基于大语言模型的沉浸式角色扮演对话系统，支持动态记忆管理、情感状态追踪、事件系统和个性化交互体验。

[![GitHub stars](https://img.shields.io/github/stars/nanzi-dev/Memoria?style=social)](https://github.com/nanzi-dev/Memoria)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## 目录

- [Memoria - 角色模拟系统](#memoria---角色模拟系统)
  - [目录](#目录)
  - [核心特性](#核心特性)
    - [深度角色模拟](#深度角色模拟)
    - [三层智能记忆系统](#三层智能记忆系统)
    - [关系与情感追踪](#关系与情感追踪)
    - [多角色对话系统](#多角色对话系统)
    - [事件系统](#事件系统)
    - [沉浸感保护](#沉浸感保护)
    - [多模型支持](#多模型支持)
    - [Web 前端](#web-前端)
  - [系统架构](#系统架构)
  - [快速开始](#快速开始)
    - [环境要求](#环境要求)
    - [Docker 一键部署](#docker-一键部署)
    - [安装步骤](#安装步骤)
  - [文档导航](#文档导航)
  - [环境变量](#环境变量)
  - [运行测试](#运行测试)
  - [许可证](#许可证)
  - [致谢](#致谢)
    - [开源项目](#开源项目)

---

## 核心特性

### 深度角色模拟
- **结构化角色卡系统**：使用 JSON 格式定义角色的完整人格、背景、语言风格和行为模式
- **多维度性格系统**：支持 MBTI、核心特质、价值观、恐惧与禁忌等多维度性格定义
- **动态语言风格**：根据角色设定自动生成符合人设的对话内容和表达方式
- **角色卡管理后台**：Web 界面管理当前用户的角色卡，支持创建、编辑、导入、导出和数据库存储

### 三层智能记忆系统
- **短期记忆**：保留最近对话历史（默认 8 轮），确保上下文连贯性
- **中期记忆**：自动生成会话摘要，支持跨会话记忆持久化
- **长期记忆**：自动提取和存储重要事实，RAG 向量检索智能召回相关记忆
- **记忆萃取引擎**：使用 AI 从对话中智能提取关键信息并评估重要性

### 关系与情感追踪
- **好感度系统**：根据对话内容动态调整角色对玩家的好感度（-100 ~ 100）
- **信任度机制**：追踪角色对玩家的信任程度，影响话题开放度
- **情绪状态**：实时跟踪角色当前情绪，影响对话表现和反应
- **角色关系网络**：支持当前用户私有的角色间关系定义（朋友、敌人、家人、师徒等）并提供网络查询 API

### 多角色对话系统
- **群聊模式**：支持 2-5 个 NPC 同时参与对话
- **讨论模式**：角色可以连续发言，每轮按上下文动态决定回应人数，最多 4 个角色回应，实现真实的群体讨论
- **智能发言策略**：5 种策略（轮询、权重、智能、触发、混合）
- **角色间互动**：角色会相互回应和讨论
- **多角色记忆**：个人记忆、角色间记忆、群体记忆三层管理；群聊结束时统一生成整场摘要并保存为群体记忆
- **动态参与者管理**：支持运行时添加/移除角色

### 事件系统
- **多类型触发条件**：好感度阈值、信任度阈值、关键词匹配、对话次数、时间、情绪、复合条件
- **丰富的事件效果**：状态修改、内容解锁、对话触发、记忆添加、情绪改变、玩家通知、关系修改、事件链、NPC 主动对话
- **事件检测引擎**：自动检测触发条件并按优先级执行
- **冷却时间管理**：支持事件冷却和触发次数限制
- **深度集成**：支持 cron 式时间事件、事件模板库和跨会话事件上下文持久化
- **用户隔离**：角色卡、事件定义和角色关系都按登录用户隔离，不同用户可以使用相同的 `character_id` / `event_id`

### 沉浸感保护
- **AI 身份检测**：自动识别并过滤可能破坏沉浸感的输出
- **角色一致性**：严格约束模型输出，确保始终保持角色人设
- **三层容错机制**：JSON 解析、修复重试、文本兜底

### 多模型支持
- **OpenAI 兼容接口**：支持 DeepSeek、Kimi、Qwen 等多种大模型
- **主辅模型分离**：主对话使用高质量模型，记忆萃取使用轻量模型降低成本
- **JSON 强制输出**：支持结构化输出的模型可获得更好的稳定性

### Web 前端
- **登录与用户资料**：支持用户注册、登录、资料编辑和头像设置
- **角色卡编辑器**：分步编辑角色身份、性格、语言风格、背景和交互规则
- **会话体验**：支持单角色对话、会话恢复、多角色群聊和会话列表
- **管理视图**：提供事件列表/编辑器和角色关系图谱页面

---

## 系统架构

```
Memoria/
├── src/memoria/                # 源代码
│   ├── api/                    # REST API 路由层
│   │   ├── dialogue.py         # 对话相关 API
│   │   ├── character_admin.py  # 角色卡管理 API
│   │   ├── event_admin.py      # 事件管理 API
│   │   ├── multi_dialogue.py   # 多角色对话 API
│   │   ├── relationship.py     # 角色关系 API
│   │   ├── developer.py        # 回放、性能指标、质量评分等开发者 API
│   │   └── user.py             # 用户注册、登录、资料和头像 API
│   ├── characters/             # 角色卡 JSON 配置文件
│   │   ├── npc_luo_xiaohei.json
│   │   ├── npc_wuxian.json
│   │   └── ...
│   ├── core/                   # 核心业务逻辑
│   │   ├── config.py           # 全局配置管理
│   │   ├── orchestrator.py     # 对话编排核心
│   │   ├── llm_client.py       # LLM 调用适配层
│   │   ├── memory_extractor.py # 记忆萃取模块
│   │   ├── prompt_builder.py   # Prompt 组装器
│   │   ├── vector_memory.py    # 向量记忆管理
│   │   ├── character_loader.py # 角色卡加载与缓存
│   │   ├── character_schema.py # 角色卡数据模型
│   │   ├── event_detector.py   # 事件检测引擎
│   │   ├── event_executor.py   # 事件执行器
│   │   ├── event_schema.py     # 事件数据模型
│   │   ├── multi_character_orchestrator.py  # 多角色对话编排
│   │   ├── multi_character_memory.py        # 多角色记忆管理
│   │   └── speaking_strategy.py             # 发言策略系统
│   ├── db/                     # 数据持久化层
│   │   └── repository.py       # SQLite / PostgreSQL 数据库操作
│   └── main.py                 # 应用入口
├── tests/                      # 测试文件
│   ├── test_core.py             # 核心模块测试（60 tests）
│   ├── test_repository.py       # 数据库层测试（39 tests）
│   ├── test_events.py           # 事件系统测试（16 tests）
│   ├── test_orchestrator.py     # 编排器测试（15 tests）
│   ├── test_multi_dialogue_api.py # 多角色 API 测试（14 tests）
│   ├── test_dialogue_api.py     # 单角色 API 测试（7 tests）
│   ├── test_api_models.py       # API 模型测试（19 tests）
│   ├── test_memory_extractor.py # 记忆/提示测试（28 tests）
│   ├── test_cli_debug.py        # CLI debug 标志测试（1 test）
│   ├── test_developer_experience.py # 开发者体验端点测试（5 tests）
│   ├── test_postgres_compat.py  # PostgreSQL 兼容层测试（5 tests）
│   ├── test_security_fixes.py   # 安全回归测试（8 tests）
│   ├── test_system.py           # 系统级测试（12 tests）
│   ├── test_vector_memory.py    # 向量记忆测试（2 tests）
├── docs/                       # 项目文档
│   ├── API.md                  # API 文档
│   ├── ARCHITECTURE.md         # 系统架构与数据库
│   ├── FAQ.md                  # 故障排查
│   ├── ROADMAP.md              # 开发路线图
│   └── CONTRIBUTING.md         # 贡献指南
├── data/                       # 运行时数据
│   ├── sqlite_db/              # SQLite 开发数据库
│   └── chroma_db/              # 向量数据库 (ChromaDB)
├── scripts/                    # 工具脚本
│   ├── chat.sh                 # CLI 聊天启动脚本
│   ├── cli_chat.py             # 命令行对话工具
│   └── run_tests.sh            # 测试执行脚本
├── web/                        # React + Vite 前端
│   ├── src/pages/              # Home、ChatRoom、CharacterEditor、EventList、RelationshipGraph
│   ├── src/components/         # 通用组件与编辑器步骤组件
│   ├── src/context/            # 登录态与对话上下文
│   ├── src/api/                # 前端 API 客户端
│   ├── src/assets/             # 前端静态资源
│   └── package.json            # 前端脚本与依赖
├── config/                     # 配置文件
│   ├── .env.example            # 环境变量模板
│   └── settings.yaml           # 应用配置参考
├── pyproject.toml              # 项目配置
├── requirements.txt            # Python 依赖
└── README.md
```

---

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 18+（运行 Web 前端时需要）
- 支持 OpenAI 兼容接口的大模型 API（DeepSeek、Kimi、Qwen 等）
- Docker / Docker Compose（使用一键部署时需要）

### Docker 一键部署

适合本地体验或生产前验证。默认启动 PostgreSQL、FastAPI 后端和 Nginx 前端：

```bash
cd deploy/docker
cp .env.example .env
# 编辑 .env，至少填入 LLM_API_KEY；生产环境请修改 POSTGRES_PASSWORD
docker compose up
```

启动后访问：

- Web 应用：http://127.0.0.1:8080
- API 文档：http://127.0.0.1:8080/docs
- 后端健康检查：http://127.0.0.1:8080/health

Compose 默认使用 PostgreSQL，并通过 Docker volume 持久化数据库、ChromaDB 和模型缓存。本地 `models/` 会以只读方式挂载到容器；如需使用本地嵌入模型，在 `.env` 中设置：

```bash
EMBEDDING_MODEL=/app/models/sentence-transformers/all-MiniLM-L6-v2
```

常用命令：

```bash
docker compose up --build  # Dockerfile 或依赖变化后强制重建
docker compose logs -f backend
docker compose down
docker compose down -v  # 同时删除 PostgreSQL/ChromaDB/模型缓存数据
```

### 安装步骤

**1. 克隆项目**
```bash
git clone <repository_url>
cd Memoria
```

**2. 创建虚拟环境（推荐）**
```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows
```

**3. 安装依赖**
```bash
pip install -r requirements.txt
```

> 首次启动时会自动下载嵌入模型（约 80MB），用于向量检索功能。

**4. 配置环境变量**
```bash
cp config/.env.example .env
# 编辑 .env 文件，填入你的 API 配置
```

**支持的模型供应商配置示例：**

```bash
# DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# Kimi (Moonshot)
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k

# Qwen (通义千问)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview
```

**5. 启动服务**
```bash
uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

**6. 访问应用**
- API 文档 (Swagger): http://127.0.0.1:8001/docs
- API 文档 (ReDoc): http://127.0.0.1:8001/redoc
- CLI 聊天: `python scripts/cli_chat.py`
- CLI 调试: `python scripts/cli_chat.py --debug`（输出 LLM 请求、Prompt 与原始响应到 stderr）

**7. 启动 Web 前端（可选）**
```bash
cd web
npm install
npm run dev
```

默认访问地址为 http://127.0.0.1:5173。

---

## 文档导航

| 文档 | 内容 |
|------|------|
| [API 文档](docs/API.md) | 完整 REST API 参考（对话/角色卡/事件/关系/多角色/用户/系统管理），含请求/响应示例 |
| [系统架构](docs/ARCHITECTURE.md) | 系统架构设计、完整数据库表结构（17 张表）、三层记忆架构、角色卡开发规范 |
| [开发路线图](docs/ROADMAP.md) | 已完成功能和未来规划 |
| [故障排查](docs/FAQ.md) | 常见问题解决方案、调试技巧、性能优化建议 |
| [贡献指南](docs/CONTRIBUTING.md) | 如何贡献代码、Commit 规范、代码审查标准 |

---

## 环境变量

完整环境变量说明：

```bash
# ====== 大模型 API 配置 ======
LLM_BASE_URL=https://api.deepseek.com/v1      # API 基础 URL
LLM_API_KEY=your-api-key-here                  # API 密钥
LLM_MODEL=deepseek-chat                        # 主对话模型

# 轻量任务专用 API（可选，留空则使用主 LLM）
LLM_LIGHT_BASE_URL=                            # 轻量 API 基础 URL
LLM_LIGHT_API_KEY=                             # 轻量 API 密钥
LLM_LIGHT_MODEL=                               # 轻量模型名称

# ====== 应用配置 ======
DATABASE_PATH=./data/sqlite_db/memoria.db      # SQLite 数据库文件路径（默认开发模式）
DATABASE_URL=                                  # PostgreSQL 连接串；留空时使用 SQLite
AUTH_COOKIE_SECURE=false                       # HTTPS 部署时可设为 true
SHORT_TERM_MEMORY_TURNS=8                      # 短期记忆轮数
MAX_OUTPUT_TOKENS=600                          # 单轮最大输出 token 数

# ====== 向量数据库配置 ======
VECTOR_DB_PATH=./data/chroma_db                # 向量数据库路径
EMBEDDING_MODEL=./models/sentence-transformers/all-MiniLM-L6-v2  # 嵌入模型
VECTOR_SEARCH_TOP_K=10                         # 向量检索返回数量
```

Docker 部署文件统一存放在 `deploy/docker/`。运行时 `deploy/docker/docker-compose.yml` 会自动生成容器内 PostgreSQL 连接串；通常只需要通过 `deploy/docker/.env` 配置 `POSTGRES_*`、`LLM_*`、端口和模型参数。

---

## 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行所有测试；如本地系统端点测试环境会卡住，可传 --ignore=tests/test_system.py
bash scripts/run_tests.sh

PYTHONPATH=src pytest tests/test_core.py -v              # 核心模块
PYTHONPATH=src pytest tests/test_repository.py -v        # 数据库层
PYTHONPATH=src pytest tests/test_events.py -v            # 事件系统
PYTHONPATH=src pytest tests/test_memory_extractor.py -v  # 记忆/提示
PYTHONPATH=src pytest tests/test_multi_dialogue_api.py -v # 多角色 API
PYTHONPATH=src pytest tests/test_system.py -v            # 系统端点与限流
```

当前测试集合以 `pytest --collect-only -q` 为准。

---

## 许可证

本项目使用 **MIT 许可证**。

---

## 致谢

### 开源项目

感谢以下优秀的开源项目：

- **[FastAPI](https://fastapi.tiangolo.com/)** - 现代化、高性能的 Web 框架
- **[Pydantic](https://docs.pydantic.dev/)** - 强大的数据验证库
- **[OpenAI Python SDK](https://github.com/openai/openai-python)** - LLM 客户端库
- **[ChromaDB](https://www.trychroma.com/)** - 向量数据库，支持语义检索
- **[sentence-transformers](https://www.sbert.net/)** - 文本嵌入模型库
- **[Uvicorn](https://www.uvicorn.org/)** - 轻量级 ASGI 服务器
