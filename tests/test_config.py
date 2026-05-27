import os
from unittest.mock import patch

import pytest

from src.agent.config import AgentConfig


def test_config_defaults():
    cfg = AgentConfig()
    assert cfg.model_provider == "openai"
    assert cfg.model_name == "gpt-4o-mini"
    assert cfg.max_tokens == 1000
    assert cfg.compression_threshold == 0.7


def test_config_field_aliases(tmp_path):
    env = {
        "OPENAI_API_KEY": "sk-test",
        "AGENT_MODEL_PROVIDER": "anthropic",
        "AGENT_MODEL_NAME": "claude-3-5-sonnet",
        "AGENT_MAX_TOKENS": "2000",
        "AGENT_COMPRESSION_THRESHOLD": "0.8",
        "AGENT_MEMORY_DB_PATH": str(tmp_path / "mem.db"),
        "AGENT_CHROMA_PATH": str(tmp_path / "chroma"),
        "AGENT_SERVER_HOST": "0.0.0.0",
        "AGENT_SERVER_PORT": "9000",
    }
    with patch.dict(os.environ, env, clear=False):
        cfg = AgentConfig()
        assert cfg.model_provider == "anthropic"
        assert cfg.model_name == "claude-3-5-sonnet"
        assert cfg.max_tokens == 2000
        assert cfg.compression_threshold == 0.8
        assert cfg.server_host == "0.0.0.0"
        assert cfg.server_port == 9000


def test_config_memory_paths(tmp_path):
    with patch.dict(os.environ, {
        "AGENT_MEMORY_DB_PATH": str(tmp_path / "custom.db"),
        "AGENT_CHROMA_PATH": str(tmp_path / "custom_chroma"),
    }, clear=False):
        cfg = AgentConfig()
        assert "custom.db" in cfg.memory_db_path
        assert "custom_chroma" in cfg.chroma_path
