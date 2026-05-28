import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agent.agent import Agent
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
from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor
from src.agent.context.memory import MemoryManager
from src.agent.event_bus import event_bus
from src.agent.supervisor import CustomSupervisor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

config = AgentConfig()
agent: Agent | None = None
memory: MemoryManager | None = None


def get_agent() -> Agent:
    global agent
    if agent is None:
        agent = Agent(config)
    return agent


def get_memory() -> MemoryManager:
    global memory
    if memory is None:
        memory = MemoryManager(config)
    return memory


supervisor_instance: CustomSupervisor | None = None


def get_supervisor() -> CustomSupervisor:
    global supervisor_instance
    if supervisor_instance is None:
        supervisor_instance = CustomSupervisor(config)
    return supervisor_instance


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="LangGraph Agent v2", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request Models ──────────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class OrchestrateRequest(BaseModel):
    task: str
    session_id: str | None = None


class MemoryStoreRequest(BaseModel):
    key: str
    content: str
    namespace: str = "default"


class MemoryQueryRequest(BaseModel):
    query: str
    namespace: str = "default"
    top_k: int = 5


class CompactRequest(BaseModel):
    session_id: str


# ── Thinking Batching ──────────────────────────────────────────

_THINK_BATCH_CHARS = 50  # flush thinking buffer every N chars


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


# ── Chat ────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or create_session()
    memory_context = get_memory().inject_context(request.message)
    history = load_history(session_id)

    async def stream():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        _saved = False
        _sse_idx = 0
        try:
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
                await asyncio.sleep(0)  # yield control to flush SSE chunk

            if assistant_content and not _saved:
                save_turn(session_id, request.message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)
        except Exception as e:
            logger.error("[SSE-TRACE] POST-stream error: %s", e, exc_info=True)
            error_payload = f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"
            yield error_payload

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/chat/stream")
async def chat_stream(message: str = Query(...), session_id: str | None = Query(None)):
    """GET-based SSE endpoint using EventSourceResponse for proper browser streaming."""
    sid = session_id or create_session()
    memory_context = get_memory().inject_context(message)
    history = load_history(sid)

    async def event_generator():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        _saved = False
        _sse_idx = 0
        try:
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
        except Exception as e:
            logger.error("[SSE-TRACE] GET-stream error: %s", e, exc_info=True)
            yield {"event": "error", "data": json.dumps({"type": "error", "data": str(e), "session_id": sid}, ensure_ascii=False)}

        yield {"event": "done", "data": json.dumps({"type": "done", "session_id": sid}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


# ── Multi-Agent Orchestration ───────────────────────────────────


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


# ── SSE Events ──────────────────────────────────────────────────


@app.get("/api/events/stream/{stream_id}")
async def sse_stream(stream_id: str):
    async def event_generator():
        queue = event_bus.subscribe(stream_id)
        try:
            while True:
                event = await queue.get()
                yield event_bus.format_sse(event)
        except asyncio.CancelledError:
            pass
        finally:
            event_bus.unsubscribe(stream_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Sessions ────────────────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions_endpoint(user_id: str | None = Query(None)):
    sessions = db_list_sessions(user_id=user_id, ttl_hours=config.session_ttl_hours)
    return {"sessions": sessions}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    messages = load_history_with_meta(session_id)
    summary = get_session_summary(session_id)
    if not messages and not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "messages": messages, "summary": summary}


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    delete_session(session_id)
    return {"status": "ok"}


@app.post("/api/compact")
async def compact_endpoint(request: CompactRequest):
    """Compact a session: summarize old messages, keep recent ones."""
    history = load_history(request.session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found or empty")

    # Use the compression module to generate a summary
    compressor = ContextCompressor(config)
    summary_text, recent = await compressor.compress(history)

    # Persist: mark old messages as compacted, save summary
    marked = db_compact_session(request.session_id, summary_text)

    return {
        "session_id": request.session_id,
        "summary": summary_text,
        "deleted_messages": marked,
        "kept_messages": len(recent),
    }


# ── Skills ──────────────────────────────────────────────────────


@app.get("/api/skills")
async def list_skills_endpoint():
    from src.agent.skills import list_skills
    return {"skills": list_skills()}


# ── Tools ───────────────────────────────────────────────────────


@app.get("/api/tools")
async def list_tools():
    return {
        "tools": [
            {"name": t.name, "description": t.description}
            for t in get_agent().tools
        ]
    }


# ── Memory ──────────────────────────────────────────────────────


@app.post("/api/memory/store")
async def memory_store(request: MemoryStoreRequest):
    get_memory().store(request.key, request.content, request.namespace)
    return {"status": "ok"}


@app.post("/api/memory/query")
async def memory_query(request: MemoryQueryRequest):
    results = get_memory().retrieve(request.query, request.namespace, request.top_k)
    return {"results": results}


@app.get("/api/memory/list/{namespace}")
async def memory_list(namespace: str = "default"):
    return {"memories": get_memory().list_memories(namespace)}


@app.delete("/api/memory/{namespace}/{key}")
async def memory_delete(namespace: str, key: str):
    get_memory().delete(key, namespace)
    return {"status": "ok"}


# ── Health ──────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok", "model": f"{config.model_provider}/{config.model_name}"}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (may fail on Windows)")
    args = parser.parse_args()

    uvicorn.run("server:app", host=config.server_host, port=config.server_port, reload=args.reload)
