# Memoria 快速开始与开发运行

本文承接 README 中的安装、运行、测试和演示说明。运行时配置来自环境变量和仓库根目录 `.env`，完整变量见 [配置说明](CONFIGURATION.md) 和 `config/.env.example`。

## 环境要求

- Python 3.10+
- Node.js 18+（仅在开发 Web 前端时需要）
- 支持 OpenAI 兼容接口的大模型 API
- Docker / Docker Compose（使用容器化部署时需要）

## Docker 一键部署

默认启动 PostgreSQL、FastAPI 后端和 Nginx 前端：

```bash
cd deploy/docker
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY，并设置高强度且唯一的
# POSTGRES_PASSWORD 和 ADMIN_BOOTSTRAP_TOKEN
docker compose up
```

启动后访问：

- Web 应用：http://127.0.0.1:8080
- API 文档：http://127.0.0.1:8080/docs
- 后端健康检查：http://127.0.0.1:8080/health

首次启动后，可以使用 `.env` 中的 `ADMIN_BOOTSTRAP_TOKEN` 创建唯一的初始管理员：

```bash
curl -c memoria-admin.cookies \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"replace-with-a-strong-password1","admin_bootstrap_token":"replace-with-your-bootstrap-token"}' \
  http://127.0.0.1:8080/api/v1/user/register
```

普通 Web 注册不会提交该凭据，因此始终创建普通用户。Compose 默认使用 Docker volume 持久化数据库、ChromaDB 和模型缓存；本地 `models/` 会以只读方式挂载到容器。

常用命令：

```bash
docker compose up --build  # Dockerfile 或依赖变化后强制重建
docker compose logs -f backend
docker compose down
docker compose down -v  # 同时删除 PostgreSQL/ChromaDB/模型缓存数据
```

## 本地源码安装

1. 克隆项目并进入仓库：

```bash
git clone <repository_url>
cd Memoria
```

2. 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
source .venv/bin/activate  # Linux/macOS
# Windows: venv\Scripts\activate
pip install -r requirements.txt
```

首次启动时会自动下载嵌入模型（约 80MB），用于向量检索。

3. 创建配置：

```bash
cp config/.env.example .env
# 编辑 .env，至少填入 LLM_BASE_URL、LLM_API_KEY 和 LLM_MODEL
```

4. 启动后端：

```bash
uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

常用入口：

- Swagger：http://127.0.0.1:8001/docs
- ReDoc：http://127.0.0.1:8001/redoc
- CLI 聊天：`python scripts/cli_chat.py`
- CLI 调试：`python scripts/cli_chat.py --debug`

5. 启动 Web 前端：

```bash
cd web
npm install
npm run dev
```

默认访问地址为 http://127.0.0.1:5173。

## 完整演示模块

`examples/next_door/` 提供“隔壁寝室”完整故事模块，包含玩家角色卡、4 个 NPC、关系网络、事件、3 个知识库、群聊和检索评测问题。后端配置完成后可播种到独立的 `memoria_demo` 普通用户：

```bash
python scripts/seed_next_door_demo.py --password '<choose-a-strong-password>'
```

- `--skip-knowledge-index`：只创建结构和知识文档队列，不加载本地嵌入模型。
- `--reset-module`：清理并重建该模块。

播种脚本不会创建或占用系统管理员名额。破冰指南见 [Next Door README](../examples/next_door/README.md) 和 [WALKTHROUGH](../examples/next_door/WALKTHROUGH.md)。

## 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行全部后端测试
bash scripts/run_tests.sh

# 按模块运行示例
PYTHONPATH=src pytest tests/test_core.py -v
PYTHONPATH=src pytest tests/test_repository.py -v
PYTHONPATH=src pytest tests/test_events.py -v
PYTHONPATH=src pytest tests/test_event_e2e.py -v
PYTHONPATH=src pytest tests/test_relationship_delta_policy.py -v
PYTHONPATH=src pytest tests/test_memory_extractor.py -v
PYTHONPATH=src pytest tests/test_multi_dialogue_api.py -v
PYTHONPATH=src pytest tests/test_csrf.py -v
PYTHONPATH=src pytest tests/test_output_safety.py -v
PYTHONPATH=src pytest tests/test_world_clock.py -v
PYTHONPATH=src pytest tests/test_knowledge_base.py -v
PYTHONPATH=src pytest tests/test_fact_claims.py -v
PYTHONPATH=src pytest tests/test_security_fixes.py -v
PYTHONPATH=src pytest tests/test_domain_events.py -v
PYTHONPATH=src pytest tests/test_memory_curve.py -v
PYTHONPATH=src pytest tests/test_speech.py -v

# 前端测试
cd web
npm test
```

当前测试数量以 `pytest --collect-only -q` 和 `npm test` 的实际输出为准。PostgreSQL 集成测试可用 `MEMORIA_PG_TEST_URL` 指向独立的测试数据库；测试流程会重建表，不要连接开发或生产数据库。

## 便携发布包

`release/` 包含便携源码包的一键启动器和静态服务入口。发布包使用方式、数据备份和常见问题见 [发布包说明](../release/RELEASE.md)。

## 相关文档

- [配置说明](CONFIGURATION.md)
- [功能说明](FEATURES.md)
- [系统架构](ARCHITECTURE.md)
- [API 文档](API.md)
- [故障排查](FAQ.md)
- [贡献指南](CONTRIBUTING.md)
