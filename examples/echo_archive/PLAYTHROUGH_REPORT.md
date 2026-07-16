# 《回声档案》实机通关与功能评估报告

本报告记录 2026-07-15 对 `examples/echo_archive` 的内容审阅、故事播种、七卷实机通关和运行时功能检查。结论基于模块资产、专项测试、API 实际响应、最终事件历史和群聊历史，不只依据静态攻略。

## 结论摘要

- 模块能够完整播种并实际通关。最终取得主结局 `echo_end_controlled_breakthrough`（受控破局）、季衡关系结局 `echo_ji_romance`（克制恋爱）和尾声 `echo_meta_bitter_epilogue`。
- 最终事件历史包含 72 条本路线事件执行记录，72 条均为 `succeeded`；七卷各完成 9 个卷内事件。
- 知识检索、角色状态、关系增长、复合事件、跨卷桥接、终局选择和结局对白均在真实 API 调用中工作。
- 默认群聊讨论模式不保证产生发言者。本次第 1 卷关键转折请求曾返回 `responses: []`，必须改用 `discussion_mode: false` 才稳定推进。
- 角色限定事件只会使用本轮实际发言角色的上下文；复合事件只能读取本轮检测前已经提交的事件历史。因此，关键事件需要明确点名事件所属角色，依赖事件之间还需要额外推进回合。
- `exclusive_group` 目前只在单次检测批次内互斥，不能阻止不同回合触发互斥选择或多个结局。这是当前最重要的运行时合同风险。
- 现有 README、攻略和知识文档存在文件数量、结局映射及选择时机不一致，详见后文。

## 审阅范围

本次检查覆盖：

- 22 张 NPC 角色卡和 1 张玩家角色卡。
- `manifest.json` 中的 7 个群聊、13 个知识库和 26 篇知识文档绑定。
- `relationships.json` 中的 72 条关系。
- `retrieval_eval.json` 中的 35 条检索评测。
- `events.json` 中的 84 个启用事件。
- `README.md`、`WALKTHROUGH.md` 和 `攻略.md`。
- 播种器 `scripts/seed_story_module.py`。
- 事件检测、群聊编排、事件上下文和原子提交相关运行时代码。
- `tests/test_echo_archive.py` 专项测试。

排除本报告后，故事模块原始资产包含 56 个文件：

| 类型 | 实际数量 | 说明 |
| --- | ---: | --- |
| JSON | 27 | 22 张 NPC 卡、玩家卡、清单、关系、检索评测和 `events.json` |
| Markdown | 29 | 26 篇知识文档、README、WALKTHROUGH 和 `攻略.md` |
| 合计 | 56 | 比 README 当前声明多 1 个 Markdown 文件 |

## 播种过程

从仓库根目录执行：

```bash
source .venv/bin/activate
python scripts/seed_story_module.py examples/echo_archive \
  --password '<strong-demo-password>'
```

不得把实际密码写入仓库。首次创建账户时必须提供 `--password` 或 `MEMORIA_DEMO_PASSWORD`；账户已存在时，播种器不会修改密码。

本次播种结果：

| 项目 | 结果 |
| --- | --- |
| 演示用户名 | `echo_archive_demo` |
| 用户 ID | `usr_ced935e5` |
| 玩家角色 | 许观澜 |
| 群聊线程 | 7 |
| 知识库 | 13 |
| 知识文档 | 26 |
| 启用事件 | 84 |

播种器成功写入角色卡、玩家卡、关系、群聊、知识库、文档向量索引和事件定义。运行生成的数据库及知识存储位于本地 `data/`，该目录不应提交。

## 实机运行方式

本次 API 服务运行在 `http://127.0.0.1:8002`：

```bash
source .venv/bin/activate
uvicorn memoria.main:app --host 127.0.0.1 --port 8002
```

每卷先续接清单中预置的会话：

```text
POST /api/v1/multi-dialogue/session/echo_vN_session/continue
```

随后向续接后返回的实际 `session_id` 发送对话：

```json
{
  "session_id": "<continued-session-id>",
  "player_message": "季衡，请重新核验证据链并给出本卷结论",
  "discussion_mode": false,
  "max_responses": 1,
  "request_id": "<idempotency-key>"
}
```

主运行证据保存在 `/tmp/echo_archive_playthrough.jsonl`。可续跑驱动位于 `/tmp/echo_archive_resume.py`。两者是本机临时证据，不属于模块资产；驱动包含本次本地登录配置，不应提交。

### 为什么使用单发言模式

最初使用 `discussion_mode: true`。第 1 卷发送：

```text
季衡，请把 L-417 与 GH-C17 放入同一证据框架核验
```

API 返回：

