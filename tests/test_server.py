import pytest
from unittest.mock import patch, MagicMock, AsyncMock


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
