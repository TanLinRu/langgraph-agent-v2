# langgraph-agent-v2

## Process rules

1. Read config/docs/README first, not the full tree. Limit glob depth to 2.
2. Say what you're about to do and how you'll verify, then do it.

## Commands

| Command | Use |
|---------|-----|
| `pip install -e ".[dev]"` | install with dev deps |
| `python server.py` | start FastAPI (port 8000, `--reload` likely fails on Windows) |
| `cd ui && npm run dev` | Vite dev server (port 3000, proxies `/api` to :8000) |
| `cd ui && vue-tsc -b && vite build` | production build |
| `pytest --cov=src -v` | all 69 tests (auto-isolated, no API keys needed) |
| `pytest -k "test_name"` | single test |
| `ruff check .` | lint gate (passes clean). `ruff check --fix` for auto-fixables |
| `ruff check . --fix` | auto-fix sortable imports + unused imports |

## Architecture

### Backend: 3 execution paths
- **Agent** (`src/agent/agent/core.py`) — single ReAct loop, used by `/chat` endpoint
- **Orchestrator** (`src/agent/orchestrator/core.py`) — `plan→dispatch→summarize` pipeline, used by `/api/orchestrate`
- **ACP** (`src/agent/acp_agent.py`) — external CLI agent via JSON-RPC 2.0 stdio

### Backend packages
- `orchestrator/` — 5 files: `core.py`, `planner.py`, `dispatcher.py`, `summarizer.py`, `_events.py`
- `db/` — 6 files: `connection.py`, `sessions.py`, `messages.py`, `tasks.py`, `tools.py`, `compact.py`
- `agent/` — 2 files: `core.py`, `streaming.py`
- `events.py` — unified event protocol (`EventType` enum + `make_event` factory)
- `message.py` — `Message` dataclass with `to_langchain()` / `from_db_row()` / `to_frontend_dict()`

### Frontend: composable decomposition
- `useMessageManager()` (`utils/messageManager.ts`) — all message state mutations (add/append/merge/clear)
- `useStreamManager(msg, sessionId)` (`utils/streamManager.ts`) — 3 send paths + abort + typewriter scheduling + backpressure
- `useChatStore` (`stores/chat.ts`) — Pinia shell that delegates to both composables
- `useMarkdown()` (`utils/useMarkdown.ts`) — marked + highlight.js + KaTeX rendering
- ChatMessage → routes to `message/UserMessage.vue` / `SystemMessage.vue` / `AgentMessage.vue`

### Config
- `.env` → `AgentConfig` (`src/agent/config.py`). See `.env.example`.
- `config/*.json` → agents/tools/skills/ACP, loaded by `ConfigManager` with 5s hot-reload polling
- `ui/.env.development` sets `VITE_API_BASE=http://localhost:8000`

### SSE streaming
- Event types: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `plan`, `task_update`, `metrics`, `summary`, `error`, `done`
- Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no`
- Backend server-side: `_passthrough()` batching in `server.py`; all events forwarded with `session_id` injected
- Frontend: backpressure queue with MICRO/STEP/MACRO tiers; 120ms delay defers `tool_call`/`message`/`plan`/`summary` for visual stepping

## Gotchas

### Import pattern for `resolve_model`
**Must use** `from src.agent import models as _models; _models.resolve_model()` in modules that get mocked in tests (`orchestrator/planner.py`, `orchestrator/core.py`). Direct `from src.agent.models import resolve_model` breaks `unittest.mock.patch("src.agent.models.resolve_model")` due to Python import binding leakage.

### `load_history()` returns BaseMessage; `_convert_history` expects dict
- `server.py` **must** use `load_history_with_meta(session_id)` (returns `list[dict]`) when feeding history to `orchestrator.run()`. Using `load_history()` (returns `list[BaseMessage]`) causes `'AIMessage' object has no attribute 'get'` at runtime.
- The compact endpoint uses `load_history()` → `list[BaseMessage]` which is correct for `ContextCompressor.compress()`.

### Vue reactivity: never alias a message ref
```ts
// CORRECT: always index through the array
messages.value[idx].content = (messages.value[idx].content || '') + chunk
// WRONG: Vue Proxy bypasses local references
const m = messages.value[idx]; m.content += chunk
```
Applies to all 3 send paths in `streamManager.ts`.

### SSE stream must reconcile task state on end
When stream ends (error, abort, done), `msg.reconcileStreamEnd()` marks all `running`/`pending` tasks as `failed`. Without this, sidebar shows "处理中" forever. `_processPendingMessages()` is called in all `finally` blocks.

### `sessionId` sync between stores
- `chat.ts` creates a `sessionId` ref and passes it to `useStreamManager`. Both share the same ref.
- Watcher on `sessionsStore.activeSessionId` sets `sessionId` only when values differ.
- `restoreSession()` only nulls `sessionId` on 404 (not transient errors), to avoid breaking `/compact`.
- `handleCompact()` falls back to `sessionsStore.activeSessionId` as safety net.

### ACP agents
- Configured in `config/acp_agents.json` with `command`, `timeout` (600s), `cwd`
- Lazy-imported inside `ACPDispatcher.stream()` to avoid circular deps; tests patch `src.agent.acp_agent.get_acp_agent`
- On Windows, `.ps1` scripts detected via `Get-Command` (`server.py`)

### Session
- DB: `memory/sessions.db` (auto-created). Chroma: `memory/chroma/`. Agent memory: `memory/agent.db`.
- Compaction marks old messages as `compacted=1`, updates `sessions.summary` + `compacted_at`. `keep` parameter controls retained turns.
- Auto-title: first user message truncated to 50 chars.

### Test quirks
- `tests/conftest.py` auto-isolates env vars (mock keys, temp DB paths) — no real API keys needed
- Markers: `unit`, `integration`, `slow` (defined in `pyproject.toml`)
- 69 tests across 10 files (as of 2026-06)
- Orchestrator tests mock `resolve_model` via `unittest.mock.patch("src.agent.models.resolve_model")`. The `from src.agent import models as _models` pattern in `planner.py`/`core.py` makes this work.
- No CI pipeline

### Known pre-existing issues
- `--reload` flag on `python server.py` often fails on Windows (uvicorn reload compatibility)
- `mypy src` has pre-existing errors, advisory-only
- Chunk size warning on Vite build (>500 kB after minification, KaTeX-related)