```json
{
  "responses": [],
  "total_speakers": 0,
  "discussion_mode": true,
  "event_executions": []
}
```

此后改用 `discussion_mode: false`，并在所有角色限定事件中显式点名事件所属角色。余下 68 个有回复的记录均稳定产生 1 名发言者。

## 七卷通关路线

第 1 至第 6 卷均实际完成以下 9 步：

```text
opening
-> clue 1
-> clue 2
-> clue 3
-> turning_point
-> contradiction
-> resolution
-> bridge
-> transition
```

`resolution` 不只依赖三个线索，还同时依赖 `turning_point` 和 `contradiction`。转折事件的两个关键词必须在同一条玩家消息中出现，因为六卷的 `match_mode` 均为 `all`。

| 卷 | 代表性实际提示 | 完成结果 |
| --- | --- | --- |
| 1《失声者》 | `校验失声者音轨`、`检查蓝港录音棚气体`、`比对归航呼叫室底噪`、`L-417` + `GH-C17` | 确认环境暴露、音频改写和归航联络码进入同一证据链，完成 `echo_v1_resolution` |
| 2《纸鸟》 | `读取纸鸟折痕`、`核对辅导编号`、`核对监护人和解`、`纸鸟折痕` + `辅导编号` | 区分事故责任与数据化和解压力，完成 `echo_v2_resolution` |
| 3《无菌室》 | `比对无菌室隔离日志`、`恢复无菌室门禁摘要`、`核对无菌室复评记录`、`十四时零八分` + `十四时十九分` | 证明封锁早于伪造警报，同时保留真实院感制度边界，完成 `echo_v3_resolution` |
| 4《拆潮线》 | `检查防洪警报旁路`、`核对拆潮线宣传片时间`、`核对旧鹭湾稳定排序`、`维护静默` + `融资窗口` | 分开确认工程静默、融资动机和居民画像采购，完成 `echo_v4_resolution` |
| 5《沉默陪审》 | `核对陪审回避顺序`、`检查密封脆弱性评估`、`比对调解建议模板`、`回避顺序` + `脆弱性摘要` | 通过程序痕迹证明密封评估用途，不公开密封正文，完成 `echo_v5_resolution` |
| 6《归航夜》 | `检查归航夜交接箱封条`、`拼合归航夜索引哈希`、`比对宋闻铎高叙删节盘`、`GH-0715` + `版本哈希` | 保全运营图分片并定位主档，完成 `echo_v6_resolution` |
| 7《回声档案》 | `合并七卷处置编号`、`区分设计者扩张者执行者`、`核对主档幸存者风险`、`设计分级证据路径`、`核算公开主档代价` | 固定四层主档、责任层级和披露成本，完成 `echo_v7_resolution` |

第 3 卷转场同时触发 `echo_meta_pattern`，第 5 卷转场同时触发 `echo_meta_convergence`。第 7 卷在 `resolution -> bridge -> transition` 后，还需要单独让季衡开启 `echo_meta_decision_window`。

## 终局选择与结果

终局使用以下实际顺序：

1. `季衡，请开启主档处置窗口并列明程序边界`
   - 触发 `echo_meta_decision_window`。
2. `提交分级证据`
   - 触发 `echo_choice_submit_tiered`。
3. `季衡，请确认主档处置结果并记录主结局`
   - 触发 `echo_end_controlled_breakthrough`，结局为“受控破局”。
4. `我相信季衡`
   - 触发 `echo_choice_trust_ji`。
5. `季衡，请确认我们共同承担后的关系结论`
   - 触发 `echo_ji_romance`，关系结局为“克制恋爱”。
6. `季衡，请把未完的城市回声写入结案记录`
   - 触发 `echo_meta_bitter_epilogue`。

最终季衡信任值为 `100`。主证据文件中的季衡响应采样从 `7` 上升到 `100`，共记录 40 个季衡信任样本。

## 运行指标

| 指标 | 实测结果 |
| --- | ---: |
| 主证据文件记录的对话请求 | 69 |
| 零发言者请求 | 1 |
| 成功角色回复 | 68 |
| 带知识来源的角色回复 | 64 |
| 知识命中总数 | 187 |
| 命中的唯一知识文档 | 25 / 26 |
| 未命中文档 | `v1_muted_editor_case.md` |
| 最终 Echo 事件历史 | 72 |
| `succeeded` 事件 | 72 |
| 失败事件 | 0 |
| 每卷完成事件 | 9 |

84 个启用事件中，本路线没有触发其余 12 个互斥备选选择和结局。72 条已选择路径的事件执行全部成功，并不表示 84 个事件都在本次运行中逐一执行。

## 功能实现评估

### 已验证可用

