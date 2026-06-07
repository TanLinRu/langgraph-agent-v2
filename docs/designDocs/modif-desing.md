# Modification Guide: Diff Alignment

> This document describes every code change between the base (`diff/langgraph-agent-v2-main`) and current project. Another agent can use this to replicate changes 1:1.

---

## File 1: `src/agent/checkpoint.py`

### 1.1 Add imports

```python
# Add at top, after existing imports
from datetime import datetime, timedelta, timezone
```

### 1.2 Add constant after `_DB_PATH`

```python
_DB_PATH = Path("memory/sessions.db")

# Keep this many recent messages after compaction
_KEEP_RECENT = 5
```

### 1.3 Add auto-migration in `_get_conn()`

After the `messages` table CREATE TABLE block, before `conn.commit()`:

```python
    # Auto-migrate: add new columns if missing
    for col, dtype, default in [
        ("user_id", "TEXT", "DEFAULT 'default'"),
        ("title", "TEXT", "DEFAULT ''"),
        ("summary", "TEXT", "DEFAULT ''"),
        ("compacted_at", "TIMESTAMP", "DEFAULT NULL"),
    ]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Auto-migrate messages table
    for col, dtype, default in [
        ("thinking", "TEXT", "DEFAULT ''"),
        ("compacted", "INTEGER", "DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE messages ADD COLUMN {col} {dtype} {default}")
        except sqlite3.OperationalError:
            pass
```

### 1.4 Fix `_deserialize_message()` — add missing tool_call `id`

In the `elif role == "ai"` branch, after `tool_calls = json.loads(...)`:

```python
    elif role == "ai":
        tool_calls = json.loads(tool_calls_json) if tool_calls_json else []
        # Ensure each tool_call has required 'id' field
        for i, tc in enumerate(tool_calls):
            if isinstance(tc, dict) and "id" not in tc:
                tc["id"] = f"call_{i}"
        return AIMessage(content=content, tool_calls=tool_calls)
```

### 1.5 Modify `create_session()` — add parameters

```python
def create_session(user_id: str = "default", title: str = "") -> str:
    session_id = str(uuid.uuid4())
    conn = _get_conn()
    conn.execute(
        "INSERT INTO sessions (session_id, user_id, title) VALUES (?, ?, ?)",
        (session_id, user_id, title),
    )
    conn.commit()
    conn.close()
    return session_id
```

### 1.6 Modify `load_history()` — filter compacted

Change the SQL query to add `AND compacted = 0`:

```python
def load_history(session_id: str) -> list[BaseMessage]:
    """Load non-compacted messages for LLM context."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, tool_calls, tool_call_id, name FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    return [_deserialize_message(row) for row in rows]
```

### 1.7 Add `load_history_with_meta()` — new function

```python
def load_history_with_meta(session_id: str) -> list[dict]:
    """Load ALL messages (including compacted) with metadata for frontend restore."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, thinking, tool_calls, compacted, name FROM messages WHERE session_id = ? ORDER BY id",
        (session_id,),
    ).fetchall()
    conn.close()
    result = []
    for role, content, thinking, tool_calls_json, compacted, name in rows:
        entry: dict = {"type": role, "content": content or ""}
        if thinking:
            entry["thinking"] = thinking
        if tool_calls_json:
            try:
                entry["tool_calls"] = json.loads(tool_calls_json)
            except (json.JSONDecodeError, TypeError):
                pass
        if compacted:
            entry["compacted"] = True
        if name:
            entry["name"] = name
        result.append(entry)
    return result
```

### 1.8 Modify `save_turn()` — add thinking/tool_calls parameters

```python
def save_turn(
    session_id: str,
    user_message: str,
    assistant_content: str,
    thinking: str = "",
    tool_calls: str = "",
) -> None:
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, 'human', ?)",
        (session_id, user_message),
    )
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls) VALUES (?, 'ai', ?, ?, ?)",
        (session_id, assistant_content, thinking, tool_calls),
    )
    conn.commit()
    conn.close()
```

### 1.9 Add `save_message()` — new function

```python
def save_message(
    session_id: str,
    role: str,
    content: str,
    thinking: str = "",
    tool_calls: str = "",
    name: str = "",
) -> None:
    """Save a single message (not a turn pair). Used for orchestration intermediate messages."""
    conn = _get_conn()
    if not session_exists(session_id):
        conn.execute("INSERT INTO sessions (session_id) VALUES (?)", (session_id,))
    conn.execute(
        "INSERT INTO messages (session_id, role, content, thinking, tool_calls, name) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, role, content, thinking, tool_calls, name),
    )
    # Auto-title: use first user message (truncated)
    if role == "human":
        row = conn.execute("SELECT title FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row and not row[0]:
            title = content[:50].replace("\n", " ")
            conn.execute(
                "UPDATE sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
                (title, session_id),
            )
    conn.execute(
        "UPDATE sessions SET updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (session_id,),
    )
    conn.commit()
    conn.close()
```

### 1.10 Add `get_session_summary()` — new function

```python
def get_session_summary(session_id: str) -> str:
    conn = _get_conn()
    row = conn.execute("SELECT summary FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""
```

### 1.11 Add `compact_session()` — new function

