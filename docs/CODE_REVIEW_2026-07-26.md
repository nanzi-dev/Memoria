# 全量代码审查报告（2026-07-26）

## 审查范围

已完成：数据库仓储层（`src/memoria/db/repository/`）、前端与工程配置（`web/`、`scripts/`、依赖与配置文件）、核心编排层（`src/memoria/core/` 中 orchestrator / event_runtime / event_detector / cron_schedule / multi_character_orchestrator 等）、核心服务层（`llm_client.py`、prompt_builder、multi_character_memory、vector_memory、speech_provider/service 等），共约 4.5 万行代码。

**未完成**（因推理网关容量限制中断，未获得可用结论）：
- `src/memoria/api/`（含本次改动的 `avatar_fetcher.py`）
- 安全专项：CSRF 完整评估、avatar_fetcher SSRF 绕过手法、限流绕过

以上部分建议后续单独补审。

---

## 🔴 严重

### 1. 事件批次提交失败被静默吞掉，用户看到的和数据库里的对不上
- **位置**：`src/memoria/core/orchestrator.py:1036-1058`，`src/memoria/core/event_runtime.py:660-696`
- **问题**：`_commit_planned_batch` 先把生成的对话 turn 放进内存 `turn_holder`，再执行数据库原子提交。若提交失败（DB 锁超时，或对话耗时超过 240 秒导致租约失效引发 `DialogueTurnConflictError`），异常被一个本意是"容忍事件检测失败"的过宽 `except Exception` 吞掉。随后代码只判断 `turn_holder` 中是否存在 turn，误判为成功并直接返回。
- **失败场景**：一次慢对话（检索+生成+事件规划超过 240 秒租约）→ 批次提交因租约失效抛错 → 玩家收到"成功"的 NPC 回复，但消息、runtime_state、后台任务全部未持久化，`dialogue_turn` 卡在 `processing` 直到租约过期；玩家下一轮看到的历史里没有这条回复，重试同一 request_id 会重新生成完全不同的内容。

### 2. 跨用户记忆泄露
- **位置**：`src/memoria/db/repository/sessions_and_messages.py:1082-1106`（`get_character_group_memories`），调用点 `src/memoria/core/multi_character_memory.py:714`
- **问题**：`owner_user_id` 参数可选，不传时执行 `WHERE participants LIKE '%{character_id}%'`，不限定用户。已确认存在真实的不传 owner 调用路径（群体记忆回退分支）。角色 ID 可能跨用户重复（预置角色卡 `source='file'` 对所有用户是同一 ID），会把 A 用户群聊中形成的记忆注入 B 用户的 prompt。
- **附带问题**：`LIKE '%char-a%'` 是子串匹配，会误命中 `char-a-2`；character_id 若含 `%`/`_` 会被当通配符。

---

## 🟡 中等

