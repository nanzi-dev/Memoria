# 世界时间记忆曲线

Memoria 默认对玩家事实、角色印象和群体经历应用基于世界时间的记忆曲线。曲线只决定一次生成中哪些候选记忆可被召回、应以多确定的语气表达，以及候选之间的顺序；它不会删除或改写原始记忆，也不会改变 `fact_claim` 事实账本的状态。

该功能不增加 LLM 调用，不重建 ChromaDB 索引。单聊与多角色对话共用相同的曲线、采样和提示词规则。

## 适用范围

| `memory_type` | 原始数据 | 曲线所属角色 |
|---|---|---|
| `player_fact` | 玩家事实声明；旧数据可来自 `long_term_fact` | 知晓该事实的角色 |
| `character_impression` | `shared_memory` 中的方向性角色印象 | 形成印象的观察者角色 |
| `group_experience` | `group_memory` 中的群体经历或会话摘要 | 经历的每个参与角色 |

曲线状态按用户、角色、记忆类型和记忆 ID 隔离。同一条群体经历对不同角色可以具有不同强度，其他用户也无法看到或影响当前用户的曲线。

短期消息、会话摘要、知识库文档和当前关系图谱不使用本曲线。关系图谱仍是角色关系的最高优先级来源；图谱修订前的过时关系记忆会先按现有规则排除，不能通过记忆闪回覆盖当前图谱。

## 保留度模型

曲线以 `retention` 表示当前保留度，范围为 `0.0–1.0`：

```text
retention = anchor_strength / (1 + elapsed_days / stability_days)
```

- `anchor_strength`：形成记忆时为 `1.0`；强化后成为新的强度锚点。
- `elapsed_days`：从当前锚点起累计的世界时间天数。
- `stability_days`：记忆稳定期。稳定期越长，衰减越慢。

初始稳定期按以下公式计算：

```text
importance_multiplier = 2 ** (4 * (importance - 0.5))
stability_days = clamp(7 * importance_multiplier * source_multiplier, 0.5, 365)
```

`importance` 在计算前归一化到 `0.0–1.0`。来源倍率如下：

| `source_kind` | 倍率 | 含义 |
|---|---:|---|
| `authored_event` | 2.0 | 作者定义的事件记忆 |
| `player_message` | 1.5 | 玩家直接提供的证据 |
| `admin` / `admin_verification` | 1.5 | 管理员写入或确认 |
| `legacy` | 1.0 | 没有新来源元数据的存量记忆 |
| `model_inference` | 0.75 | 模型从对话中推断的印象或经历 |

未知来源按 `1.0` 处理。基础稳定期为 7 个世界日，最终稳定期始终限制在 `0.5–365` 个世界日。

### 世界时钟语义

曲线只累计向前经过的世界时间：

- 世界时钟暂停时，世界时间不变，记忆不衰减。
- 倍速运行或向前跳时时，按实际推进的世界时间衰减。
- 世界时间回拨时，不扣减已累计时间，也不恢复强度。
- `world_time_watermark` 保存已处理的最高世界时间，避免重试或重复召回对同一段时间重复计入衰减。回拨后要等世界时间再次超过水位，才会继续累计新的衰减时间。

存量记忆没有曲线状态时，第一次参与正常召回会以满强度初始化。开发者诊断接口不会触发该初始化。

## 强化

同一事实出现新的证据、共享印象去重命中，或同一群体经历再次出现时，会使用发生时的世界时间先结算衰减，再强化记忆：

```text
new_strength = current_retention + (1 - current_retention) * 0.5
new_stability = min(current_stability * 1.7, 365)
```

也就是恢复当前缺失强度的一半，并把稳定期扩大到原来的 `1.7` 倍。首次形成只初始化，`reinforcement_count` 仍为 `0`。

每次写入携带 evidence、message 或 pulse ID。`memory_curve_reinforcement` 对“用户 + 角色 + 类型 + 记忆 + evidence ID”建立复合主键，因此任务重试不会重复强化；SQLite 写入使用即时事务，PostgreSQL 更新使用行锁，避免并发丢失更新。

## 清晰度、采样与排序