```python
def compact_session(session_id: str, summary: str) -> int:
    """Mark old messages as compacted (keep in DB but exclude from LLM context).

    Returns the number of messages marked as compacted.
    """
    conn = _get_conn()
    # Count total non-compacted messages
    row = conn.execute(
        "SELECT COUNT(*) FROM messages WHERE session_id = ? AND compacted = 0", (session_id,)
    ).fetchone()
    total = row[0] if row else 0

    if total <= _KEEP_RECENT:
        # Nothing to compact, just save summary
        conn.execute(
            "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP WHERE session_id = ?",
            (summary, session_id),
        )
        conn.commit()
        conn.close()
        return 0

    # Mark all but the most recent _KEEP_RECENT messages as compacted
    conn.execute(
        """UPDATE messages SET compacted = 1 WHERE session_id = ? AND compacted = 0 AND id NOT IN (
            SELECT id FROM messages WHERE session_id = ? AND compacted = 0 ORDER BY id DESC LIMIT ?
        )""",
        (session_id, session_id, _KEEP_RECENT),
    )
    marked = total - _KEEP_RECENT

    conn.execute(
        "UPDATE sessions SET summary = ?, compacted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE session_id = ?",
        (summary, session_id),
    )
    conn.commit()
    conn.close()
    return marked
```

### 1.12 Modify `list_sessions()` — add filtering

```python
def list_sessions(user_id: str | None = None, ttl_hours: int = 0) -> list[dict]:
    conn = _get_conn()
    query = "SELECT session_id, user_id, title, created_at, updated_at, summary, compacted_at FROM sessions"
    params: list = []

    conditions = []
    if user_id:
        conditions.append("user_id = ?")
        params.append(user_id)
    if ttl_hours > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        conditions.append("updated_at > ?")
        params.append(cutoff)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY updated_at DESC"

    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [
        {
            "session_id": r[0],
            "user_id": r[1],
            "title": r[2],
            "created_at": r[3],
            "updated_at": r[4],
            "summary": r[5] or "",
            "compacted_at": r[6],
        }
        for r in rows
    ]
```

---

## File 2: `src/agent/config.py`

### 2.1 Add session TTL field

After `agent_server_port`:

```python
    # ── Session ──────────────────────────────────────────────────
    agent_session_ttl_hours: int = Field(default=24, alias="AGENT_SESSION_TTL_HOURS")
```

### 2.2 Add convenience property

At the end of the class:

```python
    @property
    def session_ttl_hours(self) -> int:
        return self.agent_session_ttl_hours
```

---

## File 3: `src/agent/models.py`

### 3.1 Replace entire file — use `init_chat_model`

Replace the entire file with:

```python
from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from src.agent.config import AgentConfig


def resolve_model(config: AgentConfig) -> BaseChatModel:
    """使用 init_chat_model 统一初始化，根据 provider 前缀自动选择正确的模型类。

    例如：
    - "deepseek:deepseek-chat" → ChatDeepSeek（支持 reasoning_content）
    - "openai:gpt-4o" → ChatOpenAI
    - "anthropic:claude-sonnet-4-5" → ChatAnthropic
    """
    model_id = f"{config.model_provider}:{config.model_name}"

    # Anthropic 使用独立的 API key
    if config.model_provider == "anthropic":
        return init_chat_model(
            model_id,
            anthropic_api_key=config.anthropic_api_key,
        )

    # OpenAI 兼容接口（含 DeepSeek、OpenRouter 等）
    return init_chat_model(
        model_id,
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
    )
```

**关键变化**：
- 删除手动 `ChatOpenAI`/`ChatAnthropic` 构造
- `init_chat_model` 根据 `model_id` 前缀（如 `"deepseek:"`）自动选择正确的模型类
- `ChatDeepSeek` 自动提取 `reasoning_content` 到 `additional_kwargs`，无需手动处理
- `ChatOpenAI` 不提取 `reasoning_content`（文档明确声明），用 DeepSeek 时必须用 `ChatDeepSeek`

---

## File 4: `src/agent/prompts/system_prompt.py`

### 4.1 Replace `SUPERVISOR_PROMPT`

```python
SUPERVISOR_PROMPT = """You are a supervisor managing a team of specialized agents:

- **coder**: Expert at writing and executing code. Use for programming tasks, debugging, code generation.
- **researcher**: Expert at finding information. Use for searching files, looking up documentation, gathering data.
- **analyst**: Expert at data analysis. Use for processing data, generating insights, creating reports.
- **direct**: Execute simple tasks directly without dispatching to sub-agents. Use ONLY for trivial tasks that need a single tool call (e.g., "run this code", "read this file").

When given a task:

1. THINK carefully about what needs to be done. Consider dependencies and the best order of operations.
2. After thinking, you will be asked to produce a PLAN. Output the plan using this exact format:

## Plan
- agent_name: description of the subtask

Where agent_name is one of: direct, coder, researcher, analyst.

Rules:
- Use **direct** for simple, single-step tasks (e.g., "print current time in Python", "read file X")
- Use **coder/researcher/analyst** for tasks that require reasoning, multi-step tool use, or specialized expertise
- Each subtask should be self-contained and clear
- For complex tasks, break into multiple subtasks across different agents
- If a task only needs one agent, just list one step
- Do NOT include any other text in your plan response besides the plan itself"""
```

---

## File 5: `src/agent/supervisor.py`

**Complete rewrite.** Replace the entire file with the `CustomSupervisor` implementation.

Key changes:
- `SupervisorManager` class removed
- `create_default_supervisor()` now returns `CustomSupervisor`
- New `CustomSupervisor` class with think+plan+dispatch+summarize flow
- **子代理使用 `create_agent` + `astream_events`**（LangChain 原生流式 ReAct 循环）
- **Supervisor 自身使用 `model.astream()`**（替代原始 `openai.AsyncOpenAI` 客户端）
- `reasoning_content` 通过 `chunk.additional_kwargs.get("reasoning_content")` 提取（由 `ChatDeepSeek` 自动填充）
- Plan parsing via regex `_PLAN_RE`
- `_CODER_TOOLS`, `_RESEARCHER_TOOLS`, `_ANALYST_TOOLS` tool subsets
- `direct` agent name = execute code directly without sub-agent LLM
- Single-agent results skip summarize phase
- 子代理 `_invoke_agent_stream` 流式推送 thinking + tool_call + message 事件

**核心架构变化**：

