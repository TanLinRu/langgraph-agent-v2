# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A LangGraph-based multi-agent AI system with supervisor orchestration, context compression, dual memory, SSE streaming, tool execution, skills injection, and ACP (Agent Client Protocol) integration for external agents (OpenCode/Claude Code).

- **Backend**: Python 3.11+, LangGraph + LangChain, FastAPI
- **Frontend**: Vue 3 + Vite + Pinia + TypeScript
- **Storage**: SQLite (sessions/messages/memories) + ChromaDB (vector memory)
- **Configuration**: JSON files in `config/` with hot-reload support
- **Tests**: 66 passing (pytest)

## Commands

### Backend
```bash
pip install -e ".[dev]"          # Install with dev deps
python server.py                 # FastAPI server (port 8000)
python -m src.agent.main --input "msg"  # CLI single-shot
python -m src.agent.main --interactive  # CLI interactive
pytest                           # All tests (66 tests)
pytest tests/test_tools.py      # Single test file
pytest -k "test_execute_code"   # Single test by name
pytest --cov=src                # With coverage
ruff check .                    # Lint
mypy src                        # Type check
```

### Frontend
```bash
cd ui
npm install
npm run dev                     # Vite dev server (port 3000, proxies to 8000)
vue-tsc -b && vite build        # Production build
```

## Architecture

### JSON Configuration System (`config/`)

All agent/tool/skill/ACP configurations are stored in JSON files with hot-reload:

- `config/agents.json` — 7 agents (supervisor, coder, researcher, analyst, direct, opencode, claude). Each has: tools list, system_prompt, model override, temperature, max_tokens, enabled flag. ACP agents have `acp_mode: true` and `acp_cli_id` linking to `acp_agents.json`.
- `config/tools.json` — 5 tools with module path, function name, category, icon. Tools: execute_code, read_file, write_file, list_directory, search_files.
- `config/skills.json` — Skill metadata with per-agent assignment and enabled flag.
- `config/acp_agents.json` — ACP agent definitions (replaced clis.json). Each has: command, args, timeout, cwd. Used by `ACPClient` to start external agent processes.

`ConfigManager` (`src/agent/config_manager.py`) loads all configs, caches by mtime, and runs a background watcher thread for hot-reload. Global singleton via `get_config_manager()`. CRUD methods write back to JSON files.

**Per-agent model support**: Each agent in `agents.json` can specify `model` (e.g. `"deepseek:deepseek-chat"`), `temperature`, and `max_tokens`. The supervisor's `_build_agents()` creates per-agent model instances via `resolve_model(config, model_override, temperature, max_tokens)`.

### Core Agent (`src/agent/agent.py`)

`Agent` class uses LangChain native `create_agent` + `astream_events`. Implements automatic ReAct loop (LLM → tools → LLM until no tool_calls). `reasoning_content` extracted from `chunk.additional_kwargs`. Context compression triggers before first call if token threshold exceeded. Emits `file_refs` in message events and `metrics` events.

### Multi-Agent Supervisor (`src/agent/supervisor.py`)

`CustomSupervisor` with think→plan→dispatch→summarize flow:
1. Supervisor uses `model.astream()` for thinking/planning
2. Plan parsed via regex from supervisor output — matches any agent ID in `agents.json`
3. Dispatches to sub-agents via `create_agent` + `astream_events`, each with its own model/tools from config
4. ACP agents dispatched via `ACPClient` + `ACPAgent` wrapper (JSON-RPC over stdio)
5. Emits `task_update` events per agent (running/completed) and final `metrics` event
6. Single-agent results skip summarize phase

### ACP Integration (Agent Client Protocol)

External AI coding agents (OpenCode, Claude Code) are integrated via ACP protocol:

