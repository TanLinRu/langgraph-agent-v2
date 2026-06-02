# langgraph-agent-v2

## Process rules (先读,后做)

1. **不要无限递归读文件** — 优先读配置/文档/README 来理解结构,不要无限制遍历目录树。需要探索时,指定深度(`depth ≤ 2`)。
2. **先同步预期效果,再编码** — 每步执行前,先说出目标、预期结果和验证方式,确认无误后才开始改代码。

## Available skills

- `agent-introspection-debugging` — `.opencode/skills/agent-introspection-debugging/SKILL.md`

Python 3.11+ LangGraph multi-agent system with FastAPI + Vue 3 frontend.

## Commands

| Command | Use |
|---------|-----|
| `pip install -e ".[dev]"` | install with dev deps |
| `python server.py` | start FastAPI (port 8000, `--reload` breaks on Windows) |
| `cd ui && npm run dev` | Vite dev server (port 3000, proxies `/api` to :8000) |
| `cd ui && vue-tsc -b && vite build` | production build |
| `pytest --cov=src -v` | all 72 tests (auto-isolated, no API keys needed) |
| `pytest -k "test_name"` | single test |
| `ruff check .` | lint gate (passes clean). `mypy src` has pre-existing errors, advisory only |

## Architecture

### Agent execution (3 paths)
- **Agent** (`src/agent/agent.py`) — single ReAct loop via `create_agent` + `astream_events`
- **CustomSupervisor** (`src/agent/supervisor.py`) — think→plan→dispatch→summarize, sub-agents from `config/agents.json`
- **StateGraph** (`src/agent/graph.py`) — LangGraph `StateGraph` with `ToolNode`

### SSE streaming
- Backend (`server.py`): `EventSourceResponse` forwards each event as-is — no server-side batching
- Frontend (`ui/src/stores/chat.ts`): 3 send paths — `sendMessage` (single), `sendOrchestrate` (multi), `sendACP` (external CLI)
- `SSE_DELAY_MS = 120` defers major events (`tool_call`, `message`, `plan`, `summary`) for stepped visual effect
- Event types: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `plan`, `task_update`, `metrics`, `summary`, `error`, `done`
- Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`

### Config system
- **`.env`** — secrets/model, loaded by `AgentConfig` (`src/agent/config.py`). See `.env.example` for all keys.
- **`config/*.json`** — agents/tools/skills/ACP agents, loaded by `ConfigManager` with 5s hot-reload polling

### Frontend components
- **TopologyBar** — minimal status line in chat area (no dispatch animation, just `Supervisor · 派发中` dot+text)
- **TaskGraph** (`ui/src/components/TaskGraph.vue`) — SVG supervisor→worker graph in right panel's MonitorPanel "子任务调度", with animated dashed edges for running workers, scan rings, flash-success
- **ConvAvatar** (`ui/src/components/ConvAvatar.vue`) — 5 animation types (breathe/bob/wave/think/work), used in TopologyBar, TaskGraph, ChatMessage, MonitorPanel
- **ChatMessage** — segmented structure: HandoffBadge, ThinkingBlock (inline in bubble, no card border), ToolCallBlock, ToolResultBlock, SummaryBlock, ErrorBlock

### File picker
- `POST /api/files/pick-directory` — PS `FolderBrowserDialog` with proper 503/504 error codes
- `POST /api/files/validate-directory` — check path exists and is readable
- `GET /api/files/browse?path=&depth=&include_files=` — JSON directory tree (skips hidden + `PICKER_SKIP_DIRS` dirs)
- `GET /api/files/drives` — Windows drive roots
- `DirectoryTreeBrowser.vue` — drives grid → lazy tree with breadcrumb and search
- `PICKER_SKIP_DIRS` in `src/agent/file_service.py` — system/noise directories excluded from tree

## Gotchas

### Reactivity: always mutate messages through the array
Never save a local reference to a message object and mutate it. Vue 3 Proxy bypasses local references.

**Correct:** `messages.value[msgIdx].thinking = (messages.value[msgIdx].thinking || '') + chunk`
**Wrong:** `const m = ensureAssistantMsg(agentName); m.thinking = chunk` — UI won't update.

Applies to all 3 send paths (`sendMessage`, `sendOrchestrate`, `sendACP`).

### Stream end must reconcile task state
When a stream ends (error, abort, or natural end), `_reconcileStreamEnd()` (`chat.ts:63`) marks all `running`/`pending` tasks as `failed`. Without this, the sidebar task list shows "处理中" forever while the chat shows "完成". `abort()` also calls `_setSessionStatus('completed')` at `chat.ts:99`.

### SSE delay and the typewriter
Each message has per-index `typewriterState` and `thinkTypeState` (`chat.ts:29-31`). The 120ms SSE delay is for *enqueue timing* — once enqueued, the typewriter produces characters at its own cadence. These are separate mechanisms.

### Env
- `AGENT_ENABLE_THINKING=false` for DashScope/GLM/DeepSeek (no `reasoning_content` support)
- `AGENT_SESSION_TTL_HOURS` defaults to 24 (`config.py:34`) but is **not** in `.env.example` — set explicitly if you need different TTL
- `.env.example` lists all keys; `ui/.env.development` sets `VITE_API_BASE=http://localhost:8000`
- Models: per-agent override format `"provider:model"` (e.g. `"deepseek:deepseek-chat"`) in `models.py`

### ACP agents
- Configured in `config/acp_agents.json` with `command`, `timeout` (600s), `cwd`
- Native mode: persistent JSON-RPC 2.0 stdio connection; falls back to `opencode run --format json`
- On Windows, `.ps1` scripts detected via `Get-Command` (`server.py:135`)
- ACP `tool_call` events with empty `name` filtered out (`acp_agent.py:82`)

### Windows
- `python server.py --reload` — uvicorn reload may fail
- `opencode.json` at project root (not `docs/`)
- `.opencode/commands/` for custom slash commands

### File paths
- DB: `memory/sessions.db` (auto-created)
- Chroma: `memory/chroma/`
- Agent memory DB: `memory/agent.db` (configurable)
- Config: `.env`, `config/*.json`, `skills/*.md` (optional), `opencode.json`
- Background server log: `logs/server.out.log`, stderr in `logs/server.err.log`

### Tests
- `tests/conftest.py` auto-isolates env vars (mock keys, temp DB paths) — no real API keys needed
- Markers: `unit`, `integration`, `slow` (defined in `pyproject.toml`)
- 72 tests across 12 files (as of 2026-06), includes `test_file_service.py` for directory picker
- No CI pipeline exists

### Session
- Session compaction keeps 5 recent messages, marks older as `compacted=1`
- Auto-title: first user message truncated to 50 chars
