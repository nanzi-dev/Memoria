<!-- 此文档从 README.md 中提取，作为完整的 API 参考 -->

# Memoria API 文档

## 对话系统 API

前缀: `/api/v1`

### GET /api/v1/characters - 获取角色列表

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

### POST /api/v1/dialogue/session/start - 开始新会话

**请求体：**
```json
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

### POST /api/v1/dialogue/turn - 发送对话消息

**请求体：**
```json
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
  "triggered_events": [],
  "event_notification": null
}
```

### GET /api/v1/dialogue/sessions - 获取会话列表

查询参数: `character_id`, `player_id`

### GET /api/v1/dialogue/history - 获取对话历史

查询参数: `session_id`, `offset` (默认0), `limit` (默认20)

### POST /api/v1/dialogue/session/end - 结束会话

**请求体：**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

### GET /api/v1/dialogue/summaries - 获取会话摘要

查询参数: `character_id` (必需), `player_id` (必需), `limit` (默认5)

---

## 角色卡管理 API

前缀: `/api/v1`

### GET /api/v1/admin/characters - 角色卡列表

查询参数: `only_active` (默认true)

### GET /api/v1/admin/characters/{character_id} - 角色卡详情

### POST /api/v1/admin/characters - 创建角色卡

### PUT /api/v1/admin/characters/{character_id} - 更新角色卡

### DELETE /api/v1/admin/characters/{character_id} - 删除角色卡

查询参数: `permanent` (默认false，软删除)

### POST /api/v1/admin/characters/{character_id}/activate - 激活角色卡

### POST /api/v1/admin/characters/import - 从文件导入

---

## 事件管理 API

前缀: `/api/v1`

### GET /api/v1/admin/events - 事件列表

查询参数: `character_id`, `only_active` (默认true)

### GET /api/v1/admin/events/{event_id} - 事件详情

### POST /api/v1/admin/events - 创建事件

### PUT /api/v1/admin/events/{event_id} - 更新事件

### DELETE /api/v1/admin/events/{event_id} - 删除事件

查询参数: `permanent` (默认true)

### POST /api/v1/admin/events/{event_id}/toggle - 启用/禁用

查询参数: `active` (布尔值)

### GET /api/v1/admin/events/{event_id}/history - 事件触发历史

查询参数: `character_id`, `player_id`, `limit` (默认50)

### GET /api/v1/admin/events/history/all - 全部触发历史

查询参数: `character_id`, `player_id`, `limit` (默认100)

### DELETE /api/v1/admin/events/{event_id}/history - 重置触发记录

查询参数: `character_id` (必填), `player_id` (必填)

---

## 角色关系 API

前缀: `/api/v1`

### POST /api/v1/relationships - 创建关系

### GET /api/v1/relationships/pair/{character_id_a}/{character_id_b} - 查询关系

### PUT /api/v1/relationships/pair/{character_id_a}/{character_id_b} - 更新关系

### DELETE /api/v1/relationships/{character_id_a}/{character_id_b} - 删除关系

### GET /api/v1/relationships/character/{character_id} - 角色的所有关系

### GET /api/v1/relationships/network - 关系网络图谱

### POST /api/v1/relationships/batch - 批量创建关系

---

## 多角色对话 API

前缀: `/api/v1/multi-dialogue`

### POST /api/v1/multi-dialogue/session/start - 创建多角色会话

**请求体：**
```json
{
  "player_id": "player_001",
  "player_name": "旅行者",
  "character_ids": ["npc_luo_xiaohei", "npc_wuxian"],
  "speak_frequencies": {"npc_luo_xiaohei": 1.2, "npc_wuxian": 0.8},
  "strategy_type": "hybrid"
}
```

### POST /api/v1/multi-dialogue/turn - 对话轮次

### POST /api/v1/multi-dialogue/interaction/trigger - 触发角色互动

### GET /api/v1/multi-dialogue/session/{session_id} - 会话信息

### GET /api/v1/multi-dialogue/history/{session_id} - 对话历史

### POST /api/v1/multi-dialogue/participant/add - 添加参与者

### POST /api/v1/multi-dialogue/participant/remove - 移除参与者

### PUT /api/v1/multi-dialogue/participant/update - 更新参与者

### POST /api/v1/multi-dialogue/session/end - 结束会话

---

## 自动生成文档

启动服务后访问：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