```python
# 之前：原始 OpenAI 客户端
self.raw_client = openai.AsyncOpenAI(api_key=..., base_url=...)
stream = await self.raw_client.chat.completions.create(messages=..., stream=True)
async for chunk in stream:
    reasoning = getattr(delta, "reasoning_content", None)  # 手动提取

# 现在：LangChain 原生 API
self.model = resolve_model(config)  # init_chat_model → ChatDeepSeek
async for chunk in self.model.astream(messages):
    reasoning = chunk.additional_kwargs.get("reasoning_content")  # 自动提取
```

**子代理流式化**：

```python
# 之前：ainvoke 阻塞等待
result = await agent_graph.ainvoke({"messages": [HumanMessage(content=subtask)]})
# 完成后才返回结果，中间过程不可见

# 现在：astream_events 流式推送
async for event in agent_graph.astream_events({"messages": [...]}, version="v2"):
    if event["event"] == "on_chat_model_stream":
        chunk = event["data"]["chunk"]
        reasoning = chunk.additional_kwargs.get("reasoning_content")
        yield {"type": "thinking", "data": reasoning, "agent_name": agent_name}
    elif event["event"] == "on_tool_start":
        yield {"type": "tool_call", "data": [...], "agent_name": agent_name}
```

See full file: `src/agent/supervisor.py`

---

## File 6: `server.py`

### 6.1 Add imports

```python
from src.agent.checkpoint import (
    compact_session as db_compact_session,
    create_session,
    delete_session,
    get_session_summary,
    list_sessions as db_list_sessions,
    load_history,
    load_history_with_meta,
    save_message,
    save_turn,
)
from src.agent.context.compression import ContextCompressor
from src.agent.supervisor import CustomSupervisor
```

### 6.2 Add supervisor singleton

```python
supervisor_instance: CustomSupervisor | None = None

def get_supervisor() -> CustomSupervisor:
    global supervisor_instance
    if supervisor_instance is None:
        supervisor_instance = CustomSupervisor(config)
    return supervisor_instance
```

### 6.3 Add `CompactRequest` model

```python
class CompactRequest(BaseModel):
    session_id: str
```

### 6.4 Add `_batch_thinking()` — SSE thinking batching

```python
# ── Thinking Batching ──────────────────────────────────────────

_THINK_BATCH_CHARS = 5  # flush thinking buffer every N chars (typing effect)


async def _batch_thinking(source):
    """Batch thinking chunks so the frontend receives fewer, larger events."""
    think_buf = ""
    think_meta: dict = {}  # agent_name etc. from first thinking chunk
    _in_count = 0
    _out_count = 0

    async for event in source:
        if event["type"] == "thinking":
            _in_count += 1
            think_buf += event.get("data", "")
            if not think_meta:
                think_meta = {k: v for k, v in event.items() if k not in ("type", "data")}
            if len(think_buf) >= _THINK_BATCH_CHARS:
                _out_count += 1
                logger.info("[BATCH] flush #%d: %d chars (in=%d)", _out_count, len(think_buf), _in_count)
                yield {"type": "thinking", "data": think_buf, **think_meta}
                think_buf = ""
                think_meta = {}
        else:
            # Flush pending thinking before yielding non-thinking event
            if think_buf:
                _out_count += 1
                logger.info("[BATCH] pre-flush #%d: %d chars before %s", _out_count, len(think_buf), event["type"])
                yield {"type": "thinking", "data": think_buf, **think_meta}
                think_buf = ""
                think_meta = {}
            yield event

    # Flush remaining thinking at stream end
    if think_buf:
        _out_count += 1
        logger.info("[BATCH] final-flush #%d: %d chars", _out_count, len(think_buf))
        yield {"type": "thinking", "data": think_buf, **think_meta}

    logger.info("[BATCH] done: %d input chunks → %d output batches", _in_count, _out_count)
```

### 6.5 Modify `POST /chat` stream — add batching + save thinking/tool_calls

Wrap generator with `_batch_thinking()`, accumulate thinking/tool_calls, save with `save_turn()`:

```python
    async def stream():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        _saved = False
        _sse_idx = 0
        async for event in _batch_thinking(get_agent().run(request.message, memory_context, history)):
            event["session_id"] = session_id
            _sse_idx += 1
            if event["type"] == "thinking":
                thinking_content += event.get("data", "")
            elif event["type"] == "tool_call":
                tool_calls_data = json.dumps(event.get("data", []), ensure_ascii=False)
            elif event["type"] == "message":
                assistant_content = event["data"]
                if assistant_content and not _saved:
                    save_turn(session_id, request.message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)
                    _saved = True
            payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            logger.info("[SSE-TRACE] %s server yielding #%d: type=%s bytes=%d", f"{time.time():.3f}", _sse_idx, event["type"], len(payload))
            yield payload
            await asyncio.sleep(0)

        if assistant_content and not _saved:
            save_turn(session_id, request.message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)
```

### 6.6 Modify `GET /chat/stream` — same pattern

Same changes as 6.5 but for the GET endpoint:

```python
    async def event_generator():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        _saved = False
        _sse_idx = 0
        async for event in _batch_thinking(get_agent().run(message, memory_context, history)):
            event["session_id"] = sid
            _sse_idx += 1
            if event["type"] == "thinking":
                thinking_content += event.get("data", "")
            elif event["type"] == "tool_call":
                tool_calls_data = json.dumps(event.get("data", []), ensure_ascii=False)
            elif event["type"] == "message":
                assistant_content = event["data"]
                if assistant_content and not _saved:
                    save_turn(sid, message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)
                    _saved = True
            logger.info("[SSE-TRACE] %s GET-stream yielding #%d: type=%s", f"{time.time():.3f}", _sse_idx, event["type"])
            yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}

        if assistant_content and not _saved:
            save_turn(sid, message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)

        yield {"event": "done", "data": json.dumps({"type": "done", "session_id": sid}, ensure_ascii=False)}
```

