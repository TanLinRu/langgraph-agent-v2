import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.agent.agent import Agent
from src.agent.checkpoint import create_session, delete_session, list_sessions as db_list_sessions, load_history, save_turn
from src.agent.config import AgentConfig
from src.agent.context.memory import MemoryManager
from src.agent.event_bus import event_bus

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


# ── Chat ────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or create_session()
    memory_context = get_memory().inject_context(request.message)
    history = load_history(session_id)

    async def stream():
        assistant_content = ""
        async for event in get_agent().run(request.message, memory_context, history):
            event["session_id"] = session_id
            if event["type"] == "message":
                assistant_content = event["data"]
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        if assistant_content:
            save_turn(session_id, request.message, assistant_content)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ── Multi-Agent Orchestration ───────────────────────────────────


@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    from src.agent.supervisor import create_default_supervisor

    session_id = request.session_id or str(uuid.uuid4())
    supervisor_mgr = create_default_supervisor(config)
    supervisor = supervisor_mgr.build_supervisor()

    async def stream():
        try:
            from langchain_core.messages import HumanMessage

            result = supervisor.astream({"messages": [HumanMessage(content=request.task)]})
            async for chunk in result:
                # Extract agent_name from chunk if available
                agent_name = ""
                if isinstance(chunk, dict):
                    # langgraph supervisor emits dict with agent name as key
                    for key in chunk:
                        if key not in ("messages",):
                            agent_name = key
                            break

                event = {
                    "type": "update",
                    "data": str(chunk),
                    "agent_name": agent_name,
                    "session_id": session_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


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

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Sessions ────────────────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions_endpoint():
    return {"sessions": db_list_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    history = load_history(session_id)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = [{"type": m.type, "content": m.content} for m in history]
    return {"session_id": session_id, "messages": messages}


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    delete_session(session_id)
    return {"status": "ok"}


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
