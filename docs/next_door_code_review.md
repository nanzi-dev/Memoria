# next_door 实机测试暴露系统问题：修复后代码审查

审查基线：`data/sqlite_db/memoria.db`、`examples/next_door/events.json`、`/tmp/next_door_playthrough.jsonl` 与 `examples/next_door/PLAYTHROUGH_REPORT.md`。

本次只修复系统行为，不改故事/剧情内容；用户既有未跟踪改动、`.bak` 与真实库数据均保留。

## 验证摘要

- 全量测试：`863 passed`
- 前端构建：`npm run build` 成功
- next_door 实机回归：`NEXT_DOOR_REGRESSION_OK`，记录 `/tmp/next_door_regression_20260801.jsonl`
- 真实库播种：`nd_dorm_talk` 已写入 `aggregation=count, min_characters=2, character_ids=[nd_chen_dazhuang, nd_lin_xiaoxi, nd_su_tang, nd_wang_benben], threshold=40`，未使用 `--reset-module`，事件执行历史保留
- 当前 API：`127.0.0.1:8003`

## 已修复系统问题

### 高：关系增量缺少确定性兜底，且 LLM 返回 0 时升温意图会失效

- 新建 [relationship_delta_policy.py](/home/nanzi/PY3/Memoria/src/memoria/core/relationship_delta_policy.py:156)，统一 `resolve_relationship_delta`，LLM 非零值保留并 clip 到 `[-10, 10]`；零值或缺失时按文本和动作做好感/信任兜底，默认下限 0、上限 10。
- 默认配置在 [config.py](/home/nanzi/PY3/Memoria/src/memoria/core/config.py:174)，从 `.env` 读取 `MEMORIA_RELATIONSHIP_DELTA_ENABLED/MIN/MAX`，不改 `settings.yaml`。
- 单聊、群聊、重构后的逐条脉冲三处统一调用，并把 LLM 对白与玩家消息一起传给兜底，避免“显式增量只首轮生效”：
  - [orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/orchestrator.py:946)
  - [multi_character_turn.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_turn.py:497)
  - [multi_character_orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_orchestrator.py:2042)
- 兜底规则：明确正面/信任内容给有界正增量；冲突/拒绝给 0 或负值；中性文本返回 0，避免状态精确变更被无关文本推高。覆盖测试见 [test_relationship_delta_policy.py](/home/nanzi/PY3/Memoria/tests/test_relationship_delta_policy.py:20)。

### 高：`nd_dorm_talk` 依赖单角色 crossing，群聊中任意单人达标即可触发，不符合“任意两个 NPC 好感 40”

- [event_schema.py](/home/nanzi/PY3/Memoria/src/memoria/core/event_schema.py:53) 增加 `aggregation/min_characters/character_ids`，默认 `aggregation=any`，旧事件无需迁移。
- [event_detector.py](/home/nanzi/PY3/Memoria/src/memoria/core/event_detector.py:117) 支持单聊默认当前 context、群聊传入本轮全部 scoped contexts；`count` 要求至少 `min_characters` 个角色满足，`all` 要求全部满足，`any` 保持旧行为；复合条件同步传递 group contexts。
- [event_runtime.py](/home/nanzi/PY3/Memoria/src/memoria/core/event_runtime.py:871) 在群聊 `detect_and_execute_event_contexts` 中把本轮全部上下文交给条件检测，并让分支事件执行同样使用聚合上下文（[event_executor.py](/home/nanzi/PY3/Memoria/src/memoria/core/event_executor.py:344)）。
- `nd_dorm_talk` 配置改为 4 个指定 NPC 中至少 2 个达到 40，移除 `crossing` 依赖，仍保留 cooldown：[events.json](/home/nanzi/PY3/Memoria/examples/next_door/events.json:212)。
- 聚合测试覆盖“2 个达标触发、1 个不触发、any 旧语义不变、单聊 count 不触发”：[test_events.py](/home/nanzi/PY3/Memoria/tests/test_events.py:415)。
- 管理端同步：DTO 校验与归一化在 [event_admin.py](/home/nanzi/PY3/Memoria/src/memoria/api/event_admin.py:46) 和 [event_admin.py](/home/nanzi/PY3/Memoria/src/memoria/api/event_admin.py:348)；前端默认表单、清洗、校验、summary、聚合表单在 [EventEditor.jsx](/home/nanzi/PY3/Memoria/web/src/pages/EventEditor.jsx:121)、[EventEditor.jsx](/home/nanzi/PY3/Memoria/web/src/pages/EventEditor.jsx:228)、[EventEditor.jsx](/home/nanzi/PY3/Memoria/web/src/pages/EventEditor.jsx:303)、[EventEditor.jsx](/home/nanzi/PY3/Memoria/web/src/pages/EventEditor.jsx:443)、[EventEditor.jsx](/home/nanzi/PY3/Memoria/web/src/pages/EventEditor.jsx:575)。

