# langgraph-agent-v2

## Commands

| Command | Use |
|---------|------|
| `pip install -e ".[dev]"` | install with dev deps |
| `python server.py` | start FastAPI (port 8000, `--reload` fails on Windows) |
| `python -m src.agent.main` | CLI single-shot (`--input`) or interactive (`--interactive`) |
| `cd ui && npm run dev` | Vite dev server (port 3000, proxies `/api` to :8000) |
| `cd ui && npx vue-tsc -b && npx vite build` | production build |
| `pytest --cov=src -v` | all tests (auto-isolated, no real API keys needed) |
| `pytest -k "test_name"` | single test |
| `ruff check .` | lint gate. `ruff check . --fix` for auto-fixables |
| `mypy src` | advisory only (pre-existing errors) |

## Architecture

### Backend: 3 execution paths
- **Agent** (`src/agent/agent/core.py`) — single ReAct loop, used by `/chat` endpoint
- **Orchestrator** (`src/agent/orchestrator/core.py`) — LangGraph StateGraph with 3 nodes (supervisor → execute → review), used by `/api/orchestrate`
- **ACP** (`src/agent/acp_agent.py`) — external CLI agent via JSON-RPC 2.0 over stdio

### Key packages
- `orchestrator/` — core.py (StateGraph), planner.py, tools.py (SubAgentTool, ACPSubAgentTool), _events.py. Dead: dispatcher.py, summarizer.py (replaced by StateGraph).
- `db/` — connection.py (auto-migration), sessions.py, messages.py, tasks.py, tools.py (save_metrics/load_metrics), compact.py
- `agent/` — core.py (Agent class), streaming.py
- `acp/` — client.py (ACPNativeClient: JSON-RPC over stdio subprocess)
- `config_manager.py` — singleton with 5s hot-reload polling on `config/*.json`
- `error_handler.py` — circuit breaker + structured error envelope for agent/tool errors
- `events.py` — EventType enum + make_event factory (11 event types)

### Config
- `.env` → `AgentConfig` (`src/agent/config.py`). All fields nullable; `resolve_model()` throws if both API key and env var missing.
- `config/agents.json` — 7 agents; each can override model, temperature, max_tokens. ACP agents have `acp_mode: true` + `acp_cli_id`.
- `config/acp_agents.json` — external CLI agent definitions (command, timeout, cwd)
- `config/tools.json` — 5 tools (execute_code, read_file, write_file, list_directory, search_files)
- `config/skills.json` — skill metadata with per-agent assignment
- `ui/.env.development` sets `VITE_API_BASE=http://localhost:8000`

### SSE streaming
- Event types: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `plan`, `task_update`, `metrics`, `audit_summary`, `summary`, `error`, `done`
- All events forwarded with `session_id` injected by `server.py:_passthrough()` which batches micro-events from ACP agents (200 char thinking, 150 char message thresholds)
- Frontend: backpressure queue with MICRO/STEP/MACRO tiers; 120ms STEP_DELAY defers tool_call/message/plan/summary for visual stepping

### Storage
- SQLite `memory/sessions.db` with auto-migration. ChromaDB in `memory/chroma/`. Agent memory in `memory/agent.db`.
- Compaction (`compact.py`): marks old messages `compacted=1`, writes LLM summary to `sessions.summary`. `keep` param controls retained turns.
- Metrics: JSON in `sessions.metrics` column. Audit summary: `sessions.audit_summary` column.

## Gotchas

### Import pattern for `resolve_model`
**Must use** `from src.agent import models as _models; _models.resolve_model()` in modules that get mocked in tests (`orchestrator/planner.py`, `orchestrator/core.py`). Direct `from src.agent.models import resolve_model` breaks `unittest.mock.patch("src.agent.models.resolve_model")`.

### `load_history()` vs `load_history_with_meta()`
- Feed `orchestrator.run()` with `load_history_with_meta(session_id)` (returns `list[dict]`). Using `load_history()` (returns `list[BaseMessage]`) causes `'AIMessage' object has no attribute 'get'`.
- Feed `ContextCompressor.compress()` with `load_history()` → `list[BaseMessage]`.

### Vue reactivity: never alias a message ref
```ts
// CORRECT:
messages.value[idx].content = (messages.value[idx].content || '') + chunk
// WRONG: bypasses Vue Proxy
const m = messages.value[idx]; m.content += chunk
```
Applies to all 3 send paths in `streamManager.ts`.

### SSE stream must reconcile task state on end
All 3 `finally` blocks call `msg.reconcileStreamEnd()` + `_processPendingMessages()`. Missing this leaves sidebar with "处理中" forever.

### `sessionId` sync between stores
- `chat.ts` creates a `sessionId` ref passed to `useStreamManager`; both share the same ref.
- Watcher on `sessionsStore.activeSessionId` calls `stream.abort()` before switching sessions.
- `restoreSession()` only nulls `sessionId` on 404 (not transient errors), to avoid breaking `/compact`.
- `handleCompact()` falls back to `sessionsStore.activeSessionId` as safety net.

### Token estimation
Orchestrator estimates tokens per agent as `len(text) * 1.5` (no real usage_metadata capture). Stored per-agent in `orchestrator/core.py._tokens` dict, emitted in final `metrics` event. All 3 SSE paths accumulate metrics from stream — do not hardcode `tokens: {}` in finally blocks.

### ACP agents
- Configured via `config/acp_agents.json` + `config/agents.json` (must set `acp_mode: true` + `acp_cli_id`).
- Lazy-imported inside `ACPDispatcher.stream()` to avoid circular deps; tests patch `src.agent.acp_agent.get_acp_agent`.
- On Windows, `.ps1` scripts detected via `Get-Command` in `server.py:_command_available()`.
- `@opencode` mention routes directly to `sendACP()` in frontend store, bypassing supervisor.

### Test quirks
- `tests/conftest.py` auto-isolates env vars (mock keys, temp DB paths) — no real API keys needed.
- Orchestrator tests mock `resolve_model` via `unittest.mock.patch("src.agent.models.resolve_model")`. The `from src.agent import models as _models` pattern makes this work.
- No CI pipeline — all verification is local.
