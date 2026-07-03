<!-- 此文档从 README.md 中提取，包含系统架构、数据库结构和角色卡规范 -->

# Memoria 系统架构

## 项目结构

```
Memoria/
├── src/memoria/               # 源代码
│   ├── api/                   # REST API 路由层
│   │   ├── dialogue.py        # 对话相关
│   │   ├── character_admin.py # 角色卡管理
│   │   ├── event_admin.py     # 事件管理
│   │   ├── multi_dialogue.py  # 多角色对话
│   │   └── relationship.py    # 角色关系
│   ├── characters/            # 角色卡 JSON 文件
│   ├── core/                  # 核心业务逻辑
│   │   ├── config.py          # 全局配置
│   │   ├── orchestrator.py    # 对话编排
│   │   ├── llm_client.py      # LLM 适配层
│   │   ├── prompt_builder.py  # Prompt 组装
│   │   ├── memory_extractor.py# 记忆萃取
│   │   ├── vector_memory.py   # 向量记忆
│   │   ├── character_loader.py# 角色卡加载
│   │   ├── character_schema.py# 角色卡数据模型
│   │   ├── event_detector.py  # 事件检测
│   │   ├── event_executor.py  # 事件执行
│   │   ├── event_schema.py    # 事件数据模型
│   │   ├── multi_character_orchestrator.py
│   │   ├── multi_character_memory.py
│   │   └── speaking_strategy.py
│   ├── db/                    # 数据持久化
│   │   └── repository.py
│   ├── static/                # 静态资源
│   └── main.py                # 应用入口
├── tests/                     # 测试
├── docs/                      # 文档
├── data/                      # 运行时数据
│   ├── sqlite_db/             # SQLite 数据库
│   └── chroma_db/             # 向量数据库
├── scripts/                   # 工具脚本
├── config/                    # 配置模板
│   ├── .env.example
│   └── settings.yaml
└── pyproject.toml
```

## 核心架构

### 对话编排器 (Orchestrator)

单角色对话的核心编排逻辑：
1. 加载角色卡和运行时状态
2. 构建系统 Prompt 和对话历史
3. 调用 LLM 生成回复
4. 解析响应、更新状态
5. 检测并执行事件
6. 萃取并保存长期记忆

### 多角色编排器 (MultiCharacterOrchestrator)

多角色对话的编排逻辑：
1. 加载所有参与角色的卡片和状态
2. 使用发言策略选择回应角色
3. 构建包含多角色上下文的 Prompt
4. 调用 LLM 生成回复
5. 更新参与者和关系状态
6. 保存多角色记忆

### 发言策略 (SpeakingStrategy)

5 种策略：

| 策略 | 特点 | 适用场景 |
|------|------|---------|
| Round Robin | 轮流发言 | 确保公平 |
| Weighted Random | 按权重随机 | 控制发言比例 |
| Smart Selection | 综合多因素 | 自然互动 |
| Trigger-based | 条件触发 | 事件驱动 |
| Hybrid | 混合模式 | 默认推荐 |

### 三层记忆架构

```
短期记忆 (short_term_message) → 8 轮对话窗口
       ↓
中期记忆 (session_summary)    → 会话摘要
       ↓
长期记忆 (long_term_fact)      → 向量检索永久存储
```

## 数据库设计

### 表结构

**character_card** - 角色卡存储
| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT | 主键 |
| card_data | TEXT | 完整 JSON |
| version | TEXT | 版本号 |
| is_active | INTEGER | 启用状态 |

**relationship_state** - 玩家-角色关系
| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT | 联合主键 |
| player_id | TEXT | 联合主键 |
| state_data | TEXT | JSON 状态数据 |

**long_term_fact** - 长期记忆
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| fact_text | TEXT | 记忆内容 |
| importance | INTEGER | 重要性 (1-10) |

**session** - 会话管理
| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT | UUID 主键 |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| status | TEXT | active/ended |