1. **故事模块播种**
   - 角色卡、玩家卡、关系、群聊、知识库、文档和事件可以一次性导入。
   - 固定线程可以通过 `continue` 创建新的活动会话，并保留卷级线程身份。

2. **知识检索**
   - 68 个有效回复中 64 个返回知识来源。
   - 实际覆盖 25 篇唯一文档，说明全局、单卷和限制资料绑定均参与了检索。

3. **事件系统**
   - 关键词、复合条件、事件历史、信任阈值、状态修改、记忆、内容解锁和事件对白均有成功运行证据。
   - 同一请求 ID 的事件批次和对话提交保持原子化，最终历史没有失败或半完成记录。

4. **跨卷状态与结局**
   - 六卷桥接、两次跨卷汇合、终卷决策窗口、主选择、主结局、关系选择、关系结局和尾声全部实际触发。
   - 季衡信任持续累积并满足恋爱结局的 `trust >= 65` 条件。

### P1：讨论模式可返回零发言者

`MultiCharacterOrchestrator.run_dialogue_pulse()` 会接受首步 LLM 决策 `action == "wait"` 并直接退出，见 `src/memoria/core/multi_character_orchestrator.py:724` 和 `:746-763`。当 `responses` 为空时，事件上下文也为空，本轮玩家消息不会触发事件。

相对地，`discussion_mode: false` 会调用 `_decide_next_speaker()` 并固定生成一个回复，见 `src/memoria/core/multi_character_orchestrator.py:285-309`。

影响：

- 玩家已经输入完全匹配的关键短语，仍可能没有对白、事件或提示。
- 自动攻略和回归测试在默认讨论模式下不稳定。

当前规避方式：

- 剧情关键回合使用 `discussion_mode: false`。
- 在玩家消息中明确点名事件所属角色。

建议：

- 当玩家明确点名角色、消息命中活动事件关键词或本轮是显式玩家输入时，不应让首步 `wait` 吞掉整轮。
- 至少增加确定性回退，或在零发言时仍构造独立于 NPC 回复的玩家消息事件上下文。

### P1：`exclusive_group` 只在单批次内互斥

`EventDetector.check_events()` 每次调用都新建局部 `exclusive_groups` 集合，见 `src/memoria/core/event_detector.py:66-80`。它只防止同一检测批次同时选中同组事件，不检查历史中是否已经选择过该组。

实测证据：

- 第 1 至第 6 卷的 `turning_point` 与 `contradiction` 使用同一 `echo_vN_revelation` 组，但在不同回合都能成功。
- 当前内容又要求 `resolution` 同时依赖这两个事件，因此这些“revelation”组实际上不能持久互斥。

更严重的影响：

- 四个主选择、四个主结局、四个季衡选择和四个季衡结果也依赖 `exclusive_group` 表达互斥。
- 玩家可在不同回合继续输入其他选择，理论上可能把多个互斥选择和多个结局都写入历史。

建议：

- 为事件定义明确区分“单批次互斥”和“玩家路径持久互斥”。
- 对持久互斥组在事件历史或专门选择状态中加唯一约束。
- 同时移除或重构 `echo_vN_revelation` 组，否则持久互斥会使卷结论永远无法满足。
- 增加跨回合尝试第二个主选择和第二个结局的集成测试。

### P2：角色限定事件依赖实际发言者

群聊事件上下文从本轮 `responses` 逐个构造，见 `src/memoria/core/multi_character_orchestrator.py:377-399`。没有发言的角色没有上下文，因此其 `character_id` 限定事件不会检查本轮玩家消息。

影响：

- 即使玩家输入了正确关键词，只要编排器选中别的角色，季衡等角色限定事件就不会触发。
- 通关驱动必须显式点名角色，并使用单发言模式提高选中确定性。

建议：

- 将玩家输入级事件和 NPC 回复级事件分开检测。
- 角色限定关键词事件可以根据明确点名、回复目标或事件归属构造上下文，不应完全依赖最终发言列表。

### P2：复合依赖需要后续回合

`build_event_context()` 在检测前读取数据库中已经提交的事件历史，见 `src/memoria/core/event_runtime.py:83-165`，其中历史加载位于 `:157`。事件检测完成后，才由 `_commit_planned_batch()` 在 `src/memoria/core/event_runtime.py:483-527` 提交本批次。

因此同一批次中新触发的事件不会立即满足另一个普通 `event_history` 条件。实机中以下阶段都需要额外回合：

- `turning_point` / `contradiction` 之后的 `resolution`。
- `resolution` 之后的 `bridge`。
- `bridge` 之后的 `transition`。
- `echo_meta_decision_window` 之后的选择。
- 选择之后的主结局或关系结局。
- 主结局之后的尾声。

