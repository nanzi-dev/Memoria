# 灰潮港：第十三声钟鸣真实通关记录

## 1. 运行范围

本记录依据 [`examples/graytide/WALKTHROUGH.md`](../examples/graytide/WALKTHROUGH.md)
完成。调查没有直接修改剧情表、关系值或事件状态；所有进展均通过真实 FastAPI
对话、LLM 回复、事件检测器和世界时钟产生。

- 演示账号：`memoria_demo`
- 玩家 ID：`usr_b53d49ca`
- 玩家角色：岑澜，独立潮痕测绘员
- SQLite：`data/sqlite_db/memoria.db`
- Chroma：`data/chroma_db`
- 固定群聊线程：`graytide_investigation_thread`
- 最终群聊承载 session：`2676e082-6992-4b6d-8d1a-241551e9e09e`
- 最终结论消息：`short_term_message.id = 99`

数据库和向量库均为项目的持久目录，不是临时数据库。

## 2. 通关判定

攻略定义的四项目标均已完成：

1. 还原了 23:37 异常电报、23:49 记忆封锁、午夜十二声及第十三声的时间线。
2. 核验了蓝线航图和半枚测绘牌，并取得电报、校验摘要、零号货单、冷凝液诊断和逆向棘轮采购线索。
3. 证明逆向棘轮可让地下传动轴在锁止间隙反转，将压力峰值送入第七共振管。
4. 明确代理采购和批准链值得调查，但证据尚不能指认实际安装者、泵站操作者或记忆封锁执行者。

系统没有独立的“案件完成”状态。这里的通关判定来自攻略目标、成功事件、解锁记录
和最终玩家结论的共同证据。

## 3. 调查过程

### 3.1 艾琳：建立证物边界和时间线

先以岑澜的身份说明半枚测绘牌、蓝线航图和六年前复测经历。艾琳将玩家记录为
A-00 证物持有人，并给出三条核验路线：

- 米拉核验复测章和档案登记。
- 奥斯卡核验工程符号和地下压力路径。
- 阿特拉斯核验登记格式和时间戳摘要。

随后连续询问钟鸣前半小时、主钟锤锁止记录、第七码头地图删除、钟鸣前的人为行动
和证据缺口。第五轮触发 `graytide_erin_fifth_question`。回答坚持“只能确认有人利用
压力网制造额外共振，不能确认操作者”，从一开始区分了事实、推论与嫌疑。

### 3.2 诺娅：取得钟鸣前电报

使用“三短一长”和“延迟报码”询问诺娅，触发 `graytide_noa_telegram` 并解锁
`graytide_telegram_copy_13`。

得到的关键事实是：异常报码在 23:37 出现，比午夜钟鸣早二十三分钟。诺娅因为通信
保密规则延迟上报，这解释了传递延迟，但不能把她认定为报码制造者。

### 3.3 阿特拉斯：读取封锁前摘要

使用“黄铜记忆匣”和“维护口令七零七”请求只开放时间戳与校验摘要，先后触发：

- `graytide_atlas_memory_key`
- `graytide_atlas_hears_bell`

阿特拉斯确认记忆在 23:49 被高级维护指令封锁，比钟鸣早十一分钟；其长期事实记录
还保留了“第十三声并非来自主钟，而是从地下传动轴反向传入”。摘要能证明封锁时间
和机械方向，不能证明谁签发或执行了封锁。

### 3.4 伊芙琳：确认冷凝液暴露

围绕“银雾咳嗽”和“手套发蓝”询问，触发 `graytide_evelyn_diagnosis`。

诊断结论为：症状不是人际传播，蓝染来自未经中和的钟塔冷凝液；样本中的磷铜抑制剂
进一步指向旧潮汐泵站设备。该结论证明近期设备活动，不证明操作者身份。

### 3.5 奥斯卡：还原机械路径

依次核验蓝线航图双短横、主钟锁止后的地下压力路径、逆向棘轮九十秒反转、维护日志
笔迹和停用密钥。`graytide_oskar_under_pressure` 成功触发，数据库长期事实记录：
事发前一夜的维护日志不是奥斯卡的笔迹。

奥斯卡给出的完整路径是：

> 废弃泵站操作者启动逆向棘轮，地下传动轴反转，主管产生压力峰值，压力沿仍然连通
> 的第七共振管绕过地表封闭控制，进入钟塔共振层，在主钟锤锁止间隙形成全城可闻的
> 第十三声。

