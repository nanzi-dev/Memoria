# Memoria 系统架构

## 项目结构

```
Memoria/
├── src/memoria/                # 源代码
│   ├── api/                    # REST API 路由层
│   │   ├── dialogue.py         # 对话相关 API（角色列表、会话、对话轮次）
│   │   ├── character_admin.py  # 角色卡管理 API（CRUD、导入导出）
│   │   ├── event_admin.py      # 事件管理 API（CRUD、触发历史）
│   │   ├── multi_dialogue.py   # 多角色对话 API（群聊、互动、参与者管理）
│   │   ├── relationship.py     # 角色关系 API（关系CRUD、网络查询）
│   │   ├── knowledge.py        # 知识库、文档、绑定和检索预览 API
│   │   ├── developer.py        # 回放、性能指标、质量评分等开发者 API
│   │   └── user.py             # 用户注册、登录、资料和头像 API
│   ├── characters/             # 角色卡 JSON 配置文件
│   │   ├── npc_luo_xiaohei.json
│   │   ├── npc_wuxian.json
│   │   ├── npc_blacksmith_garran.json
│   │   ├── npc_luye.json
│   │   └── npc_merchant_lina.json
│   ├── core/                   # 核心业务逻辑
│   │   ├── config.py           # 全局配置管理 (Pydantic Settings + .env)
│   │   ├── orchestrator.py     # 单角色对话编排核心
│   │   ├── llm_client.py       # LLM 调用适配层（懒加载 + 指数退避重试） (OpenAI SDK)
│   │   ├── memory_extractor.py # 记忆萃取模块
│   │   ├── prompt_builder.py   # Prompt 组装器
│   │   ├── vector_memory.py    # 向量记忆管理（懒加载） (ChromaDB)
│   │   ├── knowledge_documents.py    # 知识文档校验、提取与切块
│   │   ├── knowledge_service.py      # 文档存储与异步索引
│   │   ├── knowledge_retriever.py    # 知识检索、排序与 Prompt 注入
│   │   ├── knowledge_vector_store.py # 知识向量存储（线程安全懒加载）
│   │   ├── world_clock.py      # 用户世界时钟计算与持久化
│   │   ├── character_loader.py # 角色卡加载与 LRU 缓存
│   │   ├── character_schema.py # 角色卡 Pydantic 数据模型
│   │   ├── event_detector.py   # 事件检测引擎
│   │   ├── event_executor.py   # 事件执行器
│   │   ├── event_schema.py     # 事件数据模型
│   │   ├── multi_character_orchestrator.py  # 多角色对话编排
│   │   ├── multi_character_memory.py        # 多角色记忆管理
│   │   ├── performance.py      # 开发者性能采样
│   │   ├── replay.py           # 会话回放构建
│   │   ├── quality_scorer.py   # 对话质量评分
│   │   ├── tracing.py          # OpenTelemetry 可选追踪封装
│   │   └── speaking_strategy.py             # 发言策略系统（5种策略）
│   ├── db/                     # 数据持久化层
│   │   └── repository.py       # SQLite / PostgreSQL 数据库操作
│   └── main.py                 # FastAPI 应用入口
├── tests/                      # 测试（pytest）
├── data/                       # 运行时数据
│   ├── sqlite_db/memoria.db    # SQLite 开发数据库
│   ├── chroma_db/              # ChromaDB 向量数据库
│   └── knowledge/              # 知识文档原文件
├── docs/                       # 项目文档
├── scripts/                    # 工具脚本
│   ├── cli_chat.py             # 命令行对话工具
│   ├── chat.sh                 # CLI 快捷启动
│   └── run_tests.sh            # 测试执行
├── web/                        # React + Vite 前端
│   ├── src/pages/              # Home、ChatRoom、CharacterEditor、EventList、RelationshipGraph
│   ├── src/components/         # 通用组件与编辑器步骤组件
│   ├── src/context/            # 登录态与对话上下文
│   ├── src/api/                # 前端 API 客户端
│   ├── src/assets/             # 前端静态资源
│   └── package.json            # npm 脚本与依赖声明
├── config/                     # 配置模板
│   ├── .env.example
│   └── settings.yaml
├── pyproject.toml              # 项目配置 (src layout)
└── requirements.txt
```

---

## 系统管理端点

- `GET /health` — 存活检查，返回 `{"status": "ok", "version": "0.4.0"}`
- `GET /ready` — 数据库就绪检查，失败返回 503
- `POST /admin/log-level?level=DEBUG` — 动态调整日志级别，需要登录态

API 写操作通过速率限制中间件保护（60 请求 / 60 秒窗口）。限流 key 优先使用认证 token 解析出的用户 ID，未登录或 token 无效时退回客户端 IP，不信任客户端传入的 `X-Player-ID`。

## 核心架构模式

### 对话编排器 (Orchestrator)

单角色对话的核心流程：

```
玩家消息
  → 加载角色卡 (LRU缓存)
  → 加载运行时状态 (好感度、信任度、情绪)
  → 按全局/角色绑定检索外部知识库
  → 向量检索相关长期记忆
  → 获取近期会话摘要
  → 构建系统 Prompt（角色设定 + 记忆 + 状态）
  → 组装对话历史（短期记忆窗口）
  → 调用 LLM 生成回复
  → JSON 解析响应（三层容错）
  → 萃取新记忆并评估重要性
  → 更新好感度/信任度/情绪
  → 检测并执行事件
  → 保存对话状态与短期/长期记忆
  → 返回角色回复
```