- `src/agent/acp/client.py` — `ACPNativeClient` manages persistent `opencode acp` subprocess. Uses JSON-RPC 2.0 over stdio (stdin/stdout). Supports: `initialize`, `session/new`, `session/load`, `session/prompt` (streaming), `session/cancel`, `session/close`.
- `src/agent/acp_agent.py` — `ACPAgent` wraps `ACPNativeClient` for supervisor integration. Creates sessions, sends prompts, yields SSE-compatible events.
- `src/agent/config_manager.py` — `get_acp_agents()`, `get_acp_agent(id)`, `save_acp_agent()` for CRUD.

**ACP flow**: `opencode acp` starts as subprocess → JSON-RPC handshake (`initialize`) → create session (`session/new`) → send prompt (`session/prompt`) → stream `session/update` notifications (message chunks, tool calls, thinking, metrics) → complete.

**@mention routing**: `@opencode` in chat bypasses supervisor, calls ACP agent directly via `sendACP()` in the frontend store.

### Context Layer

- **Compression** (`src/agent/context/compression.py`): `ContextCompressor` triggers when token count > max_tokens * threshold (default 0.7). Keeps 5 most recent messages, summarizes older ones via LLM. Summary injected into system prompt as `[Previous Conversation Summary]`.
- **Memory** (`src/agent/context/memory.py`): SQLite (structured metadata) + ChromaDB (vector similarity). Dual-write on store; query uses ChromaDB with fallback to empty.

### Server (`server.py`)

FastAPI with CORS. Key endpoints:

**Chat**: `POST /chat` (SSE stream), `GET /chat/stream` (EventSourceResponse), `POST /api/orchestrate` (multi-agent SSE)

**Sessions**: `GET /api/sessions`, `POST /api/sessions`, `GET /api/sessions/{id}`, `DELETE /api/sessions/{id}`, `POST /api/compact`

**Agents**: `GET /api/agents`, `GET /api/agents/{id}`, `POST /api/agents/{id}`, `DELETE /api/agents/{id}`

**ACP**: `GET /api/acp/agents`, `GET /api/acp/config`, `POST /api/acp/send` (SSE stream), `GET /api/acp/sessions/{id}`

**Tools/Skills**: `GET /api/tools`, `GET /api/skills`

**Files**: `GET /api/files/tree?root=`, `GET /api/files/content?path=`

**Memory**: `POST /api/memory/store`, `POST /api/memory/query`, `GET /api/memory/list/{ns}`, `DELETE /api/memory/{ns}/{key}`

**Config**: `POST /api/config/reload`, `GET /health`

### SSE Event Types

| Event | Data | Source |
|-------|------|--------|
| `thinking_start` | `{agent_name}` | agent/supervisor |
| `thinking` | `{data, agent_name}` | agent/supervisor |
| `thinking_done` | `{agent_name}` | agent/supervisor |
| `tool_call` | `[{name, args}]`, `{agent_name}` | agent/supervisor |
| `message` | `{data, file_refs, agent_name}` | agent/supervisor |
| `plan` | `{data, agent_name}` | supervisor only |
| `task_update` | `{agent, task, status}` | supervisor only |
| `metrics` | `{elapsed_ms, agent_calls, tokens}` | agent/supervisor |
| `summary` | `{data, agent_name}` | supervisor only |
| `error` | `{data, session_id}` | server |
| `done` | `{session_id}` | server |

### Frontend (`ui/`)

**Layout**: 3-column (Sidebar 310px | Center flex | Right Panel 360px resizable) + optional FileDrawer overlay.

**Stores** (`ui/src/stores/`):
- `chat.ts` — Messages, SSE streaming, typewriter animation, metrics/taskItems/thinkingChunks state, message queue. Includes `sendACP()` for direct ACP agent calls.
- `sessions.ts` — Multi-session management, activeSessionId, initSession() validates localStorage
- `agents.ts` — Agent list and config management
- `theme.ts` — Dark/light theme toggle with localStorage persistence

