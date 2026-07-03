# Memoria 多角色对话系统实现总结

## 概述

本文档记录了 Memoria 角色模拟系统的多角色对话功能实现。该功能支持 2 个或更多 NPC 角色同时参与群聊，实现角色间的自然互动。

**实现时间**: 2026年7月2日  
**状态**: ✅ 已完成  
**版本**: v1.0

---

## 核心功能

### 1. 多角色群聊支持
- ✅ 支持 2+ 个 NPC 角色同时在线
- ✅ 玩家消息触发角色回应
- ✅ 角色主动发言和互动
- ✅ 自动发言顺序管理
- ✅ **讨论模式**：多个角色可以连续发言（每轮最多3个）

### 2. 智能发言策略
- ✅ **轮询策略** (Round Robin): 角色按顺序依次发言
- ✅ **权重随机策略** (Weighted Random): 根据发言频率配置随机选择
- ✅ **智能策略** (Smart Selection): 综合考虑关键词、关系、频率等因素
- ✅ **触发策略** (Trigger-based): 基于特定条件触发发言
- ✅ **混合策略** (Hybrid): 结合多种策略的优点

### 3. 角色关系网络
- ✅ 角色间关系建模（类型、亲密度、互动历史）
- ✅ 关系影响发言决策
- ✅ 动态关系更新
- ✅ 双向关系查询

### 4. 多角色记忆系统
- ✅ **个人记忆**: 每个角色独立的记忆库
- ✅ **角色间记忆**: 角色之间的共同经历
- ✅ **群体记忆**: 所有参与者的集体记忆
- ✅ 三层记忆自动整合到对话上下文

### 5. 完整的 REST API
- ✅ 创建/结束多角色会话
- ✅ 处理对话轮次
- ✅ 触发角色互动
- ✅ 查询会话信息和历史
- ✅ 动态管理参与者（添加/移除/更新）

---

## 架构设计

### 数据模型

#### 1. Session 表扩展
```sql
ALTER TABLE session ADD COLUMN is_multi_character INTEGER DEFAULT 0;
```

#### 2. Multi-Session Participant 表（新增）
```sql
CREATE TABLE multi_session_participant (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    display_name TEXT,
    speak_frequency REAL DEFAULT 1.0,
    message_count INTEGER DEFAULT 0,
    last_spoke_at TEXT,
    is_active INTEGER DEFAULT 1,
    joined_at TEXT,
    FOREIGN KEY (session_id) REFERENCES session(id)
);
```

#### 3. Short-Term Message 表扩展
```sql
ALTER TABLE short_term_message ADD COLUMN character_id TEXT;
ALTER TABLE short_term_message ADD COLUMN character_name TEXT;
```

#### 4. Character Relationship 表（新增）
```sql
CREATE TABLE character_relationship (
    id TEXT PRIMARY KEY,
    character_a_id TEXT NOT NULL,
    character_b_id TEXT NOT NULL,
    relationship_type TEXT,
    affinity_score REAL DEFAULT 0.0,
    interaction_count INTEGER DEFAULT 0,
    last_interaction_at TEXT,
    created_at TEXT,
    updated_at TEXT
);
```

### 核心模块

#### 1. MultiCharacterOrchestrator（`multi_character_orchestrator.py`）
**职责**: 多角色对话编排

**主要方法**:
- `start_conversation()`: 启动会话，生成开场白
- `process_player_message()`: 处理玩家消息，决定回应角色
- `trigger_character_interaction()`: 触发角色主动发言
- `_decide_next_speaker()`: 使用策略系统选择发言角色
- `_format_history_for_llm()`: 格式化多角色对话历史

**设计特点**:
- 使用策略模式，支持动态切换发言策略
- 集成角色关系网络，影响发言决策
- 自动管理发言频率和均衡性
- 支持角色间的自然互动

#### 2. SpeakingStrategy（`speaking_strategy.py`）
**职责**: 发言策略系统

**策略类型**:

| 策略 | 类名 | 特点 | 适用场景 |
|------|------|------|---------|
| 轮询 | `RoundRobinStrategy` | 按顺序轮流发言 | 简单场景，确保公平 |
| 权重随机 | `WeightedRandomStrategy` | 按频率权重随机 | 需要控制发言比例 |
| 智能选择 | `SmartSelectionStrategy` | 综合多因素决策 | 复杂场景，自然互动 |
| 触发式 | `TriggerBasedStrategy` | 基于条件触发 | 特定事件驱动 |
| 混合策略 | `HybridStrategy` | 结合多种策略 | 默认推荐 |