| # | 问题 | 位置 | 影响 |
|---|---|---|---|
| 3 | PostgreSQL 下消息分页必崩 | `db/repository/sessions_and_messages.py:638-641` | `fetchone()[0]` 对 psycopg 的 `dict_row` 按位置取列会抛 `KeyError`；切到 PG 后消息分页接口 100% 报 500。且算出的 `total_count` 从未被使用（死代码），SQLite 下掩盖了此 bug |
| 4 | 会话摘要竞态重复 | `db/repository/sessions_and_messages.py:780-808`（`save_session_summary`） | check-then-act，表无 `UNIQUE(session_id, character_id, player_id)` 约束，并发生成摘要产生重复行，之后每次更新只改其中一条，数据永久分叉 |
| 5 | SQLite 事件领取快照竞态 | `db/repository/events.py:348-463`（`claim_event_trigger_guard`） | 未像同类函数一样用 `BEGIN IMMEDIATE`，事务以 SELECT 开头，WAL 模式下并发触发时以 `SQLITE_BUSY_SNAPSHOT` 异常失败，而非有序落败 |
| 6 | 剧情二次终态更新回滚整批事务 | `db/repository/story.py:310-392`，调用点 `events.py:1601-1606` | 对已完成的剧情再次应用 completed 更新无幂等短路，抛 `StoryStateTransitionError` 导致整个事件执行批次（消息、状态、触发记录、对话轮次）回滚，且重试仍会失败 |
| 7 | 群聊会话列表 N+1 查询 | `db/repository/sessions_and_messages.py:531-594`（`get_all_player_sessions`） | 每个群聊线程循环内执行 3 条独立查询，50 个线程 = 150+ 条 SQL |
| 8 | 世界时间窗口按 UTC 而非玩家时区判定 | `core/event_detector.py:314-332`（`_check_world_time_window`） | `world_time` 快照恒为 UTC，玩家本地时区/星期完全未使用；上海玩家配置的"22:00-23:00 深夜事件"实际在本地早上 6 点触发，与 cron 调度使用的时区语义矛盾 |
| 9 | 群聊同回合发言两次，首次好感度增量丢失 | `core/multi_character_orchestrator.py:1855-1860, 2026-2027` | 同一角色第二次发言的基线未包含第一次的状态增量，落库时取"最后一个 context"，第一次的 +N 好感度被静默覆盖丢弃 |
| 10 | cron 补跑循环无上界 | `core/cron_schedule.py:129-185` | 世界时钟大幅前跳或长期离线场景下，`collect_due_cron_runs` 可迭代数百万次，调度线程卡死数分钟到数小时，期间全体玩家的定时事件和自主群聊停摆 |
| 11 | 群聊每回合重复查询事件上下文 | `core/multi_character_orchestrator.py:495-552` → `core/event_runtime.py:84-168` | 对每个参与者（含未发言者）重复执行约 6 条查询，其中 session/turn计数/200行历史等在同回合内完全相同，延迟随参与人数线性放大 |
| 12 | CSRF 新规则导致"结束会话"请求必然 403（回归） | `web/src/api/memoria.js:615-631, 713-729` + `core/csrf.py:20-23` + `main.py:286-292` | `sendBeacon`/keepalive fetch 无法携带 `X-CSRF-Token`，豁免列表只有登录/注册；页面关闭/刷新时结束会话请求 100% 被拒，会话残留为 active |
| 13 | `cli_chat.py` 默认参数必然运行失败 | `scripts/cli_chat.py:28-36, 62-72` | 默认 `--player-id cli_player`，`character_loader.py:93-110` 在传了 `owner_user_id` 时只查数据库、不回退文件角色卡，除非数据库恰好有该用户，默认运行直接 `FileNotFoundError` |
| 32 | 任意 `BadRequestError` 被永久误判为"不支持 response_format" | `core/llm_client.py:751-757`（黑名单定义在 270 行） | 一次超长 prompt 引发 400 后，模型在整个进程生命周期内永久失去 JSON 模式，未检查错误是否真的与 response_format 相关，也不会在降级后回滚 |
| 33 | 流式响应消费阶段无异常保护、无重试，且提前记成功指标 | `core/llm_client.py:747-768, 221-253` | `_retry_call` 只包住 `create()`，真正网络 I/O 在流迭代中发生；网络抖动会使整回合以未处理异常失败，且失败前已计入 `llm.calls.succeeded`，绕过"永不崩溃"的兜底设计 |
| 34 | `call_role_turn` 对非 dict 的合法 JSON（数组/字符串/数字）直接返回 | `core/llm_client.py:810-815`，`_extract_json` 412-453 行 | 模型输出合法但非对象的 JSON 时，调用方 `result.get("dialogue")` 抛 `AttributeError`，回合 500，绕过 `_plain_text_fallback` 兜底 |
| 35 | 开场白 prompt 读取错误的 runtime_state 键，好感度恒为 0 | `core/prompt_builder.py:353`（`build_opening_line_prompt`） | 用 `runtime_state.get('affinity', 0)` 而非正确的 `affection_level`，高好感玩家重新进入会话时角色以陌生态度开场，人设不连贯 |
| 36 | 多角色记忆提取用裸 `json.loads`，未复用同文件容错解析器 | `core/multi_character_memory.py:205` | 轻量模型输出带围栏或前置文字时解析失败，按角色记忆提取长期静默返回 `[]`，功能形同虚设 |
| 37 | `get_group_memories` 回退分支跨用户查询群体记忆 | `core/multi_character_memory.py:686-717` | 未传 `owner_user_id` 调用与 #2 同源的 `get_character_group_memories`，目前仅测试代码调用，但作为公开 API 一旦被业务复用即造成越权 |

---

## 🟢 低

