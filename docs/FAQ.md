# Memoria 故障排查与 FAQ

## 常见问题

### Q: 启动时提示"模块未找到"

**解决方案：**
```bash
# 确保在项目根目录
cd Memoria
# 确保虚拟环境已激活
source .venv/bin/activate  # Linux/Mac
# 重新安装依赖
pip install -r requirements.txt
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
PYTHONPATH=src uvicorn memoria.main:app --reload
```

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

### Q: 数据库锁定错误（database is locked）

**原因：** 多个进程同时写入数据库。

**解决方案：**
1. Memoria 已启用 WAL 模式，支持并发读
2. 如需高并发写入，考虑迁移到 PostgreSQL

```bash
# 检查数据库占用
lsof data/sqlite_db/memoria.db

# 强制释放（谨慎使用）
rm -f data/sqlite_db/memoria.db-shm data/sqlite_db/memoria.db-wal
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

启动时设置环境变量：`LOG_LEVEL=DEBUG PYTHONPATH=src uvicorn memoria.main:app`

运行时动态调整：`curl -X POST http://localhost:8000/admin/log-level?level=DEBUG`

可选级别：DEBUG / INFO / WARNING / ERROR

### Q: API 返回 429 Too Many Requests

触发了 per-player 速率限制（60次/60秒）。等待窗口重置后重试。可通过 `X-Player-ID` 请求头区分不同玩家。

### Q: 启动时出现配置警告

系统会检查 `LLM_API_KEY` 等必需配置。警告不影响服务启动，但对话功能需要有效 API Key 才能正常工作。

### Q: LLM 调用偶发失败

系统内置 3 次指数退避重试（1s → 2s → 4s），大部分临时网络故障会自动恢复。持续失败需检查 API Key 和网络连接。

## 调试技巧

### 1. 启用详细日志

```python
# 在 src/memoria/main.py 中修改日志级别
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
```

### 2. 查看 LLM 调用详情

在 `src/memoria/core/llm_client.py` 中添加：
```python
logger.debug(f"LLM 请求: {messages}")
logger.debug(f"LLM 响应: {response}")
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

### 5. 使用 FastAPI 交互式文档

访问 http://localhost:8000/docs，点击任意接口的 "Try it out" 按钮，填写参数后点击 "Execute" 查看响应。

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
# 增加角色卡缓存大小（默认 maxsize=64）
from functools import lru_cache

@lru_cache(maxsize=128)
def load_character_card(character_id: str) -> CharacterCard:
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
