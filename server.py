import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from src.agent._utils import SSE_HEADERS, is_punctuation_only
from src.agent.agent import Agent
from src.agent.checkpoint import (
    compact_session as db_compact_session,
)
from src.agent.checkpoint import (
    create_session,
    delete_session,
    delete_task_updates_for_sessions,
    get_session_summary,
    get_tool_usage_stats,
    load_history,
    load_history_with_meta,
    load_metrics,
    load_task_updates,
    rename_session,
    save_message,
    save_metrics,
    save_task_update,
    save_turn,
    update_session_duration,
    update_session_project_path,
    update_session_status,
)
from src.agent.checkpoint import (
    list_sessions as db_list_sessions,
)
from src.agent.config import AgentConfig
from src.agent.config_manager import get_config_manager
from src.agent.context.compression import ContextCompressor
from src.agent.context.memory import MemoryManager
from src.agent.file_service import build_file_tree, read_file_content
from src.agent.orchestrator import Orchestrator

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


orchestrator_instance: Orchestrator | None = None


def get_supervisor() -> Orchestrator:
    global orchestrator_instance
    if orchestrator_instance is None:
        orchestrator_instance = Orchestrator(config)
    return orchestrator_instance


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


class CreateSessionRequest(BaseModel):
    title: str | None = None
    project_path: str | None = None


class ValidateDirectoryRequest(BaseModel):
    path: str


class AgentConfigUpdate(BaseModel):
    model: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None
    enable_thinking: bool | None = None


# ── Platform helpers ────────────────────────────────────────────


def _command_available(cmd: str) -> bool:
    """Check if a CLI command is available on PATH.

    Falls back to PowerShell ``Get-Command`` on Windows to catch
    ``.ps1`` scripts that ``shutil.which`` misses.
    """
    import shutil
    import subprocess
    import sys

    if shutil.which(cmd):
        return True
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Command '{cmd}' -ErrorAction SilentlyStop"],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return False


# ── Passthrough ────────────────────────────────────────────────


async def _passthrough(source):
    """Passthrough with intelligent batching of small events.

    ACP agents (opencode, claude) stream content in tiny word-at-a-time
    fragments.  Batching them server-side prevents the frontend from
    receiving thousands of micro-events per response.
    """
    thinking_buf = ""
    message_buf = ""
    thinking_meta: dict = {}
    message_meta: dict = {}

    _min_thinking = 200
    _min_message  = 150

    async for event in source:
        etype = event.get("type", "")

        if etype == "thinking":
            chunk = event.get("data", "")
            thinking_buf += chunk
            meta = {k: v for k, v in event.items() if k not in ("type", "data")}
            if meta:
                thinking_meta = meta
            if len(thinking_buf) >= _min_thinking:
                yield {"type": "thinking", "data": thinking_buf, **thinking_meta}
                thinking_buf = ""

        elif etype == "message":
            if thinking_buf:
                yield {"type": "thinking", "data": thinking_buf, **thinking_meta}
                thinking_buf = ""
            chunk = event.get("data", "")
            message_buf += chunk
            meta = {k: v for k, v in event.items() if k not in ("type", "data")}
            if meta:
                message_meta = meta
            ends_sentence = bool(message_buf and message_buf.rstrip()[-1:] in (".", "!", "?"))
            ends_block = message_buf.rstrip().endswith("```") or message_buf.endswith("\n\n")
            if len(message_buf) >= _min_message or ends_sentence or ends_block:
                yield {"type": "message", "data": message_buf, **message_meta}
                message_buf = ""

        else:
            if thinking_buf:
                yield {"type": "thinking", "data": thinking_buf, **thinking_meta}
                thinking_buf = ""
            if message_buf:
                yield {"type": "message", "data": message_buf, **message_meta}
                message_buf = ""
            yield event

    if thinking_buf:
        yield {"type": "thinking", "data": thinking_buf, **thinking_meta}
    if message_buf:
        yield {"type": "message", "data": message_buf, **message_meta}


