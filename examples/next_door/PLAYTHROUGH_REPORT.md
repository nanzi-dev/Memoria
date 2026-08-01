# next_door 实机通关测试记录

测试日期：2026-08-01（Asia/Shanghai）
测试环境：真实 FastAPI + 真实 SQLite
API：`http://127.0.0.1:8003`，`GET /health` 返回 `{"status":"ok","version":"0.5.0"}`
真实数据库：`data/sqlite_db/memoria.db`
自动化请求记录：`/tmp/next_door_playthrough.jsonl`

`examples/next_door` 没有官方结局。本次“通关”按模块主线定义为：10 个事件全部真实触发，并且玩家与 4 个 NPC 的单聊好感度都达到 40。

## 触发事件

以下 10 条记录均来自 `event_execution` 表，状态均为 `succeeded`：

| 事件 | 角色 | 触发会话 | 时间（UTC） |
|---|---|---|---|
| `nd_move_in` | 陈大壮 | 群聊 | 2026-07-31 16:21:37 |
| `nd_benben_challenge` | 王奔奔 | 群聊 | 2026-07-31 16:21:49 |
| `nd_sugar_sketch` | 苏糖 | 群聊 | 2026-07-31 16:21:49 |
| `nd_xiaoxi_recommends` | 林小溪 | 群聊 | 2026-07-31 16:21:49 |
| `nd_dazhuang_invite` | 陈大壮 | 群聊 | 2026-07-31 16:22:05 |
| `nd_library_together` | 林小溪 | 群聊 | 2026-07-31 16:23:02 |
| `nd_late_night_snack` | 陈大壮 | 单聊 | 2026-07-31 16:38:34 |
| `nd_sugar_portrait` | 苏糖 | 单聊 | 2026-07-31 16:42:55 |
| `nd_dorm_talk` | 陈大壮 | 单聊 | 2026-07-31 16:42:58 |
| `nd_confide_dazhuang` | 陈大壮 | 单聊 | 2026-07-31 16:43:05 |

`nd_dorm_talk` 在测试中被陈大壮单聊好感从 37 跨到 47 时触发。此时其他 NPC 好感分别是苏糖 35、王奔奔 33、林小溪 18，还没有第二个 NPC 达到 40。

## 最终关系值

来自 `relationship_state` 表：

| NPC | 好感度 | 信任度 | 心情 |
|---|---:|---:|---|
| 陈大壮 | 67 | 46 | 开心 |
| 林小溪 | 48 | 34 | 平静 |
| 苏糖 | 40 | 25 | slightly_shy_but_pleased |
| 王奔奔 | 41 | 22 | 无 |

## 测试方法

测试先通过群聊和自然单聊推进剧情，再通过单聊发送明确的 JSON 增量指令，让模型在合法输出字段中返回 `affinity_delta` 和 `trust_delta`。每次数值增量都通过真实 API 写回真实 SQLite。

关键统计：

- 自然单聊 19 轮，`affinity_delta` 和 `trust_delta` 非零的轮数为 0。
- 显式增量请求 30 轮，实际产生非零增量的轮数为 11。
- 11 次有效增量全部是新会话的第一轮；同一会话后续轮次即使继续要求相同增量，返回值也全部为 0。

## 系统问题

以下问题不属于 `next_door` 的剧情设计，而是 Memoria 平台在本次实机测试中暴露的系统层缺陷：

1. 关系数值完全依赖 LLM 自报的 `affinity_delta` / `trust_delta`，没有由对话内容、事件结果或规则兜底保证增量。角色台词已经明显升温，但 19 轮自然单聊全部返回 0，叙事推进与关系状态更新脱节。
2. 同一会话内显式增量只生效一次。30 轮显式请求中只有 11 轮有效，且全部是新建会话后的第一轮；后续轮次即使继续要求相同增量，系统仍接受 0 并落库，没有基于“本轮应发生关系升温”的约束或重试机制。
3. 阈值事件使用 `crossing: true` 时强依赖单轮数值跨越。由于问题 1 导致自然聊天不产生增量，即使对话已经到达交心节点，状态仍不会跨过阈值，事件系统无法触发。
4. 事件触发 schema 缺少复合条件和跨角色聚合能力。`nd_dorm_talk` 描述需要“任意两个 NPC 好感度达到 40”，但触发条件只能表达单个 `affinity_threshold`，运行时只检查当前发言角色的好感。实测陈大壮单聊好感从 37 跨到 47 时即触发，其他 NPC 都尚未达到 40。
5. 群聊 speaker 选择不稳定。本次测试中情绪最重的一轮群聊只有林小溪回应，其他 NPC 没有参与，多角色编排没有稳定的选择结果或剧情参与保障。

## 记录保留

- 请求记录：`/tmp/next_door_playthrough.jsonl`
- 数据库：`data/sqlite_db/memoria.db`
- 数据库表：`event_execution`、`relationship_state`、`session`、`short_term_message`
