# Memoria

基于大语言模型的沉浸式角色扮演对话系统，支持长期记忆、知识库 RAG、角色关系、事件系统、世界时钟、多角色对话、语音交互和 Web 前端。

[中文](README.md) | [English](README.en.md)

[![License: Non-Commercial](https://img.shields.io/badge/License-Non--Commercial-red.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev/)

## 核心能力

- **角色模拟**：结构化角色卡、玩家角色卡、动态语言风格和用户级资源隔离。
- **沉浸式对话**：单角色对话、多角色群聊、SSE 流式输出、幂等轮次和逻辑群聊线程。
- **记忆系统**：短期历史、会话摘要、长期事实、向量召回和世界时间记忆曲线。
- **世界知识**：TXT、Markdown、PDF、DOCX 知识库，支持角色或群聊绑定和来源追溯。
- **关系与剧情**：好感度、信任度、情绪、角色关系图谱、事件触发、事件链和剧情投影。
- **安全运行**：Cookie CSRF、请求限流、输出安全过滤、用户隔离和远程资源防护。

完整功能说明见 [功能文档](docs/FEATURES.md)。

## 快速开始

### Docker

```bash
cd deploy/docker
cp .env.example .env
# 填写 LLM_API_KEY、POSTGRES_PASSWORD 和 ADMIN_BOOTSTRAP_TOKEN
docker compose up
```

启动后访问 http://127.0.0.1:8080，API 文档位于 http://127.0.0.1:8080/docs。

### 本地开发

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
# 至少填写 LLM_BASE_URL、LLM_API_KEY、LLM_MODEL
uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

前端开发：

```bash
cd web
npm install
npm run dev
```

完整安装、Docker、前端、测试、环境变量和示例模块说明见 [快速开始](docs/GETTING_STARTED.md) 与 [配置说明](docs/CONFIGURATION.md)。

## 项目结构

```text
Memoria/
├── src/memoria/     # FastAPI 后端、领域逻辑和持久化
├── web/             # React + Vite 前端
├── tests/           # pytest 测试
├── docs/            # 项目文档
├── examples/        # 可播种的完整故事模块
├── scripts/         # 开发、测试和 CLI 脚本
├── deploy/          # Docker 部署配置
└── release/         # 便携发布包
```

## 文档

| 文档 | 内容 |
|------|------|
| [快速开始](docs/GETTING_STARTED.md) | 安装、Docker、前端、测试和示例模块 |
| [配置说明](docs/CONFIGURATION.md) | 环境变量、模型、数据库、语音和安全配置 |
| [功能说明](docs/FEATURES.md) | 完整功能清单与行为边界 |
| [系统架构](docs/ARCHITECTURE.md) | 架构、数据表、核心流程和安全设计 |
| [API 文档](docs/API.md) | REST API、请求响应示例和流式事件 |
| [记忆曲线](docs/MEMORY_CURVE.md) | 世界时间衰减、强化、采样和诊断 |
| [开发路线图](docs/ROADMAP.md) | 已完成功能和后续规划 |
| [故障排查](docs/FAQ.md) | 常见问题、调试和性能建议 |
| [贡献指南](docs/CONTRIBUTING.md) | 开发环境、提交规范和代码审查 |
| [发布包说明](release/RELEASE.md) | 便携包启动、配置、备份和升级 |

## 技术栈

- 后端：Python 3.10+、FastAPI、Pydantic、SQLAlchemy、SQLite / PostgreSQL、ChromaDB。
- 前端：React 18、Vite、Tailwind CSS、React Router、D3、Three.js。
- 模型：OpenAI 兼容接口；主对话和轻量任务可使用不同模型。

## 许可证

本项目使用 [PolyForm Noncommercial License 1.0.0](LICENSE)。

仅允许个人学习、研究、实验、非商业组织和其它非商业用途。**禁止任何商业使用**；如需商用，必须事先取得版权持有者的书面授权。

PolyForm Noncommercial 不属于 OSI 认可的开源许可证，更准确的描述是“源码可见、仅限非商业使用”。