**智能策略评分因素**:
- 关键词匹配（30%）
- 角色关系亲密度（25%）
- 发言频率配置（20%）
- 发言均衡性（15%）
- 最近发言时间（10%）

#### 3. MultiCharacterMemory（`multi_character_memory.py`）
**职责**: 多角色记忆管理

**记忆层次**:
1. **个人记忆** (`PersonalMemory`)
   - 每个角色独立的长期记忆
   - 使用向量检索获取相关记忆
   
2. **角色间记忆** (`SharedMemory`)
   - 两个角色共同经历的记忆
   - 支持双向查询
   
3. **群体记忆** (`GroupMemory`)
   - 所有参与者的集体记忆
   - 自动去重和整合

**核心功能**:
- `build_multi_character_context()`: 构建完整的多角色记忆上下文
- `save_shared_memory()`: 保存角色间共享记忆
- `save_group_memory()`: 保存群体记忆
- `get_character_interaction_history()`: 获取角色互动历史

#### 4. Prompt Builder 扩展（`prompt_builder.py`）
**新增函数**:

```python
def build_multi_character_system_prompt(
    card: CharacterCard,
    runtime_state: dict,
    player_name: str,
    other_characters: list[dict],
    character_relationships: dict = None,
    is_opening: bool = False,
    is_interaction: bool = False
) -> str
```

**功能**:
- 构建包含其他角色信息的系统提示
- 自动集成角色关系描述
- 支持开场白和互动两种模式
- 与单角色提示保持格式一致

#### 5. REST API（`multi_dialogue.py`）
**端点列表**:

| 端点 | 方法 | 功能 | 路径 |
|------|------|------|------|
| 开始会话 | POST | 创建多角色会话 | `/multi-dialogue/start` |
| 对话轮次 | POST | 处理玩家消息 | `/multi-dialogue/turn` |
| 角色互动 | POST | 触发角色发言 | `/multi-dialogue/interact` |
| 获取会话 | GET | 查询会话信息 | `/multi-dialogue/session/{id}` |
| 获取历史 | GET | 查询对话历史 | `/multi-dialogue/history/{id}` |
| 添加参与者 | POST | 添加新角色 | `/multi-dialogue/participant` |
| 移除参与者 | DELETE | 移除角色 | `/multi-dialogue/participant` |
| 更新频率 | PUT | 更新发言频率 | `/multi-dialogue/participant/frequency` |
| 结束会话 | POST | 结束会话 | `/multi-dialogue/end` |

---

## 工作流程示例

### 场景：玩家与两个 NPC 对话

```
1. 创建会话
   POST /multi-dialogue/start
   {
     "player_id": "player_001",
     "player_name": "旅行者",
     "character_ids": ["npc_luo_xiaohei", "npc_wuxian"],
     "strategy_type": "hybrid"
   }
   
   响应: 第一个角色（罗小黑）生成开场白
   "大家好！今天天气真不错呢~"

2. 玩家发言
   POST /multi-dialogue/turn
   {
     "session_id": "xxx",
     "player_message": "小黑，最近忙什么呢？"
   }
   
   智能策略分析:
   - 关键词匹配: "小黑" → 罗小黑 (高分)
   - 关系检查: 罗小黑与玩家亲密度 70
   - 发言频率: 罗小黑最近发言1次，巫仙0次
   
   决策: 罗小黑回应
   "嘿嘿，我在练习新的法术！要看看吗？"

3. 玩家继续
   POST /multi-dialogue/turn
   {
     "session_id": "xxx",
     "player_message": "哇，巫仙你觉得怎么样？"
   }
   
   智能策略分析:
   - 关键词匹配: "巫仙" → 巫仙 (高分)
   - 关系检查: 巫仙与玩家亲密度 65
   - 发言频率: 需要均衡（巫仙0次）
   
   决策: 巫仙回应
   "小黑的进步确实很快，不过还需要多练习控制力。"

4. 触发互动
   POST /multi-dialogue/interact
   {
     "session_id": "xxx"
   }
   
   系统选择: 罗小黑（最久未发言）
   罗小黑主动发言: "师父，你觉得我这次的咒语念得怎么样？"

5. 角色关系更新
   - 罗小黑 ↔ 巫仙: 互动次数 +1
   - 亲密度微调（基于对话内容）
```

---

## 数据库操作函数

### Repository 新增函数（`repository.py`）

