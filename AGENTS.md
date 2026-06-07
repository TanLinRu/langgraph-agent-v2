# langgraph-agent-v2

## Commands

| Command | Use |
|---------|------|
| `pip install -e ".[dev]"` | install with dev deps |
| `python server.py` | start FastAPI (port 8000, `--reload` fails on Windows) |
| `python -m src.agent.main` | CLI single-shot (`--input`) or interactive (`--interactive`) |
| `cd ui && npm run dev` | Vite dev server (port 3000, proxies `/api` to :8000) |
| `cd ui && npx vue-tsc -b && npx vite build` | production build |
| `pytest --cov=src -v` | all tests (140 tests, auto-isolated, no real API keys) |
| `pytest -k "test_name"` | single test |
| `ruff check .` | lint gate. `ruff check . --fix` for auto-fixables |
| `mypy src` | advisory only (pre-existing errors) |

## Architecture

### Backend: 4 execution paths
- **Agent** (`src/agent/agent/core.py`) — single ReAct loop, used by `/chat` endpoint
- **Orchestrator** (`src/agent/orchestrator/core.py`) — LangGraph StateGraph with 5 nodes (plan→wait→dispatch→synthesize→reflect), used by `/api/orchestrate`
- **ACP** (`src/agent/acp_agent.py`) — external CLI agent via JSON-RPC 2.0 over stdio
- **Workflow Engine** (`src/agent/workflow/`) — DynamicGraphEngine executes JSON-defined DAG graphs from `config/workflows.json`, calling Agent/Orchestrator/ACP as node executors; supports approval gates. Triggered via `/api/workflows/*` or `/workflow` chat command.

### Orchestrator StateGraph
- `plan`: builds context summary from history + prior-cycle results, then LLM generates structured JSON `Plan` (steps with agent/task/depends_on). Conditional edge: if `auto_approve=false` and >1 step → `wait`, else → `dispatch`
- `wait`: calls `interrupt()` to suspend graph; user reviews plan via `/api/orchestrate/{session_id}/review`
- `dispatch`: executes sub-agents in DAG order; `depends_on` values are step **indices** (`"0"`, `"1"`), resolved via `step_index_map` to inject upstream outputs as context
- `synthesize`: review/audit node. Conditional edge: `approve→reflect`, `revise→plan` (re-dispatch loop), `reject→__end__`
- `reflect`: anti-pattern detection, saved to `memory/experiences.md`
- Graph paused via `interrupt()` after `wait`; resumed via `Command(resume=...)` on same `thread_id`

### Key packages
- `orchestrator/` — core.py (StateGraph), planner.py (Plan/Step/GraphState models), tools.py (SubAgentTool, ACPSubAgentTool)
- `workflow/` — DynamicGraphEngine (configurable JSON-defined DAG graphs), command_dispatcher.py (/workflow and /wf commands), context_manager.py, checkpoint_manager.py, graph_config_manager.py
- `eval/` — offline regression evaluation framework: case_builder.py, runner.py, assertions.py, analyzer.py (5-dimension), storage.py, cli.py, models.py
- `db/` — connection.py (auto-migration), sessions.py, messages.py, tasks.py, tools.py (save_metrics/load_metrics), compact.py
- `agent/` — core.py (Agent class), streaming.py (file ref extraction)
- `acp/` — client.py (ACPNativeClient: JSON-RPC over stdio subprocess)
- `config_manager.py` — singleton with 5s hot-reload polling on `config/*.json`
- `error_handler.py` — circuit breaker + structured error envelope for agent/tool errors
- `events.py` — EventType enum + make_event factory (14 event types)

### Config
- `.env` → `AgentConfig` (`src/agent/config.py`). All fields nullable; `resolve_model()` throws if both API key and env var missing.
- `config/agents.json` — 8 agents (supervisor + 7 sub-agents); ACP agents have `acp_mode: true` + `acp_cli_id`
- `config/acp_agents.json` — external CLI agent definitions (command, timeout, cwd)
- `config/tools.json` — 5 tools (execute_code, read_file, write_file, list_directory, search_files)
- `config/skills.json` — skill metadata with per-agent assignment
- `config/workflows.json` — predefined workflow DAG definitions (nodes with type: agent/approval/finish, edges)
- `ui/.env.development` sets `VITE_API_BASE=http://localhost:8000`
- `config/agents.json` system_prompt for verifier scoped to "only verify claims present in upstream results"

