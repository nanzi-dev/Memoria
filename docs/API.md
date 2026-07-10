# Memoria API 文档

完整的 REST API 参考，所有端点前缀为 `/api/v1`（多角色对话为 `/api/v1/multi-dialogue`）。

访问 http://localhost:8000/docs 可查看 Swagger 交互式文档，http://localhost:8000/redoc 可查看 ReDoc 文档。

---
  - [对话系统 API](#对话系统-api)
  - [角色卡管理 API](#角色卡管理-api)
  - [事件管理 API](#事件管理-api)
  - [角色关系 API](#角色关系-api)
  - [多角色对话 API](#多角色对话-api)
  - [用户 API](#用户-api)
  - [系统管理 API](#系统管理-api)
  - [发言策略说明](#发言策略说明)
---

## 对话系统 API

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

如果该玩家与角色已有活跃会话，接口会复用原会话并返回 `recovered: true` 与最近消息；否则创建空会话，开场白为空字符串。

**响应示例：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "opening_line": "[好奇地打量]你好呀！你是谁？",
  "action": "greeting_curious",
  "current_affinity": 0,
  "assistant_message_id": null,
  "recovered": false,
  "messages": []
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
  "user_message_id": 101,
  "assistant_message_id": 102,
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

### 4. 获取会话列表
```http
GET /api/v1/dialogue/sessions?character_id=npc_luo_xiaohei&player_id=player_001
```

**响应示例：**
```json
[
    {
        "session_id": "d3096e32-58de-45fc-8ca6-89e758c7c7ae",
        "character_id": "npc_merchant_lina",
        "player_id": "南子",
        "player_name": "南子",
        "created_at": "2026-06-25T14:58:29.988857+00:00",
        "ended_at": "2026-06-25T15:02:35.799106+00:00",
        "status": "ended",
        "last_message": "您...您慢走啊！[强扯着嘴角挥着手，声音发虚]抓...抓不着您的！您这么厉害，谁能抓得着啊...[看着他的背影，悄悄用袖子擦了把额头的冷汗，心里默念]明天...明天我绝对不开摊...不不不，换个地方摆摊...[深吸一口气]来来来，下一位客官！看货看货！没事了没事了！",
        "message_count": 39
    },
    {
        "session_id": "7da35e0a-9196-4c1c-b781-886d54b03abc",
        "character_id": "npc_merchant_lina",
        "player_id": "南子",
        "player_name": "南子",
        "created_at": "2026-06-23T12:05:29.899912+00:00",
        "ended_at": null,
        "status": "active",
        "last_message": "[深吸一口气，强忍怒意，脸上职业性的笑容已经有点挂不住了]行，行吧。买卖不成仁义在嘛，这位...客官，您要是觉得不满意，那我也不强求了。[开始收拾摊位，动作明显加快]我先去别的地方转转，等您心情好些了再说。",
        "message_count": 25
    }
]
```

### 5. 获取对话历史
```http
GET /api/v1/dialogue/history?character_id=npc_luo_xiaohei&player_id=player_001&offset=0&limit=20
```

**查询参数：**
- `character_id` : 角色 ID
- `player_id`: 用户ID
- `offset` (可选): 偏移量，默认 0
- `limit` (可选): 每页数量，默认 20
- `exclude_session_id` (可选): 排除指定会话，常用于当前会话外的历史分页

**响应示例：**
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "[好奇地打量]你好呀！你是谁？",
      "created_at": "2026-06-23T10:30:00.000000+00:00",
      "message_id": 1
    },
    {
      "role": "user",
      "content": "你好，小黑！",
      "created_at": "2026-06-23T10:30:15.000000+00:00",
      "message_id": 2
    }
  ],
  "has_more": false,
  "current_affinity": 2,
  "current_mood": "开心"
}
```

### 6. 结束会话（生成摘要）
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

### 7. 获取会话摘要列表
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

### 8. 获取玩家所有会话
```http
GET /api/v1/dialogue/sessions/player?player_id=player_001
```

返回该玩家的单角色会话与多角色会话。接口会懒清理超过 5 分钟未活跃的 active 会话。

**响应字段补充：**
- `group_name`: 多角色群聊名称，单角色会话为 `null`
- `is_multi_character`: 是否多角色会话
- `last_message_at`: 最近消息时间
- `name` / `display_name` / `avatar_url`: 列表展示用角色信息

### 9. 恢复最近活跃会话
```http
GET /api/v1/dialogue/session/latest?player_id=player_001&character_id=npc_luo_xiaohei
```

`character_id` 可选；不传时恢复玩家最近一个活跃会话。

**响应示例：**
```json
{
  "found": true,
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "character_id": "npc_luo_xiaohei",
  "character": null,
  "messages": [
    {
      "role": "user",
      "content": "你好，小黑！",
      "created_at": "2026-06-23T10:30:15.000000+00:00",
      "message_id": 2
    }
  ]
}
```

---

## 角色卡管理 API

### 1. 获取角色卡列表
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
    "avatar_url": "data:image/png;base64,...",
    "version": "1.0.0",
    "is_active": 1,
    "source": "file",
    "created_at": "2026-06-20T08:00:00.000000+00:00",
    "updated_at": "2026-06-23T10:00:00.000000+00:00"
  }
]
```

### 2. 获取角色卡详情
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
  "avatar_url": "data:image/png;base64,...",
  "is_active": 1,
  "source": "file",
  "created_at": "2026-06-20T08:00:00.000000+00:00",
  "updated_at": "2026-06-23T10:00:00.000000+00:00"
}
```

### 3. 创建角色卡
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

### 4. 更新角色卡
```http
PUT /api/v1/admin/characters/{character_id}
Content-Type: application/json

{
  "character_data": { /* 更新后的完整角色卡数据 */ }
}
```

### 5. 删除角色卡
```http
DELETE /api/v1/admin/characters/{character_id}?permanent=false
```

**查询参数：**
- `permanent` (可选): 是否永久删除，默认 false（软删除）

### 6. 激活角色卡
```http
POST /api/v1/admin/characters/{character_id}/activate
```

### 7. 从文件导入角色卡
```http
POST /api/v1/admin/characters/import
Content-Type: application/json

{
  "character_id": "npc_luo_xiaohei"
}
```

### 8. 获取角色头像
```http
GET /api/v1/admin/characters/{character_id}/avatar
```

**响应示例：**
```json
{
  "character_id": "npc_luo_xiaohei",
  "avatar_url": "data:image/png;base64,..."
}
```

### 9. 上传角色头像
```http
POST /api/v1/admin/characters/{character_id}/avatar/upload
Content-Type: multipart/form-data

file=@avatar.png
```

支持 PNG / JPEG / GIF / WebP。大于 2MB 的图片会尝试压缩为 512px JPEG 后保存。

### 10. 通过 URL 设置角色头像
```http
POST /api/v1/admin/characters/{character_id}/avatar/url
Content-Type: application/json

{
  "url": "https://example.com/avatar.png"
}
```

传空字符串会清除头像。服务端会下载图片并转成 data URL 存储，以避免前端 CORS 问题。

---

## 事件管理 API

---

### 1. 获取事件列表

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

### 2. 获取事件详情

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

### 3. 创建事件

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

### 4. 更新事件（可部分更新）

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

### 5. 删除事件

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

### 6. 启用 / 禁用事件

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

### 7. 查询事件触发历史

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

### 8. 查询全部触发历史

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

### 9. 重置触发记录（调试）

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

## 角色关系 API

### 1. 创建角色关系
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

### 2. 获取角色关系
```http
GET /api/v1/relationships/pair/{character_id_a}/{character_id_b}
```

### 3. 更新角色关系
```http
PUT /api/v1/relationships/pair/{character_id_a}/{character_id_b}
Content-Type: application/json

{
  "relationship_type": "mentor",
  "affinity": 60.0,
  "description": "关系更加紧密了"
}
```

### 4. 删除角色关系
```http
DELETE /api/v1/relationships/{character_id_a}/{character_id_b}
```

### 5. 获取角色的所有关系
```http
GET /api/v1/relationships/character/{character_id}
```

### 6. 获取关系网络（用于可视化）
```http
GET /api/v1/relationships/network?character_ids=npc_luo_xiaohei,npc_wuxian
```

**参数说明：**
- `character_ids`（可选）：逗号分隔的角色 ID 列表。若提供，仅返回这些角色相关的关系；若不传，返回数据库中所有角色的完整关系网络。

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

### 7. 批量创建关系
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

---

## 多角色对话 API

多角色对话系统支持2个或更多NPC同时参与群聊，提供自然的多角色互动体验。

### 1. 开始多角色会话
```http
POST /api/v1/multi-dialogue/session/start
Content-Type: application/json

{
  "player_id": "player_001",
  "player_name": "旅行者",
  "group_name": "森林小队",
  "character_ids": ["npc_luo_xiaohei", "npc_wuxian"],
  "speak_frequencies": {
    "npc_luo_xiaohei": 1.2,
    "npc_wuxian": 0.8
  },
  "strategy_type": "hybrid"
}
```

**参数说明：**
- `player_id`: 玩家ID
- `player_name`: 玩家显示名称
- `group_name` (可选): 群聊名称，会写入会话列表
- `character_ids`: 参与角色ID列表（至少2个）
- `speak_frequencies` (可选): 角色发言频率配置，默认1.0
- `strategy_type` (可选): 发言策略类型
  - `round_robin`: 轮询策略
  - `weighted`: 权重随机
  - `smart`: 智能选择
  - `trigger`: 触发式
  - `hybrid`: 混合策略（推荐，默认）

**响应示例：**
```json
{
  "session_id": "multi-session-uuid",
  "strategy_type": "hybrid",
  "group_name": "森林小队",
  "opening": {
    "character_id": "npc_luo_xiaohei",
    "character_name": "小黑",
    "dialogue": "[好奇地看着周围]哇，这里好多人呀！",
    "action": "greeting_curious",
    "current_affinity": 0,
    "current_mood": "好奇"
  }
}
```

### 2. 发送对话消息
```http
POST /api/v1/multi-dialogue/turn
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "player_message": "大家好！",
  "strategy_type": "hybrid",
  "discussion_mode": false,
  "max_responses": 3
}
```

每次玩家发起的多角色轮次会先保存玩家消息和角色回复，再把“玩家消息 + 本轮角色回复”生成摘要，并写入 `group_memory` 作为群体事件记忆。后续多角色 Prompt 会召回这些群体记忆，帮助参与角色延续共同经历。

根据发言策略和讨论触发条件，响应可能是单角色回复，也可能是多角色连续讨论回复。讨论模式下返回结构包含 `responses` 数组，每个元素对应一个角色发言。

**响应示例：**
```json
{
  "character_id": "npc_wuxian",
  "character_name": "无限",
  "dialogue": "[微笑]你好，欢迎。",
  "action": "greeting_polite",
  "affinity_delta": 1,
  "current_affinity": 1,
  "current_mood": "平静"
}
```

**讨论模式响应示例：**
```json
{
  "responses": [
    {
      "character_id": "npc_luo_xiaohei",
      "character_name": "小黑",
      "dialogue": "[举手]我也想听听！",
      "action": "curious_talk",
      "affinity_delta": 1,
      "current_affinity": 1,
      "current_mood": "好奇"
    }
  ],
  "total_speakers": 1,
  "discussion_mode": true
}
```

### 3. 触发角色间互动
```http
POST /api/v1/multi-dialogue/interaction/trigger
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "trigger_character_id": "npc_luo_xiaohei"
}
```

**功能说明：**
让角色主动发言，可用于：
- 角色间的自发对话
- 场景氛围营造
- 推进剧情发展

留空`trigger_character_id`则自动选择一个角色。

**响应示例：**
```json
{
  "character_id": "npc_luo_xiaohei",
  "character_name": "小黑",
  "dialogue": "[转向无限]师傅，我们接下来去哪里？",
  "action": "curious_talk"
}
```

### 4. 获取会话信息
```http
GET /api/v1/multi-dialogue/session/{session_id}
```

**响应示例：**
```json
{
  "session_id": "multi-session-uuid",
  "player_id": "player_001",
  "player_name": "旅行者",
  "group_name": "森林小队",
  "created_at": "2026-07-02T10:00:00Z",
  "status": "active",
  "participants": [
    {
      "character_id": "npc_luo_xiaohei",
      "name": "罗小黑",
      "display_name": "小黑",
      "join_order": 0,
      "speak_frequency": 1.2,
      "is_active": true,
      "message_count": 5,
      "last_spoke_at": "2026-07-02T10:15:00Z"
    },
    {
      "character_id": "npc_wuxian",
      "name": "无限",
      "display_name": "无限",
      "join_order": 1,
      "speak_frequency": 0.8,
      "is_active": true,
      "message_count": 3,
      "last_spoke_at": "2026-07-02T10:12:00Z"
    }
  ]
}
```

### 5. 获取对话历史
```http
GET /api/v1/multi-dialogue/history/{session_id}?limit=50
```

**响应示例：**
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "[好奇地看着周围]哇，这里好多人呀！",
      "character_id": "npc_luo_xiaohei",
      "character_name": "小黑",
      "created_at": "2026-07-02T10:00:00Z"
    },
    {
      "role": "user",
      "content": "大家好！",
      "character_id": null,
      "character_name": null,
      "created_at": "2026-07-02T10:01:00Z"
    },
    {
      "role": "assistant",
      "content": "[微笑]你好，欢迎。",
      "character_id": "npc_wuxian",
      "character_name": "无限",
      "created_at": "2026-07-02T10:02:00Z"
    }
  ],
  "session_info": {
    "session_id": "multi-session-uuid",
    "player_name": "旅行者",
    "created_at": "2026-07-02T10:00:00Z",
    "status": "active",
    "participants": [...]
  }
}
```

### 6. 管理参与者

**添加参与者：**
```http
POST /api/v1/multi-dialogue/participant/add
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "character_id": "npc_luye",
  "speak_frequency": 1.0
}
```

**移除参与者：**
```http
POST /api/v1/multi-dialogue/participant/remove
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "character_id": "npc_luye"
}
```

为兼容旧客户端，也仍支持 `POST /api/v1/multi-dialogue/participant/remove?session_id=xxx&character_id=yyy`。

**更新参与者配置：**
```http
POST /api/v1/multi-dialogue/participant/update
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "character_id": "npc_luo_xiaohei",
  "speak_frequency": 1.5,
  "is_active": true
}
```

该接口同时支持 `POST` 和 `PUT` 方法。`speak_frequency` 与 `is_active` 均为可选字段，可单独调整发言权重或临时启用/停用参与者。

### 7. 结束会话
```http
POST /api/v1/multi-dialogue/session/end
Content-Type: application/json

{
  "session_id": "multi-session-uuid"
}
```

为兼容旧客户端，也仍支持 `POST /api/v1/multi-dialogue/session/end?session_id=xxx`。

---

## 用户 API

用户接口用于 Web 前端登录态、玩家资料和头像管理。登录成功后服务端会同时返回 token 并写入 `memoria-token` HttpOnly Cookie；后续接口支持三种认证方式：`Authorization: Bearer <token>`、`?token=<token>` 或 Cookie。

### 1. 注册
```http
POST /api/v1/user/register
Content-Type: application/json

{
  "username": "旅行者",
  "password": "pass1234",
  "gender": "unknown"
}
```

用户名长度 2-20，只能包含字母、数字、中文、下划线和连字符。密码至少 8 位，且必须包含字母和数字。

**响应示例：**
```json
{
  "token": "token-value",
  "user": {
    "user_id": "usr_ab12cd34",
    "username": "旅行者",
    "gender": "unknown",
    "avatar_url": null
  }
}
```

### 2. 登录
```http
POST /api/v1/user/login
Content-Type: application/json

{
  "username": "旅行者",
  "password": "pass1234"
}
```

响应结构同注册。

### 3. 退出登录
```http
POST /api/v1/user/logout
Authorization: Bearer token-value
```

### 4. 获取当前用户
```http
GET /api/v1/user/me
Authorization: Bearer token-value
```

### 5. 更新资料
```http
PUT /api/v1/user/profile
Authorization: Bearer token-value
Content-Type: application/json

{
  "username": "新名字",
  "gender": "female"
}
```

`gender` 仅支持 `male` / `female` / `unknown`。

### 6. 上传用户头像
```http
POST /api/v1/user/avatar/upload
Authorization: Bearer token-value
Content-Type: multipart/form-data

file=@avatar.png
```

支持 PNG / JPEG / GIF / WebP。大于 2MB 的图片会尝试压缩。

### 7. 通过 URL 设置用户头像
```http
POST /api/v1/user/avatar/url
Authorization: Bearer token-value
Content-Type: application/json

{
  "url": "https://example.com/avatar.png"
}
```

传空字符串会清除头像。

---


## 系统管理 API

---

### 1. 存活检查（Health Check）

用于检测服务是否正常运行，常用于 Kubernetes / Docker 健康探针。

```http
GET /health
```

**响应示例：**
```json
{
  "status": "ok",
  "version": "0.4.0"
}
```

---

### 2. 就绪检查（Readiness Check）

用于检查服务依赖是否已就绪（如数据库连接、缓存服务等）。当依赖不可用时返回 503。

```http
GET /ready
```

**响应示例（正常）：**
```json
{
  "status": "ready",
  "database": "ok"
}
```

**响应示例（不可用）：**
```json
{
  "status": "not_ready",
  "database": "down"
}
```

---

### 3. 动态调整日志级别

无需重启服务即可动态修改全局日志级别。

```http
POST /admin/log-level?level=DEBUG
```

**查询参数：**

| 参数  | 必需 | 说明                     |
|------|------|--------------------------|
| level | 是   | DEBUG / INFO / WARNING / ERROR |

**响应示例：**
```json
{
  "log_level": "DEBUG"
}
```

---

### 4. 速率限制（Rate Limiting）

所有 `/api/*` 路由均受基于玩家的速率限制保护。

```http
X-Player-ID: player_001
```

| 项目       | 值                    |
|------------|-----------------------|
| 窗口大小   | 60 秒                 |
| 最大请求数 | 60 次 / 窗口          |
| 识别方式   | X-Player-ID 请求头    |
| 兜底策略   | 未提供则使用客户端 IP |
| 超限响应码 | HTTP 429             |

**超限响应示例：**
```json
{
  "error": "请求过于频繁，请稍后再试",
  "retry_after": 60.0
}
```

## 发言策略说明

### 策略对比

| 策略 | 类型值 | 特点 | 适用场景 |
|------|--------|------|---------|
| 轮询 | `round_robin` | 按顺序轮流发言 | 确保公平，每人都有机会 |
| 权重随机 | `weighted` | 按频率权重随机选择 | 需要控制发言比例 |
| 智能选择 | `smart` | 综合关键词、关系、频率等多因素 | 复杂场景，自然互动 |
| 触发式 | `trigger` | 基于特定条件触发 | 事件驱动 |
| 混合策略 | `hybrid` | 结合多种策略 | **默认推荐** |

### 智能策略评分因素

1. 关键词匹配 (30%)
2. 角色关系亲密度 (25%)
3. 发言频率配置 (20%)
4. 发言均衡性 (15%)
5. 最近发言时间 (10%)

---

## 触发条件类型参考

事件系统中 `trigger_condition.trigger_type` 支持以下类型：

| 类型 | 说明 |
|------|------|
| `affinity_threshold` | 好感度阈值 |
| `trust_threshold` | 信任度阈值 |
| `keyword_match` | 关键词匹配 |
| `dialogue_count` | 对话次数 |
| `time_based` | 基于时间 |
| `item_acquired` | 获得物品（扩展）|
| `quest_completed` | 完成任务（扩展）|
| `relationship_change` | 关系变化 |
| `mood_match` | 情绪匹配 |
| `composite` | 复合条件（AND/OR）|

## 效果类型参考

`effects.effect_type` 支持：

| 类型 | 说明 |
|------|------|
| `modify_state` | 修改状态（好感度、信任度）|
| `unlock_content` | 解锁内容 |
| `trigger_dialogue` | 触发特定对话 |
| `add_memory` | 添加长期记忆 |
| `change_mood` | 改变情绪 |
| `notify_player` | 通知玩家 |
| `grant_item` | 给予物品（扩展）|
| `start_quest` | 开启任务（扩展）|
| `modify_relationship` | 修改角色间关系 |

---