#### 多角色会话管理
- `create_multi_character_session()`: 创建多角色会话
- `get_session_participants()`: 获取会话参与者列表
- `add_participant_to_session()`: 添加参与者
- `remove_participant_from_session()`: 移除参与者
- `update_participant_frequency()`: 更新发言频率
- `update_participant_stats()`: 更新发言统计

#### 多角色消息管理
- `append_multi_character_message()`: 记录多角色消息
- `get_multi_character_history()`: 获取多角色对话历史

#### 角色关系管理
- `save_character_relationship()`: 保存/更新角色关系
- `get_character_relationship()`: 查询角色关系
- `get_character_interactions()`: 获取互动历史
- `update_relationship_interaction()`: 更新互动统计

#### 多角色记忆管理
- `save_shared_memory()`: 保存共享记忆
- `get_shared_memories()`: 获取共享记忆
- `save_group_memory()`: 保存群体记忆
- `get_group_memories()`: 获取群体记忆
- `get_character_interaction_memories()`: 获取互动记忆

---

## 测试

### 测试脚本（`test_multi_dialogue.py`）

**测试用例**:
1. **基本功能测试**
   - 创建多角色会话
   - 处理玩家消息
   - 生成角色回应
   - 获取对话历史
   - 结束会话

2. **发言策略测试**
   - 测试5种不同策略
   - 验证策略切换
   - 检查发言分布

3. **参与者管理测试**
   - 动态添加参与者
   - 移除参与者
   - 更新发言频率

**运行测试**:
```bash
cd /home/nanzi/PY3/Memoria
python3 -m app.scripts.test_multi_dialogue
```

---

## 配置说明

### 发言频率配置

在创建会话时可以设置每个角色的发言频率权重：

```python
speak_frequencies = {
    "npc_luo_xiaohei": 1.2,  # 更活跃
    "npc_wuxian": 0.8        # 相对安静
}
```

### 策略选择建议

| 场景 | 推荐策略 | 理由 |
|------|---------|------|
| 正式会议 | `round_robin` | 确保每个角色都有机会发言 |
| 日常聊天 | `hybrid` | 自然的互动感 |
| 教学场景 | `weighted` | 老师发言频率高于学生 |
| 紧急事件 | `trigger` | 特定角色快速响应 |
| 探索发现 | `smart` | 最相关的角色发言 |

---

## API 使用示例

### Python 客户端示例

```python
import requests

BASE_URL = "http://localhost:8020"

# 1. 创建会话
response = requests.post(f"{BASE_URL}/multi-dialogue/start", json={
    "player_id": "player_001",
    "player_name": "旅行者",
    "character_ids": ["npc_luo_xiaohei", "npc_wuxian"],
    "speak_frequencies": {
        "npc_luo_xiaohei": 1.2,
        "npc_wuxian": 0.8
    },
    "strategy_type": "hybrid"
})

session = response.json()
session_id = session["session_id"]
print(f"开场白: {session['opening']['dialogue']}")

# 2. 对话
response = requests.post(f"{BASE_URL}/multi-dialogue/turn", json={
    "session_id": session_id,
    "player_message": "大家好！",
    "strategy_type": "hybrid"
})

reply = response.json()
print(f"{reply['character_name']}: {reply['dialogue']}")

# 3. 触发互动
response = requests.post(f"{BASE_URL}/multi-dialogue/interact", json={
    "session_id": session_id
})

interaction = response.json()
print(f"{interaction['character_name']} 主动说: {interaction['dialogue']}")

# 4. 获取历史
response = requests.get(f"{BASE_URL}/multi-dialogue/history/{session_id}?limit=20")
history = response.json()

for msg in history:
    if msg["role"] == "user":
        print(f"[玩家]: {msg['content']}")
    else:
        print(f"[{msg['character_name']}]: {msg['content']}")

# 5. 结束会话
requests.post(f"{BASE_URL}/multi-dialogue/end", json={"session_id": session_id})
```

---

## 文件清单

### 新增文件
- ✅ `app/core/multi_character_orchestrator.py` - 多角色对话编排器（450+ 行）
- ✅ `app/core/speaking_strategy.py` - 发言策略系统（400+ 行）
- ✅ `app/core/multi_character_memory.py` - 多角色记忆系统（350+ 行）
- ✅ `app/api/multi_dialogue.py` - REST API 端点（400+ 行）
- ✅ `app/scripts/test_multi_dialogue.py` - 测试脚本（300+ 行）

