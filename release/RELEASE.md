# Memoria 便携发布包使用说明

Memoria 是基于大语言模型的沉浸式角色扮演对话系统。本发布包为**便携源码包**：
解压后运行一键启动脚本，自动完成虚拟环境创建、依赖安装与服务启动，浏览器直接访问即可使用。

## 系统要求

- **Python 3.10 或更高版本**（已在 PATH 中，Windows 请在安装时勾选 "Add to PATH"）
- 可联网（首次安装依赖 + 首次向量功能加载模型时使用；Google 字体需联网，缺失时自动降级）
- 磁盘空间：依赖安装约需 5GB（torch 等），发布包本体约 100MB

## 快速开始

```bash
# 1. 解压
unzip memoria-<version>.zip
cd memoria-<version>

# 2. 启动（Linux / macOS）
./start.sh
# 或 Windows：
# start.bat
# 或任意平台：
# python start.py
```

首次运行会依次：
1. 从 `config/.env.example` 复制生成 `.env`（**请先编辑 `.env` 填入 API 密钥**，见下）；
2. 创建 `data/` 下的空数据目录；
3. 创建 `.venv` 虚拟环境并安装依赖（torch / chromadb 等体积大，耗时较长，请耐心等待，只需一次）；
4. 启动服务，输出访问地址。

浏览器打开 **http://127.0.0.1:8001** 即可使用。API 文档见 http://127.0.0.1:8001/docs 。

常用参数（追加在启动命令后）：

```bash
python start.py --port 9000       # 更换端口
python start.py --host 0.0.0.0    # 监听所有网卡（注意生产安全配置）
python start.py --no-install      # 已有 .venv 时跳过依赖安装，加速启动
```

## 必读：配置 API 密钥

编辑包根目录下的 `.env`（首次启动会自动从模板生成；若不存在可手动复制
`config/.env.example` 为 `.env`）。

**必须配置**（否则对话功能不可用）：

```ini
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_API_KEY=sk-你的密钥
LLM_MODEL=deepseek-chat
```

支持任意 OpenAI 兼容接口（DeepSeek / Kimi / Qwen / OpenAI 等），示例见 `.env` 内注释。

**可选配置**：

- `LLM_LIGHT_*`：摘要等轻量任务专用模型，留空则复用主模型；
- `SPEECH_TTS_*` / `SPEECH_STT_*`：语音合成 / 语音识别（默认 TTS 为 MiniMax、STT 为 OpenAI-compatible），未配置时语音功能返回 503，不影响其他功能；
- `ADMIN_BOOTSTRAP_TOKEN`：可选。设置后可通过 API 用该凭据创建唯一的初始管理员，否则 Web 注册的用户均为普通用户；
- `AUTH_COOKIE_SECURE`：本地 HTTP 保持 `false`；若通过 HTTPS 或公网部署请设为 `true`。

其他参数（记忆窗口、世界时钟、RAG 检索等）均可通过环境变量覆盖，完整列表见
`src/memoria/core/config.py`。

## 数据与备份

- 所有运行数据存放在 `data/` 下：`sqlite_db/`（角色、会话、记忆）、`chroma_db/`（向量库）、`knowledge/`（知识文档）、`speech/`（语音缓存）。
- **备份 = 复制整个 `data/` 目录**。恢复时把备份放回包根目录即可。
- 数据库结构由应用首次启动时自动创建，无需手动建表。

## 常见问题

- **端口被占用**：换端口 `python start.py --port 9000`。
- **首次启动很慢**：`pip install` 需下载数 GB 依赖（torch 等），属正常现象，只需一次。
- **提示需要模型但无网络**：本包已内置嵌入模型（`models/sentence-transformers/all-MiniLM-L6-v2`），向量记忆与知识库可离线使用。
- **不要用多 worker 启动**（如 `uvicorn run:app --workers 2`）：世界时钟调度器、长期记忆后台任务与进程内限流均为单进程设计。
- **想用 CLI 聊天**：在包根目录执行 `./scripts/chat.sh` 或 `.venv/bin/python scripts/cli_chat.py`（Windows：`.venv\Scripts\python.exe scripts\cli_chat.py`）。
- **升级**：备份 `data/` 与 `.env` → 下载新版本发布包 → 把备份放回新包根目录 → 启动。数据库结构变更会自动迁移（`create_all` + 迁移钩子）。

## 目录结构

```
memoria-<version>/
├── start.py / start.sh / start.bat   # 一键启动
├── run.py                            # 静态服务入口（uvicorn run:app）
├── requirements.txt                  # Python 依赖
├── config/.env.example               # 环境变量模板
├── src/memoria/                      # 后端源码
├── web/dist/                         # 前端构建产物（已内置，无需 node）
├── models/                           # 本地嵌入模型（离线向量检索）
├── scripts/                          # CLI 聊天（chat.sh / cli_chat.py）
└── data/                             # 运行数据（首次启动自动创建）
```
