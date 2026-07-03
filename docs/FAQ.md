# Memoria 故障排查与 FAQ

## 常见问题

### 启动时提示"模块未找到"

确保在项目根目录，虚拟环境已激活：
```bash
cd Memoria
source .venv/bin/activate
pip install -r requirements.txt
```

### 首次启动时下载模型缓慢

首次启动会自动下载 sentence-transformers 模型（约 80MB）。可使用国内镜像：
```bash
export HF_ENDPOINT=https://hf-mirror.com
uvicorn memoria.main:app --reload
```

### API 调用失败

检查 `.env` 中 `LLM_API_KEY` 和 `LLM_BASE_URL` 配置：
```bash
curl -X POST "https://api.deepseek.com/v1/chat/completions" \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hello"}]}'
```

### 角色对话不符合人设

优化角色卡中的 `speech_style` 字段，增加更详细的约束：
```json
"speech_style": {
  "tone_register": "轻松活泼",
  "vocabulary_notes": "使用简单直接的语言",
  "sentence_patterns": ["短句为主", "常用疑问句表达好奇"],
  "catchphrases": ["喵~"],
  "things_never_to_say": ["作为一个AI", "我是程序"]
}
```

### 数据库锁定错误

Memoria 已启用 WAL 模式支持并发读。强制释放：
```bash
lsof memoria.db
rm -f memoria.db-shm memoria.db-wal
```

### 向量检索不返回结果

检查向量记忆数量：
```python
from memoria.core.vector_memory import get_vector_store
store = get_vector_store()
count = store.get_memory_count(character_id="npc_luo_xiaohei", player_id="player_001")
```

### 内存占用过高

- 向量模型约 100MB
- 调整 `SHORT_TERM_MEMORY_TURNS` 减少短期记忆
- 定期清理旧会话数据

---

## 调试技巧

### 启用详细日志
```python
logging.basicConfig(level=logging.DEBUG)
```

### 测试角色卡加载
```python
from memoria.core import character_loader
card = character_loader.load_character_card("npc_luo_xiaohei")
print(f"角色卡加载成功: {card.meta.name}")
```

### 检查数据库
```bash
sqlite3 data/sqlite_db/memoria.db
.tables
.schema character_card
```

### API 测试
访问 http://localhost:8000/docs 使用 FastAPI 交互式文档。

---

## 性能优化

### 数据库维护
```sql
VACUUM;
REINDEX;
```

### 增加角色卡缓存
```python
@lru_cache(maxsize=128)
def load_character_card(character_id: str) -> CharacterCard:
    ...
```