事件系统异常只会记录日志，不会阻断对话状态、短期消息和长期记忆的持久化。

### 多角色对话编排器 (MultiCharacterOrchestrator)

```
玩家消息
  → 加载所有参与角色卡和状态
  → 加载当前用户的角色关系图谱
  → 按全局/角色/群聊线程绑定检索外部知识库
  → 根据关系图谱最近修订时间计算历史截止点
  → 构建多角色上下文（个人记忆 + 角色间记忆 + 群体记忆）
  → 跳过与当前图谱冲突的最近关系历史
  → 发言策略选择发言角色
  → 构建多角色 System Prompt（含其他角色信息、关系）
  → 调用 LLM 生成回复
  → 更新参与者统计和关系
  → 保存玩家消息和角色回复
  → 返回单角色或多角色讨论回复
  → 会话结束时生成整场摘要并写入 session_summary / group_memory
```

单聊和多角色 Prompt 都会把个人长期记忆、角色间共享记忆和 `group_memory` 群体记忆整合为上下文。关系图谱是角色间关系的最高优先级来源：当前图谱中存在的边覆盖旧关系事实，当前图谱缺失的边视为未定义关系，旧长期记忆或历史发言不能恢复已删除、已改写的关系。

每次创建、更新、删除角色关系都会刷新 `character_relationship_revision`。单聊编排器会读取该角色相关关系，群聊编排器会取参与角色两两关系的最新修订时间作为截止点：长期记忆、角色间共享记忆和群体记忆会先读取候选记录，再只剔除修订时间之前的关系相关旧事实；普通玩家事实、共同经历和世界事实不会因为图谱更新而消失。跨 session 原始群聊历史和群聊结束摘要提取仍使用同一截止点，避免旧发言把旧关系状态重新写回长期记忆。当前实现不会在每个玩家轮次写入群体记忆；群聊结束且有效消息数大于 6 条、摘要模型返回非空内容时，系统会将整场对话摘要写入 `session_summary`，并同步保存到 `group_memory` 供后续单聊和群聊召回。

### 三层记忆架构

```
短期记忆 (short_term_message)  ← 8 轮对话窗口
       ↓ 会话结束时
中期记忆 (session_summary)     ← AI 自动生成摘要
       ↓ 记忆萃取
长期记忆 (long_term_fact)      ← 向量化存储
       ↓ 语义检索
RAG 召回 (ChromaDB)            ← 余弦相似度搜索
```

配套技术：
- 向量数据库：ChromaDB
- 嵌入模型：sentence-transformers/all-MiniLM-L6-v2 (约 80MB)
- 检索方式：余弦相似度，Top-K 返回

### 外部知识库架构

知识库与角色长期记忆共享嵌入模型和 ChromaDB 基础设施，但使用独立集合与独立持久化表。知识库可以绑定到 `global`、`character` 或 `group_thread`；检索时只考虑当前用户拥有、已启用、至少有一个 `ready` 文档且命中当前上下文绑定的知识库。

文档处理流程：

```
上传文件 / 粘贴文本
  → 保存原文件到 data/knowledge
  → 创建 knowledge_document(status=queued)
  → FastAPI BackgroundTasks 异步执行
  → 原子声明任务(status=processing)，避免重复工作线程并发处理
  → 校验并提取 TXT / Markdown / PDF / DOCX 文本
  → 按段落优先切块并写入 knowledge_chunk
  → 写入知识向量集合
  → 成功标记 ready；任一阶段失败则清理部分数据并标记 failed
```

Web 管理页在选中知识库存在 `queued` 或 `processing` 文档时每 1.5 秒静默刷新详情；页面隐藏时暂停轮询。服务启动时会扫描未完成文档：`queued` 任务重新排队，进程中断遗留的 `processing` 任务按原状态原子接管并恢复。嵌入模型或向量存储初始化失败也会持久化为 `failed` 和错误信息，不会永久停留在“处理中”；用户可通过重试接口重新排队。

单聊与群聊每轮会组合当前消息和必要的最近上下文作为查询，向量召回后叠加词法相关性排序，默认最多返回 6 个知识块。注入内容被明确标记为低于系统约束、关系图谱、世界时钟和运行状态的外部事实，文档中的命令或提示词不会被执行。API 响应通过 `knowledge_sources` 返回知识库、文档、片段、摘要和相似度，便于前端展示来源。

### 三层容错机制

1. **JSON 解析** — 直接解析 LLM 返回的 JSON
2. **修复重试** — JSON 解析失败时尝试截断修复后重试
3. **文本兜底** — 修复失败时降级为纯文本模式

---

## 数据库设计

Memoria 默认使用 SQLite (WAL 模式)，生产部署可通过 `DATABASE_URL=postgresql://...` 切换 PostgreSQL。数据库共 24 张表。

### 1. users（用户表）

存储 Web 前端用户登录资料和头像。登录 token 持久化在 `auth_token` 表；进程内 `_tokens` 仅保留给旧测试/开发进程兼容。

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT PRIMARY KEY | 用户 ID，格式为 `usr_<8字符>` |
| username | TEXT NOT NULL UNIQUE | 用户名 |
| password_hash | TEXT NOT NULL | PBKDF2-SHA256 密码哈希；旧 SHA256 登录后会自动升级 |
| gender | TEXT DEFAULT 'unknown' | 性别：male/female/unknown |
| avatar_url | TEXT | 头像 data URL |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

