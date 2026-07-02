# Memoria - 角色模拟系统

一个基于大语言模型的沉浸式角色扮演对话系统，支持动态记忆管理、情感状态追踪、事件系统和个性化交互体验。

[![GitHub stars](https://img.shields.io/github/stars/nanzi-dev/Memoria?style=social)](https://github.com/nanzi-dev/Memoria)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## 📑 目录

- [核心特性](#-核心特性)
- [系统架构](#-系统架构)
- [快速开始](#-快速开始)
- [API 文档](#-api-文档)
  - [对话系统 API](#对话系统-api)
  - [角色卡管理 API](#角色卡管理-api)
  - [事件管理 API](#事件管理-api)
  - [角色关系 API](#角色关系-api)
- [数据库结构](#-数据库结构)
- [角色卡开发指南](#-角色卡开发指南)
- [高级功能](#-高级功能)
- [待开发功能](#-待开发功能)
- [技术亮点](#-技术亮点)
- [开发路线图](#-开发路线图)
- [故障排查](#-故障排查)
- [贡献指南](#-贡献指南)

---

## ✨ 核心特性

### 🎭 深度角色模拟
- **结构化角色卡系统**：使用 JSON 格式定义角色的完整人格、背景、语言风格和行为模式
- **多维度性格系统**：支持 MBTI、核心特质、价值观、恐惧与禁忌等多维度性格定义
- **动态语言风格**：根据角色设定自动生成符合人设的对话内容和表达方式
- **角色卡管理后台**：Web 界面管理角色卡，支持创建、编辑、导入、导出和数据库存储
- **角色卡可视化编辑器**：通过 Web 界面直观编辑角色卡各个部分

### 🧠 三层智能记忆系统
- **短期记忆**：保留最近对话历史（默认 8 轮），确保上下文连贯性
- **中期记忆（会话摘要）**：自动生成会话摘要，支持跨会话记忆持久化
- **长期记忆**：自动提取和存储重要事实，支持跨会话记忆持久化
- **RAG 向量检索**：基于语义相似度智能召回相关记忆，提升召回精准度
- **记忆萃取引擎**：使用 AI 从对话中智能提取关键信息并评估重要性
- **自动摘要生成**：会话结束时自动生成对话摘要

### 💖 关系与情感追踪
- **好感度系统**：根据对话内容动态调整角色对玩家的好感度（-100 ~ 100）
- **信任度机制**：追踪角色对玩家的信任程度，影响话题开放度
- **情绪状态**：实时跟踪角色当前情绪，影响对话表现和反应
- **角色关系网络**：支持角色间关系定义（朋友、敌人、家人、师徒等）
- **关系可视化**：提供关系网络查询 API，支持关系图谱展示

### 🎯 事件系统（未实装）
- **多类型触发条件**：好感度阈值、信任度阈值、关键词匹配、对话次数、时间、情绪、复合条件
- **丰富的事件效果**：状态修改、内容解锁、对话触发、记忆添加、情绪改变、玩家通知、关系修改
- **事件检测引擎**：自动检测触发条件并按优先级执行
- **事件执行器**：执行事件效果并记录触发日志
- **冷却时间管理**：支持事件冷却和触发次数限制

### 🛡️ 沉浸感保护
- **AI 身份检测**：自动识别并过滤可能破坏沉浸感的输出（如"我是AI"等）
- **角色一致性**：严格约束模型输出，确保始终保持角色人设
- **三层容错机制**：JSON 解析、修复重试、文本兜底，确保系统稳定运行

### 🔄 多模型支持
- **OpenAI 兼容接口**：支持 DeepSeek、Kimi、Qwen 等多种大模型
- **主辅模型分离**：主对话使用高质量模型，记忆萃取使用轻量模型降低成本
- **JSON 强制输出**：支持结构化输出的模型可获得更好的稳定性

## 🏗️ 系统架构

```
Memoria/
├── app/
│   ├── api/                    # API 路由层
│   │   └── dialogue.py         # 对话相关 API 端点
│   ├── characters/             # 角色卡配置文件
│   │   ├── npc_blacksmith_garran.json
│   │   ├── npc_luo_xiaohei.json
│   │   ├── npc_luye.json
│   │   ├── npc_merchant_lina.json
│   │   └── npc_wuxian.json
│   ├── core/                   # 核心业务逻辑
│   │   ├── character_loader.py # 角色卡加载与缓存
│   │   ├── character_schema.py # 角色卡数据模型
│   │   ├── config.py           # 全局配置管理
│   │   ├── llm_client.py       # LLM 调用适配层
│   │   ├── memory_extractor.py # 记忆萃取模块
│   │   ├── orchestrator.py     # 对话编排核心
│   │   └── prompt_builder.py   # Prompt 组装器
│   ├── db/                     # 数据持久化层
│   │   └── repository.py       # SQLite 数据库操作
│   ├── static/                 # 静态资源
│   │   └── index.html          # Web UI 界面
│   ├── scripts/                # 工具脚本
│   │   └── cli_chat.py         # 命令行对话工具
│   └── main.py                 # 应用入口
├── .env.example                # 环境变量配置示例
├── requirements.txt            # Python 依赖
└── README.md                   # 项目文档
```

## 🚀 快速开始

### 环境要求

- Python 3.10+
- 支持 OpenAI 兼容接口的大模型 API（DeepSeek、Kimi、Qwen 等）

### 安装步骤

1. **克隆项目**
```bash
git clone <repository_url>
cd Memoria
```

2. **创建虚拟环境（推荐）**
```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate     # Windows
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

**注意**：首次启动时会自动下载嵌入模型（约 80MB），用于向量检索功能。

4. **配置环境变量**
```bash
cp .env.example .env
# 编辑 .env 文件，填入你的 API 配置
```

**环境变量说明：**
```bash
# 大模型 API 配置
LLM_BASE_URL=https://api.deepseek.com/v1      # API 基础 URL
LLM_API_KEY=your-api-key-here                  # API 密钥
LLM_MODEL=deepseek-chat                        # 主对话模型
LLM_LIGHT_MODEL=                               # 记忆萃取模型（可选，留空则使用主模型）

# 应用配置
DATABASE_PATH=./memoria.db                     # 数据库文件路径
SHORT_TERM_MEMORY_TURNS=8                      # 短期记忆轮数
MAX_OUTPUT_TOKENS=600                          # 单轮最大输出 token 数

# 向量检索配置（第二阶段新增）
VECTOR_DB_PATH=./chroma_db                     # 向量数据库路径
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2  # 嵌入模型
VECTOR_SEARCH_TOP_K=10                         # 向量检索返回数量
```

**支持的模型供应商配置示例：**

```bash
# DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# Kimi (Moonshot)
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k

# Qwen (通义千问)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview
```

5. **启动服务**
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

6. **访问应用**
- 主界面: http://localhost:8000
- 管理后台: http://localhost:8000/admin
- 角色卡编辑器: http://localhost:8000/editor
- API 文档: http://localhost:8000/docs
- 备用 API 文档: http://localhost:8000/redoc

## 📚 API 文档

### 对话系统 API

#### 1. 获取角色列表
```http
GET /api/v1/characters
```

**响应示例：**
```json
[
  {
    "character_id": "npc_luo_xiaohei",
    "name": "罗小黑",
    "display_name": "小黑",
    "core_identity_summary": "一只好奇心旺盛的猫妖少年"
  }
]
```

#### 2. 开始新会话
```http
POST /api/v1/dialogue/session/start
Content-Type: application/json

{
  "character_id": "npc_luo_xiaohei",
  "player_id": "player_001",
  "player_name": "旅行者"
}
```

**响应示例：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "opening_line": "[好奇地打量]你好呀！你是谁？",
  "action": "greeting_curious",
  "current_affinity": 0
}
```

#### 3. 发送对话消息
```http
POST /api/v1/dialogue/turn
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "player_message": "你好，小黑！"
}
```

**响应示例：**
```json
{
  "dialogue": "[开心地摆尾巴]你认识我呀！",
  "action": "emotional_happy",
  "affinity_delta": 2,
  "current_affinity": 2,
  "current_mood": "开心",
  "triggered_events": [
    {
      "event_id": "first_meeting",
      "event_name": "初次见面",
      "effects_applied": ["状态已修改", "记忆已添加"]
    }
  ],
  "event_notification": "解锁新话题：童年回忆"
}
```

#### 4. 获取会话列表
```http
GET /api/v1/dialogue/sessions?character_id=npc_luo_xiaohei&player_id=player_001
```

**响应示例：**
```json
[
  {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "character_id": "npc_luo_xiaohei",
    "player_id": "player_001",
    "player_name": "旅行者",
    "created_at": "2026-06-23T10:30:00.000000+00:00",
    "last_message": "那我们做朋友吧！",
    "message_count": 12
  }
]
```

#### 5. 获取对话历史
```http
GET /api/v1/dialogue/history
```

**查询参数：**
- `session_id` (必需): 会话 ID
- `offset` (可选): 偏移量，默认 0
- `limit` (可选): 每页数量，默认 20

**响应示例：**
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "[好奇地打量]你好呀！你是谁？",
      "created_at": "2026-06-23T10:30:00.000000+00:00"
    },
    {
      "role": "user",
      "content": "你好，小黑！",
      "created_at": "2026-06-23T10:30:15.000000+00:00"
    }
  ],
  "has_more": false,
  "current_affinity": 2,
  "current_mood": "开心"
}
```

#### 6. 结束会话（生成摘要）
```http
POST /api/v1/dialogue/session/end
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**响应示例：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "summary": "玩家与小黑初次见面，小黑表现出好奇和友好，双方约定成为朋友。",
  "message_count": 12
}
```

#### 7. 获取会话摘要列表
```http
GET /api/v1/dialogue/summaries
```

**查询参数：**
- `character_id` (必需): 角色 ID
- `player_id` (必需): 玩家 ID
- `limit` (可选): 返回数量，默认 5

**响应示例：**
```json
[
  {
    "id": 1,
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "summary_text": "玩家与小黑初次见面...",
    "message_count": 12,
    "created_at": "2026-06-23T11:00:00.000000+00:00",
    "session_created_at": "2026-06-23T10:30:00.000000+00:00"
  }
]
```

---

### 角色卡管理 API

#### 1. 获取角色卡列表
```http
GET /api/v1/admin/characters?only_active=true
```

**查询参数：**
- `only_active` (可选): 是否仅返回启用的角色卡，默认 true

**响应示例：**
```json
[
  {
    "character_id": "npc_luo_xiaohei",
    "name": "罗小黑",
    "display_name": "小黑",
    "version": "1.0.0",
    "is_active": 1,
    "source": "file",
    "created_at": "2026-06-20T08:00:00.000000+00:00",
    "updated_at": "2026-06-23T10:00:00.000000+00:00"
  }
]
```

#### 2. 获取角色卡详情
```http
GET /api/v1/admin/characters/{character_id}
```

**响应示例：**
```json
{
  "character_id": "npc_luo_xiaohei",
  "card_data": {
    "character_id": "npc_luo_xiaohei",
    "version": "1.0.0",
    "meta": {
      "name": "罗小黑",
      "display_name": "小黑"
    }
  },
  "version": "1.0.0",
  "name": "罗小黑",
  "display_name": "小黑",
  "is_active": 1,
  "source": "file",
  "created_at": "2026-06-20T08:00:00.000000+00:00",
  "updated_at": "2026-06-23T10:00:00.000000+00:00"
}
```

#### 3. 创建角色卡
```http
POST /api/v1/admin/characters
Content-Type: application/json

{
  "character_data": {
    "character_id": "new_character",
    "version": "1.0.0",
    "meta": { ... },
    "identity": { ... },
    "personality": { ... }
  }
}
```

#### 4. 更新角色卡
```http
PUT /api/v1/admin/characters/{character_id}
Content-Type: application/json

{
  "character_data": { /* 更新后的完整角色卡数据 */ }
}
```

#### 5. 删除角色卡
```http
DELETE /api/v1/admin/characters/{character_id}?permanent=false
```

**查询参数：**
- `permanent` (可选): 是否永久删除，默认 false（软删除）

#### 6. 激活角色卡
```http
POST /api/v1/admin/characters/{character_id}/activate
```

#### 7. 从文件导入角色卡
```http
POST /api/v1/admin/characters/import
Content-Type: application/json

{
  "character_id": "npc_luo_xiaohei"
}
```

---

### 事件管理 API

---

#### 1. 获取事件列表

```http
GET /api/v1/admin/events?character_id=&only_active=true
```

**查询参数：**
- `character_id` (可选): 过滤某角色事件（同时包含全局事件）
- `only_active` (可选): 是否仅返回启用事件，默认 true

**响应示例：**
```json
[
  {
    "event_id": "evt_npc_luo_xiaohei_idle",
    "event_name": "闲聊触发",
    "description": "角色进入闲置状态时触发",
    "character_id": "npc_luo_xiaohei",
    "priority": 1,
    "is_active": true,
    "trigger_count": 12,
    "last_triggered_at": "2026-06-28T10:12:00Z",
    "created_at": "2026-06-01T00:00:00Z",
    "updated_at": "2026-06-20T12:00:00Z",
    "trigger_type": "state"
  }
]
```

---

#### 2. 获取事件详情

```http
GET /api/v1/admin/events/{event_id}
```

**响应示例：**
```json
{
  "event_id": "evt_npc_luo_xiaohei_idle",
  "event_name": "闲聊触发",
  "description": "角色进入闲置状态时触发",
  "character_id": "npc_luo_xiaohei",
  "priority": 1,
  "is_active": true,
  "trigger_count": 12,
  "last_triggered_at": "2026-06-28T10:12:00Z",
  "created_at": "2026-06-01T00:00:00Z",
  "updated_at": "2026-06-20T12:00:00Z",

  "trigger_type": "state",

  "trigger_condition": {
    "trigger_type": "state",
    "threshold": 0.6,
    "comparison": "gte",
    "logic_operator": "and",
    "cooldown_hours": 2
  },

  "effects": [
    {
      "effect_type": "dialogue",
      "dialogue_text": "你在做什么呀？",
      "dialogue_action": "curious_talk"
    }
  ]
}
```

---

#### 3. 创建事件

```http
POST /api/v1/admin/events
Content-Type: application/json

{
  "event_id": "evt_npc_luo_xiaohei_idle",
  "event_name": "闲聊触发",
  "description": "角色进入闲置状态时触发",
  "character_id": "npc_luo_xiaohei",

  "trigger_condition": {
    "trigger_type": "state",
    "threshold": 0.5,
    "comparison": "gte",
    "cooldown_hours": 1
  },

  "effects": [
    {
      "effect_type": "dialogue",
      "dialogue_text": "你在干嘛？",
      "memory_text": "角色主动发起闲聊"
    }
  ],

  "priority": 1,
  "is_active": true
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "事件创建成功",
  "event_id": "evt_npc_luo_xiaohei_idle"
}
```

---

#### 4. 更新事件（可部分更新）

```http
PUT /api/v1/admin/events/{event_id}
Content-Type: application/json

{
  "event_name": "更新后的事件名称",
  "priority": 2,
  "is_active": false
}
```

**响应示例：**
```json
{
  "success": true,
  "message": "事件更新成功",
  "event_id": "evt_npc_luo_xiaohei_idle"
}
```

---

#### 5. 删除事件

```http
DELETE /api/v1/admin/events/{event_id}?permanent=true
```

**查询参数：**
- `permanent` (可选): 是否永久删除（默认 true）

**响应示例：**
```json
{
  "success": true,
  "message": "事件删除成功",
  "event_id": "evt_npc_luo_xiaohei_idle"
}
```

---

#### 6. 启用 / 禁用事件

```http
POST /api/v1/admin/events/{event_id}/toggle
Content-Type: application/json
```
**查询参数：**
- `active` : 是否启用

**响应示例：**
```json
{
  "success": true,
  "message": "事件已启用",
  "event_id": "evt_npc_luo_xiaohei_idle"
}
```

---

#### 7. 查询事件触发历史

```http
GET /api/v1/admin/events/{event_id}/history?character_id=&player_id=&limit=50
```

**查询参数：**
- `character_id` (可选)
- `player_id` (可选)
- `limit` (可选): 默认 50

**响应示例：**
```json
[
  {
    "id": 1,
    "event_id": "evt_npc_luo_xiaohei_idle",
    "character_id": "npc_luo_xiaohei",
    "player_id": "player_001",
    "session_id": "xxx",
    "triggered_at": "2026-06-28T10:12:00Z",
    "effects_applied": "{}"
  }
]
```

---

#### 8. 查询全部触发历史

```http
GET /api/v1/admin/events/history/all?character_id=&player_id=&limit=100
```

**查询参数：**
- `character_id` (可选)
- `player_id` (可选)
- `limit` (可选): 默认 100

**响应示例：**
```json
[
  {
    "id": 2,
    "event_id": "evt_npc_luo_xiaohei_idle",
    "character_id": "npc_luo_xiaohei",
    "player_id": "player_001",
    "session_id": "xxx",
    "triggered_at": "2026-06-28T11:00:00Z",
    "effects_applied": "{}"
  }
]
```

---

#### 9. 重置触发记录（调试）

```http
DELETE /api/v1/admin/events/{event_id}/history?character_id=&player_id=
```

**查询参数：**
- `character_id` (必填)
- `player_id` (必填)

**响应示例：**
```json
{
  "success": true,
  "message": "触发记录已清除",
  "event_id": "evt_npc_luo_xiaohei_idle"
}
```

---

### 角色关系 API

#### 1. 创建角色关系
```http
POST /api/v1/relationships
Content-Type: application/json

{
  "character_id_a": "npc_luo_xiaohei",
  "character_id_b": "npc_wuxian",
  "relationship_type": "friend",
  "affinity": 50.0,
  "description": "无限是小黑的师傅"
}
```

**关系类型：** `friend` (朋友), `enemy` (敌人), `family` (家人), `rival` (对手), `mentor` (师徒), `lover` (恋人)

#### 2. 获取角色关系
```http
GET /api/v1/relationships/{character_id_a}/{character_id_b}
```

#### 3. 更新角色关系
```http
PUT /api/v1/relationships/{character_id_a}/{character_id_b}
Content-Type: application/json

{
  "relationship_type": "mentor",
  "affinity": 60.0,
  "description": "关系更加紧密了"
}
```

#### 4. 删除角色关系
```http
DELETE /api/v1/relationships/{character_id_a}/{character_id_b}
```

#### 5. 获取角色的所有关系
```http
GET /api/v1/relationships/character/{character_id}
```

#### 6. 获取关系网络（用于可视化）
```http
GET /api/v1/relationships/network?character_ids=npc_luo_xiaohei,npc_wuxian
```

**响应示例：**
```json
{
  "nodes": [
    {
      "character_id": "npc_luo_xiaohei",
      "name": "罗小黑"
    },
    {
      "character_id": "npc_wuxian",
      "name": "无限"
    }
  ],
  "edges": [
    {
      "source": "npc_luo_xiaohei",
      "target": "npc_wuxian",
      "relationship_type": "mentor",
      "affinity": 60.0,
      "description": "无限是小黑的师傅"
    }
  ]
}
```

#### 7. 批量创建关系
```http
POST /api/v1/relationships/batch
Content-Type: application/json

[
  {
    "character_id_a": "npc_luo_xiaohei",
    "character_id_b": "npc_wuxian",
    "relationship_type": "mentor",
    "affinity": 50.0
  }
]
```

## 🎨 角色卡开发指南

### 角色卡结构

角色卡使用 JSON 格式定义，包含以下核心部分：

```json
{
  "character_id": "unique_id",
  "version": "1.0.0",
  "meta": {
    "name": "角色名称",
    "display_name": "显示名称",
    "aliases": ["别名1", "别名2"]
  },
  "identity": {
    "age": 16,
    "gender": "男",
    "occupation": "学生",
    "appearance": "外貌描述"
  },
  "personality": {
    "core_traits": ["好奇", "善良", "机警"],
    "values_and_beliefs": ["保护朋友", "探索未知"],
    "fears_and_tabooes": ["被束缚", "失去自由"]
  },
  "speech_style": {
    "tone_register": "轻松活泼",
    "vocabulary_notes": "使用简单直接的语言",
    "sentence_patterns": ["短句为主", "常用疑问句"],
    "catchphrases": ["喵~", "好奇怪哦"]
  },
  "action_vocabulary": {
    "greeting_actions": ["[好奇地打量]", "[友好地摆尾巴]"],
    "emotional_reactions": ["[开心地跳起来]", "[警惕地后退]"],
    "default_action": "neutral"
  },
  "runtime_state_schema": {
    "current_mood": {
      "emotions": ["开心", "好奇", "警惕", "放松"],
      "default_mood": "好奇"
    }
  }
}
```

### 创建新角色

1. 在 `app/characters/` 目录创建新的 JSON 文件
2. 参考现有角色卡填写完整信息
3. 使用 Pydantic 自动校验格式正确性
4. 重启服务即可加载新角色

### 最佳实践

- **性格一致性**：确保各字段相互呼应，形成统一人格
- **语言风格**：详细定义说话方式，提升角色辨识度
- **动作词库**：提供丰富的动作描述，增强表现力
- **情绪设定**：合理设置情绪列表和默认情绪

### 🔧 高级功能

#### 命令行对话工具

```bash
python -m app.scripts.cli_chat
```

支持在命令行中直接与角色对话，适合快速测试和调试。

#### 已实现的核心模块

**1. 记忆系统（app/core/）**
- `memory_extractor.py`：记忆萃取引擎，从对话中提取重要事实
- `vector_memory.py`：向量记忆存储，基于 ChromaDB 的语义检索
- `prompt_builder.py`：Prompt 组装器，整合记忆和上下文

**2. 事件系统（app/core/）**
- `event_schema.py`：事件数据模型定义
- `event_detector.py`：事件检测引擎，支持多种触发条件
- `event_executor.py`：事件执行器，执行各种事件效果

**3. 角色管理（app/api/ & app/core/）**
- `character_admin.py`：角色卡管理 API
- `character_loader.py`：角色卡加载器，支持缓存和热重载
- `character_schema.py`：角色卡数据模型

**4. 关系系统（app/api/）**
- `relationship.py`：角色关系网络 API
- 支持多种关系类型和关系强度管理

#### 数据库迁移

当前使用 SQLite 作为轻量级数据库，可无缝迁移到 PostgreSQL：

1. 修改 `app/core/config.py` 中的数据库配置
2. 更新 `app/db/repository.py` 中的连接方式
3. SQL 语句保持兼容，无需大规模改动

**PostgreSQL 连接示例：**
```python
# config.py
database_url: str = "postgresql://user:password@localhost:5432/memoria"

# repository.py
import psycopg2
conn = psycopg2.connect(configs.database_url)
```

---

### 🚧 待开发功能

#### 多角色对话
目前系统仅支持单角色与玩家对话，计划扩展为多角色群聊模式。

**需要实现：**
- 角色轮流发言机制
- 角色间互动逻辑（基于关系网络）
- 多角色上下文管理
- 发言顺序和频率控制

#### 语音集成
计划集成 TTS（文本转语音）和 STT（语音转文本）。

**技术选型：**
- TTS：Azure TTS / Google TTS / 本地 VITS
- STT：Whisper / Azure STT
- 实时语音流处理（WebSocket）

#### Web UI 增强
现有 Web 界面功能较为基础，计划增强：

- [ ] 更美观的对话界面（类似聊天应用）
- [ ] 角色头像和动画
- [ ] 记忆时间轴可视化
- [ ] 关系网络图谱展示（D3.js / vis.js）
- [ ] 好感度和信任度仪表盘

## 🎯 技术亮点

### 三层记忆架构

Memoria 实现了完整的三层记忆体系：

| 记忆类型 | 存储方式 | 召回策略 | 容量 | 用途 | 实现状态 |
|---------|---------|---------|------|------|---------|
| **短期记忆** | `short_term_message` 表 | 最近 N 轮 | 8 轮 | 当前会话上下文 | ✅ 已实现 |
| **中期记忆** | `session_summary` 表 | 最近 M 次会话 | 3 次摘要 | 跨会话连续性 | ✅ 已实现 |
| **长期记忆** | `long_term_fact` + ChromaDB | RAG 向量检索 | 无限 | 重要事实和关系 | ✅ 已实现 |

**向量检索优势：**
- ✅ 基于语义相似度，而非关键词匹配
- ✅ 能够检索到语义相关但表述不同的记忆
- ✅ 随着记忆量增长，检索效率仍保持稳定（O(log n)）
- ✅ 支持模糊召回和关联记忆

**记忆召回流程：**
```
用户输入 → 向量化 → ChromaDB 检索 → Top-K 相关记忆 → 注入 Prompt → LLM 生成
```

---

### 事件系统架构

Memoria 实现了灵活的事件驱动系统：

**事件检测流程：**
```
对话轮次 → EventDetector.check_events()
           ↓
       检查触发条件（好感度/关键词/时间等）
           ↓
       过滤冷却中的事件
           ↓
       按优先级排序
           ↓
       返回触发的事件列表
```

**事件执行流程：**
```
触发事件 → EventExecutor.execute_event()
          ↓
      执行各种效果（状态修改/对话覆盖/记忆添加等）
          ↓
      记录触发日志
          ↓
      返回事件结果（注入对话响应）
```

**支持的触发条件：**
- ✅ 阈值类：好感度、信任度、对话次数、会话时长
- ✅ 匹配类：关键词、情绪
- ✅ 复合类：AND/OR 逻辑组合
- 📋 计划中：物品持有、任务状态、时间点

**支持的事件效果：**
- ✅ 状态修改：好感度、信任度、情绪
- ✅ 内容解锁：解锁新话题、新剧情
- ✅ 对话触发：强制触发特定对话
- ✅ 记忆添加：自动添加重要记忆
- ✅ 通知玩家：发送系统通知
- ✅ 关系修改：改变与其他角色的关系
- 📋 计划中：道具授予、任务开始

---

### 三层容错机制

LLM 输出的不确定性是角色模拟系统的核心挑战，Memoria 实现了三层容错：

```python
1. 标准 JSON 解析
   ↓ 失败
2. 请求模型修正格式（repair prompt）
   ↓ 仍失败
3. 文本兜底（保留对话，默认值填充）
```

**实现细节：**
```python
try:
    # 第一层：直接解析
    result = json.loads(llm_output)
except:
    # 第二层：修复重试
    repair_prompt = "请修正 JSON 格式..."
    fixed_output = llm.call(repair_prompt)
    try:
        result = json.loads(fixed_output)
    except:
        # 第三层：兜底机制
        result = {
            "dialogue": extract_text(llm_output),
            "action": "neutral",
            "affinity_delta": 0,
            ...
        }
```

这确保了系统**永不崩溃**，即使在模型输出异常时也能优雅降级。

---

### 沉浸感保护

通过正则表达式检测和替换可能破坏角色扮演沉浸感的输出：

**检测模式：**
```python
AI_LEAK_PATTERNS = [
    r"作为(一个)?AI|作为(一个)?语言模型",
    r"我是(一个)?人工智能|我是(一个)?AI",
    r"我只是(一个)?程序|我只是(一个)?机器人",
    r"我没有真实的?(感情|情感|身体)",
    ...
]
```

**替换策略：**
- 检测到泄露 → 使用角色专属兜底话术
- 记录警告日志 → 便于监控和优化
- 不中断对话 → 保持用户体验流畅

**示例：**
```
检测到：我作为一个 AI 助手...
替换为：[挠头]嗯...我也不太清楚该怎么说...（根据角色卡）
```

---

### 角色卡热重载

支持运行时重新加载角色卡，无需重启服务：

```python
from app.core import character_loader

# 清除缓存并重新加载
character_loader.reload_character_card("character_id")

# 或清除所有缓存
character_loader.load_character_card.cache_clear()
```

**使用场景：**
- 角色卡更新后立即生效
- 调试和快速迭代
- 动态角色管理

---

### LRU 缓存优化

角色卡加载使用 LRU 缓存（最多 64 个），避免重复 I/O 和解析开销：

```python
@lru_cache(maxsize=64)
def load_character_card(character_id: str) -> CharacterCard:
    # 从文件或数据库加载角色卡
    # 第二次调用直接返回缓存结果
    ...
```

**性能对比：**
- 首次加载：~50ms（文件读取 + JSON 解析 + Pydantic 验证）
- 缓存命中：~0.1ms（内存读取）
- **提速 500 倍**

---

### 关系网络系统

支持定义和管理角色之间的关系：

**关系类型：**
- `friend` (朋友)
- `enemy` (敌人)
- `family` (家人)
- `rival` (对手)
- `mentor` (师徒)
- `lover` (恋人)

**应用场景：**
- 角色提及其他角色时自动注入关系信息
- 事件系统可触发关系变化
- 关系网络可视化（图谱展示）
- 多角色对话中的互动依据

**查询示例：**
```python
# 获取小黑的所有关系
relationships = repository.list_character_relationships("npc_luo_xiaohei")

# 获取关系网络（用于可视化）
network = get_relationship_network(character_ids="npc_luo_xiaohei,npc_wuxian")
```

---

### 数据库设计亮点

**1. WAL 模式：**
```sql
PRAGMA journal_mode=WAL;
```
- 支持并发读写
- 读操作不阻塞写操作
- 提升多用户场景性能

**2. 精心设计的索引：**
```sql
-- 会话查询优化
CREATE INDEX idx_session_lookup 
ON session(character_id, player_id, created_at DESC);

-- 记忆检索优化
CREATE INDEX idx_fact_lookup 
ON long_term_fact(character_id, player_id, importance DESC, last_referenced DESC);
```

**3. JSON 字段灵活性：**
- 事件配置存储为 JSON
- 支持复杂嵌套结构
- 易于扩展新字段

**4. 软删除机制：**
```sql
-- 角色卡软删除
UPDATE character_card SET is_active = 0 WHERE character_id = ?;

-- 数据可恢复
UPDATE character_card SET is_active = 1 WHERE character_id = ?;
```

---

### 可扩展架构

**模块化设计：**
```
app/
├── api/          # API 路由层（HTTP 接口）
├── core/         # 核心业务逻辑（对话、记忆、事件）
├── db/           # 数据持久化层（数据库操作）
├── characters/   # 角色卡配置文件
└── static/       # 前端静态资源
```

**依赖注入：**
- 配置通过 `pydantic-settings` 管理
- 数据库连接通过上下文管理器
- 单例模式管理全局资源（向量存储、事件检测器等）

**易于迁移：**
- SQLite → PostgreSQL：只需修改连接字符串
- 本地部署 → 云部署：配置环境变量即可
- 单体应用 → 微服务：按模块拆分

## 📊 数据库结构

Memoria 使用 SQLite 数据库（支持迁移到 PostgreSQL），采用 WAL 模式支持并发读写。

### 核心数据表

#### 1. character_card（角色卡表）
存储角色卡的完整数据和元信息。

| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT | 角色 ID（主键） |
| card_data | TEXT | 完整的角色卡 JSON 数据 |
| version | TEXT | 角色卡版本号 |
| name | TEXT | 角色名称 |
| display_name | TEXT | 显示名称 |
| is_active | INTEGER | 是否启用（1=启用，0=禁用） |
| source | TEXT | 来源（db=数据库创建，file=从文件导入） |
| created_at | TEXT | 创建时间（ISO 8601） |
| updated_at | TEXT | 更新时间（ISO 8601） |

**索引：**
- `idx_character_active`: (is_active, created_at DESC)

---

#### 2. relationship_state（角色关系状态表）
存储角色与玩家的动态关系数据（好感度、信任度、情绪）。

| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT | 角色 ID（联合主键） |
| player_id | TEXT | 玩家 ID（联合主键） |
| affection_level | REAL | 好感度（-100 ~ 100） |
| trust_level | REAL | 信任度（0 ~ 100） |
| current_mood | TEXT | 当前情绪 |
| updated_at | TEXT | 更新时间（ISO 8601） |

**主键：** (character_id, player_id)

---

#### 3. long_term_fact（长期记忆表）
存储从对话中提取的重要事实（配合向量数据库使用）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| fact_text | TEXT | 事实内容 |
| importance | INTEGER | 重要性（1-10） |
| created_at | TEXT | 创建时间（ISO 8601） |
| last_referenced | TEXT | 最后引用时间（ISO 8601） |

**索引：**
- `idx_fact_lookup`: (character_id, player_id, importance DESC, last_referenced DESC)

**配套向量数据库：**
- 使用 ChromaDB 存储记忆向量
- 嵌入模型：sentence-transformers/all-MiniLM-L6-v2
- 检索方式：余弦相似度

---

#### 4. session（会话表）
管理对话会话的生命周期。

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT | 会话 UUID（主键） |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| player_name | TEXT | 玩家名称 |
| created_at | TEXT | 创建时间（ISO 8601） |
| ended_at | TEXT | 结束时间（ISO 8601） |
| status | TEXT | 状态（active/ended） |

**索引：**
- `idx_session_lookup`: (character_id, player_id, created_at DESC)

---

#### 5. short_term_message（短期记忆表）
存储对话历史消息。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT | 会话 ID（外键） |
| role | TEXT | 角色（user/assistant） |
| content | TEXT | 消息内容 |
| created_at | TEXT | 创建时间（ISO 8601） |

**索引：**
- `idx_message_session`: (session_id, id ASC)

---

#### 6. session_summary（会话摘要表）
存储会话摘要（中期记忆）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT | 会话 ID（外键） |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| summary_text | TEXT | 摘要内容 |
| message_count | INTEGER | 摘要涵盖的消息数 |
| created_at | TEXT | 创建时间（ISO 8601） |

**索引：**
- `idx_summary_lookup`: (session_id, created_at DESC)
- `idx_summary_player`: (character_id, player_id, created_at DESC)

---

### 事件系统数据表

#### 7. event_definition（事件定义表）
存储事件的配置和定义。

| 字段 | 类型 | 说明 |
|------|------|------|
| event_id | TEXT | 事件 ID（主键） |
| event_name | TEXT | 事件名称 |
| description | TEXT | 事件描述 |
| character_id | TEXT | 角色专属事件（NULL=全局） |
| trigger_config | TEXT | 触发条件配置（JSON） |
| effects_config | TEXT | 效果配置（JSON） |
| priority | INTEGER | 优先级（默认 0） |
| is_active | INTEGER | 是否启用（1=启用，0=禁用） |
| created_at | TEXT | 创建时间（ISO 8601） |
| updated_at | TEXT | 更新时间（ISO 8601） |
| trigger_count | INTEGER | 触发次数统计 |
| last_triggered_at | TEXT | 最后触发时间（ISO 8601） |

**索引：**
- `idx_event_character`: (character_id, is_active)

**触发条件类型（trigger_config）：**
- `AFFINITY_THRESHOLD`: 好感度阈值
- `TRUST_THRESHOLD`: 信任度阈值
- `KEYWORD_MATCH`: 关键词匹配
- `DIALOGUE_COUNT`: 对话次数
- `TIME_BASED`: 基于时间
- `MOOD_MATCH`: 情绪匹配
- `RELATIONSHIP_CHANGE`: 关系变化
- `COMPOSITE`: 复合条件（支持 AND/OR 逻辑）

**效果类型（effects_config）：**
- `MODIFY_STATE`: 修改状态（好感度、信任度等）
- `UNLOCK_CONTENT`: 解锁内容
- `TRIGGER_DIALOGUE`: 触发特定对话
- `ADD_MEMORY`: 添加长期记忆
- `CHANGE_MOOD`: 改变情绪
- `NOTIFY_PLAYER`: 通知玩家
- `MODIFY_RELATIONSHIP`: 修改角色间关系
- `GRANT_ITEM`: 授予道具（预留）
- `START_QUEST`: 开始任务（预留）

---

#### 8. event_trigger_log（事件触发记录表）
记录事件触发的历史日志。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| event_id | TEXT | 事件 ID（外键） |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| session_id | TEXT | 会话 ID |
| triggered_at | TEXT | 触发时间（ISO 8601） |
| context_snapshot | TEXT | 触发时的上下文快照（JSON） |
| effects_applied | TEXT | 应用的效果列表（JSON） |

**索引：**
- `idx_event_trigger_log`: (event_id, character_id, player_id, triggered_at DESC)

---

### 关系网络数据表

#### 9. character_relationship（角色关系网络表）
存储角色之间的关系（用于多角色互动）。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id_a | TEXT | 角色 A ID |
| character_id_b | TEXT | 角色 B ID |
| relationship_type | TEXT | 关系类型 |
| affinity | REAL | 关系亲密度（-100 ~ 100） |
| description | TEXT | 关系描述 |
| created_at | TEXT | 创建时间（ISO 8601） |
| updated_at | TEXT | 更新时间（ISO 8601） |

**唯一约束：** (character_id_a, character_id_b)

**关系类型：**
- `friend`: 朋友
- `enemy`: 敌人
- `family`: 家人
- `rival`: 对手
- `mentor`: 师徒关系
- `lover`: 恋人
- 可自定义扩展

**索引：**
- `idx_relationship_lookup`: (character_id_a, character_id_b)

---

### 数据库设计特点

**1. 三层记忆架构：**
```
短期记忆 (short_term_message)
    ↓ 8 轮对话
中期记忆 (session_summary)
    ↓ 3 次摘要
长期记忆 (long_term_fact + 向量数据库)
    ↓ 永久存储
```

**2. 性能优化：**
- WAL 模式：支持并发读写
- 精心设计的索引：加速常用查询
- 向量检索：O(log n) 复杂度的语义搜索

**3. 扩展性：**
- JSON 字段：灵活存储复杂配置
- 软删除：支持数据恢复
- 时间戳：完整的审计追踪

**4. 可迁移性：**
- 兼容 PostgreSQL 的 SQL 语法
- 使用标准数据类型
- 最小化数据库特性依赖

## 🐛 故障排查

### 常见问题

#### Q: 启动时提示"模块未找到"
**解决方案：**
```bash
# 确保在项目根目录
cd Memoria

# 确保虚拟环境已激活
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

# 重新安装依赖
pip install -r requirements.txt
```

#### Q: 首次启动时下载模型缓慢
**原因：** 向量检索功能需要下载 sentence-transformers 模型（约 80MB）

**解决方案：**
```bash
# 方案 1：等待自动下载完成（推荐）
# 首次启动会自动下载到 ~/.cache/huggingface/

# 方案 2：手动预下载
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# 方案 3：使用国内镜像
export HF_ENDPOINT=https://hf-mirror.com
uvicorn app.main:app --reload
```

#### Q: 提示"角色卡 JSON 格式错误"
**解决方案：**
1. 使用 JSON 验证工具检查文件格式：https://jsonlint.com/
2. 确认所有必需字段都已填写
3. 检查字符串是否正确转义
4. 查看详细错误信息中的行号和列号

**常见错误：**
```json
// ❌ 错误：最后一个元素后有逗号
"core_traits": ["好奇", "善良",]

// ✅ 正确
"core_traits": ["好奇", "善良"]

// ❌ 错误：单引号
'name': '小黑'

// ✅ 正确：双引号
"name": "小黑"
```

#### Q: API 调用失败，提示"API key invalid"
**解决方案：**
1. 检查 `.env` 文件中的 `LLM_API_KEY` 是否正确
2. 确认 API 密钥没有过期
3. 检查 API 服务商是否正常运行
4. 验证 `LLM_BASE_URL` 配置是否正确

```bash
# 测试 API 连接
curl -X POST "https://api.deepseek.com/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hello"}]}'
```

#### Q: 角色对话不符合人设
**可能原因：**
- 角色卡定义不够详细
- Prompt 构建有问题
- 模型能力不足

**解决方案：**
1. 优化角色卡中的性格和语言风格定义
2. 调整 `speech_style` 和 `personality` 字段
3. 增加更详细的约束条件和示例
4. 使用更强大的模型（如 GPT-4、DeepSeek-Chat）

**角色卡优化示例：**
```json
"speech_style": {
  "tone_register": "轻松活泼",
  "vocabulary_notes": "使用简单直接的语言，避免复杂词汇",
  "sentence_patterns": [
    "短句为主，不超过 20 字",
    "常用疑问句表达好奇",
    "避免使用书面语和成语"
  ],
  "catchphrases": ["喵~", "好奇怪哦", "我想知道"],
  "forbidden_phrases": ["作为一个AI", "我是程序", "根据我的分析"]
}
```

#### Q: 数据库锁定错误（SQLite database is locked）
**原因：** 多个进程同时写入数据库

**解决方案：**
1. Memoria 已启用 WAL 模式，支持并发读
2. 如需高并发写入，考虑迁移到 PostgreSQL
3. 检查是否有其他进程占用数据库文件

```bash
# 检查数据库占用
lsof memoria.db

# 强制释放（谨慎使用）
rm -f memoria.db-shm memoria.db-wal
```

#### Q: 向量检索不返回结果
**可能原因：**
- 向量数据库为空（尚未添加长期记忆）
- 查询文本与记忆内容语义差异过大

**解决方案：**
```python
# 检查向量数据库中的记忆数量
from app.core.vector_memory import get_vector_store

store = get_vector_store()
count = store.get_memory_count(character_id="npc_luo_xiaohei", player_id="player_001")
print(f"向量记忆数量: {count}")

# 手动添加测试记忆
from app.db import repository
fact_id = repository.save_long_term_fact(
    character_id="npc_luo_xiaohei",
    player_id="player_001",
    fact_text="玩家喜欢吃鱼",
    importance=8
)
store.add_memory(fact_id, "npc_luo_xiaohei", "player_001", "玩家喜欢吃鱼", 8)
```

#### Q: 内存占用过高
**原因：**
- 向量模型加载到内存（约 100MB）
- 大量对话历史和记忆

**解决方案：**
1. 定期清理旧的会话数据
2. 调整 `SHORT_TERM_MEMORY_TURNS` 减少短期记忆轮数
3. 增加服务器内存
4. 考虑使用远程向量数据库（Milvus / Qdrant）

```bash
# 清理 30 天前的会话
sqlite3 memoria.db "DELETE FROM short_term_message WHERE created_at < datetime('now', '-30 days');"
```

---

### 调试技巧

#### 1. 启用详细日志
```python
# 在 app/main.py 中修改日志级别
logging.basicConfig(
    level=logging.DEBUG,  # 改为 DEBUG
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
```

#### 2. 查看 LLM 调用详情
```python
# 在 app/core/llm_client.py 中添加
logger.debug(f"LLM 请求: {messages}")
logger.debug(f"LLM 响应: {response}")
```

#### 3. 测试角色卡加载
```python
from app.core import character_loader

try:
    card = character_loader.load_character_card("npc_luo_xiaohei")
    print(f"角色卡加载成功: {card.meta.name}")
except Exception as e:
    print(f"加载失败: {e}")
```

#### 4. 检查数据库结构
```bash
sqlite3 memoria.db

# 查看所有表
.tables

# 查看表结构
.schema character_card

# 查询数据
SELECT * FROM session LIMIT 5;

# 退出
.quit
```

#### 5. API 测试
使用 FastAPI 自动生成的交互式文档：
- 访问 http://localhost:8000/docs
- 点击任意接口的 "Try it out" 按钮
- 填写参数后点击 "Execute"
- 查看响应结果和状态码

---

### 性能优化建议

#### 1. 数据库优化
```sql
-- 定期执行 VACUUM 清理空间
VACUUM;

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT * FROM session WHERE character_id = 'xxx';

-- 重建索引
REINDEX;
```

#### 2. 缓存优化
```python
# 增加角色卡缓存大小（默认 64）
@lru_cache(maxsize=128)
def load_character_card(character_id: str) -> CharacterCard:
    ...
```

#### 3. 批量操作
```python
# 批量插入记忆（而非逐条插入）
facts = [
    (char_id, player_id, "事实1", 5),
    (char_id, player_id, "事实2", 7),
    ...
]
conn.executemany(
    "INSERT INTO long_term_fact (character_id, player_id, fact_text, importance) VALUES (?, ?, ?, ?)",
    facts
)
```

#### 4. 异步化
```python
# 将耗时操作改为异步（记忆萃取、向量化等）
import asyncio

async def extract_and_save_memory(...):
    # 异步执行，不阻塞主流程
    ...
```

## 📝 开发路线图

### ✅ 已完成功能

#### 第一阶段 - 核心对话系统
- [x] 角色卡 JSON 定义和加载系统
- [x] 基于 Pydantic 的角色卡数据验证
- [x] 短期记忆（对话历史管理）
- [x] 长期记忆（事实提取和存储）
- [x] 关系和情感系统（好感度、信任度、情绪）
- [x] LLM 调用适配层（支持 OpenAI 兼容接口）
- [x] Prompt 组装器
- [x] 对话编排核心（Orchestrator）
- [x] 沉浸感保护机制（AI 身份检测）
- [x] 三层容错机制（JSON 解析、修复、兜底）
- [x] FastAPI RESTful API
- [x] Web UI 界面
- [x] SQLite 数据库持久化

#### 第二阶段 - 增强记忆与管理
- [x] RAG 向量检索（ChromaDB + sentence-transformers）
- [x] 语义相似度记忆召回
- [x] 会话摘要系统（中期记忆）
- [x] 自动摘要生成（会话结束时）
- [x] 角色卡管理后台 API
- [x] 角色卡数据库存储
- [x] 角色卡导入/导出功能
- [x] 角色卡启用/禁用管理
- [x] 管理后台 Web 界面
- [x] 可视化角色卡编辑器

#### 第三阶段 - 事件系统
- [x] 事件定义数据模型（event_schema.py）
- [x] 事件检测引擎（EventDetector）
- [x] 多类型触发条件支持
  - [x] 好感度阈值
  - [x] 信任度阈值
  - [x] 关键词匹配
  - [x] 对话次数
  - [x] 时间基础
  - [x] 情绪匹配
  - [x] 复合条件（AND/OR 逻辑）
- [x] 事件执行器（EventExecutor）
- [x] 多种事件效果实现
  - [x] 状态修改
  - [x] 内容解锁
  - [x] 对话触发
  - [x] 记忆添加
  - [x] 情绪改变
  - [x] 玩家通知
  - [x] 关系修改
- [x] 事件冷却时间管理
- [x] 事件触发日志记录
- [x] 角色关系网络系统
- [x] 角色间关系 CRUD API
- [x] 关系网络查询（用于可视化）

---

### 🔄 进行中

#### 第四阶段 - 事件系统集成与扩展
- [ ] 事件管理 Web 界面
- [ ] 事件可视化编辑器
- [ ] 预设事件模板库
- [ ] 事件触发历史查询界面
- [ ] 更丰富的表情和动作系统
- [ ] 动作词库动态扩展

---

### 📋 计划中

#### 第五阶段 - 高级特性
- [ ] 多角色对话（群聊模式）
- [ ] 角色间主动互动（基于关系网络）
- [ ] 角色记忆共享机制
- [ ] 道具和任务系统（扩展事件效果）
- [ ] 语音合成集成（TTS）
- [ ] 语音识别集成（STT）
- [ ] 多语言支持（i18n）

#### 第六阶段 - 可视化与分析
- [ ] 记忆可视化（时间轴展示）
- [ ] 关系网络可视化（图谱展示）
- [ ] 情感变化曲线图
- [ ] 对话质量分析面板
- [ ] 性能监控和分析
- [ ] 事件触发统计面板

#### 第七阶段 - 生态与扩展
- [ ] 角色卡市场和分享平台
- [ ] 插件系统
- [ ] 自定义事件脚本支持
- [ ] WebSocket 实时通信
- [ ] 移动端适配
- [ ] 导出对话记录（Markdown/PDF）

---

### 💡 功能状态说明

**✅ 已完成：** 功能已实现并通过测试，可在生产环境使用

**🔄 进行中：** 功能正在开发，部分代码已提交

**📋 计划中：** 功能已列入路线图，尚未开始开发

**❌ 已废弃：** 功能不再计划实现

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

### 如何贡献

**1. Fork 项目**
```bash
# 在 GitHub 上点击 Fork 按钮
# 克隆你的 Fork
git clone https://github.com/YOUR_USERNAME/Memoria.git
cd Memoria
```

**2. 创建特性分支**
```bash
git checkout -b feature/your-feature-name
```

**3. 提交代码**
在提交代码前，请确保：

- ✅ 代码符合 PEP 8 规范
- ✅ 添加必要的注释和文档字符串
- ✅ 测试所有相关功能
- ✅ 更新相关文档（README.md 等）

**代码风格示例：**
```python
def calculate_affinity_change(
    player_message: str,
    character_mood: str,
    current_affinity: float
) -> float:
    """
    计算好感度变化值
    
    Args:
        player_message: 玩家消息内容
        character_mood: 角色当前情绪
        current_affinity: 当前好感度
    
    Returns:
        float: 好感度变化值（-10 ~ +10）
    
    Examples:
        >>> calculate_affinity_change("你真可爱", "开心", 50.0)
        5.0
    """
    # 实现逻辑...
    pass
```

**4. 运行测试**
```bash
# TODO: 添加测试框架后更新此部分
python -m pytest tests/
```

**5. 提交 Pull Request**
```bash
git add .
git commit -m "feat: 添加 XXX 功能"
git push origin feature/your-feature-name

# 在 GitHub 上创建 Pull Request
```

### Commit 消息规范

使用语义化提交消息（Conventional Commits）：

```
feat: 新增功能
fix: 修复 Bug
docs: 文档更新
style: 代码格式调整（不影响功能）
refactor: 代码重构
perf: 性能优化
test: 添加测试
chore: 构建/工具链更新
```

**示例：**
```
feat: 添加多角色对话支持
fix: 修复向量检索返回空结果的问题
docs: 更新 API 文档中的事件系统说明
```

### 代码审查标准

**必须满足：**
- 功能完整，无明显 Bug
- 代码可读性强，注释充分
- 符合现有架构和设计模式
- 不引入安全风险

**推荐满足：**
- 有单元测试覆盖
- 性能无明显下降
- 兼容现有 API

### 需要帮助？

- 📧 提交 Issue：描述问题或建议
- � 参与讨论：在 Issue 或 PR 中交流
- 📖 阅读文档：查看现有代码和注释

---

## �📄 许可证

本项目使用 **MIT 许可证**。

```
MIT License

Copyright (c) 2024 Memoria Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 🙏 致谢

### 开源项目

感谢以下优秀的开源项目：

- **[FastAPI](https://fastapi.tiangolo.com/)** - 现代化、高性能的 Web 框架
- **[Pydantic](https://pydantic-docs.helpmanual.io/)** - 强大的数据验证库
- **[OpenAI Python SDK](https://github.com/openai/openai-python)** - LLM 客户端库
- **[ChromaDB](https://www.trychroma.com/)** - 向量数据库，支持语义检索
- **[sentence-transformers](https://www.sbert.net/)** - 文本嵌入模型库
- **[Uvicorn](https://www.uvicorn.org/)** - 轻量级 ASGI 服务器

### 技术栈

- **语言：** Python 3.10+
- **Web 框架：** FastAPI
- **数据库：** SQLite（支持 PostgreSQL）
- **向量数据库：** ChromaDB
- **嵌入模型：** sentence-transformers/all-MiniLM-L6-v2
- **LLM：** OpenAI 兼容接口（DeepSeek / Kimi / Qwen 等）

### 灵感来源

- **AI 角色扮演：** Character.AI、Replika
- **游戏 NPC 系统：** The Elder Scrolls、Cyberpunk 2077
- **记忆架构：** MemGPT、Generative Agents

### 特别感谢

感谢所有为项目提供建议、测试和反馈的用户和贡献者！

---

## 📞 联系方式

- **Issue 反馈：** [GitHub Issues](https://github.com/YOUR_USERNAME/Memoria/issues)
- **功能建议：** [GitHub Discussions](https://github.com/YOUR_USERNAME/Memoria/discussions)
- **文档改进：** 欢迎提交 PR

---

## 📈 项目统计

![GitHub stars](https://img.shields.io/github/stars/nanzi-dev/Memoria?style=social)
![GitHub forks](https://img.shields.io/github/forks/nanzi-dev/Memoria?style=social)
![GitHub issues](https://img.shields.io/github/issues/nanzi-dev/Memoria)
![GitHub license](https://img.shields.io/github/license/nanzi-dev/Memoria)

---

**Memoria** - 让每个角色都拥有真实的记忆与情感 ✨

*用 AI 创造有温度的虚拟角色，构建沉浸式的对话体验。*