### 中：高情绪/高利害群聊轮仍可能只回 1 人，实机体验像“无人接话”

- [multi_character_orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_orchestrator.py:752) 重构响应数决策：高情绪、高利害、问句、多角色提及、长文本或关系压力场景下，响应数下限为 `max(2, min(cap, participant_count - 1))`，不再概率返回 1；短 ack 仍允许单回复。
- 压力估算收敛到 [multi_character_orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_orchestrator.py:816)。
- [multi_character_orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_orchestrator.py:1362) 的 `_fallback_dialogue_decision` 在强参与场景且已有回应不足时继续发言，不再直接 `wait`。
- [multi_character_orchestrator.py](/home/nanzi/PY3/Memoria/src/memoria/core/multi_character_orchestrator.py:912) 的 `run_dialogue_pulse` 仍保持 `max_messages = min(3, ...)` 上限，避免无界刷屏。
- 测试覆盖高压力轮响应数 `>= 2`、单点名仍单回复、短 ack 仍单回复、强参与 fallback 不 wait：[test_orchestrator.py](/home/nanzi/PY3/Memoria/tests/test_orchestrator.py:210)、[test_group_dialogue_pulse.py](/home/nanzi/PY3/Memoria/tests/test_group_dialogue_pulse.py:1191)。

## 实机回归证据

- 自然升温轮：`affinity_delta=3.0, trust_delta=1.0`，关系正向增量正常进入状态；LLM 返回 0 时的确定性兜底由关系 delta 单测覆盖。
- 同一会话第二次显式升温仍生效：大壮两次显式升温轮均为 `affinity_delta=2.0, trust_delta=2.0`，亲和度升至 `57.2`。
- 单聊轮不触发 `nd_dorm_talk`；群聊高压力轮 `total_speakers=3` 且触发 `nd_dorm_talk`。
- 真实库保留 4 条 `nd_dorm_talk` 执行记录（旧 3 条 + 回归 1 条），guard 时间为最终回归触发时间，执行历史未删除。

## 低风险备注

- `examples/next_door/README.md` 中播种命令直接写了 demo 密码，属于仓库内示例文档的密钥/口令管理风险；本轮未改密码本身，建议后续用占位符或脚本提示输入。
- LLM 对显式 `affinity_delta=10` 指令实际返回 `2.0` 而非 10，系统按 LLM 非零值保留，符合“不放大模型数值”的规则；若希望实机体验更明显，应通过角色 prompt/校准处理，而非继续放大 delta 上限。
- 实机回归中个别 LLM 返回 `0.1` 的非零 delta，会被保留并产生极小的状态漂移；当前不改变默认配置，后续可考虑 prompt 引导或允许配置阈值归一化。
- 对 `events.json` 做了重复 key 检查，当前文件未发现重复 key；故事/剧情文案问题不属于本轮系统修复范围。