---

### 2. auth_token（认证 token 表）

存储用户登录态 token，支持服务重启后继续识别有效登录态。

| 字段 | 类型 | 说明 |
|------|------|------|
| token | TEXT PRIMARY KEY | 登录 token |
| user_id | TEXT NOT NULL | 用户 ID（外键）|
| created_at | TEXT NOT NULL | 创建时间 |
| expires_at | TEXT NOT NULL | 过期时间 |

**外键：** `FOREIGN KEY (user_id) REFERENCES users(user_id)`
**索引：** `idx_auth_token_user ON auth_token(user_id, expires_at)`

---

### 3. character_card（角色卡表）

存储角色卡的完整 JSON 数据。角色卡按用户隔离；`src/memoria/characters/` 下的静态 JSON 只作为开发和导入模板，不会在用户第一次使用时自动复制到 `character_card`。

| 字段 | 类型 | 说明 |
|------|------|------|
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| character_id | TEXT NOT NULL | 角色 ID |
| card_data | TEXT NOT NULL | 完整角色卡 JSON |
| version | TEXT DEFAULT '1.0.0' | 版本号 |
| name | TEXT | 角色名称（冗余，便于查询）|
| display_name | TEXT | 显示名称（冗余）|
| avatar_url | TEXT | 角色头像，data URL 或网络 URL |
| is_active | INTEGER DEFAULT 1 | 是否启用（1=启用，0=禁用）|
| source | TEXT DEFAULT 'db' | 来源：db=数据库创建，file=文件导入 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**主键：** `PRIMARY KEY(owner_user_id, character_id)`，因此不同用户可以拥有相同 `character_id`
**外键：** `FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
**索引：** `idx_character_active ON character_card(owner_user_id, is_active, created_at DESC)`

**禁用语义：** `is_active=0` 是软禁用，不删除角色卡数据。禁用角色卡不能创建新的单聊或群聊；已有单聊历史仍可查看但不能继续发送；已有群聊保留该成员和历史消息，但编排器只加载当前启用的参与角色，因此禁用角色不会继续回复。

---

### 4. relationship_state（关系状态表）

存储玩家与角色的运行时关系状态。使用显式列而非 JSON，因为好感度和信任度在每次对话中都会高频更新。

| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT NOT NULL | 角色 ID（联合主键）|
| player_id | TEXT NOT NULL | 玩家 ID（联合主键）|
| affection_level | REAL DEFAULT 0.0 | 好感度（-100 ~ 100）|
| trust_level | REAL DEFAULT 0.0 | 信任度（0 ~ 100）|
| current_mood | TEXT DEFAULT 'neutral' | 当前情绪 |
| updated_at | TEXT | 最后更新时间 |

**主键：** `PRIMARY KEY (character_id, player_id)`

> 注意：此表使用显式列存储运行时状态，与其他表中使用 JSON 字段存储配置的模式不同。好感度和信任度值在对话过程中由 Orchestrator 实时更新。

---

### 5. long_term_fact（长期记忆表）

存储从对话中萃取出的长期记忆事实，同时同步到 ChromaDB 向量数据库。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id | TEXT NOT NULL | 角色 ID |
| player_id | TEXT NOT NULL | 玩家 ID |
| fact_text | TEXT NOT NULL | 记忆事实内容 |
| importance | INTEGER DEFAULT 5 | 重要性（1-10），影响召回优先级 |
| created_at | TEXT | 创建时间 |
| last_referenced | TEXT | 最后被向量检索召回的时间 |

**索引：** `idx_fact_lookup ON long_term_fact(character_id, player_id, importance DESC, last_referenced DESC)`

---

### 6. session（会话表）

管理对话会话的生命周期，通过 `is_multi_character` 字段区分单角色和多角色会话。

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT PRIMARY KEY | 会话 UUID |
| character_id | TEXT NOT NULL | 角色 ID |
| player_id | TEXT NOT NULL | 玩家 ID |
| player_name | TEXT NOT NULL | 玩家名称 |
| created_at | TEXT | 创建时间 |
| ended_at | TEXT | 结束时间（结束时写入）|
| status | TEXT DEFAULT 'active' | 状态：active 或 ended |
| group_name | TEXT | 多角色群聊名称 |
| group_thread_id | TEXT | 逻辑群聊线程 ID，同一群聊多段 session 共享 |
| is_multi_character | INTEGER DEFAULT 0 | 0=单角色，1=多角色群聊 |

**索引：**
- `idx_session_lookup ON session(character_id, player_id, created_at DESC)` — 按角色和玩家查询历史会话
- `idx_session_multi ON session(is_multi_character, player_id, created_at DESC)` — 按会话类型筛选
- `idx_session_group_thread ON session(group_thread_id, created_at DESC)` — 按群聊线程查询续聊历史

---

### 7. multi_session_participant（多角色会话参与者表）

记录多角色群聊中每个会话的参与角色，支持动态添加/移除。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT NOT NULL | 会话 ID（外键）|
| character_id | TEXT NOT NULL | 参与角色 ID |
| join_order | INTEGER DEFAULT 0 | 加入顺序 |
| speak_frequency | REAL DEFAULT 1.0 | 发言频率权重（0.0 ~ 2.0）|
| is_active | INTEGER DEFAULT 1 | 是否活跃参与（可临时退出）|
| message_count | INTEGER DEFAULT 0 | 该角色发言次数统计 |
| created_at | TEXT | 加入时间 |
| last_spoke_at | TEXT | 最后发言时间 |

**外键：** `FOREIGN KEY (session_id) REFERENCES session(session_id)`
**唯一约束：** `UNIQUE(session_id, character_id)`
**索引：** `idx_multi_participant ON multi_session_participant(session_id, is_active)`

`multi_session_participant.is_active` 表示该成员在会话内是否活跃；查询可回复成员时还会叠加 `character_card.is_active`，因此角色卡被禁用会让其在既有群聊中显示离线且不再发言。

---

---

### 8. shared_memory（角色间共享记忆表）

存储同一用户下两个角色之间共同经历的记忆，用于多角色对话中查询角色间的历史互动信息。隔离维度是 `owner_user_id`，因此不同用户可以拥有相同的 `character_id` 组合而不会共享角色间记忆。

写入时机：
- 多角色自动记忆处理达到阈值时，从群聊历史中提取角色间印象并写入
- 群聊结束且有效消息数大于 6 条时，在生成群聊摘要后提取角色间印象并写入
- 开发或内部逻辑显式调用 `save_character_impression()` 时写入

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PRIMARY KEY | 记忆 UUID |
| owner_user_id | TEXT NOT NULL | 记忆归属用户 ID |
| character_a_id | TEXT NOT NULL | 角色 A ID |
| character_b_id | TEXT NOT NULL | 角色 B ID |
| memory_text | TEXT NOT NULL | 记忆内容 |
| context | TEXT | 记忆产生的对话上下文 |
| importance | REAL DEFAULT 0.5 | 重要性权重（0.0 ~ 1.0）|
| created_at | TEXT | 创建时间 |
| last_referenced | TEXT | 最后被检索时间 |
| reference_count | INTEGER DEFAULT 0 | 被引用次数 |

---

### 9. group_memory（群体记忆表）

存储多角色会话中的群体共同记忆，以 session 为粒度记录所有参与者的集体经历。群聊结束且有效消息数大于 6 条、摘要模型返回非空内容时，`save_multi_character_summary()` 会把整场摘要同步保存为群体记忆，`memory_text` 通常带有 `会话摘要：` 前缀。开发或内部逻辑也可以调用 `save_group_event_memory()` 写入 `群体事件：` 类型的记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | TEXT PRIMARY KEY | 记忆 UUID |
| session_id | TEXT NOT NULL | 所属会话 ID |
| memory_text | TEXT NOT NULL | 记忆内容，通常为 `会话摘要：{summary}` 或 `群体事件：{event}` |
| participants | TEXT | 参与角色列表（JSON）|
| context | TEXT | 记忆产生的对话上下文 |
| importance | REAL DEFAULT 0.5 | 重要性权重（0.0 ~ 1.0）|
| created_at | TEXT | 创建时间 |
| last_referenced | TEXT | 最后被检索时间 |
| reference_count | INTEGER DEFAULT 0 | 被引用次数 |

---

### 10. short_term_message（短期记忆表）

存储对话历史消息。多角色会话场景下，`character_id` 和 `character_name` 字段记录发言人信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT NOT NULL | 会话 ID |
| role | TEXT NOT NULL | 角色：user 或 assistant |
| content | TEXT NOT NULL | 消息内容 |
| character_id | TEXT | 发言角色 ID（多角色会话时填写）|
| character_name | TEXT | 发言角色显示名（多角色会话时填写）|
| action | TEXT | 回放/调试状态快照：动作 |
| affinity_delta | REAL | 回放/调试状态快照：好感度变化 |
| trust_delta | REAL | 回放/调试状态快照：信任度变化 |
| current_affinity | REAL | 回放/调试状态快照：当前好感度 |
| current_trust | REAL | 回放/调试状态快照：当前信任度 |
| current_mood | TEXT | 回放/调试状态快照：当前情绪 |
| event_notification | TEXT | 回放/调试状态快照：事件通知 |
| created_at | TEXT | 创建时间 |

**索引：**
- `idx_message_session ON short_term_message(session_id, id ASC)` — 按会话获取历史
- `idx_message_character ON short_term_message(session_id, character_id, created_at DESC)` — 按角色筛选发言

---

### 11. session_summary（会话摘要表）

存储会话摘要（中期记忆），在会话结束时由 AI 自动生成。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT NOT NULL | 会话 ID（外键）|
| character_id | TEXT NOT NULL | 角色 ID |
| player_id | TEXT NOT NULL | 玩家 ID |
| summary_text | TEXT NOT NULL | AI 生成的摘要内容 |
| message_count | INTEGER | 摘要涵盖的消息数量 |
| summary_status | TEXT DEFAULT 'completed' | 摘要状态：pending/generating/completed/failed |
| created_at | TEXT | 创建时间 |

**外键：** `FOREIGN KEY (session_id) REFERENCES session(session_id)`
**索引：**
- `idx_summary_lookup ON session_summary(session_id, created_at DESC)`
- `idx_summary_player ON session_summary(character_id, player_id, created_at DESC)` — 按角色和玩家查询历史摘要

---

### 12. event_definition（事件定义表）

存储事件的配置和定义。事件定义按用户隔离；`character_id` 为 NULL 时表示该用户下的全局事件。

| 字段 | 类型 | 说明 |
|------|------|------|
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| event_id | TEXT NOT NULL | 事件 ID |
| event_name | TEXT NOT NULL | 事件名称 |
| description | TEXT | 事件描述 |
| character_id | TEXT | 角色专属事件（NULL=全局）|
| trigger_config | TEXT NOT NULL | 触发条件配置（JSON）|
| effects_config | TEXT NOT NULL | 效果列表配置（JSON）|
| schedule | TEXT | 时间驱动事件调度配置 |
| template_id | TEXT | 来源事件模板 ID |
| priority | INTEGER DEFAULT 0 | 优先级（数值越大越优先）|
| is_active | INTEGER DEFAULT 1 | 是否启用 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |
| trigger_count | INTEGER DEFAULT 0 | 触发次数统计 |
| last_triggered_at | TEXT | 最后触发时间 |

**主键：** `PRIMARY KEY(owner_user_id, event_id)`，因此不同用户可以拥有相同 `event_id`
**外键：** `FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
**索引：** `idx_event_character ON event_definition(owner_user_id, character_id, is_active)`