# ── Chat ────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest):
    session_id = request.session_id or create_session()
    memory_context = get_memory().inject_context(request.message)
    history = load_history(session_id)
    # Load session summary from previous compaction
    session_summary = get_session_summary(session_id)
    if session_summary:
        logger.info("[CHAT] session=%s has summary: %d chars", session_id, len(session_summary))
    update_session_status(session_id, "processing")
    _start_time = time.time()

    async def stream():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        agent_name = ""
        _saved = False
        _sse_idx = 0
        try:
            async for event in _passthrough(get_agent().run(request.message, memory_context, history, summary=session_summary)):
                event["session_id"] = session_id
                _sse_idx += 1
                if event["type"] == "thinking":
                    thinking_content += event.get("data", "")
                elif event["type"] == "tool_call":
                    tool_calls_data = json.dumps(event.get("data", []), ensure_ascii=False)
                    logger.info("[CHAT] #%d tool_call: %s agent=%s", _sse_idx, event["data"][0]["name"] if event["data"] else "", event.get("agent_name", ""))
                elif event["type"] == "message":
                    assistant_content += event.get("data", "")
                    agent_name = event.get("agent_name", "") or agent_name
                    logger.info("[CHAT] #%d message: accumulated=%d agent=%s", _sse_idx, len(assistant_content), agent_name)
                payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                logger.info("[SSE-TRACE] %s POST-stream #%d: type=%s bytes=%d", f"{time.time():.3f}", _sse_idx, event["type"], len(payload))
                yield payload
                await asyncio.sleep(0)

            if assistant_content:
                save_turn(session_id, request.message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data, name=agent_name or None)
                _saved = True
            elif thinking_content:
                save_turn(session_id, request.message, "[No response generated]", thinking=thinking_content, tool_calls=tool_calls_data)
                _saved = True
        except Exception as e:
            logger.error("[CHAT] POST-stream error: %s", e, exc_info=True)
            if not _saved:
                try:
                    content = assistant_content or f"[Error: {e}]"
                    save_turn(session_id, request.message, content, thinking=thinking_content, tool_calls=tool_calls_data, name=agent_name or None)
                except Exception as save_err:
                    logger.error("[CHAT] failed to save on error: %s", save_err)
            error_payload = f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"
            yield error_payload
        finally:
            duration_ms = int((time.time() - _start_time) * 1000)
            update_session_status(session_id, "completed")
            update_session_duration(session_id, duration_ms)
            logger.info("[CHAT] session=%s completed: %d events, %dms, thinking=%d chars", session_id, _sse_idx, duration_ms, len(thinking_content))

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
    session_summary = get_session_summary(sid)
    if session_summary:
        logger.info("[CHAT] session=%s has summary: %d chars", sid, len(session_summary))
    update_session_status(sid, "processing")
    _start_time = time.time()

    async def event_generator():
        assistant_content = ""
        thinking_content = ""
        tool_calls_data = ""
        _saved = False
        _sse_idx = 0
        try:
            async for event in _passthrough(get_agent().run(message, memory_context, history, summary=session_summary)):
                event["session_id"] = sid
                _sse_idx += 1
                if event["type"] == "thinking":
                    thinking_content += event.get("data", "")
                elif event["type"] == "tool_call":
                    tool_calls_data = json.dumps(event.get("data", []), ensure_ascii=False)
                    logger.info("[CHAT] #%d tool_call: %s", _sse_idx, event["data"][0]["name"] if event["data"] else "")
                elif event["type"] == "message":
                    assistant_content += event.get("data", "")
                    logger.info("[CHAT] #%d message: accumulated=%d", _sse_idx, len(assistant_content))
                logger.info("[SSE-TRACE] %s GET-stream #%d: type=%s", f"{time.time():.3f}", _sse_idx, event["type"])
                yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}

            if assistant_content:
                save_turn(sid, message, assistant_content, thinking=thinking_content, tool_calls=tool_calls_data)
                _saved = True
            elif thinking_content:
                save_turn(sid, message, "[No response generated]", thinking=thinking_content, tool_calls=tool_calls_data)
                _saved = True
        except Exception as e:
            logger.error("[CHAT] GET-stream error: %s", e, exc_info=True)
            if not _saved:
                try:
                    content = assistant_content or f"[Error: {e}]"
                    save_turn(sid, message, content, thinking=thinking_content, tool_calls=tool_calls_data)
                except Exception as save_err:
                    logger.error("[CHAT] failed to save on error: %s", save_err)
            yield {"event": "error", "data": json.dumps({"type": "error", "data": str(e), "session_id": sid}, ensure_ascii=False)}
        finally:
            duration_ms = int((time.time() - _start_time) * 1000)
            update_session_status(sid, "completed")
            update_session_duration(sid, duration_ms)
            logger.info("[CHAT] session=%s completed: %d events, %dms, thinking=%d chars", sid, _sse_idx, duration_ms, len(thinking_content))

        yield {"event": "done", "data": json.dumps({"type": "done", "session_id": sid}, ensure_ascii=False)}

    return EventSourceResponse(event_generator())


