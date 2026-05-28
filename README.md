# LangGraph Agent v2

A multi-agent AI system with supervisor orchestration, real-time SSE streaming, thinking animation, context compression, and dual memory.

## Highlights

- **Multi-Agent Orchestration** — Supervisor plans and dispatches to specialized sub-agents (coder, researcher, analyst, direct), each with curated tool sets
- **Real-Time SSE Streaming** — EventSource-based streaming with backpressure queue; thinking content rendered as typewriter animation
- **Thinking Transparency** — LLM reasoning process visible via expand/collapse blocks with character-by-character rendering
- **Context Compression** — Automatic token-aware compression summarizes old messages when context exceeds threshold
- **Dual Memory** — SQLite (structured metadata) + ChromaDB (vector similarity) for persistent knowledge storage
- **Session Persistence** — Full conversation history in SQLite with auto-migration, compaction, and browser localStorage sync
- **Skills System** — Runtime-loaded markdown skill files injected into system prompt

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Vue 3 + Pinia Frontend (port 3000)                 │
│  ChatTab ─ AgentsTab ─ SSE EventSource              │
└────────────────────┬────────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────────┐
│  FastAPI Server (port 8000)                         │
│  /chat  /chat/stream  /api/orchestrate  /api/...    │
├─────────────────────────────────────────────────────┤
│  Agent (single)        │  Supervisor (multi)        │
│  create_agent +        │  think → plan → dispatch   │
│  astream_events        │  → summarize               │
│  ReAct loop            │  coder/researcher/analyst  │
├─────────────────────────────────────────────────────┤
│  Context Layer: compression · memory · checkpoint   │
├─────────────────────────────────────────────────────┤
│  SQLite (sessions/messages)  │  ChromaDB (vectors)   │
└─────────────────────────────────────────────────────┘
```

### Agent Flow

**Single Agent** (`POST /chat`): User message → context compression check → `create_agent` ReAct loop (LLM ↔ tools) → SSE stream with thinking + tool_call + message events.

**Multi-Agent** (`POST /api/orchestrate`): User task → Supervisor thinks + plans → dispatches to sub-agents via `astream_events` → collects results → summarizes (skipped for single-agent tasks).

### SSE Event Types

| Event | Description |
|-------|-------------|
| `thinking_start` | LLM reasoning begins |
| `thinking` | Reasoning content chunk (batched server-side) |
| `thinking_done` | Reasoning complete |
| `tool_call` | Tool invocation with name + args |
| `message` | Final assistant response |
| `plan` | Supervisor execution plan |
| `summary` | Multi-agent result summary |
| `error` | Error occurred |

Events include `agent_name` field (`supervisor`, `coder`, `researcher`, `analyst`, `direct`) for multi-agent differentiation.

## Quick Start

### Backend

```bash
cp .env.example .env
# Edit .env with your API keys

pip install -e ".[dev]"
python server.py
# → http://localhost:8000
```

### Frontend

```bash
cd ui
npm install
npm run dev
# → http://localhost:3000 (proxies API to :8000)
```

### CLI

```bash
python -m src.agent.main --input "What is 2+2?"
python -m src.agent.main --interactive
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/chat` | SSE stream, single agent |
| `GET` | `/chat/stream` | GET-based SSE (browser EventSource) |
| `POST` | `/api/orchestrate` | SSE stream, multi-agent supervisor |
| `POST` | `/api/compact` | Compress session context |
| `GET` | `/api/sessions` | List sessions |
| `GET` | `/api/sessions/{id}` | Get session with messages |
| `DELETE` | `/api/sessions/{id}` | Delete session |
| `GET` | `/api/tools` | List available tools |
| `GET` | `/api/skills` | List loaded skills |
| `POST` | `/api/memory/store` | Store memory entry |
| `POST` | `/api/memory/query` | Query memory by similarity |
| `GET` | `/api/memory/list/{ns}` | List memories in namespace |
| `DELETE` | `/api/memory/{ns}/{key}` | Delete memory entry |
| `GET` | `/health` | Health check |

## Configuration

All config via `.env` (see `.env.example`):

```bash
# Model
AGENT_MODEL_PROVIDER=openai    # openai | anthropic
AGENT_MODEL_NAME=gpt-4o
OPENAI_API_KEY=sk-xxx
OPENAI_BASE_URL=https://api.openai.com/v1

# Context
AGENT_MAX_TOKENS=128000
AGENT_COMPRESSION_THRESHOLD=0.7

# Storage
AGENT_MEMORY_DB_PATH=memory/agent.db
AGENT_CHROMA_PATH=memory/chroma

# Server
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8000
```

Supports any OpenAI-compatible API (DeepSeek, DashScope, GLM, etc.) via `OPENAI_BASE_URL`.

## Development

```bash
# Backend
pytest                           # All tests
pytest tests/test_tools.py      # Single file
pytest -k "test_name"           # Single test
pytest --cov=src                # Coverage
ruff check .                    # Lint
mypy src                        # Type check

# Frontend
cd ui
npm run dev                     # Dev server
vue-tsc -b && vite build        # Production build
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| LLM Framework | LangChain + LangGraph |
| Agent | `create_agent` (ReAct loop) + `astream_events` |
| Server | FastAPI + sse-starlette |
| Frontend | Vue 3 + Pinia + Vite + TypeScript |
| Markdown | marked + highlight.js + KaTeX |
| Storage | SQLite + ChromaDB |
| Config | Pydantic Settings |
