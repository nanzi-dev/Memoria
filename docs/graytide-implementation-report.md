# Graytide 真实通关后的功能实现说明

## 1. 结论

Memoria 已能用真实 FastAPI、LLM、RAG、关系系统、事件系统、群聊和世界时钟完成
Graytide 主线。核心交互状态均持久化到项目 SQLite 和 Chroma 目录，关系门槛、
关键词/复合事件、世界时间窗口、Cron 调度和解锁效果均在本次运行中实际生效。

但系统目前只能认定为“主线可玩、核心机制已实现”，不能认定为“剧情运行时完整可靠”。
主要差距集中在：

- 没有规范化的案件完成状态。
- 群聊同步响应与自主脉冲的语义不一致。
- 事件主动对白错误绑定物理 session。
- 生成事实缺少证据约束和写入前校验。
- 共享事实被复制到每个角色，放大了幻觉污染。

## 2. 已验证架构

### 2.1 单角色对话

单聊入口位于
[`src/memoria/api/dialogue.py`](../src/memoria/api/dialogue.py)。请求先领取幂等轮次，
再加载角色、关系、历史与知识，由 LLM 生成基础回复，随后执行事件检测和效果合并，
最后原子提交玩家消息、最终 NPC 消息、关系状态和事件结果。

主要实现：

- 对话编排：[`src/memoria/core/orchestrator.py`](../src/memoria/core/orchestrator.py)
- 事件运行时：[`src/memoria/core/event_runtime.py`](../src/memoria/core/event_runtime.py)
- 事件检测：[`src/memoria/core/event_detector.py`](../src/memoria/core/event_detector.py)
- 事件效果：[`src/memoria/core/event_executor.py`](../src/memoria/core/event_executor.py)
- 持久化：[`src/memoria/db/repository.py`](../src/memoria/db/repository.py)

本次 44 个单聊轮次均通过该链路完成。

### 2.2 多角色对话

群聊由
[`src/memoria/core/multi_character_orchestrator.py`](../src/memoria/core/multi_character_orchestrator.py)
决定参与者发言、等待、回复对象和重复抑制，并在同一事务中提交玩家消息、NPC 回复、
状态及事件。

自主群聊由
[`src/memoria/core/group_dialogue_runtime.py`](../src/memoria/core/group_dialogue_runtime.py)
基于逻辑线程运行；当旧承载 session 结束时，该运行时能够创建新的承载 session。
仓储层再做一次重复检查并提交消息。

本次固定线程跨 4 个物理 session，证明“逻辑线程 + 可更换承载 session”已实际工作。

### 2.3 事件系统

[`src/memoria/core/event_detector.py`](../src/memoria/core/event_detector.py) 已实现：

- 关键词和复合条件。
- 好感、信任阈值及 crossing 语义。
- mood 精确匹配。
- 世界时间窗口。
- 事件优先级、互斥组、每轮上限和 `stop_processing`。

[`src/memoria/core/event_runtime.py`](../src/memoria/core/event_runtime.py) 负责幂等事件批次、
计划、提交和 Cron 世界日历调度。

本次证据：

- 罗文从好感 14 提升到 27 后解锁零号货单。
- 米拉从信任 0 经多轮提升至 37 后触发禁档，最终为 48。
- “货单 + 冷凝液 + 反向棘轮”触发调查阶段推进。
- “地下传动 + 第十三声”触发反向钟声理论。
- 05:30、06:00、23:55 三类世界时间事件均成功。
- 17 个事件成功、5 个 unlock 持久化。

### 2.4 知识检索

知识检索使用向量和关键词混合排序，并在仓储层执行 `global`、`character` 和
`group_thread` 绑定过滤。Graytide 播种结果为：

- 4 个知识库。
- 8 个 `ready` 文档。
- 50 个知识分块。
- 全局、角色和固定群聊线程绑定均存在。

授权过滤实现是有效的，但“允许检索哪些知识”不等于“模型只能陈述这些事实”，这正是
本次最大的数据质量问题之一。

### 2.5 持久化与幂等

默认仓储使用 SQLite/WAL，可切换 PostgreSQL，并提供事务回滚、对话轮次 claim、
事件批次幂等和关系状态持久化。

本次持久记录包含：

- 14 个 session。
- 48 个 `dialogue_turn`。
- 102 条短期消息。
- 18 条事件执行。
- 5 个解锁。
- 99 条长期事实。
- 11 条群聊记忆。
- 世界时钟 revision 4。

数据库能够支持逐消息复盘，但外层 `dialogue_turn.status = completed` 不代表该轮内部
每个事件都成功；最终复盘轮次就是外层完成、内部主动对白事件失败。

## 3. 已实现但存在语义缺口

### 3.1 没有规范化“案件完成”状态