# ── Multi-Agent Orchestration ───────────────────────────────────


@app.post("/api/orchestrate")
async def orchestrate(request: OrchestrateRequest):
    session_id = request.session_id or create_session()
    orchestrator = get_supervisor()
    update_session_status(session_id, "processing")
    _start_time = time.time()
    history = load_history(session_id)
    session_summary = get_session_summary(session_id)

    async def stream():
        _message_accum = ""
        _thinking_accum = ""
        _agent_name = "supervisor"
        _user_saved = False
        _sse_idx = 0

        def _save_accumulated():
            nonlocal _message_accum, _thinking_accum
            if _message_accum and _message_accum.strip():
                if not is_punctuation_only(_message_accum) and len(_message_accum.strip()) >= 3:
                    try:
                        save_message(
                            session_id, "ai", _message_accum,
                            thinking=_thinking_accum or "",
                            name=_agent_name,
                        )
                    except Exception as save_err:
                        logger.warning("[ORCH] save_message failed: %s", save_err)
            _message_accum = ""
            _thinking_accum = ""

        try:
            async for event in _passthrough(
                orchestrator.run(request.task, history=history or None, summary=session_summary)
            ):
                event["session_id"] = session_id
                _sse_idx += 1
                _agent_name = event.get("agent_name", "supervisor")
                etype = event.get("type", "")
                payload = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

                try:
                    if not _user_saved:
                        save_message(session_id, "human", request.task)
                        _user_saved = True

                    if etype == "message":
                        _message_accum += event.get("data", "") or ""
                    elif etype == "thinking":
                        _thinking_accum += event.get("data", "") or ""
                    elif etype == "thinking_done":
                        pass
                    elif etype == "plan":
                        _save_accumulated()
                        try:
                            save_message(session_id, "ai", event.get("data", ""), name="plan")
                        except Exception as save_err:
                            logger.warning("[ORCH] save plan failed: %s", save_err)
                    elif etype == "tool_call":
                        tcs = event.get("data", []) or []
                        if tcs:
                            tc_json = json.dumps(tcs, ensure_ascii=False)
                            try:
                                save_message(session_id, "ai", "", tool_calls=tc_json, name=_agent_name)
                            except Exception as save_err:
                                logger.warning("[ORCH] save tool_call failed: %s", save_err)
                    elif etype == "task_update":
                        tu = event.get("data", {}) or {}
                        try:
                            save_task_update(
                                session_id,
                                agent=tu.get("agent", ""),
                                task=tu.get("task", ""),
                                status=tu.get("status", "pending"),
                                state=tu.get("state"),
                                started_at=tu.get("started_at"),
                                ended_at=tu.get("ended_at"),
                                elapsed_ms=tu.get("elapsed_ms"),
                            )
                        except Exception as save_err:
                            logger.warning("[ORCH] save_task_update failed: %s", save_err)
                    elif etype == "summary":
                        _save_accumulated()
                        try:
                            save_message(
                                session_id, "ai", event.get("data", ""),
                                thinking=_thinking_accum or None,
                                name="summary",
                            )
                        except Exception as save_err:
                            logger.warning("[ORCH] save summary failed: %s", save_err)
                    elif etype == "metrics":
                        try:
                            save_metrics(session_id, json.dumps(event.get("data", {}), ensure_ascii=False))
                        except Exception as save_err:
                            logger.warning("[ORCH] save_metrics failed: %s", save_err)
                except Exception as save_err:
                    logger.warning("[ORCH] persistence failed: %s", save_err)

                yield payload
                await asyncio.sleep(0)

            _save_accumulated()
            yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error("[ORCH] stream error: %s", e, exc_info=True)
            _save_accumulated()
            yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"
        finally:
            duration_ms = int((time.time() - _start_time) * 1000)
            update_session_status(session_id, "completed")
            update_session_duration(session_id, duration_ms)
            logger.info("[ORCH] session=%s completed: %d events, %dms", session_id, _sse_idx, duration_ms)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── SSE Events (handled per-endpoint: /chat, /api/orchestrate, /api/acp/send) ──