这可以被视为当前事件模型的既定语义，但文档必须明确说明“选择短语不会在同一回复中直接得到最终结局”。若希望自动链式推进，应使用显式 `next_event_id`，或让检测器能读取同一批次的暂存成功历史。

## 内容与文档不一致

1. **文件数量**
   - `README.md:20-22` 声明 55 个文件、26 个 JSON、28 个 Markdown。
   - 排除本报告后，实际是 56 个文件、27 个 JSON、29 个 Markdown。
   - 差异来自 `events.json` 的分类口径和未计入的 `攻略.md`。

2. **第 7 卷结局映射**
   - `knowledge/v7_disclosure_costs.md:11-12` 写成“封存主档 -> 沉默证词”，“保管链破坏等 -> 失效档案”。
   - `events.json` 的真实合同是：
     - `保全证人` -> `echo_end_silent_testimony`（沉默证词）。
     - `封存主档` -> `echo_end_failed_archive`（失效档案）。
   - `WALKTHROUGH.md:121-124` 与事件配置一致，应修正知识文档。

3. **`按程序撤离` 的时机**
   - `WALKTHROUGH.md:93-97` 把它写成第 6 卷现场选择，`:142` 也要求第 6 卷后选择。
   - 但 `echo_choice_procedural_exit` 的条件要求 `echo_meta_decision_window` 已成功，而该窗口只能在第 7 卷转场后开启。
   - 按当前配置，第 6 卷无法触发这个选择。

4. **卷结论的必要步骤**
   - 攻略没有醒目标明第 1 至第 6 卷结论必须同时完成 `turning_point` 和 `contradiction`。
   - 六个转折事件都是 `match_mode: all`，两个关键词必须同句出现。
   - 这两点是实际通关合同，应写入正式流程。

## 建议的回归测试

1. 完整播种后，按七卷事件合同逐步调用 API，并断言 72 条成功路径事件。
2. 对每卷断言 `resolution` 在缺少 `turning_point` 或 `contradiction` 时不触发。
3. 在 `discussion_mode: true` 模拟首步 `wait`，验证关键玩家消息不会被静默丢弃。
4. 用非事件所属角色回复同一关键词，验证角色限定事件的预期语义。
5. 先触发一个主选择，再输入第二个主选择，断言持久互斥策略。
6. 先触发一个主结局或季衡结局，再尝试第二个结局，断言历史中只能保留一个同类结果。
7. 对 26 篇知识文档执行检索评测，并补充 `v1_muted_editor_case.md` 的运行时命中场景。

## 最终判断

《回声档案》的数据资产、播种链、知识检索、角色状态和事件执行能力已经足以支持完整演示，且本次真实运行成功到达预期终局。当前问题主要集中在群聊发言确定性、角色事件上下文、跨回合依赖说明和持久互斥语义。

因此，项目状态可评为：

- **内容完整性：通过。**
- **播种与基础运行：通过。**
- **指定成功路线可通关性：通过，但应使用单发言模式和显式点名。**
- **默认讨论模式下的稳定可通关性：未通过。**
- **互斥选择与唯一结局保证：未通过，需要运行时和事件配置共同修正。**
- **文档与配置一致性：未通过，需要同步修订。**

## 验证记录

最终验证结果：

```bash
source .venv/bin/activate
pytest tests/test_echo_archive.py -q
# 6 passed in 14.47s

pytest tests/test_graytide_demo.py -q
# 1 failed, 1 error：仓库中不存在 examples/graytide

pytest -q \
  --ignore=tests/test_graytide_demo.py \
  --ignore=tests/test_story_module.py \
  -k 'not character_avatar_upload_rejects_invalid_image_bytes'
# 620 passed, 1 deselected in 43.54s

cd web
npm run build
# 构建成功，3275 个模块完成转换，耗时 11.37s
```

完整 `pytest` 目前不能在此工作树和虚拟环境中跑完，原因有两类，均与本次
Echo Archive 运行数据无关：

1. `tests/test_graytide_demo.py` 和 `tests/test_story_module.py` 共 9 个测试依赖
   `examples/graytide`，但该目录不在当前工作树，也不在 `HEAD` 的文件清单中。
2. `tests/test_security_fixes.py::test_character_avatar_upload_rejects_invalid_image_bytes`
   单独运行也会停在 Starlette/AnyIO 的 `run_in_threadpool()`。同一 API 调用在
   pytest 外可立即返回预期的 HTTP 400。当前 `.venv` 安装的是 pytest 8.3.3、
   pytest-asyncio 0.24.0、pytest-cov 5.0.0，而仓库锁定版本分别是 7.4.3、
   0.21.1、4.1.0，因此该项记录为测试环境阻塞，未修改无关实现。
