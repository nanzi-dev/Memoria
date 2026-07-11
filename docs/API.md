# Memoria API 文档

完整的 REST API 参考，业务端点前缀为 `/api/v1`（多角色对话为 `/api/v1/multi-dialogue`），系统端点 `/health`、`/ready`、`/admin/log-level` 不带该前缀。

访问 http://127.0.0.1:8001/docs 可查看 Swagger 交互式文档，http://127.0.0.1:8001/redoc 可查看 ReDoc 文档。

除用户注册/登录外，业务接口通常需要登录态。认证方式支持 `Authorization: Bearer <token>`、`?token=<token>` 或登录后写入的 `memoria-token` HttpOnly Cookie。带 `player_id` 的接口会校验 `player_id` 必须等于当前登录用户 ID。角色卡、事件定义和角色关系都按当前登录用户隔离；不同用户可以拥有相同的 `character_id` / `event_id`。

---
  - [对话系统 API](#对话系统-api)
  - [角色卡管理 API](#角色卡管理-api)
  - [事件管理 API](#事件管理-api)
  - [角色关系 API](#角色关系-api)
  - [多角色对话 API](#多角色对话-api)
  - [用户 API](#用户-api)
  - [开发者体验 API](#开发者体验-api)
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

该列表只返回当前登录用户已创建或导入、且启用的角色卡。`src/memoria/characters/` 下的静态 JSON 是开发/导入模板，不会在用户第一次使用时自动复制为用户角色卡。

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

如果该玩家与角色已有活跃会话，接口会复用原会话并返回 `recovered: true` 与最近消息；否则创建空会话，开场白为空字符串。角色卡被禁用后不能创建新的单聊；已有历史仍可通过历史接口查看，继续发送消息会返回 400。

**响应示例：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "opening_line": "",
  "action": "",
  "current_affinity": 0,
  "current_trust": 0,
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
  "trust_delta": 0,
  "current_affinity": 2,
  "current_trust": 0,
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
  "current_trust": 0,
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
- `name` / `display_name` / `avatar_url` / `is_active`: 列表展示用角色信息；禁用角色会保留在已有会话列表中，前端展示为离线

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

本节接口均需要登录态，且只操作当前登录用户拥有的角色卡。相同 `character_id` 可以被不同用户分别创建或导入。

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

本节接口均需要登录态。

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
    "trigger_type": "state",
    "schedule": null,
    "template_id": null
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
  "schedule": "*/30 * * * *",
  "template_id": "tpl_story_keyword_node",

  "trigger_condition": {
    "trigger_type": "state",
    "threshold": 0.6,
    "comparison": "gte",
    "logic_operator": "and",
    "cooldown_hours": 2
  },

  "effects": [
    {
      "effect_type": "trigger_dialogue",
      "dialogue_text": "你在做什么呀？",
      "dialogue_action": "curious_talk"
    },
    {
      "effect_type": "trigger_event",
      "next_event_id": "evt_follow_up"
    },
    {
      "effect_type": "npc_proactive_dialogue",
      "target_session_id": "multi-session-id",
      "proactive_character_id": "npc_luo_xiaohei",
      "proactive_prompt": "围绕刚触发的剧情主动说一句话"
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
  "is_active": true,
  "schedule": null,
  "template_id": "tpl_story_keyword_node"
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
DELETE /api/v1/admin/events/{event_id}
```

该接口会永久删除事件定义及其触发记录。

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

### 10. 获取事件模板库

```http
GET /api/v1/admin/event-templates?category=relationship
```

内置模板包括好感度里程碑、信任度里程碑和关键剧情节点。服务启动时会自动初始化模板库。模板库是全局系统模板；套用模板创建事件时，事件会保存到当前登录用户自己的 `event_definition` 中。

**响应示例：**
```json
[
  {
    "template_id": "tpl_affinity_milestone",
    "template_name": "好感度里程碑",
    "category": "relationship",
    "description": "当玩家与 NPC 的好感度达到指定阈值时通知玩家并记录记忆。",
    "trigger_config": {"trigger_type": "affinity_threshold", "threshold": 50},
    "effects_config": [
      {"effect_type": "notify_player", "notification_message": "关系出现了新的变化。"}
    ],
    "metadata": {"threshold_editable": true}
  }
]
```

### 10.1 创建或更新系统事件模板（开发用途）

```http
POST /api/v1/admin/event-templates
```

该接口用于开发维护系统模板库，不在普通用户前端暴露。

**请求体：**
```json
{
  "template_id": "tpl_dev_keyword",
  "template_name": "开发关键词模板",
  "category": "dev",
  "description": "玩家提到指定关键词时通知玩家。",
  "trigger_config": {
    "trigger_type": "keyword_match",
    "keywords": ["线索"],
    "match_mode": "any"
  },
  "effects_config": [
    {
      "effect_type": "notify_player",
      "notification_message": "触发了开发模板事件。"
    }
  ],
  "metadata": {
    "dev_only": true
  }
}
```

**响应：**
```json
{
  "success": true,
  "message": "事件模板 'tpl_dev_keyword' 已保存",
  "template_id": "tpl_dev_keyword"
}
```

### 10.2 删除系统事件模板（开发用途）

```http
DELETE /api/v1/admin/event-templates/{template_id}
```

删除指定模板记录。内置默认模板在服务启动或模板列表自动初始化时可能被重新写入。

**响应：**
```json
{
  "success": true,
  "message": "事件模板 'tpl_dev_keyword' 已删除",
  "template_id": "tpl_dev_keyword"
}
```

---

### 11. 注册时间驱动事件

```http
POST /api/v1/admin/events/schedules
Content-Type: application/json

{
  "event_id": "evt_daily_check",
  "character_id": "npc_luo_xiaohei",
  "player_id": "player_001",
  "schedule": "*/30 * * * *"
}
```

`schedule` 使用 5 字段 cron 表达式：`minute hour day month weekday`，支持 `*`、`*/N`、逗号列表和范围。

**响应示例：**
```json
{
  "success": true,
  "message": "事件调度已注册",
  "event_id": "evt_daily_check"
}
```

---

### 12. 手动执行到期时间事件

```http
POST /api/v1/admin/events/schedules/run-due?limit=50
```

用于后台任务或调试入口。会检查已注册且到期的调度事件，执行事件效果和事件链，并更新下一次执行时间。

**响应示例：**
```json
{
  "success": true,
  "triggered_count": 1,
  "triggered_events": [
    {
      "event_id": "evt_daily_check",
      "event_name": "每日检查",
      "effects": ["notify_player: 通知已发送"],
      "chained_events": [],
      "proactive_dialogues": []
    }
  ]
}
```

---

### 13. 查询事件上下文

```http
GET /api/v1/admin/event-context?character_id=&player_id=&status=&limit=100
```

返回事件链、分支和定时事件执行后保存的跨会话进度。

**响应示例：**
```json
[
  {
    "event_id": "evt_story_01",
    "character_id": "npc_luo_xiaohei",
    "player_id": "player_001",
    "context_data": {
      "event_name": "第一条线索",
      "state_changes": {},
      "chained_events": ["evt_story_02"]
    },
    "status": "completed",
    "progress": 1.0,
    "last_session_id": "session-id",
    "updated_at": "2026-07-10T14:30:00Z"
  }
]
```

---

## 角色关系 API

本节接口均需要登录态，且只读写当前登录用户的角色关系。相同角色 ID 组合可以在不同用户下保存不同关系。

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

**关系类型：** 后端按字符串保存，不限制固定枚举；前端提供常用类型并支持新增/删除自定义类型。

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

多角色对话系统支持 2-5 个 NPC 同时参与群聊，提供自然的多角色互动体验。

### 1. 开始多角色会话
```http
POST /api/v1/multi-dialogue/session/start
Content-Type: application/json

{
  "player_id": "player_001",
  "player_name": "旅行者",
  "group_name": "森林小队",
  "character_ids": ["npc_luo_xiaohei", "npc_wuxian"]
}
```

**参数说明：**
- `player_id`: 玩家ID
- `player_name`: 玩家显示名称
- `group_name` (可选): 群聊名称，会写入会话列表
- `character_ids`: 参与角色ID列表（至少2个）；禁用角色不能用于新建群聊

**响应示例：**
```json
{
  "session_id": "multi-session-uuid",
  "group_name": "森林小队",
  "group_thread_id": "multi-session-uuid",
  "opening": {
    "character_id": "npc_luo_xiaohei",
    "character_name": "小黑",
    "dialogue": "[好奇地看着周围]哇，这里好多人呀！",
    "action": "greeting_curious",
    "current_affinity": 0,
    "current_trust": 0,
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
  "discussion_mode": true,
  "max_responses": 4
}
```

每次玩家发起的多角色轮次会保存玩家消息和角色回复。群聊结束且有效消息数大于 6 条、摘要模型返回非空内容时，系统会将整场对话统一摘要写入 `session_summary`，并同步保存到 `group_memory` 作为群聊会话记忆；后续多角色 Prompt 会召回这些群体记忆，帮助参与角色延续共同经历。

根据讨论触发条件，响应可能是单角色回复，也可能是多角色连续讨论回复。`discussion_mode` 默认启用；`max_responses` 可传 1-5，但编排器会结合语境、参与人数和内部上限动态决定实际接话人数，当前最多 4 个角色发言。讨论模式下返回结构包含 `responses` 数组，每个元素对应一个角色发言。已有群聊中如果某个角色卡被禁用，该成员仍保留在参与者列表和历史中，但不会再被编排器选中回复；如果没有任何在线可回复角色，本接口返回 400。

**响应示例：**
```json
{
  "character_id": "npc_wuxian",
  "character_name": "无限",
  "dialogue": "[微笑]你好，欢迎。",
  "action": "greeting_polite",
  "affinity_delta": 1,
  "trust_delta": 0,
  "current_affinity": 1,
  "current_trust": 0,
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
      "trust_delta": 0,
      "current_affinity": 1,
      "current_trust": 0,
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
  "group_thread_id": "multi-session-uuid",
  "created_at": "2026-07-02T10:00:00Z",
  "status": "active",
  "participants": [
    {
      "character_id": "npc_luo_xiaohei",
      "name": "罗小黑",
      "display_name": "小黑",
      "join_order": 0,
      "speak_frequency": 1.2,
      "is_active": false,
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

### 6. 结束会话
```http
POST /api/v1/multi-dialogue/session/end
Content-Type: application/json

{
  "session_id": "multi-session-uuid"
}
```

### 7. 继续群聊会话
```http
POST /api/v1/multi-dialogue/session/{session_id}/continue
```

当原群聊已结束时，该接口会在同一个 `group_thread_id` 下创建新的 active 会话；若同一线程已有 active 会话，则直接返回该会话。

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


## 开发者体验 API

以下端点均需要登录态，路径前缀为 `/api/v1/developer`。

### 1. 对话回放
```http
GET /api/v1/developer/replay/{session_id}?step=3&limit=1000
Authorization: Bearer token-value
```

加载历史 session，按消息顺序返回可逐步查看的回放数据。`step` 为空时返回完整回放；传入数字时只返回前 N 条消息。新生成的单角色 assistant 消息会包含状态快照，旧消息可能没有状态字段。

### 2. 性能分析
```http
GET /api/v1/developer/performance
Authorization: Bearer token-value
```

返回最近 200 个样本窗口内的关键耗时分布，包括 `llm.role_turn`、`llm.light_task`、`llm.json_repair`、`memory.vector_search`。

```http
POST /api/v1/developer/performance/reset
Authorization: Bearer token-value
```

清空当前进程内的性能采样。

### 3. 对话质量评分
```http
POST /api/v1/developer/quality-score
Authorization: Bearer token-value
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "use_llm": false
}
```

也可以直接传入 `messages`。默认使用本地启发式评分，返回角色一致性、趣味性和综合分；`use_llm: true` 时会调用轻量模型评估，失败时自动回退到启发式评分。

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
Authorization: Bearer token-value
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

所有 `/api/*` 写操作（非 GET/HEAD/OPTIONS）均受速率限制保护。服务端优先使用认证 token 解析出的用户 ID 作为限流 key，未登录或 token 无效时退回客户端 IP；不会信任客户端传入的 `X-Player-ID`。

| 项目       | 值                    |
|------------|-----------------------|
| 窗口大小   | 60 秒                 |
| 最大请求数 | 60 次 / 窗口          |
| 识别方式   | 登录用户 ID           |
| 兜底策略   | 未登录则使用客户端 IP |
| 超限响应码 | HTTP 429             |

**超限响应示例：**
```json
{
  "error": "请求过于频繁，请稍后再试",
  "retry_after": 60.0
}
```

## 发言策略说明

多角色对话使用固定的混合发言策略。编排器会结合关键词、角色关系、发言均衡性、最近发言时间和上下文语义选择下一位发言角色，客户端不再传入策略类型或角色发言权重。

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
| `trigger_event` | 触发另一个事件（事件链）|
| `branch_event` | 按上下文分支触发事件 |
| `npc_proactive_dialogue` | NPC 主动发言（多角色编排器）|

---