### SSE streaming
- 14 event types: `thinking_start`, `thinking`, `thinking_done`, `tool_call`, `message`, `plan`, `task_update`, `metrics`, `audit_summary`, `summary`, `interrupt`, `permission_request`, `error`, `done`
- `audit_summary` events carry an optional top-level `agent_outputs: {agent_name: full_raw_output}` field
- All events forwarded with `session_id` by `server.py:_passthrough()` which batches micro-events from ACP agents (200 char thinking, 150 char message thresholds)
- Frontend: backpressure queue with MICRO/STEP/MACRO tiers; 120ms STEP_DELAY defers tool_call/message/plan/summary for visual stepping

### Storage
- SQLite `memory/sessions.db` with auto-migration. ChromaDB in `memory/chroma/`. Agent memory in `memory/agent.db`.
- Workflow checkpoints: separate SQLite `memory/workflow_checkpoints.db`.
- Compaction (`compact.py`): marks old messages `compacted=1`, writes LLM summary to `sessions.summary`. `keep` param controls retained turns.
- Metrics: JSON in `sessions.metrics` column. Audit summary: `sessions.audit_summary` column.

## Gotchas

### Import pattern for `resolve_model`
**Must use** `from src.agent import models as _models; _models.resolve_model()` in modules that get mocked in tests (`orchestrator/planner.py`, `orchestrator/core.py`). Direct `from src.agent.models import resolve_model` breaks `unittest.mock.patch("src.agent.models.resolve_model")`.

### `load_history()` vs `load_history_with_meta()`
- Feed `orchestrator.run()` with `load_history_with_meta(session_id)` (returns `list[dict]`). Using `load_history()` (returns `list[BaseMessage]`) causes `'AIMessage' object has no attribute 'get'`.
- Feed `ContextCompressor.compress()` with `load_history()` → `list[BaseMessage]`.

### `create_react_agent` keyword
Use `prompt=` not `system_prompt=` for langgraph 1.1.10+ (`src/agent/tools.py`).

### `allowed_msgpack_modules` registration
`Plan` model must be registered to suppress deserialization warning: `allowed_msgpack_modules: set[Any] = set(); allowed_msgpack_modules.add(Plan)` at module init (`src/agent/orchestrator/core.py`).

### Vue reactivity: never alias a message ref
```ts
// CORRECT:
messages.value[idx].content = (messages.value[idx].content || '') + chunk
// WRONG: bypasses Vue Proxy
const m = messages.value[idx]; m.content += chunk
```
Applies to all 3 send paths in `streamManager.ts`.

### SSE stream must reconcile task state on end
All 3 `finally` blocks call `msg.reconcileStreamEnd()` + `_processPendingMessages()`. **Skip** reconcile when `pendingReview` is set (HITL interrupt) — otherwise pending tasks are marked `failed` prematurely.

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

### Agent output truncation retry
`SubAgentTool._arun` checks `_is_truncated()` (heuristic: ends mid-sentence, missing closing code fence, or abrupt cutoff patterns). Retries once with "Continue from where you left off". Does NOT block downstream agents if retry also truncated.

### DAG dependency resolution
`depends_on` in plan steps are step **indices** (`"0"`, `"1"`), not agent names. `_dispatch_node` builds `step_index_map` keyed by index string to resolve upstream outputs for context injection. The DAG loop tracks `executed_indices` (set of indices), not agent names.

### HITL interrupt flow
- Plan with `auto_approve=false` and >1 step → graph enters `wait` node → `interrupt()` pauses execution
- Server emits `interrupt` event with `{thread_id, plan}`; frontend shows review dialog
- User approves/rejects via `POST /api/orchestrate/{session_id}/review` → calls `orchestrator.resume(thread_id, decision)`
- `submitReview` in frontend handles resumed stream (plan + dispatch + synthesize + reflect)
- `_passthrough` must map step index → agent ID when constructing `interrupt` event data

### Test quirks
- `tests/conftest.py` auto-isolates env vars (mock keys, temp DB paths) — no real API keys needed.
- Orchestrator tests mock `resolve_model` via `unittest.mock.patch("src.agent.models.resolve_model")`. The `from src.agent import models as _models` pattern makes this work.
- Events are imported directly from `src.agent.events` (no `orchestrator/_events.py` shim).
- No CI pipeline — all verification is local.
- Main test files: `test_orchestrator_v2.py` (v2 5-node graph), `test_supervisor.py` (old 3-node graph), `test_eval.py` (eval framework), `test_mock_flow.py` (truncation/memory/skills).