该路径解释“主钟没有第十三次撞击但全城听见钟声”，仍无法识别安装者、泵站操作者
和维护密钥使用者。

### 3.6 罗文：跨过好感门槛取得零号货单

先用非指控式问题区分“知道旧航道”和“参与作案”，再核对空舱登记、燃料消耗、
许可证压力和原始货单。罗文好感从 14 提升至 27 后，三个相关事件同轮成功：

- `graytide_open_cipher_ledger`
- `graytide_ledger_followup`
- `graytide_rowan_manifest`

解锁：

- `graytide_manifest_zero`
- `graytide_pump_station_route`

零号货单显示货物伪装为钟表修复件，相关凭证指向克劳工业代理采购，收货点为废弃
潮汐泵站。代理签章证明运输链被使用，不等于塞拉斯本人签发。

### 3.7 米拉：跨过信任门槛核验禁档

米拉的档案事件需要持续建立信任。本次共进行了 15 轮玩家/NPC 消息交换，其中 13 轮
用于把信任从 0 提升到 37，达到禁档门槛；最终关系值为好感 72、信任 48。

调查先触发 `graytide_mira_silas_dispute`，确认米拉拒绝永久封存令；随后触发
`graytide_mira_trust_archive` 并解锁
`graytide_archive_tidemark_register`。

她核验了六年前复测章，并在账册夹层确认逆向棘轮采购线索。一次回复曾错误声称凭证
带有塞拉斯本人签名；追问原件后，她更正为“克劳工业代理印章加身份不明的经办人
手签”，撤回了直接关联塞拉斯亲笔签名的说法。

### 3.8 群聊：合并证据和验证理论

在固定线程中把“货单、冷凝液、反向棘轮”放入同一条消息，成功触发
`graytide_case_progress`。这一阶段把历史路径证据与近期运行证据连接起来：

- 蓝线航图证明第七支路历史路径与归档摘要矛盾。
- 零号货单证明近期采购和运输。
- 冷凝液证明设备近期运行。
- 逆向棘轮解释人为制造额外压力峰值的工具。

群聊中的“地下传动 + 第十三声”轮次 API 返回 `[]`，因此改在奥斯卡单聊正式核验，
成功触发 `graytide_composite_bell_theory`。

### 3.9 世界时钟：验证低潮、雾笛和午夜压降

玩家世界时钟推进并触发三类时间事件：

| 世界时间 | 事件 | 结果 |
| --- | --- | --- |
| 2026-07-15 05:30 UTC | `graytide_dawn_low_tide` | 旧海堤检修门约五十分钟可通行 |
| 2026-07-15 06:00 UTC | `graytide_harbor_siren_schedule` | 调度器投递雾笛例检，第三短鸣缺失 |
| 2026-07-15 23:55 UTC | `graytide_midnight_power_dip` | 地下传动声更清晰并解锁监听线索 |

当前持久时钟为 `UTC/fixed`，`clock_revision = 4`，锚定世界时间为
`2026-07-15T23:55:00Z`。

### 3.10 塞拉斯：核对批准链而不提前定罪

对话依次核对稳定剂批准范围、归档摘要修改、代理签章权限、最终收货点和正式调取条件。
塞拉斯承认代理链和批准节点需要说明，但要求按授权程序开放材料。

最终阶段结论是：

- 克劳工业代理运输链和工业席批准体系需要解释。
- 凭证只有代理印章和身份不明经办人签字。
- 批准者不等于安装棘轮、操作泵站或执行记忆封锁的人。
- 塞拉斯是需要接受正式调取的批准链节点，不是已被证明的实际执行者。

塞拉斯最终关系值为好感 -46、信任 5，说明高压审问确实产生了关系代价，但没有阻止
程序性答复。

### 3.11 最终复盘

最后在联合调查组要求按时间顺序区分事实、推论和执行者缺口，再发送玩家结论。结论
完整保存在 `short_term_message.id = 99`：

