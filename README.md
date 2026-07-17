# Memoria - 角色模拟系统

一个基于大语言模型的沉浸式角色扮演对话系统，支持动态记忆管理、外部知识库 RAG、情感状态追踪、事件系统、中英双语会话和语音交互。

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
    - [外部知识库 RAG](#外部知识库-rag)
    - [关系与情感追踪](#关系与情感追踪)
    - [多角色对话系统](#多角色对话系统)
    - [多语言与语音](#多语言与语音)
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
- **图谱修订隔离**：角色关系图谱更新或删除后，单聊和群聊生成上下文只过滤图谱变更前的旧关系事实；普通长期记忆、共同经历和世界事实继续保留。最近对话里若出现与当前图谱冲突的关系表述，也会在送入模型前跳过，避免旧关系覆盖当前图谱

### 外部知识库 RAG
- **多格式文档导入**：支持上传 UTF-8 TXT、Markdown、PDF、DOCX，或直接粘贴文本
- **异步处理与状态恢复**：文档按 `queued → processing → ready/failed` 流转；前端自动轮询，服务重启后会恢复排队中或被中断的任务
- **精细绑定范围**：知识库可绑定为全局、指定角色或指定群聊线程，并可随时启用、禁用
- **安全检索注入**：单聊和群聊按绑定范围检索知识块，知识内容只作为低优先级世界事实，不执行文档中的指令
- **来源可追溯**：对话响应返回 `knowledge_sources`，管理页支持检索预览、失败原因展示和重试

### 关系与情感追踪
- **好感度系统**：根据对话内容动态调整角色对玩家的好感度（-100 ~ 100）
- **信任度机制**：追踪角色对玩家的信任程度，影响话题开放度
- **情绪状态**：实时跟踪角色当前情绪，影响对话表现和反应
- **角色关系网络**：支持当前用户私有的角色间关系定义并提供网络查询 API；关系类型是可自定义文本，不限制固定枚举。单聊和群聊都以当前关系图谱为最高优先级，缺失关系边表示未定义关系；`affinity` 在 prompt 中作为中性的关系强度呈现，具体含义以关系类型和说明为准

### 多角色对话系统
- **群聊模式**：每个群聊至少需要 2 个不重复 NPC；公开 API 当前不设置参与人数上限
- **讨论模式**：角色可以连续发言，`max_responses` 接受 1-5，编排器按上下文动态决定回应人数，当前每个玩家轮次最多 3 个角色回应
- **智能发言策略**：固定使用混合策略，优先处理关键词与角色点名，再综合关系、发言频率、均衡性和最近发言上下文选择角色
- **角色间互动**：角色会相互回应和讨论
- **多角色记忆**：个人记忆、角色间记忆、群体记忆三层管理；群聊结束时统一生成整场摘要并保存为群体记忆
- **逻辑群聊线程**：`group_thread_id` 跨越物理 session 保持不变，结束后续聊仍可读取完整历史；历史消息提供稳定 `message_id`，支持按游标增量同步
- **群聊脉冲**：世界时钟调度器可触发有剧情动机的 NPC 自主发言，事件效果也可立即触发群聊发言；当前每次脉冲最多提交 1 条角色消息
- **未读聚合通知**：自主/事件脉冲在提交消息时原子创建线程级未读通知，客户端同步到最新消息后可整线程标记已读
- **SSE 流式回复**：单聊和玩家发起的群聊轮次支持 Server-Sent Events，提供阶段、角色开始、增量文本、角色完成和最终结果事件

### 多语言与语音
- **会话语言切换**：单聊和群聊支持 `zh-CN` / `en-US`，会话持久化语言并向 Prompt 注入最高优先级语言约束
- **角色卡 i18n**：角色卡可为中英文维护局部覆盖，加载时按会话语言深度合并
- **语音输入**：浏览器录音上传到认证 STT 接口，按会话语言转写，可配置自动发送
- **语音播放**：单聊和群聊的角色消息支持 TTS、自动播放和本地文件缓存
- **角色声音**：支持内置声音与自定义声音授权、创建、状态查询和解绑；自定义声音不可用时回退内置声音

### 事件系统
- **多类型触发条件**：好感度阈值、信任度阈值、关键词匹配、对话次数、时间、情绪、复合条件
- **丰富的事件效果**：状态修改、内容解锁、对话触发、记忆添加、情绪改变、玩家通知、关系修改、事件链、NPC 主动对话
- **事件检测引擎**：自动检测触发条件并按优先级执行
- **冷却时间管理**：支持事件冷却和触发次数限制
- **深度集成**：支持 cron 式时间事件、事件模板库和跨会话事件上下文持久化
- **用户隔离**：角色卡、事件定义和角色关系都按登录用户隔离，不同用户可以使用相同的 `character_id` / `event_id`
- **世界时钟与通知**：每个用户拥有独立的 IANA 时区和 0/1/2/5/10 倍世界时间；事件通知持久化到用户收件箱并支持已读状态
- **事件模拟**：管理 API 可在不执行、不写入副作用的情况下评估事件条件并预览计划结果

### 沉浸感保护
- **AI 身份检测**：自动识别并过滤可能破坏沉浸感的输出
- **角色一致性**：严格约束模型输出，确保始终保持角色人设
- **三层容错机制**：JSON 解析、修复重试、文本兜底

### 多模型支持
- **OpenAI 兼容接口**：支持 DeepSeek、Kimi、Qwen 等多种大模型
- **主辅模型分离**：主对话使用高质量模型，记忆萃取使用轻量模型降低成本
- **JSON 强制输出**：支持结构化输出的模型可获得更好的稳定性

### Web 前端
- **登录与用户资料**：支持用户注册、登录、资料编辑和头像设置；浏览器登录态只使用 HttpOnly Cookie，不把 token 持久化到 `localStorage`
- **玩家角色卡**：独立编辑玩家名称、头像、身份、外观、性格、背景和目标，并从下一条单聊或群聊消息开始参与 Prompt 与关系图谱
- **角色卡编辑器**：分步编辑角色身份、性格、语言风格、背景和交互规则；界面只编辑基础角色卡，不提供 i18n 版本切换，导入或已有的中英文覆盖数据会继续保留
- **会话体验**：支持单角色对话、会话恢复、多角色群聊、会话语言选择、录音转写和角色语音播放；好感度/信任度变化只在当前会话新回复上展示，历史加载消息不回放旧变化提示
- **流式与群聊同步**：单聊和群聊按 SSE 增量展示回复；群聊使用逻辑线程合并续聊历史，并同步自主脉冲产生的新消息和聚合未读状态
- **管理工作台**：事件与知识库页面采用左右分栏工作台，支持汇总、搜索、筛选、排序、详情查看及编辑；事件关联角色可直接选择当前用户已有角色
- **用户设置**：账户、世界时间和语音设置分区管理；世界时钟按 IANA 时区展示，支持暂停、同步、设置、推进及 `0/1/2/5/10` 倍速

---

## 系统架构

```
Memoria/
├── src/memoria/                # 源代码
│   ├── api/                    # REST API 路由层
│   │   ├── dialogue.py         # 对话相关 API
│   │   ├── streaming.py        # 同步编排器到 SSE 的流式桥接
│   │   ├── character_admin.py  # 角色卡管理 API
│   │   ├── event_admin.py      # 事件管理 API
│   │   ├── multi_dialogue.py   # 多角色对话 API
│   │   ├── relationship.py     # 角色关系 API
│   │   ├── knowledge.py        # 知识库、文档与检索预览 API
│   │   ├── speech.py           # STT、TTS 与角色自定义声音 API
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
│   │   ├── knowledge_documents.py    # 知识文档校验、提取与切块
│   │   ├── knowledge_service.py      # 文档持久化与异步索引
│   │   ├── knowledge_retriever.py    # 知识检索、排序与 Prompt 注入
│   │   ├── knowledge_vector_store.py # 知识向量存储
│   │   ├── world_clock.py      # 用户世界时钟
│   │   ├── locale.py           # 会话语言约束与 STT 语言映射
│   │   ├── speech_provider.py  # MiniMax TTS / OpenAI-compatible STT 适配层
│   │   ├── speech_service.py   # 语音鉴权、缓存与角色声音工作流
│   │   ├── character_loader.py # 角色卡加载与缓存
│   │   ├── character_schema.py # 角色卡数据模型
│   │   ├── event_detector.py   # 事件检测引擎
│   │   ├── event_executor.py   # 事件执行器
│   │   ├── event_runtime.py    # 事件上下文、检测、规划与执行协调
│   │   ├── event_schema.py     # 事件数据模型
│   │   ├── multi_character_orchestrator.py  # 多角色对话编排
│   │   ├── multi_character_memory.py        # 多角色记忆管理
│   │   ├── group_dialogue_runtime.py         # 逻辑群聊自主/事件脉冲运行时
│   │   ├── background_jobs.py                # 持久化 checkpoint 记忆任务工作器
│   │   ├── domain_events.py                  # 领域事件账本与剧情状态投影
│   │   └── speaking_strategy.py             # 发言策略系统
│   ├── db/                     # 数据持久化层
│   │   └── repository.py       # SQLite / PostgreSQL 数据库操作
│   └── main.py                 # 应用入口
├── tests/                      # pytest 测试（核心、API、安全、知识库、世界时钟等）
├── docs/                       # 项目文档
│   ├── API.md                  # API 文档
│   ├── ARCHITECTURE.md         # 系统架构与数据库
│   ├── FAQ.md                  # 故障排查
│   ├── ROADMAP.md              # 开发路线图
│   └── CONTRIBUTING.md         # 贡献指南
├── data/                       # 运行时数据
│   ├── sqlite_db/              # SQLite 开发数据库
│   ├── chroma_db/              # 向量数据库 (ChromaDB)
│   ├── knowledge/              # 知识库上传原文件
│   └── speech/                 # TTS 文件缓存
├── scripts/                    # 工具脚本
│   ├── chat.sh                 # CLI 聊天启动脚本
│   ├── cli_chat.py             # 命令行对话工具
│   └── run_tests.sh            # 测试执行脚本
├── web/                        # React + Vite 前端
│   ├── src/pages/              # Home、ChatRoom、CharacterEditor、PersonaEditor、EventList、EventEditor、RelationshipGraph、KnowledgeManager
│   ├── src/components/         # 通用组件与编辑器步骤组件
│   ├── src/context/            # 登录态与对话上下文
│   ├── src/api/                # 前端 API 客户端
│   ├── src/assets/             # 前端静态资源
│   └── package.json            # 前端脚本与依赖
├── config/                     # 配置文件
│   ├── .env.example            # 环境变量模板
│   └── settings.yaml           # 兼容性/参考标记，不参与运行时加载
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
# 编辑 .env，填入 LLM_API_KEY，并设置高强度且唯一的 POSTGRES_PASSWORD（必填）
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
| [API 文档](docs/API.md) | 完整 REST API 参考（对话/角色卡/事件/关系/多角色/知识库/语音/用户/系统管理），含请求/响应示例 |
| [系统架构](docs/ARCHITECTURE.md) | 系统架构设计、完整数据库表结构（39 张表）、记忆、知识检索与语音架构、角色卡开发规范 |
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
LLM_TIMEOUT_SECONDS=45                         # 单次 LLM 请求超时
LLM_LIGHT_TIMEOUT_SECONDS=12                   # 轻量任务单次请求超时
MAX_OUTPUT_TOKENS=400                          # 主模型单次最大输出 token 数

# 轻量任务专用 API（可选，留空则使用主 LLM）
LLM_LIGHT_BASE_URL=                            # 轻量 API 基础 URL
LLM_LIGHT_API_KEY=                             # 轻量 API 密钥
LLM_LIGHT_MODEL=                               # 轻量模型名称
LIGHT_TASK_MAX_OUTPUT_TOKENS=400               # 轻量任务单次最大输出 token 数

# ====== Speech 配置（可选） ======
# TTS 默认使用 MiniMax 流式合成；STT 使用独立 OpenAI-compatible 转写端点
SPEECH_TTS_PROVIDER=minimax
SPEECH_TTS_API_KEY=                            # MiniMax API 密钥
SPEECH_TTS_BASE_URL=https://api.minimax.io/v1
SPEECH_TTS_MODEL=speech-2.8-turbo
SPEECH_TTS_TIMEOUT_SECONDS=30
SPEECH_TTS_MAX_RETRIES=1
SPEECH_TTS_DEFAULT_VOICE=female-shaonv
SPEECH_STT_PROVIDER=openai_compatible
SPEECH_STT_API_KEY=                            # ASR API 密钥
SPEECH_STT_BASE_URL=https://api.openai.com/v1
SPEECH_STT_MODEL=gpt-4o-mini-transcribe
SPEECH_STT_TIMEOUT_SECONDS=30
SPEECH_STT_MAX_RETRIES=1
SPEECH_OUTPUT_FORMAT=mp3
SPEECH_STORAGE_PATH=./data/speech

# ====== 应用配置 ======
DATABASE_PATH=./data/sqlite_db/memoria.db      # SQLite 数据库文件路径（默认开发模式）
DATABASE_URL=                                  # PostgreSQL 连接串；留空时使用 SQLite
AUTH_COOKIE_SECURE=false                       # 本地 HTTP 为 false；HTTPS 部署必须设为 true
SHORT_TERM_MEMORY_TURNS=8                      # 短期记忆轮数
LONG_TERM_MEMORY_INTERVAL_TURNS=5              # 每隔多少个玩家回合保存一次长期记忆
WORLD_CLOCK_SCHEDULER_INTERVAL_SECONDS=30      # 世界时钟调度扫描间隔
WORLD_CLOCK_SCHEDULER_LEASE_SECONDS=90         # 到期事件调度租约

# ====== 向量数据库配置 ======
VECTOR_DB_PATH=./data/chroma_db                # 向量数据库路径
EMBEDDING_MODEL=./models/sentence-transformers/all-MiniLM-L6-v2  # 嵌入模型
VECTOR_SEARCH_TOP_K=10                         # 向量检索返回数量
KNOWLEDGE_RETRIEVAL_TOP_K=4                    # 每轮知识注入来源上限
KNOWLEDGE_SIMILARITY_THRESHOLD=0.60            # 知识检索最低相似度
```

运行时配置统一由 `src/memoria/core/config.py` 的 `Configs` 定义，并通过环境变量或仓库根目录 `.env` 注入；`config/settings.yaml` 仅是兼容性/参考标记。默认知识上传限制为 10 MiB、Top-K 为 4、相似度阈值为 0.60；分块目标为 200 token、重叠 36 token、硬上限 240 token。

语音的 TTS 与 STT 分别配置。TTS 默认使用 MiniMax 的 T2A v2 流式响应：浏览器在收到首个音频分块后即可播放，完整 MP3 会原子写入 `SPEECH_STORAGE_PATH/cache` 供历史消息复播。STT 始终调用独立的 OpenAI-compatible `/audio/transcriptions` 端点，不会请求 MiniMax TTS 地址。角色 Custom Voice 需要先上传授权录音，再上传参考样本；成功后会持久化 MiniMax `voice_id`，失败时继续回退到角色的内置音色。旧的 `SPEECH_PROVIDER`、`SPEECH_API_KEY`、`SPEECH_BASE_URL` 和 `SPEECH_TIMEOUT_SECONDS` 仅作为迁移回退，并会发出弃用警告。

Docker 部署文件统一存放在 `deploy/docker/`。运行时 `deploy/docker/docker-compose.yml` 会自动生成容器内 PostgreSQL 连接串；通常只需要通过 `deploy/docker/.env` 配置 `POSTGRES_*`、`LLM_*`、语音、端口和模型参数。后端直连端口默认绑定 `127.0.0.1`，显式设置 `API_BIND_HOST=0.0.0.0` 才会对所有网络接口开放。

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

当前测试集合以 `pytest --collect-only -q` 为准，覆盖核心编排、持久化、事件、单聊/群聊 API、安全、知识库、语音、向量存储、世界时钟和系统端点。前端测试由 `npm test` 收集。

---

## 许可证

本项目使用 [MIT 许可证](LICENSE)。

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
