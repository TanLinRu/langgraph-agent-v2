import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Set env vars so AgentConfig never picks up real credentials."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AGENT_MODEL_PROVIDER", "openai")
    monkeypatch.setenv("AGENT_MODEL_NAME", "gpt-4o-mini")
    monkeypatch.setenv("AGENT_MAX_TOKENS", "1000")
    monkeypatch.setenv("AGENT_MEMORY_DB_PATH", str(tmp_path / "agent.db"))
    monkeypatch.setenv("AGENT_CHROMA_PATH", str(tmp_path / "chroma"))
    monkeypatch.setenv("AGENT_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENT_SERVER_PORT", "0")
    yield


@pytest.fixture
def tmp_dir(tmp_path):
    return tmp_path


@pytest.fixture
def mock_config():
    """Return an AgentConfig with test defaults."""
    from src.agent.config import AgentConfig
    with patch.dict(os.environ, {
        "OPENAI_API_KEY": "test-key",
        "AGENT_MODEL_PROVIDER": "openai",
        "AGENT_MODEL_NAME": "gpt-4o-mini",
        "AGENT_MAX_TOKENS": "1000",
        "AGENT_MEMORY_DB_PATH": ":memory:",
        "AGENT_CHROMA_PATH": "/tmp/test_chroma",
    }):
        return AgentConfig()