**short_term_message** - 短期消息
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT | 会话 ID |
| role | TEXT | user/assistant |
| content | TEXT | 消息内容 |

**session_summary** - 会话摘要
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT | 会话 ID |
| summary_text | TEXT | 摘要内容 |

**event_definition** - 事件定义
| 字段 | 类型 | 说明 |
|------|------|------|
| event_id | TEXT | 主键 |
| trigger_config | TEXT | 触发条件 (JSON) |
| effects_config | TEXT | 效果配置 (JSON) |

**event_trigger_log** - 事件触发日志
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| event_id | TEXT | 事件 ID |
| triggered_at | TEXT | 触发时间 |

**character_relationship** - 角色关系网络
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id_a | TEXT | 角色 A |
| character_id_b | TEXT | 角色 B |
| relationship_type | TEXT | 关系类型 |
| affinity | REAL | 亲密度 |

## 角色卡规范

角色卡使用 JSON 格式，完整结构如下：

```json
{
  "character_id": "唯一标识",
  "version": "1.0.0",
  "meta": {
    "name": "角色名",
    "display_name": "显示名",
    "aliases": ["别名"],
    "game_module": "所属模块",
    "created_by": "作者",
    "last_updated": "ISO 8601"
  },
  "identity": {
    "age": "年龄",
    "gender": "性别",
    "occupation": "职业",
    "race_or_species": "种族",
    "appearance": "外貌描述",
    "social_status": "社会地位",
    "core_identity_summary": "一句话身份概述"
  },
  "personality": {
    "mbti_or_archetype": "MBTI 或原型",
    "core_traits": ["特质列表"],
    "values_and_beliefs": ["价值观"],
    "fears_and_tabooes": ["恐惧与禁忌"],
    "quirks_and_habits": ["怪癖习惯"],
    "moral_alignment": "道德阵营"
  },
  "speech_style": {
    "tone_register": "语气基调",
    "vocabulary_notes": "词汇特点",
    "sentence_patterns": ["句式特征"],
    "catchphrases": ["口头禅"],
    "things_never_to_say": ["绝不说的话"],
    "language": "zh-CN",
    "formality_default": "formal/casual"
  },
  "background": {
    "story_bio": "背景故事",
    "key_events": ["关键事件"],
    "relationships": [],
    "secrets": ["秘密"]
  },
  "goals_and_motivations": {
    "current_goals": ["当前目标"],
    "long_term_goals": ["长期目标"],
    "what_triggers_anger": ["愤怒触发"],
    "what_brings_joy": ["快乐触发"]
  },
  "interaction_rules": {
    "initial_attitude_to_player": "初始态度",
    "topics_to_avoid_unless_trusted": ["信任前回避话题"],
    "topics_he_or_she_loves_to_discuss": ["喜爱话题"],
    "response_to_rudeness": ["对粗鲁的回应"],
    "gift_reactions": []
  },
  "action_vocabulary": {
    "greeting_actions": ["[打招呼]"],
    "farewell_actions": ["[告别]"],
    "agreement_actions": ["[同意]"],
    "disagreement_actions": ["[反对]"],
    "emotional_reactions": ["[开心]", "[悲伤]"],
    "default_action": "neutral",
    "fallback_priority": []
  },
  "runtime_state_schema": {
    "relationships": [{"target_id": "player", "affection_level": 0, "trust_level": 10}],
    "current_mood": {"default_mood": "neutral"},
    "known_player_facts": {}
  },
  "safety_constraints": {
    "topics_to_avoid": ["禁忌话题"],
    "out_of_character_handling": "OOC 处理方式"
  }
}
```

## 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| Web 框架 | FastAPI |
| 数据库 | SQLite (WAL 模式) |
| 向量数据库 | ChromaDB |
| 嵌入模型 | sentence-transformers/all-MiniLM-L6-v2 |
| LLM | OpenAI 兼容接口 |
| 包管理 | pip / pyproject.toml (src layout) |
