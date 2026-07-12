# 知识库注入 RAG 设计方案

## 背景

Memoria 现有长期记忆链路已经支持 RAG：角色与玩家的长期记忆写入 `long_term_fact`，同步到 ChromaDB 的 `long_term_memory` collection，并在对话时按玩家消息检索后注入 prompt。

当前多角色记忆链路还包含关系图谱修订过滤：角色关系图谱创建、更新或删除后，系统会用该角色对的最新修订时间过滤修订前的旧关系事实；普通长期记忆、共同经历和世界事实不会被自动清空。跨 session 原始群聊历史和结束摘要提取仍按修订时间截止，避免旧关系被重新萃取；同一会话中后续产生的错误关系发言若与当前图谱冲突，也会在送入 LLM 前跳过。世界观知识库属于外部设定资料，不应写入 `known_player_facts`；如果世界知识与当前关系图谱冲突，多角色行为仍应以当前关系图谱为准。

世界观知识库与长期记忆的语义不同：

- 长期记忆描述角色对玩家的认识，属于关系状态的一部分。
- 世界观知识描述外部设定、地点、组织、规则、历史、人物资料，属于角色可参考的客观资料。
- 有些世界观应被多个角色共享，例如同一城市、组织、剧情背景。
- 有些世界观只能给单个角色使用，例如角色私密情报、个人档案、只对某角色开放的隐藏设定。

因此知识库不能简单做成“全局文档”或“角色字段”，需要显式的可见范围与授权模型。

## 目标

1. 支持角色在对话中引用外部世界观文档，并通过 RAG 按当前上下文检索。
2. 支持单角色私有知识、多角色共享知识、用户全局知识、群聊可用知识。
3. 知识库与长期记忆隔离，避免世界设定污染 `known_player_facts`。
4. 单聊与群聊使用同一套知识可见性规则。
5. 第一版保持实现可控：支持 `.txt` / `.md` / 手动文本，不引入 PDF、网页抓取或知识图谱。

## 非目标

第一版不实现：

- 自动网页爬取。
- PDF / Word 复杂解析。
- 自动知识冲突检测。
- 知识图谱推理。
- 对外公开知识库市场。
- 让 LLM 自动永久修改知识库。

## 核心概念

### 知识文档

一份原始世界观资料，例如：

- 城市设定《兰泽城概览》
- 组织设定《星火会内部规章》
- 角色私密资料《万吉吉隐藏经历》
- 剧情设定《第一章事件线索》

### 知识分块

文档切分后的 RAG 检索单元。分块用于向量检索和 prompt 注入。

### 知识作用域

作用域表示这份知识允许被谁检索到。第一版支持以下类型：

| 作用域 | 含义 | 示例 |
| --- | --- | --- |
| `global` | 当前用户下所有角色可用 | 通用世界地图、通用货币体系 |
| `character` | 仅指定单个角色可用 | 某角色私密背景、专属口供 |
| `character_group` | 指定多个角色共享 | 同一组织成员共知资料 |
| `session` | 指定会话可用 | 某次群聊临时导入的调查资料 |

### 知识授权

授权表示文档与角色/会话的可见关系。共享不是复制文档，而是给多个目标授予可见权。

## 数据模型

### knowledge_document

保存文档元信息。