### 6.7 Rewrite `POST /api/orchestrate`

Replace the entire orchestrate endpoint:

```python
@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    session_id = request.session_id or create_session()
    supervisor = get_supervisor()

    async def stream():
        assistant_content = ""
        _user_saved = False
        try:
            async for event in _batch_thinking(supervisor.run(request.task)):
                event["session_id"] = session_id

                # Save each event to DB (fault-tolerant)
                try:
                    if not _user_saved:
                        save_message(session_id, "human", request.task)
                        _user_saved = True

                    if event["type"] == "thinking":
                        save_message(session_id, "ai", "", thinking=event.get("data", ""), name="thinking")
                    elif event["type"] == "plan":
                        save_message(session_id, "ai", event.get("data", ""), name="plan")
                    elif event["type"] == "tool_call":
                        tool_calls_json = json.dumps(event.get("data", []), ensure_ascii=False)
                        agent = event.get("agent_name", "supervisor")
                        save_message(session_id, "ai", "", tool_calls=tool_calls_json, name=agent)
                    elif event["type"] == "message":
                        agent = event.get("agent_name", "supervisor")
                        save_message(session_id, "ai", event.get("data", ""), name=agent)
                    elif event["type"] == "summary":
                        assistant_content = event["data"]
                        save_message(session_id, "ai", assistant_content, name="summary")
                except Exception as save_err:
                    logger.warning("[Orchestrate] save_message failed: %s", save_err)

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
```

### 6.8 Modify `GET /api/sessions` — add filtering

```python
@app.get("/api/sessions")
async def list_sessions_endpoint(user_id: str | None = Query(None)):
    sessions = db_list_sessions(user_id=user_id, ttl_hours=config.session_ttl_hours)
    return {"sessions": sessions}
```

### 6.9 Modify `GET /api/sessions/{session_id}` — return meta + summary

```python
@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    messages = load_history_with_meta(session_id)
    summary = get_session_summary(session_id)
    if not messages and not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": messages, "summary": summary}
```

### 6.10 Add `POST /api/compact` — new endpoint

```python
@app.post("/api/compact")
async def compact_endpoint(request: CompactRequest):
    """Compact a session: summarize old messages, keep recent ones."""
    history = load_history(request.session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found or empty")

    # Use the compression module to generate a summary
    compressor = ContextCompressor(config)
    summary_text, recent = await compressor.compress(history)

    # Persist: delete old messages, save summary
    deleted = db_compact_session(request.session_id, summary_text)

    return {
        "session_id": request.session_id,
        "summary": summary_text,
        "deleted_messages": deleted,
        "kept_messages": len(recent),
    }
```

---

## File 7: `ui/src/utils/api.ts`

### 7.1 Add fields to `ChatMessage`

```typescript
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string
  toolCalls?: Array<{ name: string; args: Record<string, unknown> }>
  agentName?: string
  thinking?: string
  isSummary?: boolean
  isPlan?: boolean
  compacted?: boolean
}
```

### 7.2 Replace `listSessions()` — add `SessionInfo` type

```typescript
export interface SessionInfo {
  session_id: string
  user_id: string
  title: string
  created_at: string
  updated_at: string
  summary: string
  compacted_at: string | null
}

export async function listSessions(): Promise<SessionInfo[]> {
  const res = await fetch(`${API_BASE}/api/sessions`)
  const data = await res.json()
  return data.sessions
}
```

### 7.3 Add `restoreSession()` — new function

```typescript
export async function restoreSession(sessionId: string): Promise<{
  session_id: string
  messages: Array<{ type: string; content: string; thinking?: string; tool_calls?: Array<{ name: string; args: Record<string, unknown> }>; name?: string; compacted?: boolean }>
  summary: string
}> {
  const res = await fetch(`${API_BASE}/api/sessions/${sessionId}`)
  if (!res.ok) throw new Error(`Session not found: ${sessionId}`)
  return res.json()
}
```

### 7.4 Add `compactSession()` — new function

```typescript
export async function compactSession(sessionId: string): Promise<{
  session_id: string
  summary: string
  deleted_messages: number
  kept_messages: number
}> {
  const res = await fetch(`${API_BASE}/api/compact`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Compact failed: ${res.status}`)
  return res.json()
}
```

---

## File 8: `ui/src/stores/chat.ts`

### 8.1 Add imports

```typescript
import { defineStore } from 'pinia'
import { ref, watch } from 'vue'
import {
  streamChatCallbacks,
  streamOrchestrate,
  compactSession,
  restoreSession as apiRestoreSession,
  type ChatMessage,
} from '../utils/api'

const SESSION_KEY = 'chat_session_id'
const SSE_DELAY_MS = 120  // delay before major SSE events (tool_call, message, plan, summary)
```

### 8.2 Add store state + SSE queue + localStorage

After `sessionId`:

```typescript
  const mode = ref<'single' | 'multi'>('single')

  // SSE backpressure: major events queued with 120ms delay
  let _eventQueue: Array<() => void> = []
  let _eventTimer: ReturnType<typeof setTimeout> | null = null

  // Thinking: backend batches chunks, frontend renders directly
  let _thinkChunkCount = 0

  function _enqueueEvent(fn: () => void, label?: string) {
    _eventQueue.push(fn)
    console.log(`[CHAT:QUEUE] enqueued: ${label || 'fn'}, queue=${_eventQueue.length}`)
    if (!_eventTimer) {
      _eventTimer = setTimeout(() => {
        const next = _eventQueue.shift()!
        console.log(`[CHAT:QUEUE] fired: queue remaining=${_eventQueue.length}`)
        next()
        _eventTimer = null
        if (_eventQueue.length > 0) _scheduleNextMajor()
      }, SSE_DELAY_MS)
    }
  }

  function _scheduleNextMajor() {
    if (_eventTimer) return
    _eventTimer = setTimeout(() => {
      const next = _eventQueue.shift()!
      console.log(`[CHAT:QUEUE] fired: queue remaining=${_eventQueue.length}`)
      next()
      _eventTimer = null
      if (_eventQueue.length > 0) _scheduleNextMajor()
    }, SSE_DELAY_MS)
  }

  function _flushEventQueue() {
    console.log(`[CHAT:QUEUE] flush all: ${_eventQueue.length} queued events`)
    for (const fn of _eventQueue) fn()
    _eventQueue = []
    if (_eventTimer) { clearTimeout(_eventTimer); _eventTimer = null }
  }

  // Restore sessionId from localStorage on init
  const savedSessionId = localStorage.getItem(SESSION_KEY)
  if (savedSessionId) {
    sessionId.value = savedSessionId
  }

  // Persist sessionId to localStorage when it changes
  watch(sessionId, (id) => {
    if (id) {
      localStorage.setItem(SESSION_KEY, id)
    } else {
      localStorage.removeItem(SESSION_KEY)
    }
  })