> 我的蓝线航图和半枚测绘牌证明第七支路的历史走向与归档摘要矛盾，它们建立了调查
> 入口，但不替代当夜操作证据。第十三声不是主钟的第十三次撞击。有人让废弃泵站的
> 逆向棘轮驱动地下传动轴反转，在十二声结束后的锁止间隙把压力峰值送入第七共振管。
> 零号货单、蓝色冷凝液和订货凭证证明泵站仍在秘密使用；23:37 提前出现的电报和
> 23:49 记忆封锁证明事件包含人为准备。克劳工业代理链和塞拉斯的批准值得继续调查，
> 但现有证据还不能确定实际安装者、泵站操作者和记忆封锁执行者。因此本案主线完成，
> 结论是不提前宣布凶手，继续按授权链追查三个执行环节。

最终结论轮次的 API 同样返回 `[]`，但玩家消息已落库；约三十秒后，自主群聊又持久化
了艾琳和塞拉斯的后续回复。

## 4. 事件与解锁结果

17 个事件执行成功：

`graytide_fog_warning`、`graytide_erin_fifth_question`、
`graytide_noa_telegram`、`graytide_atlas_memory_key`、
`graytide_atlas_hears_bell`、`graytide_evelyn_diagnosis`、
`graytide_oskar_under_pressure`、`graytide_open_cipher_ledger`、
`graytide_ledger_followup`、`graytide_rowan_manifest`、
`graytide_mira_silas_dispute`、`graytide_mira_trust_archive`、
`graytide_case_progress`、`graytide_composite_bell_theory`、
`graytide_dawn_low_tide`、`graytide_harbor_siren_schedule`、
`graytide_midnight_power_dip`。

5 个持久解锁：

- `graytide_telegram_copy_13`
- `graytide_manifest_zero`
- `graytide_pump_station_route`
- `graytide_archive_tidemark_register`
- `graytide_listen_underground_drive`

`graytide_group_proactive` 执行失败，错误为
`NPC 主动对白目标不是可用群聊`。它硬编码指向已经结束的播种 session
`graytide_investigation_session`，不影响上述主线证据和最终结论落库。

## 5. 持久数据库复盘索引

通关后的数据库状态：

| 项目 | 数量 |
| --- | ---: |
| 会话 | 14（4 群聊、10 单聊） |
| 对话轮次 | 48（全部外层状态为 `completed`） |
| 消息 | 102（48 user、54 assistant） |
| 事件执行 | 18（17 succeeded、1 failed） |
| 解锁 | 5 |
| 长期事实 | 99 行、22 个不同文本 |
| 群聊记忆 | 11 |
| 事件收件箱 | 5 |
| 知识库 | 4 |
| 知识文档 | 8，全部 `ready` |
| 知识分块 | 50 |

最终关系状态：

| 角色 | 好感 | 信任 |
| --- | ---: | ---: |
| 阿特拉斯 | 42 | 5 |
| 艾琳 | 51 | 24 |
| 伊芙琳 | 48 | 4 |
| 米拉 | 72 | 48 |
| 诺娅 | 25 | 5 |
| 奥斯卡 | 47 | 14 |
| 罗文 | 27 | 14 |
| 塞拉斯 | -46 | 5 |

可从仓库根目录执行以下只读查询开始复盘：

```bash
sqlite3 -header -column data/sqlite_db/memoria.db \
  "SELECT id, session_id, role, character_id, content, created_at, world_created_at
   FROM short_term_message
   WHERE id >= 95
   ORDER BY id;"
```

```bash
sqlite3 -header -column data/sqlite_db/memoria.db \
  "SELECT event_id, trigger_source, status, error, created_at
   FROM event_execution
   WHERE owner_user_id = 'usr_b53d49ca'
   ORDER BY created_at;"
```

```bash
sqlite3 -header -column data/sqlite_db/memoria.db \
  "SELECT character_id, affection_level, trust_level, current_mood
   FROM relationship_state
   WHERE player_id = 'usr_b53d49ca'
   ORDER BY character_id;"
```

## 6. 复盘注意事项

数据库保存了完整玩家消息、事件、解锁、关系和知识索引，但不是所有长期事实都可信。
群聊生成了文档中不存在的“潮声代理”、1998/2003 印鉴备案、错误年份和额外机构，
随后其中 11 个文本被各复制到 8 个角色，共形成 88 行重复长期事实。

复盘时应优先采用：

1. `examples/graytide` 的原始文档和事件定义。
2. 成功事件的固定效果与解锁记录。
3. 玩家原始消息和带知识来源的回复。
4. 经追问、更正和交叉核验后的 NPC 结论。

不要把生成式群聊中的新增专名、年份或机构自动视为设定事实。
