# Memoria 故障排查与 FAQ

## 常见问题

### Q: 启动时提示"模块未找到"

**解决方案：**
```bash
# 确保在项目根目录
cd Memoria
# 确保虚拟环境已激活
source .venv/bin/activate  # Linux/Mac
# 以可编辑模式安装项目和开发依赖
pip install -e ".[dev]"
```

完成可编辑安装后，通常可以直接运行 `uvicorn memoria.main:app`。如果不安装项目，则必须显式把 `src/` 加入模块搜索路径：

```bash
PYTHONPATH=src uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

---

### Q: 首次启动时下载模型缓慢

**原因：** 向量检索功能需要下载 sentence-transformers 模型（约 80MB）。

**解决方案：**

```bash
# 方案 1：等待自动下载完成
# 首次启动会自动下载到 ~/.cache/huggingface/

# 方案 2：手动预下载
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# 方案 3：使用国内镜像
export HF_ENDPOINT=https://hf-mirror.com
PYTHONPATH=src uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

---

### Q: 知识文档一直显示“处理中”

知识文档有四种状态：

- `queued`：已入队，等待后台任务接管
- `processing`：正在提取文本、切块和写入向量
- `ready`：处理完成，可用于检索
- `failed`：处理失败，界面会显示错误原因并提供重试

知识库页面会在选中知识库存在 `queued` 或 `processing` 文档时每 1.5 秒静默刷新详情；浏览器标签页隐藏时暂停轮询，重新可见后继续。后端启动时也会扫描未完成任务：重新执行 `queued` 文档，并恢复上次进程中断遗留的 `processing` 文档。

当前实现会把文本提取、嵌入模型初始化、向量存储写入等异常持久化为 `failed`，不会因为异常永久停留在“处理中”。遇到失败时：

1. 展开文档查看 `error_message`，先处理文件格式、编码、PDF 加密/OCR 或模型初始化问题。
2. 确认知识原文件仍位于 `KNOWLEDGE_STORAGE_PATH`（默认 `./data/knowledge`）指定的目录。
3. 在管理页点击“重试”，或调用 `POST /api/v1/knowledge/documents/{document_id}/retry`。
4. 如果状态仍不变化，检查后端日志中 `知识文档处理失败` 或 `恢复知识文档` 相关记录，并确认只有一个实例共享本地 SQLite/ChromaDB 和知识文件目录。

支持的上传格式为 UTF-8 TXT、Markdown、PDF 和 DOCX，最大 10 MiB；PDF 最多 300 页且不支持纯扫描 OCR 文档，提取文本最多 1,000,000 字符。

---

### Q: 提示"角色卡 JSON 格式错误"

**解决方案：**
1. 使用 JSON 验证工具检查文件格式：https://jsonlint.com/
2. 确认所有必需字段都已填写
3. 检查字符串是否正确转义

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

---

### Q: API 调用失败，提示"API key invalid"

**解决方案：**
1. 检查 `.env` 文件中 `LLM_API_KEY` 是否正确
2. 确认 API 密钥没有过期
3. 验证 `LLM_BASE_URL` 配置是否正确

**测试 API 连接：**
```bash
curl -X POST "https://api.deepseek.com/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hello"}]}'
```

---

### Q: 浏览器登录后仍然显示未登录

仓库内 Web 前端只使用服务端写入的 `memoria-token` HttpOnly Cookie，不从响应 token 构造 Bearer 头，也不把 token 保存到 `localStorage`。排查时确认：

1. 前端请求使用 `credentials: include`，API 与 Web 的域名、端口和反向代理 Cookie 转发配置正确。
2. 本地 HTTP 开发使用 `AUTH_COOKIE_SECURE=false`；HTTPS 部署必须设置为 `true`。
3. 浏览器未阻止当前站点 Cookie，登录响应中存在 `Set-Cookie`。
4. 旧版前端保存过的 `localStorage` token 会在启动时清理，不应再依赖该值恢复登录。

脚本或第三方 API 客户端仍可使用 `Authorization: Bearer <token>` 或 Cookie；Cookie-only 约束只针对仓库内浏览器客户端。

---

### Q: 如何初始化第一个管理员