```

### 8.3 Add `restoreSession()` — new function

```typescript
  async function restoreSession() {
    const id = sessionId.value
    if (!id) return

    try {
      console.log(`[CHAT] restoring session: ${id}`)
      const data = await apiRestoreSession(id)
      if (!data.messages || data.messages.length === 0) {
        console.log('[CHAT] restore: no messages')
        return
      }

      // Convert backend messages to ChatMessage format
      // Skip intermediate orchestration events (thinking, empty tool_call)
      const restored: ChatMessage[] = []
      for (const m of data.messages) {
        if (m.type === 'human') {
          const msg: ChatMessage = { role: 'user', content: m.content }
          if ((m as any).compacted) msg.compacted = true
          restored.push(msg)
        } else if (m.type === 'ai') {
          const name = (m as any).name as string | undefined
          const hasContent = m.content && m.content.trim()
          const hasThinking = !!(m as any).thinking
          const hasToolCalls = !!(m as any).tool_calls
          const isPlan = name === 'plan'
          const isSummary = name === 'summary'
          const isThinkingOnly = name === 'thinking'

          // Skip thinking-only messages (thinking content is embedded in the final message)
          if (isThinkingOnly) continue
          // Skip tool_call messages with no content (intermediate events)
          if (hasToolCalls && !hasContent && !isPlan && !isSummary) continue

          const msg: ChatMessage = { role: 'assistant', content: m.content || '' }
          if (hasThinking) msg.thinking = (m as any).thinking
          if (hasToolCalls) msg.toolCalls = (m as any).tool_calls
          if ((m as any).compacted) msg.compacted = true
          if (isPlan) msg.isPlan = true
          else if (isSummary) msg.isSummary = true
          else if (name && !isThinkingOnly) msg.agentName = name
          restored.push(msg)
        }
      }

      // If there's a summary, prepend it as a system message
      if (data.summary) {
        restored.unshift({
          role: 'system',
          content: `[Compacted context]\n${data.summary}`,
        })
      }

      messages.value = restored
      console.log(`[CHAT] restored ${restored.length} messages (hasSummary=${!!data.summary})`)
    } catch (e: any) {
      // 404 is expected after DB clear — just reset silently
      if (e.message?.includes('404') || e.message?.includes('Not Found')) {
        console.log(`[CHAT] session ${id} not found, clearing sessionId`)
      } else {
        console.warn('[CHAT] restore failed:', e.message)
      }
      sessionId.value = null
    }
  }
```

### 8.4 Modify `sendMessage()` — thinking direct render + major event queue

Replace the thinking handlers:

```typescript
        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          console.log('[CHAT] thinking_start')
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          const msg = ensureAssistantMsg(agentName)
          msg.thinking = (msg.thinking || '') + (event.data as string)
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT] thinking_done: ${_thinkChunkCount} batches`)
```

Wrap `tool_call`, `message`, `summary`, `error` handlers with `_enqueueEvent()`:

```typescript
        } else if (event.type === 'tool_call') {
          _enqueueEvent(() => {
            const msg = ensureAssistantMsg(agentName)
            msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
          }, 'tool_call')
        } else if (event.type === 'message') {
          _enqueueEvent(() => {
            const msg = ensureAssistantMsg(agentName)
            const fullContent = event.data as string
            if (msgIdx >= 0 && fullContent) {
              typewriterState.value[msgIdx] = { display: '', full: fullContent, done: false }
              msg.content = ''
              _startTypewriter()
            } else {
              msg.content = fullContent
            }
          }, 'message')
        } else if (event.type === 'summary') {
          _enqueueEvent(() => {
            messages.value.push({
              role: 'assistant',
              content: event.data as string,
              agentName: 'supervisor',
              isSummary: true,
            })
            assistantMsg = null
            msgIdx = -1
          }, 'summary')
        } else if (event.type === 'error') {
          _enqueueEvent(() => {
            messages.value.push({ role: 'system', content: `Error: ${event.data}` })
          }, 'error')
```

Modify `onDone`:

```typescript
      () => {
        console.log('[CHAT] stream done')
        _flushEventQueue()
        isLoading.value = false
        streamingActive.value = false
      },
```

### 8.5 Rewrite `sendOrchestrate()` — per-agent messages + typing delay

Replace the entire function:

```typescript
  async function sendOrchestrate(task: string) {
    messages.value.push({ role: 'user', content: task })
    isLoading.value = true

    // Track per-agent state
    let supervisorMsg: ChatMessage | null = null
    const agentMsgs: Record<string, ChatMessage> = {}

    function getSupervisorMsg(): ChatMessage {
      if (!supervisorMsg) {
        supervisorMsg = { role: 'assistant', content: '', agentName: 'supervisor' }
        messages.value.push(supervisorMsg)
        streamingActive.value = true
      }
      return supervisorMsg
    }

    function getAgentMsg(agentName: string): ChatMessage {
      if (!agentMsgs[agentName]) {
        const msg: ChatMessage = { role: 'assistant', content: '', agentName }
        agentMsgs[agentName] = msg
        messages.value.push(msg)
        streamingActive.value = true
      }
      return agentMsgs[agentName]
    }

    try {
      for await (const event of streamOrchestrate(task, sessionId.value || undefined)) {
        if (event.session_id) {
          sessionId.value = event.session_id as string
        }

        const agentName = (event.agent_name as string) || 'supervisor'
        const isMajor = event.type === 'tool_call' || event.type === 'message'
          || event.type === 'plan' || event.type === 'summary' || event.type === 'error'

        // Thinking: buffer + drain at fixed rate
        if (event.type === 'thinking_start') {
          _thinkChunkCount = 0
          console.log('[CHAT:ORCH] thinking_start')
        } else if (event.type === 'thinking') {
          _thinkChunkCount++
          const msg = getSupervisorMsg()
          msg.thinking = (msg.thinking || '') + (event.data as string)
          // Small delay for typing effect
          await new Promise(r => setTimeout(r, 30))
          continue
        } else if (event.type === 'thinking_done') {
          console.log(`[CHAT:ORCH] thinking_done: ${_thinkChunkCount} batches`)
          await new Promise(r => setTimeout(r, 0))
          continue
        }

        // Major events: delay for stepped visual effect
        if (isMajor) {
          await new Promise(r => setTimeout(r, SSE_DELAY_MS))
        }

        if (event.type === 'plan') {
          console.log('[CHAT:ORCH] plan')
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isPlan: true,
          })
        } else if (event.type === 'tool_call') {
          console.log(`[CHAT:ORCH] tool_call: ${agentName}`)
          const msg = getAgentMsg(agentName)
          msg.toolCalls = event.data as Array<{ name: string; args: Record<string, unknown> }>
        } else if (event.type === 'message') {
          console.log(`[CHAT:ORCH] message: ${agentName}`)
          const msg = getAgentMsg(agentName)
          msg.content = event.data as string
        } else if (event.type === 'summary') {
          console.log('[CHAT:ORCH] summary')
          messages.value.push({
            role: 'assistant',
            content: event.data as string,
            agentName: 'supervisor',
            isSummary: true,
          })
        } else if (event.type === 'error') {
          messages.value.push({ role: 'system', content: `Error: ${event.data}` })
        }
      }
      console.log('[CHAT:ORCH] stream done')
    } catch (e: any) {
      messages.value.push({ role: 'system', content: `Connection error: ${e.message}` })
    } finally {
      isLoading.value = false
      streamingActive.value = false
    }
  }
```

### 8.6 Modify `clearMessages()` — add queue cleanup

```typescript
  function clearMessages() {
    messages.value = []
    sessionId.value = null
    typewriterState.value = {}
    if (_typeTimer) { clearInterval(_typeTimer); _typeTimer = null }
    _eventQueue = []
    if (_eventTimer) { clearInterval(_eventTimer); _eventTimer = null }
  }
```

### 8.7 Add `newSession()`, `handleCompact()`, `send()` — new functions

```typescript
  function newSession() {
    clearMessages()
    // sessionId is now null, next send will create a new session
  }

  async function handleCompact(): Promise<string> {
    const id = sessionId.value
    if (!id) return 'No active session to compact.'

    isLoading.value = true
    try {
      const result = await compactSession(id)
      // Reload the compacted session to get the updated state
      await restoreSession()
      // restoreSession replaces messages, so return the compact info
      // which will be pushed as a system message AFTER restore
      return `Session compacted: removed ${result.deleted_messages} old messages, kept ${result.kept_messages} recent.`
    } catch (e: any) {
      return `Compact failed: ${e.message}`
    } finally {
      isLoading.value = false
    }
  }

  async function send(content: string) {
    // Handle slash commands
    if (content.startsWith('/')) {
      const cmd = content.trim().toLowerCase()
      if (cmd === '/compact') {
        const result = await handleCompact()
        messages.value.push({ role: 'system', content: result })
        return
      }
      if (cmd === '/clear') {
        clearMessages()
        return
      }
      if (cmd === '/new') {
        newSession()
        return
      }
      // Unknown command
      messages.value.push({ role: 'system', content: `Unknown command: ${cmd}. Available: /compact, /clear, /new` })
      return
    }

    if (mode.value === 'multi') {
      await sendOrchestrate(content)
    } else {
      sendMessage(content)
    }
  }

  // Auto-restore session on store init
  if (sessionId.value) {
    restoreSession()
  }
```

### 8.8 Update return statement

```typescript
  return {
    messages, isLoading, streamingActive, sessionId, mode,
    typewriterState,
    sendMessage, sendOrchestrate, send, clearMessages, newSession, restoreSession,
  }
```

---

## File 9: `ui/src/components/ChatTab.vue`

### 9.1 Add command autocomplete state

After `thinkingLive`:

```typescript
const COMMANDS = [
  { cmd: '/compact', desc: 'Compress session context' },
  { cmd: '/clear', desc: 'Clear all messages' },
  { cmd: '/new', desc: 'Start a new session' },
]

const showCommands = ref(false)
const commandFilter = ref('')
const filteredCommands = ref<typeof COMMANDS>([])

function onInput(e: Event) {
  const val = (e.target as HTMLInputElement).value
  if (val.startsWith('/') && !val.includes(' ')) {
    commandFilter.value = val.toLowerCase()
    filteredCommands.value = COMMANDS.filter(c => c.cmd.startsWith(commandFilter.value))
    showCommands.value = filteredCommands.value.length > 0
  } else {
    showCommands.value = false
  }
}

function selectCommand(cmd: string) {
  input.value = cmd + ' '
  showCommands.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    showCommands.value = false
  }
  if (e.key === 'Tab' && showCommands.value && filteredCommands.value.length) {
    e.preventDefault()
    selectCommand(filteredCommands.value[0].cmd)
  }
}
```