```sql
CREATE TABLE IF NOT EXISTS knowledge_document (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id   TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    source_type     TEXT NOT NULL DEFAULT 'manual',
    source_path     TEXT,
    content_hash    TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

说明：

- `owner_user_id` 用于租户隔离。
- `content_hash` 用于避免重复 reindex。
- 文档本体可以第一版直接存在 chunk 表，也可以后续加 `raw_content` 字段。若文档较大，建议只保存 chunk。

### knowledge_chunk

保存切分后的检索单元。

```sql
CREATE TABLE IF NOT EXISTS knowledge_chunk (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL,
    owner_user_id   TEXT NOT NULL,
    title           TEXT NOT NULL,
    chunk_text      TEXT NOT NULL,
    chunk_index     INTEGER NOT NULL,
    token_count     INTEGER DEFAULT 0,
    metadata_json   TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES knowledge_document(id) ON DELETE CASCADE
);
```

### knowledge_grant

保存知识可见范围。

```sql
CREATE TABLE IF NOT EXISTS knowledge_grant (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL,
    owner_user_id   TEXT NOT NULL,
    scope_type      TEXT NOT NULL,
    target_id       TEXT,
    created_at      TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES knowledge_document(id) ON DELETE CASCADE,
    UNIQUE(document_id, scope_type, target_id)
);
```

字段解释：

- `scope_type = 'global'` 时，`target_id = NULL`。
- `scope_type = 'character'` 时，`target_id = character_id`。
- `scope_type = 'character_group'` 时，`target_id = group_id`。
- `scope_type = 'session'` 时，`target_id = session_id`。

### character_knowledge_group

保存多角色共享知识组。

```sql
CREATE TABLE IF NOT EXISTS character_knowledge_group (
    id              TEXT PRIMARY KEY,
    owner_user_id   TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);
```

### character_knowledge_group_member

保存共享组成员。

```sql
CREATE TABLE IF NOT EXISTS character_knowledge_group_member (
    group_id        TEXT NOT NULL,
    owner_user_id   TEXT NOT NULL,
    character_id    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    PRIMARY KEY(group_id, character_id)
);
```

设计理由：

- 一份文档可以授权给多个角色，也可以授权给一个共享组。
- 多角色共享世界观通过 group 管理，不需要给每个角色复制文档。
- 单角色私有知识仍然用同一张 `knowledge_grant` 表表达，逻辑统一。

## 向量索引

新增 ChromaDB collection：

```text
world_knowledge
```

向量 ID：

```text
knowledge::{chunk_id}
```

metadata：

```json
{
  "owner_user_id": "user_001",
  "document_id": 12,
  "chunk_id": 88,
  "title": "兰泽城概览",
  "chunk_index": 3
}
```

注意：Chroma metadata 不负责完整权限判断。权限判断以 SQLite/PostgreSQL 的 `knowledge_grant` 为准。检索流程先算出可见 `document_id` 集合，再在向量结果中二次过滤，避免仅依赖向量库 where 造成权限漏洞。

## 可见性规则

### 单聊

当前上下文：

```text
owner_user_id = player_id
character_id = 当前角色
session_id = 当前 session
```

可见文档集合：

1. `global` 授权的文档。
2. `character` 授权给当前角色的文档。
3. `character_group` 授权的组中包含当前角色的文档。
4. `session` 授权给当前 session 的文档。

### 群聊

当前上下文：

```text
owner_user_id = player_id
speaker_character_id = 当前发言角色
participant_character_ids = 当前群聊所有角色
session_id = 当前群聊 session
```

每个发言角色检索自己的可见知识：

1. `global` 文档。
2. 授权给当前发言角色的 `character` 文档。
3. 当前发言角色所在 `character_group` 的文档。
4. 授权给当前 session 的文档。

默认不把“其他角色私有文档”给当前发言角色，即使其他角色在同一群聊中。

### 群聊共享资料

如果用户希望某份资料被当前群聊所有参与角色引用，应使用：

- `session` 授权：只在这个群聊会话中可见。
- `character_group` 授权：长期作为某组角色共享知识。

## 检索流程

### 单聊检索

```python
visible_document_ids = repository.get_visible_knowledge_document_ids(
    owner_user_id=player_id,
    character_id=character_id,
    session_id=session_id,
)

chunks = knowledge_base.search_world_knowledge(
    owner_user_id=player_id,
    visible_document_ids=visible_document_ids,
    query_text=player_message,
    top_k=configs.knowledge_search_top_k,
)
```

### 群聊检索

```python
visible_document_ids = repository.get_visible_knowledge_document_ids(
    owner_user_id=player_id,
    character_id=speaker_character_id,
    session_id=session_id,
)

query_text = build_knowledge_query(
    player_message=player_message,
    recent_group_messages=recent_messages,
    speaker_name=speaker_name,
)