---

### 13. event_trigger_log（事件触发日志表）

记录每次事件触发的详细信息，用于调试和分析。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| event_id | TEXT NOT NULL | 事件 ID（外键）|
| character_id | TEXT NOT NULL | 角色 ID |
| player_id | TEXT NOT NULL | 玩家 ID |
| session_id | TEXT NOT NULL | 会话 ID |
| triggered_at | TEXT | 触发时间 |
| context_snapshot | TEXT | 触发时上下文快照（JSON）|
| effects_applied | TEXT | 应用的效果列表（JSON）|

**外键：** `FOREIGN KEY (player_id, event_id) REFERENCES event_definition(owner_user_id, event_id)`
**索引：** `idx_event_trigger_log ON event_trigger_log(event_id, character_id, player_id, triggered_at DESC)`

---

### 14. event_context_state（事件上下文状态表）

持久化事件链和跨会话事件进度，确保剧情事件可以在后续会话继续推进。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| event_id | TEXT NOT NULL | 事件 ID |
| character_id | TEXT NOT NULL | 角色 ID |
| player_id | TEXT NOT NULL | 玩家 ID |
| context_data | TEXT NOT NULL | 事件上下文数据（JSON）|
| status | TEXT DEFAULT 'active' | 状态：active/completed/cancelled 等 |
| progress | REAL DEFAULT 0.0 | 事件进度 |
| last_session_id | TEXT | 最后关联会话 ID |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**唯一约束：** `UNIQUE(event_id, character_id, player_id)`
**索引：** `idx_event_context_lookup ON event_context_state(character_id, player_id, status, updated_at DESC)`

