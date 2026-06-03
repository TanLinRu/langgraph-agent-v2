from unittest.mock import MagicMock

import pytest


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from fastapi.testclient import TestClient

    from server import app
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_list_tools(client):
    resp = client.get("/api/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    assert len(data["tools"]) > 0


def test_list_sessions(client):
    resp = client.get("/api/sessions")
    assert resp.status_code == 200
    data = resp.json()
    assert "sessions" in data


def test_list_skills(client):
    resp = client.get("/api/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data


def test_chat_endpoint_exists(client):
    """Verify /chat endpoint accepts POST (mock agent to avoid real API call)."""
    import server

    mock_agent = MagicMock()

    async def mock_run(*args, **kwargs):
        yield {"type": "message", "data": "mocked"}
        yield {"type": "done", "data": ""}

    mock_agent.run = mock_run

    mock_memory = MagicMock()
    mock_memory.inject_context.return_value = ""

    original_agent = server.agent
    original_memory = server.memory
    server.agent = mock_agent
    server.memory = mock_memory
    try:
        resp = client.post("/chat", json={"message": "test"}, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200
    finally:
        server.agent = original_agent
        server.memory = original_memory


def test_orchestrate_endpoint_exists(client):
    """Verify /api/orchestrate endpoint accepts POST."""
    resp = client.post("/api/orchestrate", json={"task": "test"}, headers={"Accept": "text/event-stream"})
    assert resp.status_code in (200, 500)


def test_orchestrate_sse_format(client):
    """Verify /api/orchestrate emits fine-grained SSE events."""
    import json

    import server

    mock_supervisor = MagicMock()

    async def mock_run(task, history=None, summary=""):
        yield {"type": "thinking_start", "data": "", "agent_name": "supervisor"}
        yield {"type": "thinking", "data": "thinking...", "agent_name": "supervisor"}
        yield {"type": "thinking_done", "data": "", "agent_name": "supervisor"}
        yield {"type": "plan", "data": "## Plan\n- coder: write code", "agent_name": "supervisor"}
        yield {"type": "tool_call", "data": [{"name": "coder", "args": {"task": "write code"}}], "agent_name": "coder"}
        yield {"type": "message", "data": "code result", "agent_name": "coder"}
        yield {"type": "summary", "data": "Done.", "agent_name": "supervisor"}
        yield {"type": "done"}

    mock_supervisor.run = mock_run

    original = server.orchestrator_instance
    server.orchestrator_instance = mock_supervisor
    try:
        resp = client.post("/api/orchestrate", json={"task": "test"}, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200

        # Parse SSE events
        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
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
        server.orchestrator_instance = original


@pytest.mark.asyncio
async def test_orchestrate_acp_dispatch(client):
    """Supervisor dispatches to opencode (ACP agent) — verifies SSE events flow through HTTP."""
    import json

    import server

    mock_supervisor = MagicMock()

    async def mock_run(task, history=None, summary=""):
        yield {"type": "thinking_start", "data": "", "agent_name": "supervisor"}
        yield {"type": "thinking", "data": "planning...", "agent_name": "supervisor"}
        yield {"type": "thinking_done", "data": "", "agent_name": "supervisor"}
        yield {"type": "plan", "data": "## Plan\n- opencode: initialize agent", "agent_name": "supervisor"}
        yield {"type": "task_update", "data": {"agent": "opencode", "task": "initialize agent", "status": "running"}, "agent_name": "supervisor"}
        yield {"type": "thinking", "data": "analyzing project...", "agent_name": "opencode"}
        yield {"type": "message", "data": "OpenCode agent initialized", "agent_name": "opencode"}
        yield {"type": "thinking_done", "data": "", "agent_name": "opencode"}
        yield {"type": "task_update", "data": {"agent": "opencode", "task": "initialize agent", "status": "completed"}, "agent_name": "supervisor"}
        yield {"type": "metrics", "data": {"elapsed_ms": 5000, "agent_calls": 1, "tokens": {}}, "agent_name": "supervisor"}
        yield {"type": "done"}

    mock_supervisor.run = mock_run

    original = server.orchestrator_instance
    server.orchestrator_instance = mock_supervisor
    try:
        resp = client.post("/api/orchestrate", json={"task": "test"}, headers={"Accept": "text/event-stream"})
        assert resp.status_code == 200

        events = []
        for line in resp.text.split("\n"):
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))

        event_types = [e["type"] for e in events if "type" in e]
        assert "plan" in event_types
        assert "task_update" in event_types
        assert "message" in event_types
        assert "done" in event_types

        # Verify opencode agent events
        acp_events = [e for e in events if e.get("agent_name") == "opencode"]
        assert len(acp_events) >= 3  # thinking + message + thinking_done
        acp_types = [e["type"] for e in acp_events]
        assert "thinking" in acp_types
        assert "message" in acp_types

        # Verify the opencode message content is in the SSE stream
        msgs = [e for e in acp_events if e["type"] == "message"]
        assert any("OpenCode agent initialized" in m["data"] for m in msgs)

        # Verify session_id is attached to events
        session_ids = [e.get("session_id") for e in events if e.get("session_id")]
        assert len(session_ids) > 0
    finally:
        server.orchestrator_instance = original


def test_stats_tools_endpoint(client):
    """GET /api/stats/tools returns aggregated tool-call counts."""
    from src.agent import db as checkpoint

    session_id = checkpoint.create_session(title="stats-test")
    checkpoint.record_tool_usage("test_tool", session_id)

    resp = client.get("/api/stats/tools")
    assert resp.status_code == 200
    data = resp.json()
    assert "tools" in data
    assert isinstance(data["tools"], list)
    names = {t["name"] for t in data["tools"]}
    assert "test_tool" in names

    checkpoint.delete_session(session_id)


def test_delete_session_cascades_task_updates(client):
    """DELETE /api/sessions/{id} also clears task_updates for that session."""
    from src.agent import db as checkpoint

    session_id = checkpoint.create_session(title="cascade-test")
    checkpoint.save_task_update(session_id, "coder", "do thing", "completed", "result")

    # Verify task_updates row exists
    rows = checkpoint.load_task_updates(session_id)
    assert len(rows) >= 1

    # Delete the session
    resp = client.delete(f"/api/sessions/{session_id}")
    assert resp.status_code == 200

    # task_updates for that session should be gone
    rows_after = checkpoint.load_task_updates(session_id)
    assert rows_after == []
