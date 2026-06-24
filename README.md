# Memoria - 角色模拟系统

一个基于大语言模型的沉浸式角色扮演对话系统，支持动态记忆管理、情感状态追踪和个性化交互体验。

## ✨ 核心特性

### 🎭 深度角色模拟
- **结构化角色卡系统**：使用 JSON 格式定义角色的完整人格、背景、语言风格和行为模式
- **多维度性格系统**：支持 MBTI、核心特质、价值观、恐惧与禁忌等多维度性格定义
- **动态语言风格**：根据角色设定自动生成符合人设的对话内容和表达方式

### 🧠 智能记忆系统
- **短期记忆**：保留最近对话历史（默认 8 轮），确保上下文连贯性
- **长期记忆**：自动提取和存储重要事实，支持跨会话记忆持久化
- **记忆萃取**：使用 AI 从对话中智能提取关键信息并评估重要性
- **记忆压缩**：自动总结和去重，避免记忆膨胀

### 💖 关系与情感追踪
- **好感度系统**：根据对话内容动态调整角色对玩家的好感度（-100 ~ 100）
- **信任度机制**：追踪角色对玩家的信任程度，影响话题开放度
- **情绪状态**：实时跟踪角色当前情绪，影响对话表现和反应
- **亲密度影响**：不同关系阶段解锁不同的对话内容和话题

### 🛡️ 沉浸感保护
- **AI 身份检测**：自动识别并过滤可能破坏沉浸感的输出（如"我是AI"等）
- **角色一致性**：严格约束模型输出，确保始终保持角色人设
- **安全兜底机制**：三层容错机制，确保系统稳定运行

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
- Web UI: http://localhost:8000
- API 文档: http://localhost:8000/docs
- 备用 API 文档: http://localhost:8000/redoc

## 📚 API 文档

### 1. 获取角色列表
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

### 2. 开始新会话
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

### 3. 发送对话消息
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
  "triggered_events": []
}
```

### 4. 获取会话列表
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

### 5. 获取对话历史
```http
GET /api/v1/dialogue/history?session_id=550e8400-e29b-41d4-a716-446655440000&offset=0&limit=20
```

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

## 🔧 高级功能

### 命令行对话工具

```bash
python -m app.scripts.cli_chat
```

支持在命令行中直接与角色对话，适合快速测试和调试。

### 记忆系统扩展

系统提供了完整的记忆萃取模块（`app/core/memory_extractor.py`），可扩展为：

- **定期记忆压缩**：避免长期记忆数据膨胀
- **记忆重要性评分**：智能筛选值得保留的信息
- **跨会话记忆共享**：同一角色在不同会话中共享记忆

### 数据库迁移

当前使用 SQLite 作为轻量级数据库，可无缝迁移到 PostgreSQL：

1. 修改 `app/core/config.py` 中的数据库配置
2. 更新 `app/db/repository.py` 中的连接方式
3. SQL 语句保持兼容，无需大规模改动

## 🎯 技术亮点

### 三层容错机制

LLM 输出的不确定性是角色模拟系统的核心挑战，Memoria 实现了三层容错：

1. **标准 JSON 解析**：优先尝试直接解析模型输出
2. **修复重试**：解析失败时请求模型修正格式
3. **文本兜底**：仍失败时保留对话内容，其他字段使用默认值

这确保了系统永不崩溃，即使在模型输出异常时也能优雅降级。

### 沉浸感保护

通过正则表达式检测和替换可能破坏角色扮演沉浸感的输出：

- 检测"我是AI"、"作为语言模型"等表述
- 自动替换为符合人设的兜底话术
- 记录警告日志便于监控和优化

### 角色卡热重载

支持运行时重新加载角色卡，无需重启服务：

```python
from app.core import character_loader
character_loader.reload_character_card("character_id")
```

### LRU 缓存优化

角色卡加载使用 LRU 缓存（最多 64 个），避免重复 I/O 和解析开销。

## 📊 数据库结构

### 关系状态表（relationship_state）
存储角色与玩家的动态关系数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| affection_level | REAL | 好感度（-100 ~ 100） |
| trust_level | REAL | 信任度（0 ~ 100） |
| current_mood | TEXT | 当前情绪 |
| updated_at | TEXT | 更新时间 |

### 长期记忆表（long_term_fact）
存储从对话中提取的重要事实。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| fact_text | TEXT | 事实内容 |
| importance | INTEGER | 重要性（1-10） |
| created_at | TEXT | 创建时间 |
| last_referenced | TEXT | 最后引用时间 |

### 会话表（session）
管理对话会话。

| 字段 | 类型 | 说明 |
|------|------|------|
| session_id | TEXT | 会话 UUID |
| character_id | TEXT | 角色 ID |
| player_id | TEXT | 玩家 ID |
| player_name | TEXT | 玩家名称 |
| created_at | TEXT | 创建时间 |

### 短期记忆表（short_term_message）
存储对话历史。

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER | 自增主键 |
| session_id | TEXT | 会话 ID |
| role | TEXT | 角色（user/assistant） |
| content | TEXT | 消息内容 |
| created_at | TEXT | 创建时间 |

## 🐛 故障排查

### 常见问题

**Q: 提示 "角色卡 JSON 格式错误"**
- 检查 JSON 文件语法是否正确
- 使用 JSON 验证工具检查格式
- 查看详细错误信息中的行号和列号

**Q: API 调用失败**
- 确认 `.env` 文件中的 API 密钥正确
- 检查网络连接和 API 服务状态
- 查看日志中的详细错误信息

**Q: 角色对话不符合人设**
- 优化角色卡中的性格和语言风格定义
- 调整 `speech_style` 和 `personality` 字段
- 增加更详细的约束条件

**Q: 数据库锁定错误**
- SQLite 使用 WAL 模式，支持并发读
- 如需高并发写入，考虑迁移到 PostgreSQL

## 📝 开发路线图

- [ ] 支持多轮事件触发系统
- [ ] 角色关系网络（角色间互动）
- [ ] 更丰富的表情和动作系统
- [ ] 语音合成集成
- [ ] 多语言支持
- [ ] Web UI 功能增强
- [ ] 管理后台（角色卡编辑器）
- [ ] 性能监控和分析面板

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

在提交代码前，请确保：
1. 代码符合 PEP 8 规范
2. 添加必要的注释和文档
3. 测试所有相关功能

## 📄 许可证

本项目使用 MIT 许可证。

## 🙏 致谢

感谢以下开源项目：
- [FastAPI](https://fastapi.tiangolo.com/) - 现代化 Web 框架
- [Pydantic](https://pydantic-docs.helpmanual.io/) - 数据验证
- [OpenAI Python SDK](https://github.com/openai/openai-python) - LLM 客户端

---

**Memoria** - 让每个角色都拥有真实的记忆与情感 ✨