# ── Sessions ────────────────────────────────────────────────────


@app.get("/api/sessions")
async def list_sessions_endpoint(user_id: str | None = Query(None)):
    sessions = db_list_sessions(user_id=user_id, ttl_hours=config.session_ttl_hours)
    return {"sessions": sessions}


@app.get("/api/stats/tools")
async def stats_tools():
    """Aggregate tool-call counts across all sessions for the monitoring dashboard."""
    return {"tools": get_tool_usage_stats()}


@app.post("/api/sessions")
async def create_session_endpoint(request: CreateSessionRequest):
    """Explicitly create a new session with an optional title and project path."""
    session_id = create_session(title=request.title or "", project_path=request.project_path or "")
    return {"session_id": session_id, "title": request.title or "", "project_path": request.project_path or ""}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    messages = load_history_with_meta(session_id)
    summary = get_session_summary(session_id)
    task_updates = load_task_updates(session_id)
    metrics = load_metrics(session_id)
    if not messages and not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "session_id": session_id,
        "messages": messages,
        "summary": summary,
        "task_updates": task_updates,
        "task_phases": [],
        "metrics": metrics,
    }


@app.patch("/api/sessions/{session_id}/title")
async def update_session_title(session_id: str, request: dict):
    title = request.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="Title is required")
    rename_session(session_id, title)
    return {"session_id": session_id, "title": title}


@app.patch("/api/sessions/{session_id}/project-path")
async def update_session_project_path_endpoint(session_id: str, request: dict):
    project_path = request.get("project_path", "").strip()
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    update_session_project_path(session_id, project_path)
    return {"session_id": session_id, "project_path": project_path}


@app.delete("/api/sessions/{session_id}")
async def delete_session_endpoint(session_id: str):
    delete_task_updates_for_sessions([session_id])
    delete_session(session_id)
    return {"status": "ok"}


@app.post("/api/compact")
async def compact_endpoint(request: CompactRequest):
    """Compact a session: summarize old messages, keep recent ones."""
    history = load_history(request.session_id)
    if not history:
        return {
            "session_id": request.session_id,
            "summary": "",
            "deleted_messages": 0,
            "kept_messages": 0,
            "note": "No messages to compact",
        }

    # Use the compression module with LLM for high-quality summary
    compressor = ContextCompressor(config)
    try:
        summary_text, recent = await compressor.compress(history, llm=get_agent().model, force=True)
    except Exception as e:
        logger.warning("[Compact] LLM summary failed, using fallback: %s", e)
        summary_text, recent = await compressor.compress(history, force=True)

    # Persist: mark old messages as compacted, save summary (keep last 1 turn for LLM context)
    marked = db_compact_session(request.session_id, summary_text, keep=1)
    logger.info("[Compact] session=%s marked=%d kept=%d summary_len=%d", request.session_id, marked, len(recent), len(summary_text))

    return {
        "session_id": request.session_id,
        "summary": summary_text,
        "deleted_messages": marked,
        "kept_messages": len(recent),
    }


# ── Skills ──────────────────────────────────────────────────────


@app.get("/api/skills")
async def list_skills_endpoint():
    """List all skills from config/skills.json."""
    cm = get_config_manager()
    skills_config = cm.get_skills()
    skills = []
    for name, cfg in skills_config.items():
        skills.append({
            "name": name,
            "description": cfg.get("desc", ""),
            "agents": cfg.get("agents", []),
            "enabled": cfg.get("enabled", True),
        })
    return {"skills": skills}


@app.post("/api/config/reload")
async def reload_config_endpoint():
    """Force reload all config files."""
    cm = get_config_manager()
    cm.reload()
    return {"status": "ok", "message": "Config reloaded"}


# ── ACP Agent Management ─────────────────────────────────────────


@app.get("/api/acp/agents")
async def list_acp_agents():
    """List all ACP-capable agents from config, with availability status."""
    cm = get_config_manager()
    agents_config = cm.get_agents()
    acp_config = cm.get_acp_agents()
    acp_agents = []
    for agent_id, cfg in agents_config.items():
        if cfg.get("acp_mode"):
            acp_cli_id = cfg.get("acp_cli_id", agent_id)
            acp_cfg = acp_config.get(acp_cli_id, {})
            cmd = acp_cfg.get("command", acp_cli_id)
            cwd = acp_cfg.get("cwd", ".")
            acp_agents.append({
                "id": agent_id,
                "name": cfg.get("name", agent_id),
                "desc": cfg.get("desc", ""),
                "acp_cli_id": acp_cli_id,
                "command": cmd,
                "cwd": cwd,
                "enabled": cfg.get("enabled", True),
                "available": _command_available(cmd),
            })
    return {"agents": acp_agents}