### 9.2 Change `send()` call

```typescript
  await chat.send(msg)  // was: await chat.sendMessage(msg)
```

### 9.3 Add CSS classes to message bubble

```html
:class="['msg', msg.role, { 'is-summary': msg.isSummary, 'is-plan': msg.isPlan, 'is-compacted': msg.compacted }]"
```

### 9.4 Add mode toggle + command dropdown

Before the `<form class="input-bar">`:

```html
    <div class="mode-toggle">
      <button :class="{ active: chat.mode === 'single' }" @click="chat.mode = 'single'">Single Agent</button>
      <button :class="{ active: chat.mode === 'multi' }" @click="chat.mode = 'multi'">Multi Agent</button>
    </div>
    <div class="command-dropdown" v-if="showCommands">
      <div v-for="c in filteredCommands" :key="c.cmd" class="command-item" @mousedown.prevent="selectCommand(c.cmd)">
        <span class="command-cmd">{{ c.cmd }}</span>
        <span class="command-desc">{{ c.desc }}</span>
      </div>
    </div>
```

### 9.5 Update input element

```html
<input v-model="input" placeholder="Type a message or / for commands..." :disabled="chat.isLoading" @input="onInput" @keydown="onKeydown" @blur="showCommands = false" />
```

### 9.6 CSS changes

Add new CSS rules for:
- `.mode-toggle` — button group for single/multi agent
- `.command-dropdown` / `.command-item` — slash command autocomplete
- `.msg.is-plan` — cyan accent for plan messages
- `.msg.is-compacted` — dashed border, low opacity
- `.msg.system` — neutral styling (was red, now subtle)
- Responsive `@media` rules for mobile

See full `ChatTab.vue` for complete CSS.

---

## File 10: `tests/test_server.py`

### 10.1 Add `test_orchestrate_sse_format`

```python
def test_orchestrate_sse_format(client):
    """Verify /api/orchestrate emits fine-grained SSE events."""
    import server

    mock_supervisor = MagicMock()

    async def mock_run(task):
        yield {"type": "thinking_start", "data": "", "agent_name": "supervisor"}
        yield {"type": "thinking", "data": "thinking...", "agent_name": "supervisor"}
        yield {"type": "thinking_done", "data": "", "agent_name": "supervisor"}
        yield {"type": "plan", "data": "## Plan\n- coder: write code", "agent_name": "supervisor"}
        yield {"type": "tool_call", "data": [{"name": "coder", "args": {"task": "write code"}}], "agent_name": "coder"}
        yield {"type": "message", "data": "code result", "agent_name": "coder"}
        yield {"type": "summary", "data": "Done.", "agent_name": "supervisor"}
        yield {"type": "done"}

    mock_supervisor.run = mock_run

    original = server.supervisor_instance
    server.supervisor_instance = mock_supervisor
    try:
        resp = client.post("/api/orchestrate", json={"task": "test"}, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200

        # Parse SSE events
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                import json
                events.append(json.loads(line[6:]))

        event_types = [e["type"] for e in events if "type" in e]
        assert "thinking_start" in event_types
        assert "plan" in event_types
        assert "tool_call" in event_types
        assert "message" in event_types
        assert "summary" in event_types
        assert "done" in event_types

        # Verify agent_name is present on events
        plan_events = [e for e in events if e.get("type") == "plan"]
        assert len(plan_events) == 1
        assert plan_events[0]["agent_name"] == "supervisor"
    finally:
        server.supervisor_instance = original
```

---

## File 11: `tests/test_supervisor.py` (new file)

Create `tests/test_supervisor.py` with tests for `CustomSupervisor`:
- `TestParsePlan` — regex parsing of plan text (basic, bold, Chinese colon, single agent, empty, extra text)
- `TestExtractCode` — code extraction from fenced blocks, backticks, plain text
- `TestCustomSupervisorInit` — supervisor initialization with mocked model
- `TestSupervisorRun` — integration tests for the full run() flow

**Mock 模式**（使用 LangChain 原生 API mock）：

```python
from langchain_core.messages import AIMessageChunk

def _make_chunk(content=None, reasoning=None):
    """创建 mock AIMessageChunk，模拟流式 LLM 输出。"""
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ""
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk

async def _mock_model_stream(chunks):
    """模拟 model.astream() 返回的 chunk 序列。"""
    for chunk in chunks:
        yield chunk

async def _mock_agent_stream_events(events):
    """模拟 agent_graph.astream_events() 返回的事件序列。"""
    for event in events:
        yield event
```

**Supervisor mock 示例**：

```python
with patch("src.agent.supervisor.resolve_model") as mock_resolve:
    mock_model = AsyncMock()
    mock_model.astream = MagicMock(return_value=_mock_model_stream([
        _make_chunk(reasoning="I need to think..."),
        _make_chunk(content="## Plan\n- coder: write hello world"),
    ]))
    mock_resolve.return_value = mock_model

    # Mock sub-agent astream_events
    mock_agent_graph = AsyncMock()
    mock_agent_graph.astream_events = MagicMock(return_value=_mock_agent_stream_events([
        {"event": "on_tool_start", "name": "execute_code", "data": {"input": {"code": "print('hello')"}}},
        {"event": "on_chat_model_stream", "data": {"chunk": _make_chunk(content="print('hello')")}},
    ]))

    supervisor = CustomSupervisor(config)
    supervisor.agents["coder"] = mock_agent_graph
```

See full file content in the current project.

---

## File 12: `src/agent/agent.py`

