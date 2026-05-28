# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A LangGraph-based multi-agent AI system with supervisor orchestration, context compression, dual memory, SSE streaming, tool execution, and skills injection.

- **Backend**: Python 3.11+, LangGraph + LangChain, FastAPI
- **Frontend**: Vue 3 + Vite + Pinia + TypeScript
- **Storage**: SQLite (sessions/messages/memories) + ChromaDB (vector memory)
- **Tests**: 64 passing (pytest)

## Key Documents

| File | Purpose |
|------|---------|
| `docs/langgraph-agent-v2.md` | Implementation spec — every file, class, function with full code listings |
| `docs/agent-flow-design.md` | Agent flow topology, retry/resilience policy, error handling protocol |

## Architecture (Big Picture)

### Agent (`src/agent/agent.py`)

Core `Agent` class using LangChain native `create_agent` + `astream_events`. Automatic ReAct loop (LLM → tools → LLM until no tool_calls). `reasoning_content` extracted from `chunk.additional_kwargs` (auto-populated by `ChatDeepSeek` via `init_chat_model`). Context compression before first call if token threshold exceeded.

### Graph (`src/agent/graph.py`)

LangGraph `StateGraph` with 2 nodes (think, tools) using `ToolNode`. `create_graph()` factory returns compiled graph. Conditional edges: think → tools or END, tools → think.

### Multi-Agent Supervisor (`src/agent/supervisor.py`)

`CustomSupervisor` with think→plan→dispatch→summarize flow. Supervisor uses `model.astream()` for thinking/planning, then dispatches to sub-agents (`coder`, `researcher`, `analyst`) via `create_agent` + `astream_events` for real-time streaming. `direct` agent name for simple single-tool tasks. Plan parsed via regex from supervisor output. Single-agent results skip summarize phase.

### Context Compression (`src/agent/context/compression.py`)

`ContextCompressor` triggers when token count > max_tokens * threshold (default 0.7). Keeps 5 most recent messages, summarizes older ones via LLM (or fallback truncation).

### Dual Memory (`src/agent/context/memory.py`)

SQLite (structured metadata) + ChromaDB (vector similarity). Dual-write on store; query uses ChromaDB with fallback to empty. `MemoryManager` class handles both.

### Error Handling (`src/agent/error_handler.py`)

`ErrorEnvelope` dataclass → `StructuredAgentError` exception. `CircuitBreaker` (failure_threshold=5, recovery_timeout=60s). `RetryHandler` with exponential backoff. Global instances: `llm_circuit_breaker`, `tool_circuit_breaker`.

### Server (`server.py`)

FastAPI with CORS. Key endpoints:
- `POST /chat` — SSE stream, single agent
- `GET /chat/stream` — GET-based SSE via EventSourceResponse (browser native EventSource)
- `POST /api/orchestrate` — SSE stream, multi-agent supervisor (events include `agent_name`)
- `POST /api/compact` — compress session context (summarize old, keep recent 5)
- `GET /api/tools`, `GET /api/sessions`, `GET /api/skills`
- `POST /api/memory/store`, `POST /api/memory/query`

### Frontend (`ui/`)

Vue 3 + Pinia stores. `ChatTab.vue` renders markdown (marked + highlight.js), KaTeX math, thinking expand/collapse, multi-agent message distinction (colored badges per agent), command autocomplete (`/compact`, `/clear`, `/new`), and mode toggle (single/multi agent). Session persisted to localStorage, auto-restored on page load. `AgentsTab.vue` shows tool cards.

## Commands

### Backend
```bash
pip install -e ".[dev]"          # Install with dev deps
python server.py                 # FastAPI server (port 8000)
python -m src.agent.main --input "msg"  # CLI single-shot
python -m src.agent.main --interactive  # CLI interactive
pytest                           # All tests (64 tests)
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

## Configuration

All config via `.env` (see `.env.example`). Mixed env var prefixes:
- `AGENT_*` — model, context, storage, server settings
- `OPENAI_*` / `ANTHROPIC_*` — provider credentials (no prefix)

Config class uses `Field(alias=...)` (not `env_prefix`) to support both prefix styles.

## Implementation Notes

- Tools are `@tool` decorated LangChain tools, iterated in agent via `tool_map` dict
- Tool results truncated via `truncate_result()` before appending to history (per-tool limits)
- Skills loaded at runtime from `skills/*.md`, injected into system prompt
- Shell safety: `execute_code` checks `DANGEROUS_SHELL_PATTERNS` (from deepagents) before execution
- Session persistence: SQLite tables (sessions, messages) in `checkpoint.py` with auto-migration, compaction support
- Model initialization: `init_chat_model` auto-selects correct class (ChatDeepSeek for reasoning_content, ChatOpenAI, ChatAnthropic)
- Thinking batching: server batches thinking chunks before SSE emission (`_batch_thinking`)
- Audit logging: JSONL files in `memory/audit/{date}.jsonl`

## Integration Testing Policy

When running tests that make **real API calls** (OpenAI, Anthropic, etc.), you MUST:
1. **Present the test plan to the user first** — describe the flow, endpoints, and expected outcomes
2. **Wait for user approval** before executing
3. **Report results** with actual responses, SSE event streams, and any errors

This applies to: `pytest -m integration`, manual `curl` tests against the server, any test that hits external LLM APIs.

Unit tests with mocks can run freely without approval.

## Known Design Gaps

- No Final Answer detection (relies on external Supervisor)
- No consecutive homogeneous call detection (same tool repeated without progress)
- Circuit breaker is in-memory only (not persisted with checkpoint)
- Memory dual-write has no transaction guarantee (ChromaDB failure leaves inconsistency)