### 修改文件
- ✅ `app/db/repository.py` - 新增数据库操作函数（500+ 行新代码）
- ✅ `app/core/prompt_builder.py` - 新增多角色提示构建（100+ 行）
- ✅ `app/main.py` - 注册多角色 API 路由（1 行）
- ✅ `README.md` - 更新功能文档

### 总代码量
- **新增代码**: ~2,500 行
- **修改代码**: ~600 行
- **总计**: ~3,100 行

---

## 代码质量检查

### 语法检查
```bash
python3 -m py_compile app/core/multi_character_orchestrator.py
python3 -m py_compile app/core/speaking_strategy.py
python3 -m py_compile app/core/multi_character_memory.py
python3 -m py_compile app/api/multi_dialogue.py
```
✅ 所有文件通过编译检查

### LSP 诊断
✅ 所有文件无错误、无警告

### 代码审查结果
- ✅ 无冗余代码
- ✅ 正确使用 `prompt_builder` 模块
- ✅ 所有导入正确
- ✅ 函数调用参数正确
- ✅ 异常处理完善
- ✅ 日志记录完整

---

## 性能考虑

### 优化点
1. **数据库索引**
   - `multi_session_participant.session_id` 已建立索引
   - `short_term_message` 的 `character_id` 需要索引（后续优化）

2. **缓存策略**
   - 角色卡缓存在 `MultiCharacterOrchestrator` 中
   - 最后发言者缓存避免重复查询
   - 关系网络按需加载

3. **批量操作**
   - 多角色记忆批量查询
   - 历史消息限制数量（默认 20 条）

### 扩展性
- ✅ 支持动态添加/移除参与者
- ✅ 策略模式便于扩展新策略
- ✅ 记忆系统分层设计，易于扩展
- ✅ API 设计符合 RESTful 规范

---

## 未来改进方向

### 短期（1-2周）
1. [ ] 添加单元测试和集成测试
2. [ ] 优化数据库查询性能
3. [ ] 添加更多发言策略
4. [ ] 完善错误处理和日志

### 中期（1-2个月）
1. [ ] 支持角色动态进出会话
2. [ ] 实现角色情绪传染机制
3. [ ] 添加群体事件系统
4. [ ] 支持多轮复杂互动

### 长期（3-6个月）
1. [ ] 实现角色性格一致性评估
2. [ ] 支持跨会话的角色关系持久化
3. [ ] 添加对话质量评估系统
4. [ ] 实现自动化测试框架

---

## 依赖关系

### 内部依赖
```
multi_dialogue.py
    ├── multi_character_orchestrator.py
    │   ├── speaking_strategy.py
    │   ├── multi_character_memory.py
    │   ├── prompt_builder.py
    │   ├── character_loader.py
    │   └── llm_client.py
    └── repository.py
```

### 外部依赖
- FastAPI（REST API 框架）
- SQLite（数据持久化）
- Sentence Transformers（记忆向量检索）
- LLM API（对话生成）

---

## 常见问题

### Q1: 如何控制某个角色发言更频繁？
**A**: 在创建会话时设置更高的 `speak_frequency`，或使用 API 动态更新：
```python
repository.update_participant_frequency(session_id, character_id, 1.5)
```

### Q2: 角色总是重复发言怎么办？
**A**: 检查发言策略是否设置正确，推荐使用 `hybrid` 或 `smart` 策略，它们会考虑发言均衡性。

### Q3: 如何让特定角色对特定话题更敏感？
**A**: 在角色卡的 `keywords` 中添加相关关键词，智能策略会自动提高该角色的发言优先级。

### Q4: 能否中途添加新角色？
**A**: 可以，使用 `/multi-dialogue/participant` 端点动态添加参与者。

### Q5: 角色记忆会混淆吗？
**A**: 不会，系统使用三层记忆隔离：个人记忆、角色间记忆、群体记忆，确保上下文清晰。

---

## 联系与支持

- **文档维护**: Memoria Team
- **更新日期**: 2026-07-02
- **版本**: v1.0

---

## 附录

### A. 数据库 Schema 完整定义

详见 `app/db/schema.sql`（如果存在）或参考本文档"数据模型"章节。

### B. API 完整文档

详见 FastAPI 自动生成的文档：
- Swagger UI: `http://localhost:8020/docs`
- ReDoc: `http://localhost:8020/redoc`

### C. 测试用例列表

详见 `app/scripts/test_multi_dialogue.py`

---

**END OF DOCUMENT**