---

### 15. event_schedule_state（事件调度状态表）

记录时间驱动事件的检查和运行状态，用于 cron 式事件调度。

| 字段 | 类型 | 说明 |
|------|------|------|
| event_id | TEXT NOT NULL | 事件 ID（联合主键）|
| character_id | TEXT NOT NULL | 角色 ID（联合主键）|
| player_id | TEXT NOT NULL | 玩家 ID（联合主键）|
| schedule | TEXT NOT NULL | 调度表达式 |
| last_checked_at | TEXT | 最后检查时间 |
| last_run_at | TEXT | 最后运行时间 |
| next_run_at | TEXT | 下次运行时间 |
| status | TEXT DEFAULT 'active' | 调度状态 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**主键：** `PRIMARY KEY (event_id, character_id, player_id)`
**索引：** `idx_event_schedule_due ON event_schedule_state(status, next_run_at)`

---

### 16. event_template（事件模板表）

存储可复用事件模板，用于快速创建常见事件配置。

该表是全局系统模板库，不按用户隔离。用户创建事件时会把模板的触发条件和效果复制到自己的 `event_definition`，事件本身仍按 `owner_user_id` 隔离。

| 字段 | 类型 | 说明 |
|------|------|------|
| template_id | TEXT PRIMARY KEY | 模板 ID |
| template_name | TEXT NOT NULL | 模板名称 |
| category | TEXT | 模板分类 |
| description | TEXT | 模板描述 |
| trigger_config | TEXT NOT NULL | 默认触发条件配置（JSON）|
| effects_config | TEXT NOT NULL | 默认效果配置（JSON）|
| metadata | TEXT | 模板元数据（JSON）|
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

---

### 17. character_relationship（角色关系网络表）

存储角色之间的相互关系，用于单聊、群聊互动和关系图谱。关系按用户隔离，同一对角色 ID 可以在不同用户下有不同关系。写入时会按角色 ID 排序保存为无向边。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| character_id_a | TEXT NOT NULL | 角色 A ID |
| character_id_b | TEXT NOT NULL | 角色 B ID |
| relationship_type | TEXT | 关系类型，自定义文本，不限制固定枚举 |
| affinity | REAL DEFAULT 0.0 | 关系强度数值（-100 ~ 100）；prompt 不固定解释为亲密、敌意或好感，具体含义以关系类型和说明为准 |
| description | TEXT | 关系描述 |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