@app.post("/api/acp/send")
async def acp_send_message(request: dict):
    """Send a message to an ACP agent and stream events via SSE.
    agent_id maps to acp_agents.json key (e.g. "opencode", "claude").
    session_id is the chat session ID for ACP session reuse.
    """
    agent_id = request.get("agent_id", "opencode")
    message = request.get("message", "")
    context = request.get("context", "")
    session_id = request.get("session_id", "") or ""

    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    # Validate agent exists in acp_agents.json
    cm = get_config_manager()
    if not cm.get_acp_agent(agent_id):
        raise HTTPException(status_code=404, detail=f"ACP agent not found: {agent_id}. Configure in config/acp_agents.json")

    if session_id:
        update_session_status(session_id, "processing")
    _start_time = time.time()

    from src.agent.acp_agent import get_acp_agent

    async def stream():
        acp = get_acp_agent(agent_id)
        thinking_content = ""
        message_content = ""
        _user_saved = False
        try:
            async for event in _passthrough(acp.run(message, context=context, session_id=session_id)):
                if session_id:
                    event["session_id"] = session_id

                # Persist messages — accumulate content, save only on completion boundaries
                if session_id:
                    try:
                        if not _user_saved:
                            save_message(session_id, "human", message)
                            _user_saved = True

                        if event["type"] == "thinking":
                            thinking_content += event.get("data", "")
                        elif event["type"] == "message":
                            message_content += event.get("data", "")
                        elif event["type"] == "tool_call":
                            tc_list = event.get("data", [])
                            if isinstance(tc_list, list):
                                valid_tc = [t for t in tc_list if t.get("name")]
                                if valid_tc:
                                    tc_json = json.dumps(valid_tc, ensure_ascii=False)
                                    save_message(session_id, "ai", "", tool_calls=tc_json, name=agent_id)
                        elif event["type"] == "thinking_done" and (message_content or thinking_content):
                            save_message(session_id, "ai", message_content, thinking=thinking_content, name=agent_id)
                            message_content = ""
                            thinking_content = ""
                    except Exception as save_err:
                        logger.warning("[ACP] save_message failed: %s", save_err)

                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0)
            if session_id:
                yield f"data: {json.dumps({'type': 'done', 'session_id': session_id}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e), 'session_id': session_id}, ensure_ascii=False)}\n\n"
        finally:
            if session_id:
                # Save any remaining accumulated content
                if message_content or thinking_content:
                    try:
                        save_message(session_id, "ai", message_content, thinking=thinking_content, name=agent_id)
                    except Exception as save_err:
                        logger.warning("[ACP] final save_message failed: %s", save_err)
                duration_ms = int((time.time() - _start_time) * 1000)
                update_session_status(session_id, "completed")
                update_session_duration(session_id, duration_ms)
                logger.info("[ACP] session=%s completed: %dms", session_id, duration_ms)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/acp/check/{agent_id}")
async def check_acp_agent(agent_id: str):
    """Check if an ACP agent's CLI command is available."""
    cm = get_config_manager()
    acp_config = cm.get_acp_agent(agent_id)
    if not acp_config:
        raise HTTPException(status_code=404, detail=f"ACP agent not found: {agent_id}")
    cmd = acp_config.get("command", agent_id)
    return {"agent_id": agent_id, "available": _command_available(cmd), "command": cmd}

@app.get("/api/acp/sessions/{agent_id}")
async def list_acp_sessions(agent_id: str):
    """List ACP sessions (read from local checkpoint, ACP session/list not yet implemented)."""
    sessions = []
    for s in db_list_sessions():
        if s.get("acp_session_id"):
            sessions.append({"chat_session_id": s["session_id"], "acp_session_id": s["acp_session_id"], "title": s.get("title", "")})
    return {"sessions": sessions}


# ── Tools ───────────────────────────────────────────────────────


