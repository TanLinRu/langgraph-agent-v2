# langgraph-agent-v2

Python 3.11+ LangGraph multi-agent system with FastAPI + Vue 3 frontend.

## Commands
- `pip install -e ".[dev]"` — install with dev dependencies
- `python server.py` — start FastAPI (port 8000, no `--reload` on Windows)
- `python -m src.agent.main --input "msg"` — CLI single-shot
- `python -m src.agent.main --interactive` — CLI interactive mode
- `pytest --cov=src -v` — run all 64 tests with coverage (auto-isolated, no API keys needed)
- `pytest -k "test_name"` — run single test
- `ruff check . && mypy src` — lint + type check (order matters)
- `cd ui && npm run dev` — Vite dev server (port 3000, proxies `/api` to :8000)
- `cd ui && vue-tsc -b && vite build` — production build

## Architecture

### Agent Execution (3 paths)
| Path | File | Use |
|------|------|-----|
| `Agent` (single) | `src/agent/agent.py` | ReAct loop via `create_agent` + `astream_events` |
| `CustomSupervisor` (multi) | `src/agent/supervisor.py` | think→plan→dispatch→summarize, sub-agents from `config/agents.json` |
| `StateGraph` (variant) | `src/agent/graph.py` | LangGraph `StateGraph` with `ToolNode` |

### Config System (dual)
- **`.env`** — secrets/model via Pydantic `AgentConfig` (`src/agent/config.py`). See `.env.example` for all keys.
- **`config/*.json`** — agents/tools/skills/ACP agents, loaded by `ConfigManager` with 5s hot-reload polling.

### Key Modules
- `src/agent/models.py` — `resolve_model()` supports per-agent overrides (e.g. `"deepseek:deepseek-chat"`)
- `src/agent/tools/__init__.py` — tools loaded dynamically from `config/tools.json` via `importlib`
- `src/agent/checkpoint.py` — SQLite at `memory/sessions.db`, auto-migrates columns via `ALTER TABLE` + try/except
- `src/agent/acp_agent.py` / `acp_client.py` — wraps external CLIs (opencode/claude) as agents via JSON-RPC 2.0 ACP protocol
- `src/agent/skills.py` — `config/skills.json` maps agents to `skills/*.md` files (dir may be empty)
- `src/agent/context/compression.py` — token-aware compression at 70% threshold, keeps 5 recent messages
- `src/agent/context/memory.py` — dual SQLite (structured) + ChromaDB (vector)
- `src/agent/config_manager.py` — polls JSON files every 5s for hot-reload

### SSE Streaming
- Backend (`server.py:163`): `_passthrough()` — forwards each event as-is, no server-side batching
- Frontend (`ui/src/stores/chat.ts:14`): `SSE_DELAY_MS = 120` — major events (tool_call, message, plan, summary) are deferred 120ms via `_enqueueEvent()` for stepped visual effect
- Event types: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `plan`, `task_update`, `metrics`, `summary`, `error`, `done`
- Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`

### Frontend Abort
- `ui/src/stores/chat.ts:42`: `_abortController` (AbortController for fetch) + `_currentAbort` (callback for streamChatCallbacks)
- `abort()` at line 57: cancels both, clears all state (`isLoading`, `streamingActive`, `pendingMessages`, `_eventQueue`, timers)

## Gotchas

### Reactivity: always mutate messages through the array
When handling SSE events, **never** save a local reference to a message object and mutate it. Vue 3 wraps pushed objects in a reactive Proxy — mutating the local reference mutates the original object but bypasses the Proxy, so the UI never updates.

**Correct:**
```typescript
messages.value[msgIdx].thinking = (messages.value[msgIdx].thinking || '') + chunk
```
**Wrong:**
```typescript
const m = ensureAssistantMsg(agentName)  // returns the plain object
m.thinking = chunk                        // bypasses Proxy, UI stuck
```
This applies to all 3 send paths (`sendMessage`, `sendOrchestrate`, `sendACP`).

### Env
- `AGENT_ENABLE_THINKING=false` for DashScope/GLM/DeepSeek (no `reasoning_content` support)
- `AGENT_SESSION_TTL_HOURS` defaults to 24 in `config.py:34` but is **NOT** in `.env.example` — set explicitly if you need different TTL
- `.env.example` at project root lists all keys; `ui/.env.development` sets `VITE_API_BASE=http://localhost:8000`

### ACP Agents
- ACP agents (opencode, claude) are configured in `config/acp_agents.json` with `command`, `timeout` (600s), `cwd`
- Native mode uses persistent JSON-RPC 2.0 stdio connection; falls back to `opencode run --format json` on failure
- On Windows, `.ps1` scripts are detected via `_command_available()` in `server.py:135` using `Get-Command`
- ACP tool_call events with empty `name` are filtered out in `src/agent/acp_agent.py:82`

### Windows
- `opencode.json` must be at project root (not `docs/`)
- `.opencode/commands/` for custom slash commands (if using opencode CLI)
- `python server.py --reload` may fail (uvicorn reload issue on Windows)
- ~~`bun` is not available in cmd.exe (only PowerShell via `bun.ps1`)~~ bun has been uninstalled

### File Paths
- DB: `memory/sessions.db` (auto-created)
- Chroma: `memory/chroma/`
- Agent memory DB: `memory/agent.db` (configurable via `AGENT_MEMORY_DB_PATH`)
- Config: `.env`, `config/*.json`, `skills/*.md` (optional), `opencode.json`

### Tests
- `tests/conftest.py` auto-isolates env vars (mock keys, temp DB paths) — no real API keys needed
- Markers: `unit`, `integration`, `slow` (defined in `pyproject.toml`)
- 64 tests across 8 files (as of 2026-05)
- No CI pipeline exists

### Session
- Session compaction keeps 5 recent messages, marks older as `compacted=1`
- Auto-title: first user message truncated to 50 chars
- `update_session_status(session_id, "processing"|"completed")` in `server.py` — frontend syncs via `_setSessionStatus()` in `chat.ts`

## Related config
- `docs/opencode.json` defines 14 sub-agents with per-agent tool permissions (separate from the app's own agent system)
