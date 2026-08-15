# 仓库指南

Memoria 是基于 LLM 的沉浸式角色扮演对话系统：后端为 FastAPI（`src/memoria`），前端为 React + Vite（`web`）。本文约定帮助贡献者在双端保持一致。

## 项目结构与模块

- `src/memoria/` — 后端包（Python 3.10+，FastAPI）
  - `main.py` — 应用入口、中间件（含 CSRF、限流）与路由挂载
  - `api/` — 路由模块：`dialogue`、`multi_dialogue`、`character_admin`、`event_admin`、`relationship`、`knowledge`、`speech`、`user`、`story`、`developer` 等
  - `core/` — 领域逻辑：`orchestrator`、`multi_character_orchestrator`、`memory_extractor`、`event_*`、`speaking_strategy`、`llm_client`、`vector_memory`、`prompt_builder`、`output_safety`、`csrf` 等
  - `db/repository/` — 持久化包（`__init__.py` 兼容 facade，领域拆分为 `users`、`events`、`multi_session`、`knowledge` 等；对外仍 `from memoria.db import repository`）
  - `characters/` — 角色卡 JSON 模板
- `web/` — 前端（React 18、Vite、Tailwind）
  - `src/pages/`、`src/components/`、`src/api/`（含 CSRF 自动头）、`src/assets/`
- `tests/` — pytest 套件（含 `test_repository`、`test_csrf`、`test_output_safety`、编排/API/安全等；实时列表以 `pytest --collect-only -q` 为准）
- `config/settings.yaml` — 兼容性/参考标记，**不参与运行时加载**；运行配置来自环境变量与仓库根 `.env`（`core/config.py`）
- `scripts/` — `run_tests.sh`、`chat.sh`、`cli_chat.py` 等
- `release/` — 便携发布包文件：一键启动器（`start.py`/`start.sh`/`start.bat`）、静态服务入口（`run.py`，`uvicorn release.run:app`）、随包分发说明（`RELEASE.md`）；由 `scripts/build_release.py` 打包为 `dist_release/memoria-<version>.zip`
- `data/`、`docs/` — 运行时数据与文档

## 构建、测试与开发命令

后端（仓库根目录）：

```bash
source .venv/bin/activate
uvicorn memoria.main:app --host 127.0.0.1 --port 8001   # 启动 API
pytest                                                    # 全部测试
pytest tests/test_core.py                                 # 单模块
bash scripts/run_tests.sh                                 # 完整测试脚本
pip install -e ".[dev]"                                   # 开发依赖（pytest/alembic 等）
alembic upgrade head                                      # 迁移 schema
alembic check                                             # 检查 ORM 与迁移漂移
```

前端（`web/`）：

```bash
npm install
npm run dev          # http://127.0.0.1:5173
npm run build
npm run preview
```

## 编码风格与命名

- Python：4 空格缩进，`snake_case` 模块/函数/变量，`PascalCase` 类；遵循 PEP 8；公共 API 建议类型注解。
- JavaScript/React：2 空格缩进，组件 `PascalCase`，props/handlers `camelCase`；函数组件与 hooks。
- 样式以 Tailwind 工具类为主，自定义 CSS 保持精简。
- 配置通过 `.env` / 环境变量；切勿提交密钥。

## 测试约定

- 框架：`pytest`（含 `pytest-asyncio`、`pytest-cov` 等 dev extras）。
- 测试位于 `tests/`，命名 `test_*.py`。
- 测试名 `test_<unit>_<scenario>`，保持可隔离：避免真实网络；mock `llm_client` 与外部服务。
- 变更行为时优先覆盖核心领域（`orchestrator`、`memory_extractor`、`event_*`、安全相关）。

## 提交与 PR

- Conventional Commits：`feat:`、`fix:`、`refactor:`、`docs:`、`test:`、`chore:`。中英文均可，与历史一致。
- 主题行建议不超过 72 字符；非平凡改动补充简短正文。
- PR 应关联 Issue、说明动机，并附测试输出；前端/UI 变更附截图。
- 合并前确保 `pytest` 通过，前端相关改动 `npm run build` 成功。

## 配置与安全

- 从团队密钥库复制 `.env`；源码中禁止硬编码 API key / token。
- 浏览器 Cookie 登录：`memoria-token`（HttpOnly）+ `memoria-csrf`（可读）；Cookie 会话写请求需 `X-CSRF-Token`；`Authorization: Bearer` 客户端豁免 CSRF。
- `MEMORIA_ENV=production` 时会强制 `AUTH_COOKIE_SECURE=true`；本地 HTTP 开发保持 Secure 关闭。
- 输出安全见 `core/output_safety.py`（完整回复 + 流式 `DialogueSafetyStream`）。
- 将 `.venv/`、`data/` 与构建产物排除在提交外（见 `.gitignore`）。