最终结论完整保存在 `short_term_message.id = 99`，部分语义进入 `group_memory`，
但没有进入 `long_term_fact`、`session_summary` 或单独的 case-completion 状态。
`graytide_case_progress` 仍为 `active/0.25`，
`graytide_composite_bell_theory` 仍为 `active/0.55`。

因此系统能保存“玩家说已经完成”，但不能可靠查询“这个案件已经完成”。

建议：

1. 增加显式 `case_state`/`story_progress` 聚合状态。
2. 用必要事件、必要 unlock 和最终结论校验共同驱动完成迁移。
3. 将完成迁移与最终消息放入同一事务。

### 3.2 单聊无法获得仅绑定群聊线程的卷宗

Graytide 调查卷宗只绑定 `graytide_investigation_thread`。群聊检索会传入线程 ID，
单聊检索不会，因此单聊角色不能访问这部分线程知识。

这不是权限泄漏，而是上下文可用性不足。实际表现包括艾琳曾把当前世界时间误作案件
发生时间，部分角色依靠角色卡或自由生成补齐事实。

建议：

- 为案件参与者增加显式 case binding，而不是依赖当前物理会话类型。
- 单聊若属于已加入的调查线程，应携带逻辑案件/线程上下文。
- 在回复元数据中显示“未检索到案件卷宗”，便于调试。

### 3.3 `trigger_dialogue` 完全覆盖基础回复

事件执行器收集 `trigger_dialogue` 文本后，事件运行时把最终回复直接替换为
`[事件触发] + overrides`，而不是追加或与基础 LLM 回复合并。

这会丢失模型原本给出的解释，也会让事件文本和当前问题衔接生硬。

建议把效果语义拆为：

- `replace_dialogue`
- `append_dialogue`
- `system_notification`

默认使用追加或结构化通知，只在事件定义明确要求时覆盖。

## 4. 缺陷与风险

### P0：生成事实污染长期记忆

群聊生成了原始文档中不存在的内容，包括：

- “潮声代理”中间商。
- 1998 年印鉴启用备案。
- 2003 年停用记录。
- 1999 年诊所采购样本。
- 额外仓库、机构和批准条例。

这些内容随后被记忆提取器批量写入长期事实。数据库中有 99 行长期事实，但只有
22 个不同文本；其中 11 个文本各复制到全部 8 个角色，共 88 行。

根因不是知识权限过滤错误，而是生成提示仅把检索材料描述为参考，检索失败仍允许无
RAG 继续生成，且生成后没有事实验证。共享对话提取结果又被扇出到每个角色，放大污染。

建议：

1. 对案件模式启用 evidence-grounded prompt，要求重要专名、日期、文件和因果结论
   必须引用知识 chunk 或事件固定效果。
2. 将“模型新提出的事实”先写入候选事实表，标记 `unverified`，不要直接进入长期事实。
3. 对日期、机构、人物签名和证物来源做结构化 claim 校验。
4. 群聊共享事实保存一份并按可见范围引用，不复制为 8 份角色事实。
5. 允许管理员追溯事实来源到 message、chunk 或 event execution。

### P1：主动群聊事件硬编码已结束 session

`graytide_group_proactive` 的效果在
[`examples/graytide/events.json`](../examples/graytide/events.json) 中硬编码
`graytide_investigation_session`。该播种 session 已结束，事件执行器优先使用显式
目标并拒绝 ended session，最终报错：

```text
NPC 主动对白目标不是可用群聊
```

执行 ID 为 `8444b12eca124e868b8650d20c4aa0f9`。外层
`graytide-final-review` 仍标记 `completed`，容易掩盖内部失败。

建议：

- 事件效果使用 `group_thread_id`，运行时解析当前活动承载 session。
- 复用 `group_dialogue_runtime` 已有的“旧 session 结束后创建新承载 session”逻辑。
- API 响应增加 `partial_failure` 或显式事件失败摘要。
- 播种校验拒绝将长期群聊效果绑定到物理 session ID。

### P1：群聊空响应与异步消息语义不清

以下轮次返回 `response_data = []`：

- `graytide-group-bell-theory`
- `graytide-final-conclusion`

群聊编排器允许角色选择 `wait`，也会抑制重复回复。即使响应为空，玩家消息仍会提交。
与此同时，自主脉冲可在之后产生 NPC 消息，并通过固定线程历史显示出来。

最终结论轮次在 API 完成约三十秒后新增消息 100–102；消息 100 和 101 是艾琳的近重复
回复。这使调用方难以区分：

- 本轮没有回复。
- 回复被重复抑制。
- 回复将在异步脉冲中到达。
- 回复已到达但属于另一个承载 session。

建议：

1. 返回结构化结果：`responses`、`waited`、`suppressed`、`async_expected`。
2. 异步消息带 `caused_by_turn_request_id`。
3. 对近重复自主回复使用同一幂等键或内容指纹。
4. 前端把“暂无同步回复”和“正在等待异步群聊”显示为不同状态。