普通注册始终创建普通用户。先在服务环境中设置高熵 `ADMIN_BOOTSTRAP_TOKEN`，再向注册接口额外提交同值的 `admin_bootstrap_token`：

```bash
curl -c memoria-admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"replace-with-a-strong-password1","admin_bootstrap_token":"replace-with-your-bootstrap-token"}' \
  http://127.0.0.1:8080/api/v1/user/register
```

管理员初始化名额只能占用一次。凭据错误或服务未配置时返回 403；已有管理员或名额已使用时返回 409。普通 Web 注册界面不接收该凭据。初始化成功后，数据库中的一次性占位记录会永久阻止再次初始化。直接部署可取消该环境变量；当前 Docker Compose 配置要求 `ADMIN_BOOTSTRAP_TOKEN` 保持非空，可将其轮换为新的高熵随机值并继续妥善保管。

---

### Q: 知识检索预览为什么没有显示上一条查询结果

知识管理页同一时间只保留一条活动预览请求。重复提交、切换知识库、关闭预览弹窗或离开页面时，前端会取消旧请求并忽略其结果，避免较慢的旧响应覆盖当前查询。这属于预期行为；需要对比两次查询时，应等待当前请求完成后再提交下一条。

---

### Q: 运行时配置从哪里读取

运行时配置由 `src/memoria/core/config.py` 的 Pydantic Settings 从环境变量和仓库根目录 `.env` 读取。`config/settings.yaml` 仅保留为兼容性/参考标记，当前服务不会从该文件加载运行时配置。

---

### Q: 语音转写或播放返回 503

语音服务与主对话模型使用独立配置。TTS 与 STT 也使用不同的连接配置；未设置对应的 API 密钥时，该能力会返回 503，`LLM_API_KEY` 不会自动复用。

```bash
SPEECH_TTS_PROVIDER=minimax
SPEECH_TTS_API_KEY=your-minimax-key
SPEECH_TTS_BASE_URL=https://api.minimax.io/v1
SPEECH_TTS_MODEL=speech-2.8-turbo
SPEECH_TTS_DEFAULT_VOICE=female-shaonv
SPEECH_STT_PROVIDER=openai_compatible
SPEECH_STT_API_KEY=sk-xxx
SPEECH_STT_BASE_URL=https://api.openai.com/v1
SPEECH_STT_MODEL=gpt-4o-mini-transcribe
SPEECH_OUTPUT_FORMAT=mp3
SPEECH_STORAGE_PATH=./data/speech
```

修改配置后重启后端。仍失败时检查：

1. `SPEECH_STT_BASE_URL` 必须提供 OpenAI-compatible `/audio/transcriptions` 端点；TTS 不会复用这个地址。MiniMax TTS 使用 `SPEECH_TTS_BASE_URL` 的流式端点。
2. 会话必须属于当前登录用户，且请求的 `mode` 必须与单聊或群聊会话类型一致。
3. STT 文件只支持 MP3、MP4、MPEG、MPGA、M4A、WAV 和 WebM，并受上传大小限制。
4. TTS 只允许合成 assistant/角色消息；生成文件写入 `SPEECH_STORAGE_PATH/cache`。
5. Custom Voice 需要先上传授权录音，再上传参考样本。MiniMax 创建成功后会保存角色的 `voice_id`；创建失败或仍在处理中时，系统会使用角色卡的内置音色。

当前语言只支持 `zh-CN` 和 `en-US`。STT 语言来自会话 `locale`，恢复会话后不会自动改用浏览器当前语言。

---

### Q: 角色对话不符合人设

**可能原因：** 角色卡定义不够详细、Prompt 构建有问题、模型能力不足。

**解决方案：**