**唯一约束：** `UNIQUE(owner_user_id, character_id_a, character_id_b)` — 同一用户下每对角色只有一条记录
**外键：** `FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
**索引：** `idx_relationship_lookup ON character_relationship(owner_user_id, character_id_a, character_id_b)`

---

### 18. character_relationship_revision（角色关系修订表）

记录每对角色关系最近一次图谱变更时间，包含已经删除的关系边。该表不保存关系内容，只保存“这对角色的图谱在什么时候被改过”，用于多角色记忆和历史召回的截止过滤。

| 字段 | 类型 | 说明 |
|------|------|------|
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| character_id_a | TEXT NOT NULL | 排序后的角色 A ID |
| character_id_b | TEXT NOT NULL | 排序后的角色 B ID |
| updated_at | TEXT NOT NULL | 最近一次创建、更新、关系强度变化或删除时间 |

**主键：** `PRIMARY KEY (owner_user_id, character_id_a, character_id_b)`
**外键：** `FOREIGN KEY (owner_user_id) REFERENCES users(user_id)`
**索引：** `idx_relationship_revision_lookup ON character_relationship_revision(owner_user_id, character_id_a, character_id_b)`

---

### 19. player_world_clock（玩家世界时钟表）

存储每个用户独立的世界时间锚点。世界时间按“世界锚点 + 真实经过时间 × 时间倍率”计算；倍率 `0` 表示暂停，API 支持 `0/1/2/5/10`。

| 字段 | 类型 | 说明 |
|------|------|------|
| player_id | TEXT PRIMARY KEY | 用户 ID |
| timezone | TEXT NOT NULL DEFAULT 'UTC' | IANA 时区名称 |
| anchor_real_utc | TEXT NOT NULL | 真实 UTC 锚点 |
| anchor_world_utc | TEXT NOT NULL | 世界 UTC 锚点 |
| time_scale | REAL NOT NULL DEFAULT 1 | 世界时间倍率 |
| updated_at | TEXT NOT NULL | 更新时间 |

**外键：** `FOREIGN KEY (player_id) REFERENCES users(user_id)`

---

### 20. knowledge_base（知识库表）

存储当前用户创建的知识库及总开关。

| 字段 | 类型 | 说明 |
|------|------|------|
| knowledge_base_id | TEXT PRIMARY KEY | 知识库 UUID |
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| name | TEXT NOT NULL | 知识库名称 |
| description | TEXT | 描述 |
| is_enabled | INTEGER NOT NULL DEFAULT 1 | 是否参与检索 |
| created_at | TEXT NOT NULL | 创建时间 |
| updated_at | TEXT NOT NULL | 更新时间 |

**索引：** `idx_knowledge_base_owner ON knowledge_base(owner_user_id, created_at DESC)`

---

### 21. knowledge_binding（知识库绑定表）

定义知识库的可见范围。`target_type` 为 `global` 时 `target_id` 为空；`character` 和 `group_thread` 分别绑定当前用户的角色或群聊线程。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| knowledge_base_id | TEXT NOT NULL | 知识库 ID |
| target_type | TEXT NOT NULL | `global` / `character` / `group_thread` |
| target_id | TEXT NOT NULL DEFAULT '' | 绑定目标 ID |
| created_at | TEXT NOT NULL | 创建时间 |

**唯一约束：** `UNIQUE(owner_user_id, knowledge_base_id, target_type, target_id)`
**索引：** `idx_knowledge_binding_target ON knowledge_binding(owner_user_id, target_type, target_id)`

---

### 22. knowledge_document（知识文档表）

记录上传或粘贴的原始文档及异步处理状态。新粘贴文档使用 `source_type=pasted_text`；旧数据中的 `paste` 仍可兼容显示。

| 字段 | 类型 | 说明 |
|------|------|------|
| document_id | TEXT PRIMARY KEY | 文档 UUID |
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| knowledge_base_id | TEXT NOT NULL | 所属知识库 |
| original_name | TEXT NOT NULL | 原始文件名 |
| media_type | TEXT NOT NULL | MIME 类型 |
| source_type | TEXT NOT NULL | `upload` / `pasted_text` |
| storage_path | TEXT | 原文件存储路径 |
| checksum | TEXT NOT NULL | SHA-256 校验和 |
| byte_size | INTEGER NOT NULL DEFAULT 0 | 文件字节数 |
| status | TEXT NOT NULL DEFAULT 'queued' | `queued` / `processing` / `ready` / `failed` |
| error_message | TEXT | 失败原因 |
| extracted_chars | INTEGER NOT NULL DEFAULT 0 | 提取字符数 |
| page_count | INTEGER | PDF 页数 |
| created_at | TEXT NOT NULL | 创建时间 |
| updated_at | TEXT NOT NULL | 更新时间及原子任务声明版本 |

**索引：** `idx_knowledge_document_base ON knowledge_document(owner_user_id, knowledge_base_id, created_at DESC)`

---

### 23. knowledge_chunk（知识文本块表）

保存文档提取后的文本块和来源元数据，并同步写入独立的知识向量集合。

| 字段 | 类型 | 说明 |
|------|------|------|
| chunk_id | TEXT PRIMARY KEY | 文本块 UUID |
| owner_user_id | TEXT NOT NULL | 拥有者用户 ID |
| knowledge_base_id | TEXT NOT NULL | 所属知识库 |
| document_id | TEXT NOT NULL | 所属文档 |
| chunk_index | INTEGER NOT NULL | 文档内顺序 |
| content | TEXT NOT NULL | 文本内容 |
| char_count | INTEGER NOT NULL | 字符数 |
| source_metadata | TEXT | 页码、段落/表格类型等 JSON 元数据 |
| created_at | TEXT NOT NULL | 创建时间 |

**唯一约束：** `UNIQUE(document_id, chunk_index)`
**索引：** `idx_knowledge_chunk_document ON knowledge_chunk(owner_user_id, document_id, chunk_index)`

---

### 24. player_event_inbox（玩家事件收件箱表）

持久化事件系统产生的用户通知，可按未读状态查询并标记已读。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| player_id | TEXT NOT NULL | 用户 ID |
| event_id | TEXT | 来源事件 ID |
| character_id | TEXT | 相关角色 ID |
| session_id | TEXT | 相关会话 ID |
| event_type | TEXT NOT NULL DEFAULT 'event' | 通知类型 |
| title | TEXT | 标题 |
| content | TEXT NOT NULL | 通知内容 |
| payload | TEXT | 扩展 JSON 负载 |
| world_created_at | TEXT | 事件发生时的世界时间 |
| created_at | TEXT NOT NULL | 真实创建时间 |
| read_at | TEXT | 已读时间，NULL 表示未读 |

**索引：** `idx_player_event_inbox_unread ON player_event_inbox(player_id, read_at, id DESC)`

---

### 完整索引汇总

共 23 个索引，覆盖所有高频查询路径：

| 索引名 | 表 | 列 |
|--------|-----|-----|
| `idx_session_lookup` | session | (character_id, player_id, created_at DESC) |
| `idx_session_multi` | session | (is_multi_character, player_id, created_at DESC) |
| `idx_session_group_thread` | session | (group_thread_id, created_at DESC) |
| `idx_multi_participant` | multi_session_participant | (session_id, is_active) |
| `idx_message_session` | short_term_message | (session_id, id ASC) |
| `idx_message_character` | short_term_message | (session_id, character_id, created_at DESC) |
| `idx_fact_lookup` | long_term_fact | (character_id, player_id, importance DESC, last_referenced DESC) |
| `idx_summary_lookup` | session_summary | (session_id, created_at DESC) |
| `idx_summary_player` | session_summary | (character_id, player_id, created_at DESC) |
| `idx_character_active` | character_card | (owner_user_id, is_active, created_at DESC) |
| `idx_event_character` | event_definition | (owner_user_id, character_id, is_active) |
| `idx_event_trigger_log` | event_trigger_log | (event_id, character_id, player_id, triggered_at DESC) |
| `idx_event_context_lookup` | event_context_state | (character_id, player_id, status, updated_at DESC) |
| `idx_event_schedule_due` | event_schedule_state | (status, next_run_at) |
| `idx_auth_token_user` | auth_token | (user_id, expires_at) |
| `idx_player_event_inbox_unread` | player_event_inbox | (player_id, read_at, id DESC) |
| `idx_knowledge_base_owner` | knowledge_base | (owner_user_id, created_at DESC) |
| `idx_knowledge_binding_target` | knowledge_binding | (owner_user_id, target_type, target_id) |
| `idx_knowledge_document_base` | knowledge_document | (owner_user_id, knowledge_base_id, created_at DESC) |
| `idx_knowledge_chunk_document` | knowledge_chunk | (owner_user_id, document_id, chunk_index) |
| `idx_shared_memory_owner_pair` | shared_memory | (owner_user_id, character_a_id, character_b_id, importance DESC) |
| `idx_relationship_lookup` | character_relationship | (owner_user_id, character_id_a, character_id_b) |
| `idx_relationship_revision_lookup` | character_relationship_revision | (owner_user_id, character_id_a, character_id_b) |

---

### 数据库设计特点

1. **双模式存储** — 默认 SQLite WAL 模式便于本地开发；配置 `DATABASE_URL` 后使用 PostgreSQL
2. **显式列 + JSON 混合** — 高频读写字段（好感度、信任度）使用显式列以获得更好性能；复杂配置（角色卡、事件条件）使用 JSON 字段获得灵活性
3. **软删除设计** — `is_active` 字段实现逻辑删除，支持数据恢复
4. **多角色扩展** — `session.is_multi_character` + `multi_session_participant` 表支持群聊；`short_term_message` 扩展 `character_id` / `character_name` 列区分发言人；`shared_memory` 存储用户隔离的角色间互动记忆，`group_memory` 存储群聊结束摘要和内部显式写入的群体事件记忆，单聊也会召回同一用户下相关的 shared/group 记忆
5. **关系图谱权威** — `character_relationship` 保存当前图谱，`character_relationship_revision` 保存修订截止点；单聊和多角色上下文会保留普通长期记忆和共同经历，只剔除图谱变更前的旧关系事实，原始群聊历史按修订时间截止
6. **用户资源隔离** — `character_card`、`event_definition`、`character_relationship`、`character_relationship_revision`、`shared_memory` 和全部知识库表都带用户归属；API 只读写当前登录用户的数据。`event_template` 是经过认证访问的全局系统模板，不属于用户资源
7. **知识任务可恢复** — 文档状态和错误持久化到 `knowledge_document`；原子状态声明防止重复处理，启动恢复继续排队或中断任务
8. **世界时间与通知持久化** — `player_world_clock` 保存连续的用户世界时间锚点，`player_event_inbox` 保存基于世界时间产生的事件通知
9. **轻量迁移** — 启动时为旧库补齐角色、会话、事件、认证、世界时钟、通知收件箱、关系修订和知识库相关结构；`owner_user_id` 相关主键重建不做旧数据迁移，升级前需要删除旧 SQLite 数据库或手动重建表
10. **完整索引覆盖** — 23 个索引覆盖常用查询路径
11. **可迁移性** — Repository 层适配 SQLite/PostgreSQL 占位符、自增主键和少量 UPSERT 差异

## 角色卡规范

角色卡使用 JSON 格式定义。完整结构：

```json
{
  "character_id": "npc_luo_xiaohei",
  "version": "1.0.0",
  "meta": {
    "name": "罗小黑",
    "display_name": "小黑",
    "aliases": ["小黑猫", "猫妖少年"],
    "game_module": "demo",
    "created_by": "Nanzi",
    "last_updated": "2026-06-20T08:00:00Z"
  },
  "identity": {
    "age": "约15岁（猫妖形态）",
    "gender": "男",
    "occupation": "旅行者/学徒",
    "race_or_species": "猫妖",
    "appearance": "黑发少年，猫耳朵和尾巴，金色瞳孔",
    "social_status": "流浪者",
    "core_identity_summary": "一只好奇心旺盛、善良天真的猫妖少年"
  },
  "personality": {
    "mbti_or_archetype": "ENFP",
    "core_traits": ["好奇", "善良", "天真", "勇敢", "倔强"],
    "values_and_beliefs": ["朋友很重要", "帮助他人是应该的"],
    "fears_and_tabooes": ["被抛弃", "无法保护朋友"],
    "quirks_and_habits": ["喜欢晒太阳", "对新鲜事物充满好奇"],
    "moral_alignment": "善良中立"
  },
  "speech_style": {
    "tone_register": "轻松活泼",
    "vocabulary_notes": "使用简单直接的语言，有时带童稚感",
    "sentence_patterns": [
      "短句为主，不超过20字",
      "常用疑问句表达好奇",
      "激动时会重复词语"
    ],
    "catchphrases": ["喵~", "好奇怪哦", "我想知道"],
    "things_never_to_say": [
      "作为一个AI",
      "我是程序",
      "根据我的分析"
    ],
    "language": "zh-CN",
    "formality_default": "casual"
  },
  "background": {
    "story_bio": "在森林中长大的猫妖，对世界充满好奇...",
    "key_events": ["遇到师父无限", "第一次进城"],
    "relationships": [],
    "secrets": ["害怕打雷"]
  },
  "goals_and_motivations": {
    "current_goals": ["探索世界", "变强"],
    "long_term_goals": ["成为伟大的猫妖"],
    "what_triggers_anger": ["伤害朋友", "被欺骗"],
    "what_brings_joy": ["发现新事物", "被夸奖"]
  },
  "interaction_rules": {
    "initial_attitude_to_player": "curious_friendly",
    "topics_to_avoid_unless_trusted": ["过去的创伤"],
    "response_to_rudeness": ["困惑不解，尝试理解对方"]
  },
  "action_vocabulary": {
    "greeting_actions": ["[好奇地打量]", "[挥手]"],
    "farewell_actions": ["[依依不舍]", "[挥手告别]"],
    "emotional_reactions": ["[开心地笑]", "[耷拉耳朵]"],
    "default_action": "neutral"
  },
  "runtime_state_schema": {
    "relationships": [{
      "target_id": "player",
      "affection_level": 0,
      "trust_level": 10
    }],
    "current_mood": {
      "type": "enum",
      "emotions": ["开心", "好奇", "紧张", "难过", "平静"],
      "default_mood": "平静"
    },
    "known_player_facts": {}
  },
  "safety_constraints": {
    "topics_to_avoid": ["色情", "暴力"],
    "out_of_character_handling": "ignore"
  }
}
```

### 关键字段说明

| 分类 | 字段 | 作用 |
|------|------|------|
| meta | name / display_name | 角色标识与显示名称 |
| identity | core_identity_summary | 一句话角色概述，用于列表展示 |
| personality | core_traits / fears_and_tabooes | 决定角色行为模式 |
| speech_style | tone_register / catchphrases / things_never_to_say | 控制语言输出风格 |
| speech_style | forbidden_phrases | 沉浸感保护，禁止破坏角色的话 |
| action_vocabulary | greeting_actions / emotional_reactions | 动作词库，用于 Prompt 引导 |
| runtime_state_schema | relationships / current_mood | 定义运行时状态结构 |
| safety_constraints | topics_to_avoid | 安全边界 |

### JSON 常见错误

```json
// ❌ 错误：最后一个元素后有逗号
"core_traits": ["好奇", "善良",]

// ✅ 正确
"core_traits": ["好奇", "善良"]

// ❌ 错误：单引号
'name': '小黑'

// ✅ 正确：双引号
"name": "小黑"
```

---


## 技术栈

| 组件 | 技术 | 备注 |
|------|------|------|
| 语言 | Python 3.10+ | src layout，pyproject.toml 管理 |
| Web 框架 | FastAPI | 自动生成 OpenAPI 文档 |
| ASGI 服务器 | Uvicorn | --reload 热重载 |
| 数据验证 | Pydantic v2 | BaseSettings + SettingsConfigDict |
| 数据库 | SQLite (WAL) / PostgreSQL | SQLite 默认开发模式，PostgreSQL 用于生产部署 |
| 向量数据库 | ChromaDB | 余弦相似度检索 |
| 嵌入模型 | all-MiniLM-L6-v2 | ~80MB，HuggingFace 下载 |
| LLM 客户端 | OpenAI SDK | 兼容接口，支持多供应商 |
| 包管理 | pip + pyproject.toml | 可选 dev 依赖组 |
| 测试 | pytest + pytest-asyncio | 直接调用 handler、模型校验和数据库回归测试 |
