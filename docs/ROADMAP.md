# Memoria 开发路线图

## 已完成功能

### 第一阶段 - 核心对话系统
- [x] 结构化 JSON 角色卡定义（Pydantic 校验，11 个嵌套模型）
- [x] 角色卡加载器（LRU 缓存，数据库优先 / 文件回退，热重载）
- [x] 短期记忆（会话窗口，默认 8 轮）
- [x] 长期记忆（自动萃取 + SQLite 存储 + 文本相似度去重）
- [x] 关系与情感系统（好感度 -100~100、信任度、情绪实时追踪）
- [x] LLM 调用适配层（OpenAI 兼容接口，支持 DeepSeek/Kimi/Qwen）
- [x] Prompt 组装器（角色设定 + 记忆上下文 + 状态注入）
- [x] 单角色对话编排器 (Orchestrator)
- [x] 沉浸感保护（AI 身份检测、角色一致性约束）
- [x] 三层容错机制（JSON 解析 → 修复重试 → 文本兜底）
- [x] FastAPI RESTful API + 自动生成 OpenAPI 文档

### 第二阶段 - 增强记忆与管理
- [x] RAG 向量检索（ChromaDB + all-MiniLM-L6-v2，余弦相似度）
- [x] 向量记忆自动同步（插入时同步到 ChromaDB）
- [x] 中期记忆（会话摘要，AI 自动生成，同会话去重 upsert）
- [x] **记忆去重引擎** — `_text_similarity`（SequenceMatcher）+ `_dedup_check`（LIKE 粗筛→精确比较），覆盖 long_term_fact、session_summary、shared_memory、group_memory 四张表，阈值 0.75
- [x] 角色卡管理后台 API（CRUD + 导入导出 + 软删除 + 激活/禁用）
- [x] SQLite WAL 模式（支持并发读写）

### 第三阶段 - 事件系统
- [x] 事件数据模型（TriggerCondition / EventEffect / EventDefinition，Pydantic）
- [x] 事件检测引擎（8 种触发类型 + 复合条件 AND/OR）
- [x] 事件执行器（状态修改、内容解锁、对话触发、记忆添加、情绪改变、玩家通知、关系修改）
- [x] 事件冷却时间管理（按 character+player 记录最后触发时间）
- [x] 事件触发日志（完整上下文快照 + 效果列表）
- [x] 角色关系网络 CRUD API（无向关系，自动排序唯一约束）
- [x] 事件管理 API（CRUD + 启用/禁用 + 触发历史查询 + 重置）

### 第四阶段 - 多角色对话
- [x] 多角色群聊（2-5 个 NPC，MultiCharacterOrchestrator）
- [x] 5 种发言策略（RoundRobin / WeightedRandom / SmartSelection / TriggerBased / Hybrid）
- [x] 讨论模式（角色连续发言，每轮最多 3 个回应）
- [x] 智能策略评分（关键词匹配 30% + 关系亲密度 25% + 频率配置 20% + 均衡性 15% + 发言时间 10%）
- [x] 角色间互动（主动发言触发 + 对话历史上下文注入）
- [x] 三层多角色记忆 — long_term_fact（个人）+ shared_memory（角色间）+ group_memory（群体），含 DDL、CRUD、去重
- [x] 动态参与者管理（添加/移除/更新频率）

---

## 计划中

### 第五阶段 - 质量与稳定性 🔄

**目标：** 提升系统健壮性，为生产环境做准备。

**当前进度：** 测试覆盖 61→128；记忆去重、重试、限流、健康检查、懒加载、CI/CD 已上线。

- [x] 单元测试覆盖（当前 106 tests，覆盖 schema/repository/orchestrator/events/API models）
- [x] 单元测试覆盖持续扩展（当前 128 tests，新增 test_memory_extractor.py: memory_extractor/prompt_builder/llm_client/config/character_loader/dedup_helpers）
- [ ] 数据库迁移到 PostgreSQL（保留 SQLite 开发模式）
- [x] LLM 调用重试机制（指数退避 3 次，base_delay=1s，max 7s）
- [x] 请求速率限制（per-player，60s 窗口 60 次，X-Player-ID 头识别）
- [x] 结构化日志（LOG_LEVEL 环境变量控制）+ 动态调整（POST /admin/log-level）
- [x] 健康检查端点（`/health` 存活 + `/ready` 数据库就绪）
- [x] 配置文件校验（启动时检查 LLM_API_KEY 等必需项，警告而非崩溃）
- [x] 内存使用优化（LLM Client 懒加载 + vector_memory 懒加载，首次调用时初始化）
- [x] CI/CD 流水线（GitHub Actions: Python 3.10/3.11/3.12 自动测试）

### 第六阶段 - Web 前端

**目标：** 提供开箱即用的 Web UI，降低使用门槛。

