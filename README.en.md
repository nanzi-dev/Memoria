# Memoria

An immersive role-playing dialogue system powered by large language models. It includes long-term memory, knowledge-base RAG, character relationships, events, a world clock, multi-character conversations, speech interaction, and a web frontend.

[Chinese](README.md) | [English](README.en.md)

[![License: Non-Commercial](https://img.shields.io/badge/License-Non--Commercial-red.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![React 18](https://img.shields.io/badge/React-18-61dafb.svg)](https://react.dev/)

## Highlights

- **Character simulation**: structured character cards, player personas, dynamic language style, and per-user resource isolation.
- **Immersive dialogue**: single-character chat, group chat, SSE streaming, idempotent turns, and logical group threads.
- **Memory system**: short-term history, session summaries, long-term facts, vector recall, and world-time memory curves.
- **World knowledge**: TXT, Markdown, PDF, and DOCX knowledge bases with character or group bindings and source attribution.
- **Relationships and story**: affinity, trust, mood, relationship graphs, event triggers, event chains, and story projections.
- **Secure operation**: cookie CSRF protection, rate limiting, output safety filtering, tenant isolation, and remote resource safeguards.

See [Features](docs/FEATURES.md) for the full capability list.

## Quick Start

### Docker

```bash
cd deploy/docker
cp .env.example .env
# Set LLM_API_KEY, POSTGRES_PASSWORD, and ADMIN_BOOTSTRAP_TOKEN
docker compose up
```

Open http://127.0.0.1:8080. API documentation is available at http://127.0.0.1:8080/docs.

### Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp config/.env.example .env
# Set LLM_BASE_URL, LLM_API_KEY, and LLM_MODEL
uvicorn memoria.main:app --reload --host 127.0.0.1 --port 8001
```

Frontend development:

```bash
cd web
npm install
npm run dev
```

See [Getting Started](docs/GETTING_STARTED.md) and [Configuration](docs/CONFIGURATION.md) for installation, Docker, testing, environment variables, and demo modules.

## Project Layout

```text
Memoria/
|-- src/memoria/     # FastAPI backend, domain logic, and persistence
|-- web/             # React + Vite frontend
|-- tests/           # pytest suite
|-- docs/            # Project documentation
|-- examples/        # Seedable story modules
|-- scripts/         # Development, test, and CLI scripts
|-- deploy/          # Docker deployment files
`-- release/         # Portable release package
```

## Documentation

Detailed documents are currently maintained under `docs/`, primarily in Chinese.

| Document | Contents |
|----------|----------|
| [Getting Started](docs/GETTING_STARTED.md) | Installation, Docker, frontend, tests, and demo modules |
| [Configuration](docs/CONFIGURATION.md) | Models, database, speech, security, and environment variables |
| [Features](docs/FEATURES.md) | Full feature list and behavior boundaries |
| [Architecture](docs/ARCHITECTURE.md) | Architecture, database tables, core flows, and security design |
| [API Reference](docs/API.md) | REST API, request and response examples, and streaming events |
| [Memory Curve](docs/MEMORY_CURVE.md) | World-time decay, reinforcement, sampling, and diagnostics |
| [Roadmap](docs/ROADMAP.md) | Completed features and future plans |
| [FAQ](docs/FAQ.md) | Troubleshooting, debugging, and performance tips |
| [Contributing](docs/CONTRIBUTING.md) | Development workflow, commit conventions, and review standards |
| [Release Guide](release/RELEASE.md) | Portable package startup, configuration, backup, and upgrades |

## Technology

- Backend: Python 3.10+, FastAPI, Pydantic, SQLAlchemy, SQLite / PostgreSQL, and ChromaDB.
- Frontend: React 18, Vite, Tailwind CSS, React Router, D3, and Three.js.
- Models: OpenAI-compatible APIs; separate models can be used for dialogue and lightweight tasks.

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE).

Personal study, research, experimentation, noncommercial organizations, and other noncommercial purposes are permitted. **Commercial use is prohibited.** Commercial use requires prior written permission from the copyright holder.

PolyForm Noncommercial is not an OSI-approved open-source license. It is more accurately described as source-available for noncommercial use only.