@app.get("/api/tools")
async def list_tools():
    """List all tools from config/tools.json with metadata."""
    cm = get_config_manager()
    tools_config = cm.get_tools()
    tools = []
    for name, cfg in tools_config.items():
        tools.append({
            "name": name,
            "description": cfg.get("desc", ""),
            "type": cfg.get("category", "Core"),
            "icon": cfg.get("icon", "⚙"),
            "usage": 0,
            "lastUsed": None,
        })
    return {"tools": tools}


# ── Agents ───────────────────────────────────────────────────────


class AgentUpsertRequest(BaseModel):
    name: str | None = None
    type: str | None = None
    desc: str | None = None
    tools: list[str] | None = None
    system_prompt: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    enabled: bool | None = None


@app.get("/api/agents")
async def list_agents_endpoint():
    """List all agent configurations from JSON config."""
    cm = get_config_manager()
    agents_config = cm.get_agents()
    agents = []
    for agent_id, cfg in agents_config.items():
        agents.append({
            "id": agent_id,
            "name": cfg.get("name", agent_id),
            "type": cfg.get("type", "helper"),
            "desc": cfg.get("desc", ""),
            "tools": cfg.get("tools", []),
            "system_prompt": cfg.get("system_prompt", ""),
            "model": cfg.get("model"),
            "temperature": cfg.get("temperature"),
            "max_tokens": cfg.get("max_tokens"),
            "enabled": cfg.get("enabled", True),
        })
    return {"agents": agents}


@app.get("/api/agents/{agent_id}")
async def get_agent_endpoint(agent_id: str):
    """Get a single agent configuration."""
    cm = get_config_manager()
    agent = cm.get_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return {"id": agent_id, **agent}


@app.post("/api/agents/{agent_id}")
async def upsert_agent_endpoint(agent_id: str, request: AgentUpsertRequest):
    """Create or update an agent configuration (persists to agents.json)."""
    cm = get_config_manager()
    # Get existing config and merge with updates
    existing = cm.get_agent(agent_id) or {}
    data = {**existing, **request.model_dump(exclude_none=True)}
    cm.save_agent(agent_id, data)
    return {"status": "ok", "agent_id": agent_id}


@app.delete("/api/agents/{agent_id}")
async def delete_agent_endpoint(agent_id: str):
    """Delete an agent configuration."""
    cm = get_config_manager()
    cm.delete_agent(agent_id)
    return {"status": "ok"}


# ── ACP Agent Config ─────────────────────────────────────────────


class ACPAgentUpsertRequest(BaseModel):
    name: str | None = None
    command: str | None = None
    args: list[str] | None = None
    timeout: int | None = None
    desc: str | None = None
    enabled: bool | None = None


@app.get("/api/acp/config")
async def list_acp_config():
    """List all ACP agent configurations from acp_agents.json."""
    cm = get_config_manager()
    agents = cm.get_acp_agents()
    result = [{"id": k, **v} for k, v in agents.items()]
    return {"agents": result}


@app.get("/api/acp/config/{agent_id}")
async def get_acp_config(agent_id: str):
    """Get a single ACP agent configuration."""
    cm = get_config_manager()
    agent = cm.get_acp_agent(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail=f"ACP agent not found: {agent_id}")
    return {"id": agent_id, **agent}


@app.post("/api/acp/config/{agent_id}")
async def upsert_acp_config(agent_id: str, request: ACPAgentUpsertRequest):
    """Create or update an ACP agent configuration (persists to acp_agents.json)."""
    cm = get_config_manager()
    existing = cm.get_acp_agent(agent_id) or {}
    data = {**existing, **request.model_dump(exclude_none=True)}
    cm.save_acp_agent(agent_id, data)
    return {"status": "ok", "agent_id": agent_id}


@app.delete("/api/acp/config/{agent_id}")
async def delete_acp_config(agent_id: str):
    """Delete an ACP agent configuration."""
    cm = get_config_manager()
    cm.delete_acp_agent(agent_id)
    return {"status": "ok"}


# ── Files ────────────────────────────────────────────────────────


@app.get("/api/files/tree")
async def get_file_tree(root: str | None = Query(None)):
    """Return the workspace file system tree."""
    root_path = Path(root) if root else None
    tree = build_file_tree(root=root_path)
    return {"tree": tree}


