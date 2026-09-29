# Memoria 配置说明

Memoria 的运行时配置来自环境变量和仓库根目录 `.env`。`config/.env.example` 是变量的完整模板，`config/settings.yaml` 仅是兼容性/参考标记，不参与运行时加载。

## 最小配置

至少需要配置一个 OpenAI 兼容的大模型服务：

```bash
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=deepseek-chat
```

常见供应商示例：

```bash
# DeepSeek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat

# Kimi (Moonshot)
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k

# Qwen (DashScope 兼容模式)
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL=qwen-plus

# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4-turbo-preview
```

## 常用变量

```bash
# 大模型
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=your-api-key-here
LLM_MODEL=deepseek-chat
LLM_TIMEOUT_SECONDS=45
MAX_OUTPUT_TOKENS=400
SHORT_TERM_MEMORY_TURNS=8
LONG_TERM_MEMORY_INTERVAL_TURNS=5

# 轻量任务专用模型（可选，留空时复用主模型）
LLM_LIGHT_BASE_URL=
LLM_LIGHT_API_KEY=
LLM_LIGHT_MODEL=
LLM_LIGHT_TIMEOUT_SECONDS=12
LIGHT_TASK_MAX_OUTPUT_TOKENS=400

# 数据库
DATABASE_PATH=./data/sqlite_db/memoria.db
DATABASE_URL=

# 认证与安全
MEMORIA_ENV=development
AUTH_COOKIE_SECURE=false
ADMIN_BOOTSTRAP_TOKEN=
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_MAX_REQUESTS=60
MAX_REQUEST_BODY_BYTES=33554432

# 世界时钟与记忆曲线
WORLD_CLOCK_DEFAULT_TIMEZONE=UTC
WORLD_CLOCK_SCHEDULER_INTERVAL_SECONDS=30
WORLD_CLOCK_SCHEDULER_LEASE_SECONDS=90
MEMORIA_MEMORY_CURVE_ENABLED=true

# 向量记忆与知识库
VECTOR_DB_PATH=./data/chroma_db
EMBEDDING_MODEL=./models/sentence-transformers/all-MiniLM-L6-v2
VECTOR_SEARCH_TOP_K=10
KNOWLEDGE_STORAGE_PATH=./data/knowledge
KNOWLEDGE_RETRIEVAL_TOP_K=4
KNOWLEDGE_SIMILARITY_THRESHOLD=0.60
KNOWLEDGE_UPLOAD_MAX_BYTES=10485760
```

## 知识库与向量检索

运行时配置的唯一来源是 [`Configs`](../src/memoria/core/config.py)（`memoria.core.config.Configs`）；`config/settings.yaml` 不参与加载，仅作为兼容性标记。

- 检索：默认召回 4 个知识块，相似度阈值为 0.60。
- 分块：默认目标 200 token、重叠 36 token、硬上限 240 token。
- 上传：单文件默认上限 10 MiB（`KNOWLEDGE_UPLOAD_MAX_BYTES`）。

## 语音配置

语音功能是可选的，未配置时相关接口返回 `503`，不影响其他功能。

```bash
# TTS：默认使用 MiniMax 流式合成
SPEECH_TTS_PROVIDER=minimax
SPEECH_TTS_API_KEY=
SPEECH_TTS_BASE_URL=https://api.minimax.io/v1
SPEECH_TTS_MODEL=speech-2.8-turbo
SPEECH_TTS_TIMEOUT_SECONDS=30
SPEECH_TTS_MAX_RETRIES=1
SPEECH_TTS_DEFAULT_VOICE=female-shaonv

# STT：独立的 OpenAI-compatible 转写端点
SPEECH_STT_PROVIDER=openai_compatible
SPEECH_STT_API_KEY=
SPEECH_STT_BASE_URL=https://api.openai.com/v1
SPEECH_STT_MODEL=gpt-4o-mini-transcribe
SPEECH_STT_TIMEOUT_SECONDS=30
SPEECH_STT_MAX_RETRIES=1

SPEECH_OUTPUT_FORMAT=mp3
SPEECH_STORAGE_PATH=./data/speech
```

TTS 默认使用 MiniMax T2A v2 流式响应：浏览器收到首个音频分块后即可播放，完整 MP3 会原子写入 `SPEECH_STORAGE_PATH/cache` 供历史消息复播。STT 始终调用独立的 `/audio/transcriptions` 端点。

旧的 `SPEECH_PROVIDER`、`SPEECH_API_KEY`、`SPEECH_BASE_URL` 和 `SPEECH_TIMEOUT_SECONDS` 仅作为迁移回退，并会发出弃用警告。

## 部署注意事项

- `MEMORIA_ENV=production` 会强制 `AUTH_COOKIE_SECURE=true`。
- Docker Compose 默认设置 `FORWARDED_ALLOW_IPS=*`。如果后端端口直接暴露到公网，必须收紧为可信代理 IP 或网段。
- URL 头像下载默认关闭环境代理继承，只连接经过校验的公网 IP。Fake-IP 环境需要通过 HTTPS DoH 获取真实地址；DoH 不可达时会安全拒绝。
- 完整变量、默认值和注释以 [`config/.env.example`](../config/.env.example) 和 `src/memoria/core/config.py` 为准。

## 相关文档

- [快速开始与开发运行](GETTING_STARTED.md)
- [系统架构](ARCHITECTURE.md)
- [故障排查](FAQ.md)