- [ ] 单角色对话界面（角色头像、消息气泡、好感度/情绪指示器、事件通知）
- [ ] 多角色群聊界面（角色头像、讨论模式切换、参与者管理面板）
- [x] 角色卡编辑器（分步表单：身份→性格→语言风格→背景→交互规则）
- [ ] 事件管理面板（可视化触发条件编排 + 效果配置）
- [ ] 角色关系图谱（D3.js / Cytoscape.js 力导引图）
- [ ] 响应式设计（桌面端为主，移动端适配）

### 第七阶段 - 事件系统深度集成

**目标：** 让事件系统真正影响对话体验，而非孤立的数据模型。

- [ ] 事件与对话编排器集成（对话轮次后自动触发检测 + 执行）
- [ ] 事件链（一个事件触发另一个事件，支持分支）
- [ ] 时间驱动事件（定时检查 + cron 式调度）
- [ ] 事件模板库（预设常见 RPG 事件：好感度里程碑、关键剧情节点）
- [ ] 事件效果中的 NPC 主动对话（通过多角色编排器发起）
- [ ] 事件上下文持久化（跨会话保留事件进度）

### 第八阶段 - 开发者体验

**目标：** 让二次开发和调试更高效。

- [ ] CLI 调试模式（`--debug` 标志：显示 LLM 原始请求/响应、Prompt 内容）
- [ ] 角色卡 JSON Schema 自动生成 + IDE 补全支持
- [ ] 对话回放工具（加载历史 session，逐步重放查看状态变化）
- [ ] 性能分析端点（LLM 调用耗时分布、记忆检索耗时）
- [ ] Docker 一键部署（`docker compose up`）
- [ ] OpenTelemetry 追踪（LLM 调用链路 + 数据库查询）
- [ ] 对话质量评分 API（角色一致性、趣味性自动评估）

### 第九阶段 - 高级特性

**目标：** 扩展系统能力边界。

- [ ] 道具与任务系统（通过事件效果触发，影响对话选项）
- [ ] 知识库注入（角色可引用外部世界观文档，RAG 检索）
- [ ] 语音合成集成（TTS，角色声音定制）
- [ ] 语音识别集成（STT，语音输入 → 文本 → LLM）
- [ ] 多语言支持（角色卡 i18n 字段 + Prompt 语言切换）
- [ ] 角色模板（一键创建常见角色类型：商人、卫兵、智者等）

### 第十阶段 - 生态与发布

**目标：** 构建社区和分发渠道。

- [ ] 插件系统（自定义事件处理器、记忆存储后端、LLM Provider）
- [ ] 角色卡市场（上传/下载/评分/评论）
- [ ] WebSocket 实时推送（对话流式输出 + 状态变更通知）
- [ ] 导出对话记录（Markdown / PDF / HTML）
- [ ] SDK 发布（Python `pip install memoria` + TypeScript 客户端库）

---

## 测试覆盖明细

| 文件 | 测试数 | 覆盖范围 |
|------|--------|---------|
| `tests/test_core.py` | 61 | CharacterSchema(9), EventSchema(9), SpeakingStrategies(12), EventDetector(15), MultiCharMemory(8), EdgeCases(8) |
| `tests/test_repository.py` | 17 | RuntimeState, Session, Memory CRUD, CharacterCard, EventDef, Relationship, MultiSession, Dedup(4) |
| `tests/test_orchestrator.py` | 6 | _clip/_safe_float, HistoryFormatting, LoadRelationships, CharInteraction |
| `tests/test_events.py` | 11 | EventExecutor 全部 8 种效果类型, EventDetector 边界 |
| `tests/test_api_models.py` | 11 | Dialogue(3), CharacterAdmin(2), EventAdmin(2), Relationship(2), MultiDialogue(2) |
| `tests/test_memory_extractor.py` | 22 | MemoryExtractor, PromptBuilder, Config, LLMClient, CharacterLoader, DedupHelpers |
| `tests/test_system.py` | 13 | 健康检查, 配置校验, 速率限制, 日志级别, 懒加载 |
| **合计** | **141** | |

## 版本规划

| 版本 | 阶段 | 核心交付 | 状态 |
|------|------|---------|------|
| v0.1 | 1-2 | 单角色对话 + 记忆系统 + 记忆去重 | ✅ |
| v0.2 | 3 | 事件系统 + 角色关系网络 | ✅ |
| v0.3 | 4 | 多角色对话 + 讨论模式 + shared/group 记忆 | ✅ |
| **v0.4** | **5** | **质量与稳定性（106 tests + 去重系统）** | 🔄 |
| v0.5 | 6 | Web 前端 | [ ] |
| v0.6 | 7 | 事件深度集成 | [ ] |
| v1.0 | 8-10 | 开发者体验 + 高级特性 + 生态 | [ ] |

## 功能状态说明

| 标记 | 含义 |
|------|------|
| ✅ | 已完成，可用 |
| 🔄 | 进行中 |
| [ ] | 计划中，尚未开始 |