### P1：消息顺序存在现实时间倒序

用户消息 73 的 `created_at` 为 `15:16:58Z`，而 ID 更大的消息 74–76 的
`created_at` 为 `15:16:27Z`。历史聚合按消息 ID 排序，因此显示顺序与现实时间不一致。

消息同时保存现实提交时间 `created_at` 和较早捕获的世界时间 `world_created_at`，
跨 session 自主脉冲进一步增加了排序歧义。

建议：

- 为逻辑线程分配单调递增 `thread_sequence`。
- 历史显示按 `thread_sequence` 排序，不依赖数据库自增 ID 或时钟。
- 保留 `created_at` 和 `world_created_at` 作为展示/审计字段。
- 异步脉冲必须记录触发它的玩家轮次或前置消息。

### P2：模型回答质量和自我纠错依赖玩家追问

实际出现：

- 一轮异常短句：“这话问得奇怪，不讲不讲。”
- 米拉先错误声称凭证有塞拉斯本人签名，追问后才更正为代理印章和身份不明经办人手签。
- 艾琳把当前世界时间误作案件时间。

系统能在追问后纠正，但缺少自动一致性校验。对于调查类故事，错误签名或错误时间会直接
改变嫌疑判断。

建议：

- 在输出前校验时间线、证物主体、签名者和证明边界。
- 对“证明某人”“本人签名”“确定执行者”等高风险措辞要求至少两个独立证据来源。
- 将更正记录结构化，废弃被撤回的 claim，避免旧说法继续进入记忆。

### P2：定时触发路径存在可观测性分裂

运行日志多次出现 `不支持的触发类型: time_based`，但独立调度器最终成功执行
`graytide_harbor_siren_schedule`，世界时间窗口事件也能在对话路径触发。

这说明最终功能可用，但不同检测/调度入口对触发类型的支持和日志语义不一致。

建议为每种 trigger type 建立端到端矩阵测试，并在日志中标明检测入口、事件 ID、
是否交由其他调度器处理，避免把“当前入口不处理”记录成系统级“不支持”。

## 5. 功能完成度

| 功能 | 结论 | 本次证据 |
| --- | --- | --- |
| 单聊 LLM 对话 | 已实现 | 44 轮完成并持久化 |
| 玩家角色注入 | 已实现 | NPC 能识别岑澜、测绘牌和蓝线航图 |
| 关系变化 | 已实现 | 8 个角色状态持续更新 |
| 好感/信任门槛 | 已实现 | 罗文和米拉门槛真实生效 |
| 关键词/复合事件 | 已实现 | 调查推进和反向钟声理论成功 |
| 事件解锁 | 已实现 | 5 个 unlock 持久化 |
| 世界时间窗口 | 已实现 | 05:30 和 23:55 事件成功 |
| Cron 世界调度 | 已实现 | 06:00 雾笛事件由 scheduler 执行 |
| RAG 索引与权限 | 已实现 | 4 库、8 文档、50 chunk，绑定可审计 |
| 群聊逻辑线程 | 已实现 | 固定线程跨 4 个 session |
| 群聊同步结果 | 部分实现 | 两个关键轮次返回空数组 |
| 自主群聊 | 部分实现 | 能异步落库，但有重复和因果不透明 |
| 事件主动对白 | 存在缺陷 | ended session 导致执行失败 |
| 长期记忆 | 存在高风险 | 幻觉事实跨 8 角色重复扇出 |
| 案件完成状态 | 未实现 | 最终结论仅保存为消息/部分群聊记忆 |

## 6. 建议修复顺序

1. 修复共享事实写入策略和事实来源校验，阻止幻觉长期污染。
2. 将主动群聊事件从物理 session ID 改为逻辑 `group_thread_id`。
3. 为群聊同步/异步回复增加统一因果 ID、单调线程序号和结构化空响应原因。
4. 增加规范化故事进度与完成状态。
5. 将 `trigger_dialogue` 拆分为覆盖、追加和通知三种效果。
6. 扩展单聊案件上下文绑定，并增加关键事实一致性校验。
7. 统一 `time_based` 与 Cron 调度路径的日志和测试矩阵。

## 7. 总体判断

Graytide 证明 Memoria 已具备可运行的沉浸式调查框架：角色、关系、RAG、事件、世界时钟、
单聊和群聊能够共同驱动一条非线性主线，并保留足够的数据库证据用于复盘。

当前限制不在“功能是否存在”，而在“生成内容是否可信、异步群聊是否可解释、故事状态
是否可查询”。在修复事实治理、线程因果和规范化完成状态之前，该系统适合演示、内部
测试和人工主持的故事，不适合无人监督地维护长周期、强一致性的调查世界。