| # | 问题 | 位置 |
|---|---|---|
| 14 | 群聊通知 upsert 无唯一约束，并发下产生重复通知 | `db/repository/events.py:2496-2572` |
| 15 | 子查询过滤粒度错误，导致同批结果排序键相同、顺序未定义 | `db/repository/sessions_and_messages.py:404-462`（`get_sessions_by_player_and_character`） |
| 16 | 好感度累加无 [-100,100] 钳制，与其它写路径不一致 | `db/repository/relationships.py:299-336`（`update_relationship_affinity`） |
| 17 | 长期记忆向量检索命中未做租户复验 | `db/repository/state_and_memory.py:232-241` |
| 18 | `is_multi_character` 两处用裸 `= 0` 而非 `COALESCE(...,0)` | `db/repository/sessions_and_messages.py:106, 734` |
| 19 | 消息写入与参与者统计分属两个事务，崩溃会导致数据不一致 | `db/repository/multi_session.py:398-431` |
| 20 | 无效 token 请求触发全表扫描式清理 DELETE，可被恶意请求放大成写压力 | `db/repository/users.py:324-327` |
| 21 | 无连接池，每次调用重新 connect 并设置 WAL pragma；存在嵌套开连接模式 | `db/repository/_common.py:271-305` |
| 22 | 回放功能泄露"未来"状态给前端（`current_state`/`state_timeline` 未按 step 截断） | `core/replay.py:14-47` |
| 23 | 群聊角色选择权重可为负，长会话后随机退化 | `core/multi_character_orchestrator.py:1697-1723`（`_select_character_for_interaction`） |
| 24 | 脉冲对话持久化路径非原子、无幂等保护 | `core/multi_character_orchestrator.py:1053-1075` |
| 25 | 内部字段 `_previous_affinity/_previous_trust` 泄露到 API 响应 | `core/multi_character_orchestrator.py:2026-2044` |
| 26 | 群聊 SSE 推送的是事件系统处理前的旧响应 | `core/multi_character_orchestrator.py:386-394, 1095-1103` |
| 27 | 事件配额被单个低优先级事件的 `max_triggers_per_turn` 全局压制 | `core/event_detector.py:68-71`，`core/event_runtime.py:889-892` |
| 28 | NPC 主动对白在持有 5 分钟触发守卫期间同步执行完整 LLM 生成，超时可被其他 worker 重复领取 | `core/event_executor.py:403-411` |
| 29 | 自主群聊脉冲使用领取租约前的过期状态快照判断冷却，限额可被小幅突破 | `core/group_dialogue_runtime.py:146-191` |
| 30 | seed 脚本帮助文本中的演示用户名与实际实现不一致 | `scripts/seed_story_module.py:688-691`，`scripts/seed_graytide_demo.py:67-70` |
| 31 | `ChatRoom.jsx` 会话列表加载失败被空 `catch {}` 完全吞掉，UI 无法区分"无会话"与"加载失败" | `web/src/pages/ChatRoom.jsx:1020` |
| 38 | 流式调用缺少 `stream_options={"include_usage": True}`，token 指标缺失 | `core/llm_client.py:728-729, 230-233` |
| 39 | LLM client 惰性单例无锁，并发首建可能泄漏连接 | `core/llm_client.py:368-401` |
| 40 | 嵌入模型 CUDA 降级路径无锁共享可变状态；记忆相似度未夹取到非负 | `core/vector_memory.py:96-133, 236` |
| 41 | Speech provider 默认路径每次请求新建 `httpx.AsyncClient`，无连接复用 | `core/speech_provider.py:117-120,275-279,405-408`，`speech_service.py:113-114` |
| 42 | STT locale 直接下标访问，异常库值会 `KeyError` 而非 4xx | `core/speech_provider.py:160`，`speech_service.py:179-186` |

---

## ✅ 正面确认（已排查，未发现问题）

- **仓储层拆分一致性**：`db/repository/` 拆分模块与 `repository_monolith_backup.py` 做了函数级 MD5 比对，277 个函数全部存在、逻辑完全一致，拆分无遗漏、无行为漂移。
- **前端安全**：全项目无 `dangerouslySetInnerHTML`/`innerHTML`/`eval`，消息内容全部经 React 文本节点渲染；无硬编码密钥/URL。
- **前端并发防护**：会话切换的竞态防护（generation/epoch 计数器）质量高，`ChatRoom`/`KnowledgeManager`/`EventList`/`RelationshipGraph`/`UserContext` 均有守卫，快速切换会话/账号时未发现旧响应覆盖新数据的路径。
- **依赖与配置**：`pyproject.toml`/`requirements.txt` 版本约束一致无冲突；`config/settings.yaml` 与文档一致（明确不参与运行时加载）；角色卡 JSON 均通过 schema 校验；文档（API.md/ARCHITECTURE.md/FAQ.md）与代码实现逐条核对一致。
- **核心编排的其它部分**：`claim/fail/commit_dialogue_turn` 的租约与幂等语义整体正确；事件链的深度/环检测正确；`world_clock` 的锚点换算、乐观锁、暂停语义正确；`background_jobs` worker 的租约丢失处理正确；`run_world_clock_scheduler` 的取消传播正确。
- **核心服务层**：流式 JSON 解析器（`_DialogueJsonStream`）的代理对边界处理与前缀单调性正确；知识检索授权链路（`get_authorized_*`）以 SQL 侧复核向量命中，无孤儿 chunk 泄露；知识文档解析对 zip 炸弹/路径穿越/加密条目防护完整；prompt 构建含防注入护栏；密钥全程 `SecretStr` 包装、日志不透传；语音缓存 key 设计与并发锁、原子落盘正确；`_retry_call` 的指数退避与错误分类（429/5xx 重试、400 不重试）正确。

---

## 建议的后续行动

1. **优先修复**：#1（事件提交失败误报成功）、#2（跨用户记忆泄露）— 均为数据一致性/隐私类严重问题。
2. **尽快修复**：#3（PG 分页崩溃，若计划迁移到 PostgreSQL 则是阻断性问题）、#12（CSRF 导致会话结束功能回归）、#34（非 dict JSON 输出导致回合 500）、#35（开场白好感度读错键，影响所有会话的第一印象）。
3. **补充审查**：`src/memoria/api/`（含 avatar_fetcher.py 的 SSRF 修复）、CSRF 完整安全评估、限流绕过手法，本轮因推理网关容量限制未能覆盖。