1. 优化角色卡中的性格和语言风格定义
2. 调整 `speech_style` 字段，增加更详细的约束

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
  "things_never_to_say": ["作为一个AI", "我是程序", "根据我的分析"]
}
```

3. 使用更强大的模型（如 GPT-4、DeepSeek-Chat）

---

### Q: 修改关系图谱后，角色仍然按旧关系行动

当前实现以关系图谱为角色间关系的最高优先级来源。通过关系 API 或前端图谱创建、更新、删除关系时，系统会写入 `character_relationship_revision` 修订时间；单聊、多角色生成和主动互动都会按这个时间过滤旧的关系相关长期记忆、角色间共享记忆和群体记忆，但普通玩家事实、共同经历和世界事实会保留。单聊也会召回同一玩家下相关的 shared/group 记忆，群聊原始历史和结束摘要提取仍按修订时间截止，避免旧关系被重新写回。

如果仍看到旧关系表现，请按以下顺序检查：

1. 确认修改的是当前登录用户自己的关系图谱；角色卡、事件、关系和共享记忆都按用户隔离。
2. 确认关系修改走的是 `/api/v1/relationships` 系列接口或前端关系图谱页面，而不是直接改旧数据库行；直接改 `character_relationship` 不会自动刷新修订时间。
3. 若手动改库，需要同步更新 `character_relationship_revision.updated_at`，或重新通过 API 保存一次关系。
4. 检查是否在图谱修改之后又产生了新的对话和记忆；过滤只会排除修订时间之前的旧关系上下文，不会屏蔽修订之后新写入的内容，也不会删除非关系长期记忆。
5. 删除关系表示“未定义关系”，不是“关系中立”。如果需要明确普通队友、陌生、敌对等态度，应在图谱中创建对应关系边。

---

### Q: 群聊为什么没有自主发言？

普通自主脉冲不是固定定时发言。当前实现只有在以下条件同时满足时才会生成消息：

1. 世界时钟未暂停。
2. 距离上次普通自主脉冲至少经过 2 分钟真实时间和 20 分钟世界时间。
3. 当日普通自主消息预算尚未达到 24 条。
4. 逻辑群聊线程中至少有 2 个活跃参与者。
5. 存在发言动机，例如未解决的剧情钩子、角色目标，或在线程不处于等待玩家状态时存在当前话题。

普通脉冲和事件脉冲当前每次都最多生成 1 条消息。事件脉冲会绕过普通脉冲的真实时间冷却、世界时间冷却和每日预算，但仍要求至少 2 个活跃参与者。线程状态租约用于避免多个 worker 重复执行同一个脉冲。

脉冲成功后，消息、关系变化、参与者更新、线程状态和未读通知会在同一事务中原子提交。相关记忆提取在事务提交后以 best effort 执行；提取失败会记录日志，但不会回滚已经提交的对话和状态。

---

### Q: 群聊 session 已结束，为什么同一群聊仍可能继续发言？

`session_id` 表示一次物理会话，`group_thread_id` 表示可跨多个物理 session 延续的逻辑群聊线程。历史消息、未读状态和自主脉冲都以逻辑线程为连续上下文。

结束当前 session 不等于关闭逻辑线程。后续脉冲需要写入消息时，系统可以为该 `group_thread_id` 自动创建新的 active carrier session，因此表现为同一群聊在新 session 中继续。排查时应同时查看 `group_thread_id` 和当前承载它的 active session，而不是只检查旧 `session_id`。

---

### Q: checkpoint memory 为什么没有立即出现？

单聊和群聊的 checkpoint memory 由持久后台任务处理，任务类型分别为 `single_checkpoint_memory` 和 `group_checkpoint_memory`。任务状态包括 `pending`、`running`、`retry`、`completed` 和 `failed`。

- `dedupe_key` 和数据库唯一约束防止同一 checkpoint 重复入队。
- worker 通过租约领取任务；租约过期的 `running` 任务可以被重新领取。
- 默认最多尝试 3 次，失败后默认等待 5 秒再重试。
- 完成或失败更新只有在 worker 仍持有有效租约时才会生效。

短时间处于 `pending`、`running` 或 `retry` 属于正常后台处理。持续停留或最终进入 `failed` 时，应检查后台 worker 和对应任务日志，而不是重复结束会话来触发相同任务。

---

### Q: 数据库锁定错误（database is locked）

**原因：** 多个进程同时写入数据库。

**解决方案：**
1. Memoria 已启用 WAL 模式，支持并发读
2. 如需高并发写入，配置 `DATABASE_URL=postgresql://...` 切换到 PostgreSQL

```bash
# 检查数据库占用
lsof data/sqlite_db/memoria.db

# 强制释放（谨慎使用）
rm -f data/sqlite_db/memoria.db-shm data/sqlite_db/memoria.db-wal
```