**Key Components** (`ui/src/components/`):
- `Sidebar.vue` — Conversation list with search, filter tabs (全部/进行中/已完成), delete slide-in, status indicators
- `ChatTab.vue` — Chat host: ChatHeader + StatusBar + ThinkingPanel + TaskBoard + ChatMessage + InputBar
- `ChatMessage.vue` — Dual-aligned bubbles (user right/accent, agent left/glass+avatar column), streaming cursor, file ref chips
- `ThinkingPanel.vue` — Collapsible thinking display grouped by agent, with streaming cursor
- `TaskBoard.vue` — Supervisor dispatch plan with progress bars
- `RightPanel.vue` — 4 tabs: Monitor (metrics), Agents (config), Tools (library), Files (explorer)
- `FileDrawer.vue` — Resizable overlay with code preview, syntax highlighting, search, tree sidebar
- `InputBar.vue` — Chat input with `/command` autocomplete and `@agent` mention dropdown

**SSE Streaming**: Single-agent uses `fetch + ReadableStream` (POST), multi-agent uses same. Event queue with 120ms backpressure for major events. Dual typewriter systems (message 3chars/15ms, thinking 2chars/15ms) with `pendingDone` pattern.

**Theme**: CSS variables (`:root` dark / `[data-theme="light"]` light), ~60 variables for all colors. Background orbs use `--orb-opacity`. All components use `var(--bg-glass)`, `var(--border)`, `var(--accent)` etc.

### Tools (`src/agent/tools/`)

Dynamically loaded from `config/tools.json` via `importlib`. Each tool is a `@tool`-decorated LangChain function:
- `execute_code` — Python sandbox execution with safety checks
- `read_file`, `write_file`, `list_directory` — File operations
- `search_files` — Glob-based file search

### Session Persistence (`src/agent/checkpoint.py`)

SQLite tables: `sessions`, `messages`, `tool_usage`. Auto-migration for new columns. `save_turn()` saves user + assistant in single transaction. `compact_session()` marks old messages as compacted and saves summary.

## Configuration

**Secrets** via `.env` (see `.env.example`): `AGENT_*` for model/context/storage settings, `OPENAI_*`/`ANTHROPIC_*` for provider credentials.

**Agent/Tool/Skill/ACP config** via `config/*.json` files — loaded by `ConfigManager` with hot-reload (5s polling). API endpoints write changes back to JSON.

**Per-agent model**: Each agent can override global model in `config/agents.json` via `model` field (e.g. `"deepseek:deepseek-chat"`, `"openai:gpt-4o"`).

## Key Documents

| File | Purpose |
|------|---------|
| `README.md` | Project overview, architecture, quick start, API reference |
| `AGENTS.md` | Quick reference for AI agents working in this repo |
| `docs/langgraph-agent-v2.md` | Implementation spec — every file, class, function with full code listings |
| `docs/agent-flow-design.md` | Agent flow topology, retry/resilience policy, error handling protocol |
| `docs/agent-workspace.html` | UI prototype — canonical reference for visual design, animations, layout |

## Integration Testing Policy

When running tests that make **real API calls** (OpenAI, Anthropic, etc.), you MUST:
1. **Present the test plan to the user first** — describe the flow, endpoints, and expected outcomes
2. **Wait for user approval** before executing
3. **Report results** with actual responses, SSE event streams, and any errors

Unit tests with mocks can run freely without approval.

## Gotchas

- `python server.py --reload` may fail on Windows (uvicorn reload issue)
- Set `AGENT_ENABLE_THINKING=false` for DashScope/GLM/DeepSeek (no `reasoning_content` support)
- Windows `.cmd` files need `shell=True` for subprocess — ACP client handles this automatically
- `opencode.json` must be at project root (not `docs/`) and `.opencode/commands/` for custom slash commands
- ACP agents (`opencode`, `claude`) are defined in `config/agents.json` with `acp_mode: true` and linked to `config/acp_agents.json` via `acp_cli_id`