**Complete rewrite.** Replace the raw OpenAI client ReAct loop with `create_agent` + `astream_events`.

### 12.1 Replace imports

```python
# 删除
import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

# 新增
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
```

### 12.2 Rewrite `__init__`

```python
class Agent:
    def __init__(self, config: AgentConfig) -> None:
        self.config = config
        self.model = resolve_model(config)
        self.tools = TOOLS
        self.compressor = ContextCompressor(config)
        # 使用 LangChain 原生 create_agent 构建 ReAct 循环
        # 自动处理：LLM 调用 → 工具执行 → 再次调用 LLM → 直到无 tool_calls
        self.agent_graph = create_agent(
            self.model,
            tools=self.tools,
            system_prompt=self._get_system_prompt(),
        )
```

### 12.3 删除的方法

- `_stream_raw` — 原始 OpenAI 客户端流式调用（删除）
- `_astream_with_thinking` — 流式包装器（删除）
- `_messages_to_openai` — LangChain → OpenAI 格式转换（删除）
- `_get_raw_client` — 原始客户端获取（删除）
- `run_stream` — JSON 序列化包装器（保留但可选）

### 12.4 Rewrite `run()` — 使用 astream_events

```python
async def run(self, user_input: str, memory_context: str = "",
              history: list[BaseMessage] | None = None) -> AsyncIterator[dict[str, Any]]:
    trace_id = str(uuid.uuid4())
    messages = self._build_messages(user_input, memory_context, history)

    # 上下文压缩
    if self.compressor.should_compress(messages):
        summary, recent = await self.compressor.compress(messages[1:])
        messages = self._build_messages(user_input, memory_context, recent, summary)

    self._log_request("agent", messages, trace_id=trace_id)

    # 使用 LangChain 原生 astream_events 流式处理 ReAct 循环
    thinking_started = False
    content_parts: list[str] = []

    async for event in self.agent_graph.astream_events(messages, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"]["chunk"]
            # reasoning_content 通过 ChatDeepSeek 自动提取到 additional_kwargs
            reasoning = chunk.additional_kwargs.get("reasoning_content")
            if reasoning:
                if not thinking_started:
                    yield {"type": "thinking_start"}
                    thinking_started = True
                yield {"type": "thinking", "data": reasoning}
            elif chunk.content:
                content_parts.append(chunk.content)

        elif kind == "on_tool_start":
            yield {
                "type": "tool_call",
                "data": [{"name": event["name"], "args": event["data"].get("input", {})}],
            }

    if thinking_started:
        yield {"type": "thinking_done"}

    yield {"type": "message", "data": "".join(content_parts)}
    yield {"type": "done"}
```

**关键变化**：
- 删除手动 2-call 模式（`create_agent` 自动循环直到无 tool_calls）
- 删除手动 tool 执行逻辑（`create_agent` 自动处理）
- `reasoning_content` 从 `chunk.additional_kwargs` 提取（`ChatDeepSeek` 自动填充）
- `tool_call` 从 `on_tool_start` 事件提取（`create_agent` 自动触发）
- 上下文压缩仍在 `run()` 中执行（在调用 `astream_events` 之前）

---

## Summary of Changes

| File                 | Type        | Description                                                  |
| -------------------- | ----------- | ------------------------------------------------------------ |
| `checkpoint.py`      | Modify      | Auto-migration, `save_message`, `load_history_with_meta`, `compact_session`, `get_session_summary`, tool_call id fix |
| `config.py`          | Modify      | Add `session_ttl_hours` field + property                     |
| `models.py`          | **Rewrite** | `init_chat_model` 替代手动 `ChatOpenAI`/`ChatAnthropic`，自动选择正确的模型类（如 `ChatDeepSeek`） |
| `system_prompt.py`   | Modify      | New `SUPERVISOR_PROMPT` with plan format                     |
| `supervisor.py`      | **Rewrite** | `CustomSupervisor`：子代理用 `create_agent` + `astream_events` 流式化，supervisor 用 `model.astream()` 替代 raw OpenAI 客户端 |
| `agent.py`           | **Rewrite** | `create_agent` + `astream_events` 替代手写 raw OpenAI ReAct 循环，删除 `_stream_raw`、`_messages_to_openai` 等方法 |
| `server.py`          | Modify      | `_batch_thinking`, supervisor singleton, `/api/compact`, save thinking/tool_calls |
| `api.ts`             | Modify      | `SessionInfo`, `restoreSession`, `compactSession`, `isPlan`, `compacted` |
| `chat.ts`            | Modify      | localStorage, `restoreSession`, SSE queue, slash commands, typing delay |
| `ChatTab.vue`        | Modify      | Command autocomplete, mode toggle, plan/compacted styles, responsive |
| `test_server.py`     | Modify      | Add `test_orchestrate_sse_format`                            |
| `test_supervisor.py` | **Rewrite** | Mock 从 `openai.AsyncOpenAI` 改为 `model.astream` + `astream_events`，使用 `_make_chunk` 辅助函数 |

### LangChain 原生 Streaming 迁移要点

| 之前                             | 现在                                           | 原因                                    |
| -------------------------------- | ---------------------------------------------- | --------------------------------------- |
| `openai.AsyncOpenAI` 手动客户端  | `init_chat_model` + `ChatDeepSeek`             | `ChatOpenAI` 不提取 `reasoning_content` |
| `_stream_raw` 手写 chunk 拼接    | `create_agent` + `astream_events`              | 框架自动处理 ReAct 循环                 |
| `_messages_to_openai` 格式转换   | 不需要                                         | LangChain 内部处理                      |
| `delta.reasoning_content` 手动取 | `chunk.additional_kwargs["reasoning_content"]` | `ChatDeepSeek` 自动填充                 |
| `_invoke_agent` ainvoke 阻塞     | `_invoke_agent_stream` astream_events          | 子代理 thinking 实时可见                |