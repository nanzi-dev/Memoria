# Memoria API 文档

完整的 REST 与 SSE API 参考。业务端点前缀为 `/api/v1`（多角色对话为 `/api/v1/multi-dialogue`），系统端点 `/health`、`/ready`、`/admin/log-level` 不带该前缀。

访问 http://127.0.0.1:8001/docs 可查看 Swagger 交互式文档，http://127.0.0.1:8001/redoc 可查看 ReDoc 文档。

除用户注册/登录外，业务接口通常需要登录态。API 客户端可使用 `Authorization: Bearer <token>` 或登录后写入的 `memoria-token` HttpOnly Cookie。仓库内 Web 前端只使用 HttpOnly Cookie，并在启动时清理旧版 `localStorage` token。带 `player_id` 的接口会校验 `player_id` 必须等于当前登录用户 ID。角色卡、事件定义和角色关系都按当前登录用户隔离；不同用户可以拥有相同的 `character_id` / `event_id`。

---
  - [对话系统 API](#对话系统-api)
  - [角色卡管理 API](#角色卡管理-api)
  - [事件管理 API](#事件管理-api)
  - [剧情状态 API](#剧情状态-api)
  - [角色关系 API](#角色关系-api)
  - [多角色对话 API](#多角色对话-api)
  - [知识库 API](#知识库-api)
  - [语音 API](#语音-api)
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
  "player_name": "小白",
  "locale": "zh-CN"
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
  "player_message": "你好，小黑！",
  "request_id": "turn-550e8400-001"
}
```

`request_id` 可选，建议由客户端为每次玩家发送生成唯一值。同一会话使用相同 `request_id` 重试时会返回已完成的同一结果，不会重复写入消息或执行事件。服务端不会用消息内容区分同一 ID，客户端不得把已使用的 ID 分配给另一条逻辑消息。

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
  "event_notification": "解锁新话题：童年回忆",
  "knowledge_sources": [
    {
      "knowledge_base_id": "kb-uuid",
      "knowledge_base_name": "世界设定",
      "document_id": "doc-uuid",
      "document_name": "地理.md",
      "chunk_id": "chunk-uuid",
      "excerpt": "北境终年积雪……",
      "similarity": 0.81
    }
  ]
}
```

`knowledge_sources` 只包含当前用户已授权绑定且实际注入本轮 Prompt 的来源；未命中知识时为空数组。

### 3.1 流式发送对话消息

```http
POST /api/v1/dialogue/turn/stream
Accept: text/event-stream
Content-Type: application/json

{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "player_message": "你好，小黑！",
  "request_id": "turn-550e8400-001"
}
```

请求体、鉴权、会话归属和 `request_id` 幂等语义与 `POST /api/v1/dialogue/turn` 相同。响应使用 Server-Sent Events，不需要 WebSocket。每帧格式为：

```text
event: <event_type>
data: <紧凑 JSON>
```

单聊事件顺序和载荷：

| 事件 | 关键字段 | 说明 |
|------|----------|------|
| `turn_started` | `session_id`, `request_id`, `turn_kind` | 流已被工作器接管；单聊的 `turn_kind` 为 `single` |
| `stage` | `stage` | 当前阶段：`preparation`、`retrieval`、`generation`、`events`、`commit` |
| `character_started` | `stream_id`, `character_id`, `character_name` | 某个角色开始生成 |
| `dialogue_delta` | `stream_id`, `delta` | 经过输出安全流处理的增量对话文本 |
| `character_completed` | `stream_id`, `character_id`, `response` | 角色回复完成，`response` 为该角色的完整结果 |
| `turn_completed` | `response` | 整个轮次完成，`response` 与非流式 REST 端点的最终响应等价 |
| `error` | `detail`, `error_type` | 容量不足或工作器失败；发送后结束流 |

`stream_id` 在同一轮次内关联角色开始、文本增量和角色完成事件。客户端应以 `turn_completed.response` 作为最终权威结果，不要仅用增量文本自行重建状态字段。

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

本节接口均需要登录态。事件定义只属于当前登录用户；创建、更新和注册调度时，非空 `character_id` 必须指向当前用户拥有的角色卡，禁用角色仍可用于维护已有事件。`character_id: null` 或空字符串表示当前用户下的全局事件。

创建、更新和启用/禁用接口会在同一个数据库事务内保存事件定义及其调度状态；任一步失败都不会留下半保存数据。对话或上下文检测中的 once/cooldown 事件使用数据库 claim 保护，并发请求至多一个成功提交记忆、解锁、通知和触发日志。

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
  "is_active": false,
  "character_id": null
}
```

更新请求可包含 `character_id`，其含义和所有权校验与创建事件一致；传 `null` 可把角色专属事件改为全局事件。

更新 `character_id` 或 `schedule` 时，旧调度会与新定义一起原子替换；清空调度会在同一事务中删除旧调度。

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

存在 cron 调度时，启用状态与调度的 `active` / `paused` 状态原子切换。

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

内置模板包括好感度里程碑、信任度里程碑和关键剧情节点。服务启动时会自动初始化模板库。模板库是经过认证访问的全局系统模板；套用模板创建事件时，事件会保存到当前登录用户自己的 `event_definition` 中。

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

该接口仅限系统管理员，用于开发维护共享的系统模板库，不在普通用户前端暴露。

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

该接口仅限系统管理员。删除指定共享模板记录；内置默认模板在服务启动或模板列表自动初始化时可能被重新写入。

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

非空 `character_id` 必须是当前用户拥有的角色卡；`player_id` 必须等于当前登录用户 ID。

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

用于后台任务或调试入口。会检查已注册且到期的调度事件，执行事件效果和事件链，并更新下一次执行时间。若事件链规划失败，本次 cron 不会推进；接口记录失败信息并保留当前到期时间，修复事件配置后可再次执行。

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

### 14. 查询与控制事件调度

```http
GET  /api/v1/admin/event-schedules?event_id=&status=&limit=200
POST /api/v1/admin/event-schedules/{event_id}/{character_id}/pause
POST /api/v1/admin/event-schedules/{event_id}/{character_id}/resume
```

`status` 只支持 `active` 或 `paused`，`limit` 最大按 1000 处理。暂停会清除当前租约；恢复会按玩家世界时钟和 cron 表达式重新计算 `next_run_at`。

### 15. 查询事件执行指标与历史

```http
GET /api/v1/admin/event-metrics?event_id=
GET /api/v1/admin/events/{event_id}/executions?limit=100
```

指标接口可按事件过滤，返回执行总数、成功/失败/跳过数量、去重数量和耗时统计。执行历史包含 `execution_id`、幂等键、触发来源、状态、效果、结果、错误、耗时和完成时间。

### 16. 模拟事件

```http
POST /api/v1/admin/events/{event_id}/simulate
Content-Type: application/json

{
  "character_id": "npc_luo_xiaohei",
  "session_id": "simulation-session",
  "player_message": "我找到了线索",
  "current_affinity": 35,
  "current_trust": 20,
  "current_mood": "警觉",
  "dialogue_count": 8,
  "event_data": {
    "chapter": "investigation"
  }
}
```

该端点用于事件编辑器和调试工具进行 dry-run：

1. 读取当前用户的事件定义与已有 `event_context_state`。
2. 用请求覆盖值构造模拟上下文并调用事件条件评估。
3. 条件匹配时只调用事件规划，返回计划结果。
4. 不提交事件效果，不写入触发历史、执行记录、记忆、通知、关系、剧情状态或群聊消息。

角色专属事件可省略 `character_id` 并使用事件绑定角色；模拟全局事件时必须显式提供当前用户拥有的 `character_id`。

可选上下文字段包括：

| 字段 | 说明 |
|------|------|
| `session_id` | 模拟会话 ID；省略时使用内部模拟 ID |
| `player_message`, `npc_response` | 本轮玩家与 NPC 文本 |
| `current_affinity`, `current_trust`, `current_mood` | 当前运行状态；数值省略时默认为 0，情绪默认为 `neutral` |
| `previous_affinity`, `previous_trust` | 变化前状态 |
| `affinity_delta`, `trust_delta` | 本轮关系变化 |
| `dialogue_count`, `total_dialogue_count` | 会话内和累计对话计数 |
| `session_duration_minutes` | 会话持续时间 |
| `unlocked_content` | 已解锁内容列表 |
| `character_relationships` | 角色关系上下文 |
| `event_history` | 用于条件判断的事件历史 |
| `world_time` | ISO 8601 世界时间 |
| `event_data` | 与已持久化事件上下文合并的附加数据 |

**响应示例（字段节选）：**

```json
{
  "matched": true,
  "evaluation": {
    "event_id": "evt_story_clue",
    "event_name": "发现剧情线索",
    "active": true,
    "cooldown_passed": true,
    "matched": true,
    "condition": {
      "trigger_type": "keyword_match",
      "matched": true,
      "config": {
        "trigger_type": "keyword_match",
        "keywords": ["线索"],
        "match_mode": "any"
      },
      "children": []
    }
  },
  "context": {
    "character_id": "npc_luo_xiaohei",
    "player_id": "player_001",
    "trigger_source": "simulation"
  },
  "planned_result": {
    "execution_id": "generated-execution-id",
    "execution_key": "simulation:evt_story_clue",
    "event_id": "evt_story_clue",
    "event_name": "发现剧情线索",
    "character_id": "npc_luo_xiaohei",
    "triggered": true,
    "status": "succeeded",
    "effects": [],
    "effects_applied": []
  }
}
```

实际响应中的 `context` 是完整序列化的事件上下文，`planned_result` 是完整序列化的 `EventTriggerResult`；上例仅展示常用字段。未匹配时 `planned_result` 为 `null`。这里的 `status` 描述规划结果，模拟端点仍不会提交任何效果。

---

## 剧情状态 API

### 1. 获取剧情投影状态

```http
GET /api/v1/stories/{story_id}/state
```

返回当前登录用户指定剧情的事件账本投影。剧情不存在时返回 404。

**响应示例：**

```json
{
  "owner_user_id": "player_001",
  "story_id": "story_main",
  "status": "active",
  "progress": 0.4,
  "terminal_reason": null,
  "ledger_version": 3,
  "started_at": "2026-07-15T08:00:00+00:00",
  "updated_at": "2026-07-15T08:30:00+00:00",
  "completed_at": null,
  "failed_at": null
}
```

`status` 为 `active`、`completed` 或 `failed`；`progress` 的范围为 0 到 1。

---

## 角色关系 API

本节接口均需要登录态，且只读写当前登录用户的角色关系。相同角色 ID 组合可以在不同用户下保存不同关系。

关系图谱是单聊和多角色对话中角色间关系的最高优先级来源。创建、更新、删除关系都会刷新该角色对的图谱修订时间；后续单聊、多角色生成和主动互动会过滤修订时间之前的关系相关长期记忆、角色间共享记忆和群体记忆，但会保留普通玩家事实、共同经历和世界事实。跨 session 原始群聊历史与群聊结束摘要提取仍按修订时间截止，避免旧关系状态覆盖当前图谱。删除关系后，当前图谱中缺失的边会被视为“未定义关系”，不会从旧记忆中恢复。

关系两端都必须是当前用户拥有的角色卡；禁用角色仍可维护关系。接口拒绝角色与自身建立关系（400）。重复创建返回 409，删除不存在的关系返回 404。

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

批量接口逐条尝试创建并返回每项结果。自关系、未知/他人角色和已存在关系计为失败，不会覆盖已有关系；至少一项写入成功时顶层 `success` 才为 true。

---

## 多角色对话 API

多角色会话至少需要 2 个不重复 NPC。公开创建 API 当前没有参与人数上限，也没有运行时添加/移除参与者的公开端点；参与者集合由创建或续聊时的 session 固定。

单聊和多角色对话每轮都会读取当前用户的角色关系图谱。Prompt 明确要求模型以当前图谱为准：图谱中存在的关系覆盖角色卡背景、旧记忆和历史发言，图谱中不存在的关系边表示未定义关系。关系类型按用户保存的自定义文本原样呈现，不限制固定枚举；`affinity` 作为中性的关系强度呈现，具体含义以关系类型和说明为准。

编排器还会根据关系图谱最近修订时间过滤旧上下文：长期记忆、共享记忆和群体记忆只剔除修订前的关系相关事实，非关系事实继续保留；跨 session 原始群聊历史按修订时间截止，不能推翻当前图谱。同一会话中如果已经产生了与当前图谱冲突的关系发言，例如图谱已改为某个自定义关系但历史回复仍说师徒，该发言会在送入 LLM 前跳过，避免错误历史继续强化。

每个群聊都有稳定的逻辑 `group_thread_id`。结束后继续群聊会在同一逻辑线程下创建新的物理 session，因此历史、知识绑定、自主状态和未读通知都跨 session 延续。已结束且没有 active session 的线程需要接收脉冲时，运行时会自动创建一个 active carrier session。

玩家轮次与群聊脉冲是两条不同执行路径：

- **玩家轮次**：`max_responses` 接受 1-5；编排器继续受参与人数和内部上限约束，当前最多提交 3 个角色回复。
- **普通自主脉冲**：世界时钟不能暂停；距离上次脉冲至少经过 2 个现实分钟和 20 个世界分钟；当天自主消息数未达到 24；至少有 2 个 active 参与者；并且存在未解决话题钩子、角色目标，或群聊未等待玩家且有当前主题。
- **事件脉冲**：由 `npc_proactive_dialogue` 等事件效果触发，绕过普通脉冲的现实/世界冷却和每日预算，但仍受本次消息上限约束。
- **本次消息上限**：当前普通和事件脉冲都最多生成并提交 1 条角色消息，不等同于玩家轮次的 `max_responses`。

普通脉冲通过 lease/claim 防止多个调度器并发重复生成。提交时，角色消息、临时回复引用修正、关系、参与者统计、脉冲状态和线程级未读通知位于同一事务中；失败时整体不可见。运行时还会抑制重复回复。长期记忆提取在提交后以 best effort 执行，不影响已经提交的消息与通知。

### 1. 开始多角色会话
```http
POST /api/v1/multi-dialogue/session/start
Content-Type: application/json

{
  "player_id": "player_001",
  "player_name": "旅行者",
  "group_name": "森林小队",
  "character_ids": ["npc_luo_xiaohei", "npc_wuxian"],
  "locale": "zh-CN"
}
```

**参数说明：**
- `player_id`: 玩家ID
- `player_name`: 玩家显示名称
- `group_name` (可选): 群聊名称，会写入会话列表
- `character_ids`: 参与角色 ID 列表（至少 2 个且不得重复，公开 API 当前没有上限）；不存在、属于其他用户或已禁用的角色都会被拒绝
- `locale` (可选): `zh-CN` 或 `en-US`，默认 `zh-CN`；持久化后控制整个群聊线程的输出和语音语言

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
  "max_responses": 3,
  "request_id": "group-turn-001"
}
```

每次玩家发起的多角色轮次会保存玩家消息和角色回复。群聊结束且有效消息数大于 6 条、摘要模型返回非空内容时，系统会将整场对话统一摘要写入 `session_summary`，并同步保存到 `group_memory` 作为群聊会话记忆；后续多角色 Prompt 会召回这些群体记忆，帮助参与角色延续共同经历。若群聊期间关系图谱被修改或删除，结束摘要和角色间印象提取只处理图谱修订时间之后的消息，避免旧关系被重新萃取。

`request_id` 与单聊语义一致：可选，同一会话内用于安全重试和去重。相同 ID 的已完成请求返回原结果，不会再次生成角色回复或重复提交群聊副作用。

根据讨论触发条件，响应可能是单角色回复，也可能是多角色连续讨论回复。`discussion_mode` 默认启用；`max_responses` 可传 1-5，但编排器会结合语境、参与人数和内部上限动态决定实际接话人数，当前最多 3 个角色发言。讨论模式下返回结构包含 `responses` 数组，每个元素对应一个角色发言。发送轮次前会重新校验全部会话参与者；任一参与角色卡不存在或被禁用时返回 400，避免以不完整参与者集合继续生成。

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
  "current_mood": "平静",
  "knowledge_sources": []
}
```

`affinity_delta` 和 `trust_delta` 表示本次新回复造成的关系变化。Web 前端只在当前会话中新生成的回复旁展示这些变化；从历史接口加载的旧消息不会再次显示好感度/信任度变化提示。

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

### 2.1 流式发送多角色消息

```http
POST /api/v1/multi-dialogue/turn/stream
Accept: text/event-stream
Content-Type: application/json

{
  "session_id": "multi-session-uuid",
  "player_message": "大家怎么看？",
  "discussion_mode": true,
  "max_responses": 3,
  "request_id": "group-turn-001"
}
```

请求体和幂等语义与 `POST /api/v1/multi-dialogue/turn` 相同，SSE 帧格式与单聊流式端点相同。当前多角色流会发送：

- `turn_started`：`turn_kind` 为 `multi`
- 每个实际发言角色各自的 `character_started`、`dialogue_delta`、`character_completed`
- `turn_completed`：`response` 与非流式端点等价；讨论模式为包含 `responses` 的群体响应
- `error`：返回安全错误详情后结束流

多角色流当前不发送显式 `stage` 事件。多个角色的增量可能通过不同 `stream_id` 区分，客户端应分别渲染，并以 `turn_completed.response` 对齐最终消息 ID、事件结果和状态变化。

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

留空 `trigger_character_id` 则自动选择一个角色。

互动只允许在 `active` 会话中触发。指定 `trigger_character_id` 时，该角色必须是当前会话的活跃参与者；会话中任一参与角色卡不存在或被禁用时请求会被拒绝。

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
GET /api/v1/multi-dialogue/history/{session_id}?offset=0&limit=50
```

该接口以 `session_id` 定位群聊，但读取的是其 `group_thread_id` 对应的完整逻辑线程，因此续聊产生的新 session 仍能读取前序消息。

**查询参数：**

| 参数 | 必需 | 说明 |
|------|------|------|
| `offset` | 否 | 已加载消息数，默认 0；用于向前分页 |
| `limit` | 否 | 返回数量，默认 50，范围 1-200 |
| `after_message_id` | 否 | 只返回该稳定消息 ID 之后的新消息；提供时忽略 `offset` |

**响应示例：**
```json
{
  "messages": [
    {
      "role": "assistant",
      "content": "[好奇地看着周围]哇，这里好多人呀！",
      "message_id": 101,
      "character_id": "npc_luo_xiaohei",
      "character_name": "小黑",
      "created_at": "2026-07-02T10:00:00Z"
    },
    {
      "role": "user",
      "content": "大家好！",
      "message_id": 102,
      "character_id": null,
      "character_name": null,
      "created_at": "2026-07-02T10:01:00Z"
    },
    {
      "role": "assistant",
      "content": "[微笑]你好，欢迎。",
      "message_id": 103,
      "character_id": "npc_wuxian",
      "character_name": "无限",
      "created_at": "2026-07-02T10:02:00Z"
    }
  ],
  "has_more": false,
  "latest_message_id": 103,
  "session_info": {
    "session_id": "multi-session-uuid",
    "current_session_id": "multi-session-uuid",
    "group_thread_id": "group-thread-uuid",
    "player_name": "旅行者",
    "created_at": "2026-07-02T10:00:00Z",
    "status": "active",
    "participants": [...]
  }
}
```

### 5.1 标记逻辑群聊线程已读

```http
POST /api/v1/multi-dialogue/thread/{group_thread_id}/read
```

客户端完成该逻辑线程的历史或增量消息同步后调用。接口验证线程属于当前用户，并一次性清除该线程由自主/事件脉冲创建的聚合未读通知。

**响应示例：**

```json
{
  "group_thread_id": "group-thread-uuid",
  "marked_read": 2
}
```

`marked_read` 是本次实际标记为已读的通知数量。

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

继续会话前会校验原参与者仍存在且全部启用；否则返回 400。

---

## 知识库 API

前缀为 `/api/v1/knowledge`，本节全部接口都需要登录态，只能访问当前用户拥有的知识库、文档和绑定目标。

知识库绑定支持：

- `global`：对当前用户所有单聊和群聊生效，`target_id` 为空字符串
- `character`：对指定角色的单聊，以及该角色在群聊中生成回复时生效
- `group_thread`：仅对指定逻辑群聊线程生效

### 1. 知识库 CRUD

```http
GET    /api/v1/knowledge/bases
POST   /api/v1/knowledge/bases
GET    /api/v1/knowledge/bases/{knowledge_base_id}
PUT    /api/v1/knowledge/bases/{knowledge_base_id}
PATCH  /api/v1/knowledge/bases/{knowledge_base_id}/enabled
DELETE /api/v1/knowledge/bases/{knowledge_base_id}
```

创建请求：

```json
{
  "name": "北境世界观",
  "description": "地理、历史和势力设定"
}
```

启用状态请求：

```json
{
  "is_enabled": true
}
```

详情响应包含 `bindings` 和 `documents`。删除知识库会同时删除其绑定、文档记录、文本块、向量和知识目录内的原文件。

### 2. 设置绑定与查询绑定目标

```http
PUT /api/v1/knowledge/bases/{knowledge_base_id}/bindings
GET /api/v1/knowledge/binding-targets
```

设置绑定会整体替换该知识库现有绑定：

```json
{
  "bindings": [
    {"target_type": "global", "target_id": ""},
    {"target_type": "character", "target_id": "npc_luo_xiaohei"},
    {"target_type": "group_thread", "target_id": "thread-uuid"}
  ]
}
```

角色和群聊线程目标必须属于当前用户。`binding-targets` 返回可选角色与逻辑群聊线程。

### 3. 查询文档

```http
GET /api/v1/knowledge/bases/{knowledge_base_id}/documents
```

文档状态：

| 状态 | 含义 |
|------|------|
| `queued` | 已保存，等待后台任务接管 |
| `processing` | 正在提取、切块和写入向量 |
| `ready` | 可用于检索 |
| `failed` | 处理失败，`error_message` 包含原因 |

### 4. 上传文件

```http
POST /api/v1/knowledge/bases/{knowledge_base_id}/documents/upload
Content-Type: multipart/form-data

file=@world.md
```

支持 UTF-8 TXT、Markdown、PDF 和 DOCX，最大 10 MiB。PDF 最多 300 页且暂不支持无文本 OCR 扫描件；提取文本最多 1,000,000 字符。成功返回 202 和初始文档记录，后台异步处理。

### 5. 粘贴文本

```http
POST /api/v1/knowledge/bases/{knowledge_base_id}/documents/paste
Content-Type: application/json

{
  "title": "王国年表",
  "text": "帝国历 417 年……"
}
```

成功返回 202。新记录的 `source_type` 为 `pasted_text`。

### 6. 删除或重试文档

```http
DELETE /api/v1/knowledge/documents/{document_id}
POST   /api/v1/knowledge/documents/{document_id}/retry
```

删除会清理数据库文本块、向量和原文件。重试只适用于终态文档；`queued` 或 `processing` 文档返回 409。重试成功返回 202 并将状态重新设为 `queued`。

### 7. 检索预览

```http
POST /api/v1/knowledge/preview
Content-Type: application/json

{
  "query": "北境首都在哪里？",
  "character_id": "npc_luo_xiaohei",
  "group_thread_id": null,
  "knowledge_base_id": "kb-uuid"
}
```

`query` 最长 4000 字符。指定 `knowledge_base_id` 时只预览该知识库；否则按全局、角色和群聊线程绑定检索。响应返回实际查询文本及最多 4 个来源：

```json
{
  "query_text": "北境首都在哪里？",
  "sources": [
    {
      "knowledge_base_id": "kb-uuid",
      "knowledge_base_name": "北境世界观",
      "document_id": "doc-uuid",
      "document_name": "地理.md",
      "chunk_id": "chunk-uuid",
      "excerpt": "北境首都是白塔城……",
      "similarity": 0.79,
      "vector_similarity": 0.79,
      "keyword_score": 0.85,
      "hybrid_score": 0.91,
      "source_metadata": {
        "heading_path": ["北境地理", "首都"]
      }
    }
  ]
}
```

`similarity` 保留为向量相似度兼容字段；`vector_similarity`、`keyword_score` 和 `hybrid_score` 分别表示向量通道、词法通道和最终综合排序分数。新前端优先展示 `hybrid_score`，旧响应缺少该字段时才回退到词法或向量分数。

Web 管理页在重复提交、切换知识库、关闭弹窗或组件卸载时会取消上一条预览请求，并忽略已过期响应，避免旧结果覆盖当前查询。仓库内 Web API 客户端可通过标准 `AbortSignal` 传递取消信号。

上传和粘贴文档后，前端会对选中知识库中的 `queued/processing` 文档轮询详情。服务启动也会恢复排队中或被中断的任务；处理异常会落为 `failed`，不会永久停留在“处理中”。

---

## 语音 API

本节接口均需要登录态。TTS 使用 `SPEECH_TTS_*` 配置，STT 使用独立的 `SPEECH_STT_*` 配置；对应服务未配置时返回 503。会话必须属于当前用户，且 `mode` 必须与单聊/群聊类型一致。

### 1. 语音转写

```http
POST /api/v1/speech/transcriptions
Content-Type: multipart/form-data

session_id=<session-id>
mode=single
file=@recording.webm
```

`mode` 支持 `single` / `group`。支持 MP3、MP4、MPEG、MPGA、M4A、WAV 和 WebM，转写语言取自会话 `locale`。

```json
{
  "text": "转写后的文本",
  "locale": "zh-CN"
}
```

### 2. 获取消息语音

```http
GET /api/v1/speech/single/sessions/{session_id}/messages/{message_id}/audio
GET /api/v1/speech/group/sessions/{session_id}/messages/{message_id}/audio
```

仅 assistant/角色消息可合成。缓存命中时直接返回已缓存的音频文件；未命中时以流式响应立即转发首段音频，并在生成完成后原子写入缓存。默认格式为 MP3，响应包含私有缓存、ETag、`X-Speech-Cache` 和 `X-AI-Generated-Audio` 响应头；生成文件缓存到 `SPEECH_STORAGE_PATH`。

### 3. 语音能力配置

```http
GET /api/v1/speech/configuration
```

返回当前部署的 TTS 厂商显示名称、可用内置音色、默认音色，以及是否支持自定义音色。前端应以此结果渲染语音设置，不应硬编码厂商或音色列表。

### 4. 角色声音

```http
GET    /api/v1/admin/characters/{character_id}/voice
POST   /api/v1/admin/characters/{character_id}/voice/consent
POST   /api/v1/admin/characters/{character_id}/voice
DELETE /api/v1/admin/characters/{character_id}/voice
```

授权接口使用 multipart 字段 `locale`、`recording` 和可选 `name`；创建接口使用 `audio_sample`、必填 `reference_transcript` 和可选 `name`。授权录音是创建自定义音色的前置条件，参考音频及其逐字文本会提交给 TTS 厂商完成复刻。自定义声音只对当前用户拥有的角色生效；供应商账户不支持 Custom Voices 时，角色仍可使用角色卡中的内置声音。

---

## 用户 API

用户接口用于 Web 前端登录态、账户资料、玩家角色卡、语音偏好、世界时钟和头像管理。登录成功后服务端会写入 `memoria-token` HttpOnly Cookie，响应体不返回原始 token；通用 API 客户端支持 Bearer、查询参数或 Cookie，仓库内 Web 前端只使用 Cookie。

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

用户名长度 2-20，只能包含字母、数字、中文、下划线和连字符。密码至少 8 位，且必须包含字母和数字。普通注册始终创建普通用户。仅部署者初始化管理员时额外提交可选字段 `admin_bootstrap_token`，其值必须与服务端 `ADMIN_BOOTSTRAP_TOKEN` 一致；该名额只能使用一次。

**初始化管理员请求：**

```json
{
  "username": "admin",
  "password": "replace-with-a-strong-password1",
  "gender": "unknown",
  "admin_bootstrap_token": "the-deployment-bootstrap-secret"
}
```

| 场景 | 状态码 | 说明 |
|------|--------|------|
| 普通注册或首次有效管理员初始化 | 200 | 写入登录 Cookie 并返回用户资料 |
| 初始化凭据无效或服务未配置 | 403 | 不访问用户创建流程 |
| 管理员名额已占用或已有管理员 | 409 | 不创建新用户 |
| 用户名已存在 | 409 | 不覆盖现有用户 |

**响应示例：**
```json
{
  "user": {
    "user_id": "usr_ab12cd34",
    "username": "旅行者",
    "is_admin": false,
    "gender": "unknown",
    "avatar_url": null
  }
}
```

登录态通过响应中的 `memoria-token` HttpOnly Cookie 建立，响应体不返回原始 token。Cookie 默认有效 30 天，使用 `HttpOnly`、`SameSite=Lax` 和根路径；HTTPS 部署必须设置 `AUTH_COOKIE_SECURE=true`。

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

### 8. 更新语音偏好

```http
PUT /api/v1/user/speech-settings
Content-Type: application/json

{
  "tts_auto_play": true,
  "stt_auto_send": false
}
```

响应为更新后的用户资料。`tts_auto_play` 控制角色消息自动播放，`stt_auto_send` 控制录音转写后是否自动发送。

### 9. 获取玩家角色卡

```http
GET /api/v1/user/character-card
```

首次读取会为当前用户创建默认玩家角色卡。响应包含稳定的关系图节点 ID `node_id`，以及 `display_name`、`avatar_url`、`gender`、`pronouns`、`age`、`species`、`occupation`、`appearance`、`personality`、`background` 和 `goals`。

### 10. 更新玩家角色卡

```http
PUT /api/v1/user/character-card
Content-Type: application/json

{
  "display_name": "旅行者",
  "gender": "unknown",
  "pronouns": "TA",
  "age": 24,
  "species": "人类",
  "occupation": "调查员",
  "appearance": "常穿深色旅行外套",
  "personality": "冷静、好奇",
  "background": "正在追查一段失落的历史",
  "goals": "找到真相并保护同伴"
}
```

所有字段均可选，只更新请求中出现的字段。保存后的玩家角色卡从下一条单聊或群聊消息开始进入 Prompt，并作为玩家节点参与关系图。

### 11. 上传玩家角色卡头像

```http
POST /api/v1/user/character-card/avatar/upload
Content-Type: multipart/form-data

file=@persona.png
```

支持 PNG / JPEG / GIF / WebP，上传大小上限为 8 MB；响应为更新后的完整玩家角色卡。

### 12. 通过 URL 设置玩家角色卡头像

```http
POST /api/v1/user/character-card/avatar/url
Content-Type: application/json

{
  "url": "https://example.com/persona.png"
}
```

服务端会下载并校验图片后保存为 data URL。传空字符串会清除玩家角色卡头像。

### 13. 获取或更新世界时钟

```http
GET /api/v1/user/world-clock
PUT /api/v1/user/world-clock
```

更新请求必须带当前 `expected_revision`，其余字段可选；`timezone` 必须是有效 IANA 时区，`timezone_mode` 支持 `fixed` / `device`，`time_scale` 只允许 `0`、`1`、`2`、`5`、`10`，其中 `0` 表示暂停。修订号不匹配时返回 409，避免多个页面覆盖彼此的时钟修改。

```json
{
  "expected_revision": 3,
  "timezone": "Asia/Shanghai",
  "timezone_mode": "device",
  "time_scale": 2
}
```

响应包含 `world_now`、`real_now`、`timezone`、`timezone_mode`、`time_scale`、`paused`、`clock_revision`、`real_offset_seconds` 和最近待执行事件 `next_event`。Web 客户端只接受不低于当前本地 `clock_revision` 的响应，因此较旧的 GET 即使晚于更新请求返回，也不会覆盖新的时钟状态。

### 14. 修改世界时间

```http
POST /api/v1/user/world-clock/sync
POST /api/v1/user/world-clock/set
POST /api/v1/user/world-clock/advance
```

三个接口都必须提交 `expected_revision`。`sync` 保留当前时区和倍率，把世界时间锚点重置为当前真实 UTC 时间；`set` 额外提交 ISO 8601 `world_now`；`advance` 提交正整数 `seconds`，上限为 366 天。

### 15. 查询事件收件箱

```http
GET /api/v1/user/event-inbox?unread_only=true&limit=50
```

`limit` 范围为 1-100。通知包含来源事件/角色/会话、内容、世界创建时间、真实创建时间和 `read_at`。

### 16. 标记事件通知已读

```http
POST /api/v1/user/event-inbox/{inbox_id}/read
```

只能操作当前用户自己的通知；记录不存在时返回 404。

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

仅用于检测应用进程是否存活，常用于 Kubernetes / Docker liveness 探针；不检查数据库可访问性。

```http
GET /health
```

**响应示例：**
```json
{
  "status": "ok",
  "version": "0.5.0"
}
```

---

### 2. 就绪检查（Readiness Check）

用于检查数据库是否可访问。当数据库不可用时返回 503。

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
  "database": "unavailable"
}
```

具体数据库异常只写入服务端日志，不返回给客户端。

---

### 3. 动态调整日志级别

系统管理员无需重启服务即可动态修改全局日志级别。普通登录用户会收到 403。

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

所有 `/api/*` 写操作（非 GET/HEAD/OPTIONS）均受速率限制保护。服务端优先使用认证 token 解析出的用户 ID 作为限流 key，未登录或 token 无效时退回客户端 IP；不会信任客户端传入的 `X-Player-ID`。反向代理部署必须配置 Uvicorn 的可信代理地址，使 `request.client.host` 来自受信任的转发链。计数器使用单调时钟和线程锁，并周期清理过期 key。

| 项目       | 值                    |
|------------|-----------------------|
| 窗口大小   | 60 秒                 |
| 最大请求数 | 60 次 / 窗口          |
| 识别方式   | 登录用户 ID           |
| 兜底策略   | 未登录则使用客户端 IP |
| 超限响应码 | HTTP 429             |

当前限流器保存在单个应用进程内；多 worker 或多实例部署不会共享额度，生产环境需要外部集中式限流器才能获得全局配额。

Docker Compose 默认设置 `FORWARDED_ALLOW_IPS=*`，仅适用于后端端口不直接暴露公网的内置 Nginx 拓扑。若设置 `API_BIND_HOST=0.0.0.0` 直接开放后端端口，必须将 `FORWARDED_ALLOW_IPS` 收紧到实际可信代理 IP 或网段。

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
| `item_acquired` | 获得物品（枚举保留，检测尚未实现）|
| `quest_completed` | 完成任务（枚举保留，检测尚未实现）|
| `relationship_change` | 关系变化（枚举保留，检测尚未实现）|
| `mood_match` | 情绪匹配 |
| `npc_keyword_match` | NPC 回复关键词匹配 |
| `state_delta` | 本轮好感度或信任度变化量 |
| `event_history` | 已提交事件历史及状态 |
| `world_time_window` | 玩家世界时间窗口与星期 |
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
| `grant_item` | 给予物品（枚举保留，执行尚未实现）|
| `start_quest` | 开启任务（枚举保留，执行尚未实现）|
| `modify_relationship` | 修改角色间关系（枚举保留，执行尚未实现）|
| `trigger_event` | 触发另一个事件（事件链）|
| `branch_event` | 按上下文分支触发事件 |
| `npc_proactive_dialogue` | NPC 主动发言（多角色编排器）|
| `update_event_progress` | 更新多阶段事件的进度或状态 |

---