chunks = knowledge_base.search_world_knowledge(
    owner_user_id=player_id,
    visible_document_ids=visible_document_ids,
    query_text=query_text,
    top_k=configs.knowledge_search_top_k,
)
```

### 排序策略

第一版排序：

1. 向量相似度。
2. `session` 文档加权，因为它通常与当前剧情最相关。
3. `character` 文档加权，因为它更贴近当前角色。
4. `character_group` 和 `global` 正常排序。

建议权重：

```text
session: +0.08
character: +0.05
character_group: +0.03
global: +0.00
```

最终仍受 `knowledge_max_prompt_chars` 限制。

## Prompt 注入

给 prompt builder 增加可选参数：

```python
world_knowledge: list[dict] | None = None
```

注入位置：角色设定、当前状态、玩家记忆、历史摘要之后；行为规则之前。

建议格式：

```text
# 可参考世界知识
以下是你在当前场景中可以知道并引用的世界设定。只在相关话题中自然使用，不要背诵资料，不要提及“知识库”“检索”“文档片段”。

- 《兰泽城概览》：兰泽城分为上城、河港、旧矿区三个主要区域……
- 《星火会规章》：星火会成员之间以铜星徽记确认身份……
```

冲突处理规则：

```text
如果世界知识与角色卡核心身份冲突，以角色卡为准。
如果世界知识之间互相冲突，优先使用 session 文档，其次 character 文档，其次 character_group 文档，最后 global 文档。
如果问题与世界知识无关，不要强行提及。
```

## 后端模块设计

新增模块：

```text
src/memoria/core/knowledge_base.py
```

职责：

- `chunk_document(text, chunk_size, overlap)`
- `index_document(document_id)`
- `delete_document_vectors(document_id)`
- `reindex_document(document_id)`
- `search_world_knowledge(owner_user_id, visible_document_ids, query_text, top_k)`
- embedding 不可用时 fallback 到数据库关键词查询。

Repository 新增函数：

- `create_knowledge_document(...)`
- `update_knowledge_document(...)`
- `delete_knowledge_document(document_id, owner_user_id)`
- `list_knowledge_documents(owner_user_id, character_id=None, scope_type=None)`
- `replace_knowledge_chunks(document_id, chunks)`
- `set_knowledge_grants(document_id, grants)`
- `get_visible_knowledge_document_ids(owner_user_id, character_id, session_id=None)`
- `create_character_knowledge_group(...)`
- `add_character_to_knowledge_group(...)`
- `remove_character_from_knowledge_group(...)`

## API 设计

新增路由：

```text
src/memoria/api/knowledge_admin.py
```

### 文档管理

```http
GET    /api/v1/admin/knowledge/documents
POST   /api/v1/admin/knowledge/documents
GET    /api/v1/admin/knowledge/documents/{document_id}
PUT    /api/v1/admin/knowledge/documents/{document_id}
DELETE /api/v1/admin/knowledge/documents/{document_id}
POST   /api/v1/admin/knowledge/documents/{document_id}/reindex
```

创建/更新请求示例：

```json
{
  "title": "兰泽城概览",
  "description": "主城公共世界观",
  "content": "兰泽城坐落在……",
  "grants": [
    { "scope_type": "character_group", "target_id": "group_lanze_city" }
  ],
  "is_active": true
}
```

### 共享组管理

```http
GET    /api/v1/admin/knowledge/groups
POST   /api/v1/admin/knowledge/groups
PUT    /api/v1/admin/knowledge/groups/{group_id}
DELETE /api/v1/admin/knowledge/groups/{group_id}
POST   /api/v1/admin/knowledge/groups/{group_id}/members
DELETE /api/v1/admin/knowledge/groups/{group_id}/members/{character_id}
```

### 检索预览

```http
POST /api/v1/admin/knowledge/search-preview
```

请求：

```json
{
  "character_id": "npc_wuxian",
  "session_id": null,
  "query": "兰泽城旧矿区有什么传闻？",
  "top_k": 5
}
```

响应：

```json
{
  "results": [
    {
      "document_id": 12,
      "chunk_id": 88,
      "title": "兰泽城概览",
      "scope_type": "character_group",
      "similarity": 0.82,
      "chunk_text": "旧矿区位于……"
    }
  ]
}
```

## 前端设计

新增知识库管理入口，建议放在角色管理或开发者工具附近。

### 文档列表

显示：

- 标题
- 状态：启用 / 停用
- 作用域：全局 / 单角色 / 共享组 / 会话
- 绑定角色或共享组
- 更新时间
- 操作：编辑、重建索引、停用、删除

### 文档编辑

字段：

- 标题
- 描述
- 正文 textarea，第一版支持 Markdown / 纯文本
- 作用域选择
- 授权目标选择

作用域控件：

- 全局：无需选择角色。
- 单角色：选择一个角色。
- 多角色共享：选择已有共享组，或新建共享组并选择多个角色。
- 会话：选择一个 active 或历史 session，第一版可先放后端 API，前端暂缓。

### 共享组管理

共享组是长期可复用的多角色知识授权对象，例如：

- 兰泽城居民
- 星火会成员
- 第一章调查团

共享组成员变化后，不需要重建文档索引，只影响可见性判断。

### 检索预览

输入：

- 测试角色
- 测试问题

输出：

- 召回 chunk
- 来源文档
- 作用域
- 相似度

用于调试“为什么角色知道/不知道某条设定”。

## 配置项

新增配置：

```python
knowledge_search_top_k: int = 5
knowledge_chunk_size: int = 600
knowledge_chunk_overlap: int = 120
knowledge_max_prompt_chars: int = 2400
knowledge_vector_collection: str = "world_knowledge"
```

## 安全与隔离

必须满足：

1. 所有查询按 `owner_user_id` 过滤。
2. 单聊角色不能检索未授权给自己的单角色私有知识。
3. 群聊发言角色不能因为同场角色拥有私有知识而读取该知识。
4. 停用文档不参与检索。
5. 删除文档时同步删除 chunks 和向量索引。
6. 检索预览也必须走同一套权限规则。

## Fallback 设计

向量库或 embedding 模型不可用时，不能影响正常对话。

fallback 行为：

1. 记录 warning。
2. 在可见文档集合内按 `title LIKE query`、`chunk_text LIKE keyword` 做关键词查询。
3. 最多返回 2-3 条，避免低质量关键词命中污染 prompt。
4. 如果 fallback 也失败，返回空知识，不阻断对话。

## 测试计划

### Repository

- 创建文档并写入 chunks。
- 为文档设置 global 授权。
- 为文档设置单角色授权。
- 为文档设置共享组授权。
- 共享组成员变更后，可见文档集合正确变化。
- 删除文档级联删除 grants/chunks。

### Knowledge Base

- 长文按 overlap 切分。
- 重建索引会删除旧 chunk 向量。
- 检索结果只返回 visible document IDs 中的 chunk。
- embedding disabled 时 fallback 不抛错。

### Orchestrator

- 单聊只注入当前角色可见知识。
- 群聊当前发言者只能看到自己的私有知识和共享知识。
- session 授权知识在指定会话中优先出现。

### Prompt Builder

- 无知识时不出现空段落。
- 有知识时包含标题和片段。
- prompt 中包含禁止暴露知识库机制的规则。

### API

- 用户不能访问其他 owner 的文档。
- 检索预览不能越权。
- 停用文档不会被召回。

## 实施顺序

1. 添加 DB schema 与 repository CRUD。
2. 添加 `knowledge_base.py`，实现 chunk、index、search、fallback。
3. 添加 prompt_builder 的 `world_knowledge` 注入。
4. 接入单聊 orchestrator。
5. 接入多角色 orchestrator，并按当前发言角色检索。
6. 添加 Admin API。
7. 添加前端知识库管理页、共享组管理、检索预览。
8. 补齐测试与文档。

## 第一版建议范围

第一版建议只做：

- 手动创建 / 编辑 `.txt`、`.md` 文档。
- 全局、单角色、多角色共享组三种长期作用域。
- session 作用域先在后端数据模型保留，前端可以第二版再开放。
- 单聊和群聊对话时检索注入。
- 检索预览。
- ChromaDB 向量检索 + SQLite/PostgreSQL 关键词 fallback。

这样可以覆盖“部分世界观多角色共享、部分只能单角色使用”的核心需求，同时不会把第一版复杂度扩散到文件解析、外部抓取或知识冲突管理。