---

### Q: 如何切换到 PostgreSQL？

**解决方案：** 保留 `DATABASE_PATH` 作为 SQLite 开发模式；生产环境设置 `DATABASE_URL` 后，Repository 层会自动使用 PostgreSQL。

```bash
DATABASE_URL=postgresql://memoria:password@127.0.0.1:5432/memoria
PYTHONPATH=src uvicorn memoria.main:app --host 127.0.0.1 --port 8001
```

首次启动会自动创建表并补齐轻量迁移。已有 SQLite 数据不会自动搬迁，需要单独导出导入。

用户隔离版将 `character_card`、`event_definition`、`character_relationship` 改为带 `owner_user_id` 的复合主键/唯一约束；这类主键变化不会自动迁移旧 SQLite 表。升级到该版本前请先删除旧开发库，让系统按新 schema 重建：

```bash
rm -f data/sqlite_db/memoria.db data/sqlite_db/memoria.db-wal data/sqlite_db/memoria.db-shm
PYTHONPATH=src uvicorn memoria.main:app --host 127.0.0.1 --port 8001
```

---

### Q: 如何用 Docker 一键部署？

**解决方案：** 使用仓库内置的 Compose 配置，默认启动 PostgreSQL、后端和前端 Nginx。

```bash
cd deploy/docker
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY，并设置高强度且唯一的
# POSTGRES_PASSWORD 和 ADMIN_BOOTSTRAP_TOKEN（必填）
docker compose up
```

默认访问地址：

- Web 应用：http://127.0.0.1:8080
- API 文档：http://127.0.0.1:8080/docs
- 后端直连：http://127.0.0.1:8001

后端直连端口默认只绑定 `127.0.0.1`。Compose 默认设置 `FORWARDED_ALLOW_IPS=*`，内置 Nginx 会用连接端的 `$remote_addr` 覆盖客户端自带的 `X-Forwarded-For`，使匿名请求按真实客户端 IP 限流。需要从其他主机访问时，可在 `deploy/docker/.env` 中显式设置 `API_BIND_HOST=0.0.0.0`，并同时把 `FORWARDED_ALLOW_IPS` 收紧到可信代理 IP 或网段，配置防火墙、HTTPS 反向代理和安全 Cookie。直接运行 Uvicorn 时也建议默认使用 `--host 127.0.0.1`。

如果首次向量检索较慢，通常是容器正在下载嵌入模型。已有本地模型时可在 `.env` 中设置：

```bash
EMBEDDING_MODEL=/app/models/sentence-transformers/all-MiniLM-L6-v2
```

---

### Q: 向量检索不返回结果

**可能原因：** 向量数据库为空（尚未添加长期记忆），或查询文本与记忆内容语义差异过大。

**解决方案：**
```python
# 检查向量记忆数量
from memoria.core.vector_memory import get_vector_store

store = get_vector_store()
count = store.get_memory_count(character_id="npc_luo_xiaohei", player_id="player_001")
print(f"向量记忆数量: {count}")

# 手动添加测试记忆
from memoria.db import repository
fact_id = repository.save_long_term_fact(
    character_id="npc_luo_xiaohei",
    player_id="player_001",
    fact_text="玩家喜欢吃鱼",
    importance=8
)
store.add_memory(fact_id, "npc_luo_xiaohei", "player_001", "玩家喜欢吃鱼", 8)
```

---

### Q: 内存占用过高

**原因：** 向量模型约 100MB，加上大量对话历史和记忆。

**解决方案：**
1. 调整 `SHORT_TERM_MEMORY_TURNS` 减少短期记忆轮数
2. 定期清理旧会话数据
3. 考虑使用远程向量数据库（Milvus / Qdrant）

```bash
# 清理 30 天前的会话
sqlite3 data/sqlite_db/memoria.db \
  "DELETE FROM short_term_message WHERE created_at < datetime('now', '-30 days');"
```

---



### Q: 如何调整日志级别

启动时设置环境变量：`LOG_LEVEL=DEBUG PYTHONPATH=src uvicorn memoria.main:app --host 127.0.0.1 --port 8001`