| 保留度 | `clarity` | 召回规则 | Prompt 表达约束 |
|---:|---|---|---|
| `>= 0.65` | `clear` | 始终召回 | 可清晰表达 |
| `0.35–0.65` | `fuzzy` | 以 `retention` 为概率采样 | 使用“似乎、好像、可能”等不确定表达 |
| `0.15–0.35` | `fragment` | 以 `retention` 为概率采样 | 不得主动断言细节，只能作为模糊联想 |
| `< 0.15` | `forgotten` | 本轮不可召回 | 不注入 Prompt |

边界值归入较清晰的区间，例如 `0.65` 为 `clear`、`0.35` 为 `fuzzy`、`0.15` 为 `fragment`。

弱记忆的采样值由以下输入计算：

```text
SHA-256(recall_key + NUL + memory_id)
```

`recall_key` 来自当前请求、流、消息或脉冲标识。同一召回键的结果可复现，不同回合则可能产生偶发闪回。清晰记忆不受采样影响。

通过采样的候选按以下得分重新排序：

```text
rank = 0.60 * original_relevance
     + 0.25 * retention
     + 0.15 * importance
```

`original_relevance` 保留既有向量/词法检索顺序的主导地位，曲线不会重建或改写向量索引。

## 存储模型

曲线使用两个同时兼容 SQLite 与 PostgreSQL 的旁路投影表：

### `memory_curve_state`

以 `(owner_user_id, character_id, memory_type, memory_id)` 为主键，保存：

- 强度锚点和锚点对应的累计衰减时间；
- 稳定期、累计衰减秒数和世界时间水位；
- 来源、归一化 importance 和强化次数；
- 创建、更新时间。

### `memory_curve_reinforcement`

保存已处理的幂等证据 ID、证据对应的世界发生时间和创建时间。它引用对应的 `memory_curve_state`，只用于去重强化。

这两个表都不替代原始记忆表。关闭曲线或曲线计算失败时，原始玩家事实、`shared_memory`、`group_memory` 与 `fact_claim` 账本仍保持原样。

## 配置与故障回退

功能默认开启：

```bash
MEMORIA_MEMORY_CURVE_ENABLED=true
```

修改根目录 `.env` 或部署环境变量后需要重启服务。设置为 `false` 后，召回顺序和 Prompt 格式回到曲线接入前的行为，不再初始化、推进或强化曲线状态；已有旁路状态不会被删除。历史兼容名 `MEMORY_CURVE_ENABLED` 仍可读取，但新部署应使用带 `MEMORIA_` 前缀的名称。

曲线读取、写入或计算异常时，运行链路记录警告并回退到既有召回/写入行为，不因旁路投影故障丢失对话或原始记忆。

## 只读诊断

已登录用户可检查自己角色的候选记忆：

```http
GET /api/v1/developer/memory-curve?character_id=npc_luo_xiaohei&session_id=<session_id>&recall_key=<turn_id>&include_forgotten=true
Authorization: Bearer <token>
```

- `character_id` 必填；角色必须属于当前用户。
- `session_id` 可选；提供时会校验会话归属和角色参与关系，并把群体经历限制到该会话。
- `recall_key` 可选；省略时使用稳定的诊断默认值。
- `include_forgotten` 默认为 `false`；设为 `true` 才返回 `forgotten` 项。确定性采样未命中的弱记忆仍会返回，便于诊断。

每项包含原始文本、类型、来源、importance、retention、清晰度、稳定期、累计衰减秒数、强化次数、召回概率、采样值、采样结果、排序分和排除原因。常见 `exclusion_reason`：

| 值 | 含义 |
|---|---|
| `null` | 当前候选未被排除 |
| `deterministic_sample_miss` | 弱记忆本次确定性采样未命中 |
| `retention_below_threshold` | 保留度低于 `0.15` |
| `stale_relationship_history` | 关系图谱修订前的过时关系记忆 |

诊断端点只读取当前世界时钟和已有曲线行：它不会创建存量记忆的曲线状态、推进水位、累计衰减或增加强化次数。即使功能开关关闭，也可用它检查已有状态或预览候选计算结果。完整字段示例见 [API 文档](API.md#4-记忆曲线诊断)。