@app.post("/api/files/pick-directory")
async def pick_directory():
    """Open native OS folder picker dialog and return selected path."""
    import os
    import tempfile
    import time

    fd, tmp = tempfile.mkstemp(suffix=".picker.txt", prefix="picker_")
    os.close(fd)
    if os.path.exists(tmp):
        os.unlink(tmp)

    ps_script = f'''
$ErrorActionPreference = "Stop"
try {{
    Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
    $folder = New-Object System.Windows.Forms.FolderBrowserDialog
    $folder.Description = "选择项目目录"
    $folder.ShowNewFolderButton = $true
    $result = $folder.ShowDialog()
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {{
        $folder.SelectedPath | Out-File -FilePath "{tmp}" -Encoding UTF8
        [Console]::Error.WriteLine("PICKER_OK:" + $folder.SelectedPath)
    }} else {{
        [Console]::Error.WriteLine("PICKER_CANCEL")
    }}
}} catch {{
    [Console]::Error.WriteLine("PICKER_ERROR:" + $_.Exception.Message)
    exit 1
}}
'''
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.TimeoutError:
            try:
                proc.kill()
            except Exception:
                pass
            raise HTTPException(
                status_code=504,
                detail="文件夹选择器超时(120s),可能没有图形桌面会话或被取消",
            )

        stderr_text = (stderr_b or b"").decode("utf-8", errors="replace").strip()
        if proc.returncode != 0 or stderr_text.startswith("PICKER_ERROR"):
            err_msg = stderr_text or f"PowerShell exited with code {proc.returncode}"
            raise HTTPException(
                status_code=503,
                detail=f"无法打开文件夹选择器: {err_msg}",
            )

        if not os.path.exists(tmp):
            return {"path": None}

        deadline = time.time() + 2.0
        path: str | None = None
        while time.time() < deadline:
            try:
                with open(tmp, "r", encoding="utf-8-sig") as f:
                    raw = f.read()
                if raw.strip():
                    path = raw.strip().rstrip("\r\n")
                    break
            except OSError:
                pass
            await asyncio.sleep(0.05)

        return {"path": path} if path else {"path": None}
    except HTTPException:
        raise
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"系统找不到 PowerShell: {e}")
    except Exception as e:
        logger.exception("[pick-directory] unexpected error")
        raise HTTPException(status_code=500, detail=f"文件夹选择器异常: {e}")
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


@app.post("/api/files/validate-directory")
async def validate_directory(request: ValidateDirectoryRequest):
    """Check whether a given path exists and is a readable directory.

    Returns {"valid": true, "path": "..."} on success, or
    {"valid": false, "error": "..."} on failure (404-like but explicit).
    """
    raw = (request.path or "").strip().rstrip('"').rstrip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="path 不能为空")
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {p}")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"不是目录: {p}")
    try:
        next(p.iterdir())
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"无访问权限: {p}")
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取目录失败: {e}")
    return {"valid": True, "path": str(p)}


@app.get("/api/files/browse")
async def browse_directories(
    path: str = Query(...),
    depth: int = Query(2, ge=0, le=8),
    include_files: bool = Query(False),
):
    """Return a directory tree (depth-limited) for the project picker.

    Skips system / noisy directories and hidden folders. Symlinks are not
    followed. Read errors on subfolders produce empty children rather than 5xx.
    """
    from src.agent.file_service import browse_directories
    raw = (path or "").strip().rstrip('"').rstrip("'")
    if not raw:
        raise HTTPException(status_code=400, detail="path 不能为空")
    p = Path(raw).expanduser()
    try:
        tree = browse_directories(p, max_depth=depth, include_files=include_files)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotADirectoryError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取目录失败: {e}")
    return {"tree": tree}


@app.get("/api/files/drives")
async def list_drives():
    """List available drive roots (Windows) or '/' fallback (Unix)."""
    roots: list[dict] = []
    if os.name == 'nt':
        from string import ascii_uppercase
        for letter in ascii_uppercase:
            drive = f"{letter}:\\"
            p = Path(drive)
            if p.exists():
                roots.append({"path": drive, "label": drive})
    else:
        roots.append({"path": "/", "label": "Root"})
        home = str(Path.home())
        if home != "/":
            roots.append({"path": home, "label": "Home"})
    return {"drives": roots}


@app.get("/api/files/content")
async def get_file_content(path: str = Query(...)):
    """Return file content with line numbers and syntax highlighting."""
    try:
        result = read_file_content(path)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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