系统管理员可运行时动态调整：`curl -X POST http://127.0.0.1:8001/admin/log-level?level=DEBUG -H "Authorization: Bearer <token>"`。普通登录用户会收到 403。

可选级别：DEBUG / INFO / WARNING / ERROR

### Q: API 返回 429 Too Many Requests

触发了写操作速率限制（60 次/60 秒）。登录请求优先按认证用户限流，未登录或 token 无效时按客户端 IP 限流；`X-Player-ID` 不会作为可信限流依据。计数器使用线程锁和单调时钟，并周期清理过期 key。

当前额度只在单个应用进程内共享；多 worker 或多实例部署不会形成全局限额。生产环境需要在反向代理或 Redis 等集中式存储上实现统一限流。

Docker Compose 部署依赖 Uvicorn 的可信代理配置解析 Nginx 设置的转发头。默认 `FORWARDED_ALLOW_IPS=*` 仅适用于后端端口不直接暴露公网的拓扑；直接开放后端端口时必须限制为实际代理地址，否则客户端可伪造转发头绕过按 IP 的限流。

### Q: 启动时出现配置警告

系统会检查 `LLM_API_KEY` 等必需配置。警告不影响服务启动，但对话功能需要有效 API Key 才能正常工作。

### Q: LLM 调用偶发失败

系统内置 3 次指数退避重试（1s → 2s → 4s），大部分临时网络故障会自动恢复。持续失败需检查 API Key 和网络连接。

## 调试技巧

### 1. 启用详细日志

```bash
LOG_LEVEL=DEBUG PYTHONPATH=src uvicorn memoria.main:app --host 127.0.0.1 --port 8001
```

### 2. 查看 LLM 调用详情

CLI 调试模式会把 LLM 请求、Prompt 和原始响应输出到 stderr：

```bash
python scripts/cli_chat.py --debug
```

Web/API 调试可结合开发者端点查看历史回放、性能采样和质量评分：

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8001/api/v1/developer/replay/<session_id>
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8001/api/v1/developer/performance
```

### 3. 测试角色卡加载

```python
from memoria.core import character_loader

try:
    card = character_loader.load_character_card("npc_luo_xiaohei")
    print(f"角色卡加载成功: {card.meta.name}")
except Exception as e:
    print(f"加载失败: {e}")
```

这段代码测试的是静态模板加载。业务 API 会按当前登录用户从数据库加载角色卡；如果该用户还没有创建或导入 `npc_luo_xiaohei`，对话页不会自动显示这个角色。

### 4. 检查数据库结构

```bash
sqlite3 data/sqlite_db/memoria.db

# 查看所有表
.tables

# 查看表结构
.schema character_card

# 查询数据
SELECT * FROM session LIMIT 5;

# 退出
.quit
```

PostgreSQL 模式下可使用 `psql "$DATABASE_URL"` 查看同名表结构。

### 5. 使用 FastAPI 交互式文档

访问 http://127.0.0.1:8001/docs，点击任意接口的 "Try it out" 按钮，填写参数后点击 "Execute" 查看响应。

---

## 性能优化建议

### 数据库优化

```sql
-- 定期执行 VACUUM 清理空间
VACUUM;

-- 分析查询计划
EXPLAIN QUERY PLAN SELECT * FROM session WHERE character_id = 'xxx';

-- 重建索引
REINDEX;
```

### 缓存优化

```python
# 增加角色卡缓存大小（默认 maxsize=256）
from functools import lru_cache

@lru_cache(maxsize=512)
def load_character_card(character_id: str, owner_user_id: str | None = None) -> CharacterCard:
    ...
```

### 批量操作

```python
# 批量插入记忆（而非逐条插入）
facts = [
    (char_id, player_id, "事实1", 5),
    (char_id, player_id, "事实2", 7),
]
conn.executemany(
    "INSERT INTO long_term_fact (character_id, player_id, fact_text, importance) "
    "VALUES (?, ?, ?, ?)",
    facts
)
```

### 异步化

将记忆萃取、向量化等耗时操作改为异步执行，不阻塞主流程：

```python
import asyncio

async def extract_and_save_memory(...):
    # 异步执行
    ...
```
