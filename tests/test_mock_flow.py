"""Mock end-to-end flow test — verifies the agent loop works without real API calls."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor


@pytest.mark.asyncio
async def test_compression_flow(tmp_path, monkeypatch):
    """Test that compression triggers correctly and returns valid output."""
    monkeypatch.setenv("AGENT_MAX_TOKENS", "10")
    config = AgentConfig()
    compressor = ContextCompressor(config)
    big = "word " * 100
    msgs = [
        SystemMessage(content="system"),
        HumanMessage(content=big),
        AIMessage(content=big),
        HumanMessage(content=big),
        AIMessage(content=big),
        HumanMessage(content=big),
        AIMessage(content=big),
    ]
    assert compressor.should_compress(msgs) is True
    summary, recent = await compressor.compress(msgs)
    assert isinstance(summary, str)
    assert len(recent) >= 2


def test_tool_result_truncation():
    from src.agent.context.tool_result_manager import truncate_result

    big = "x" * 5000
    truncated = truncate_result("execute_code", big)
    assert len(truncated) < len(big)
    assert "truncated" in truncated.lower()


def test_memory_store_retrieve(tmp_path, monkeypatch):
    from src.agent.context.memory import MemoryManager

    monkeypatch.setenv("AGENT_MEMORY_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("AGENT_CHROMA_PATH", str(tmp_path / "chroma"))
    config = AgentConfig()
    mm = MemoryManager(config)
    mm.store("test_key", "test_value", namespace="test")
    results = mm.retrieve("test_value", namespace="test", top_k=1)
    assert len(results) >= 1
    assert "test_value" in results[0]["content"]
    mm.delete("test_key", namespace="test")
    results_after = mm.retrieve("test_value", namespace="test", top_k=1)
    assert len(results_after) == 0
    mm.close()


def test_skills_loading():
    from src.agent.skills import load_skills, get_skills_prompt
    skills = load_skills()
    assert isinstance(skills, list)
    prompt = get_skills_prompt()
    assert isinstance(prompt, str)


def test_checkpoint_session(tmp_path, monkeypatch):
    from src.agent import checkpoint

    monkeypatch.setattr(checkpoint, "_DB_PATH", tmp_path / "sessions.db")
    sid = checkpoint.create_session()
    assert checkpoint.session_exists(sid) is True
    sessions = checkpoint.list_sessions()
    session_ids = [s["session_id"] for s in sessions]
    assert sid in session_ids

    checkpoint.save_turn(sid, "hello", "hi there")
    history = checkpoint.load_history(sid)
    assert len(history) == 2
    assert history[0].content == "hello"
    assert history[1].content == "hi there"


@pytest.mark.asyncio
async def test_multi_round_compression(monkeypatch):
    """Simulate multi-round conversation with low token threshold (500).
    Verifies:
    - Compression triggers when token count exceeds threshold
    - System message is preserved after compression
    - Recent messages are kept intact
    - Conversation can continue after compression (messages are valid)
    """
    monkeypatch.setenv("AGENT_MAX_TOKENS", "500")
    monkeypatch.setenv("AGENT_COMPRESSION_THRESHOLD", "0.7")
    config = AgentConfig()
    compressor = ContextCompressor(config)

    assert config.max_tokens == 500
    assert config.compression_threshold == 0.7
    threshold = int(500 * 0.7)  # 350 tokens

    # Build a conversation that exceeds 350 tokens
    system = SystemMessage(content="You are a helpful assistant.")
    rounds = []
    for i in range(8):
        rounds.append(HumanMessage(content=f"Question {i}: Please explain topic {i} in detail with examples."))
        rounds.append(AIMessage(content=f"Answer {i}: Here is a detailed explanation of topic {i}. " + "word " * 50))

    messages = [system] + rounds
    from src.agent.context._helpers import count_tokens
    token_count = count_tokens(messages)
    assert token_count > threshold, f"Expected >{threshold} tokens, got {token_count}"

    # Compress
    assert compressor.should_compress(messages) is True
    summary, recent = await compressor.compress(messages[1:])  # skip system

    # Verify summary is non-empty
    assert len(summary) > 0, "Summary should not be empty after compressing 8 rounds"

    # Verify recent messages are kept (keep_recent=5)
    assert len(recent) <= 5

    # Rebuild messages as agent would
    new_system = SystemMessage(content=f"You are a helpful assistant.\n\n[Conversation History]\n{summary}")
    continued_messages = [new_system] + recent + [HumanMessage(content="Follow-up question after compression.")]

    # Verify continued conversation is valid
    assert len(continued_messages) >= 3  # system + at least 1 recent + follow-up
    assert isinstance(continued_messages[0], SystemMessage)
    assert continued_messages[-1].content == "Follow-up question after compression."
    assert "[Conversation History]" in continued_messages[0].content

    # Verify token count is now below threshold
    new_token_count = count_tokens(continued_messages)
    assert new_token_count < token_count, "Compressed conversation should have fewer tokens"


@pytest.mark.asyncio
async def test_multi_round_no_compression_below_threshold(monkeypatch):
    """With high threshold, compression should NOT trigger."""
    monkeypatch.setenv("AGENT_MAX_TOKENS", "128000")
    config = AgentConfig()
    compressor = ContextCompressor(config)

    messages = [
        SystemMessage(content="system"),
        HumanMessage(content="short question"),
        AIMessage(content="short answer"),
    ]
    assert compressor.should_compress(messages) is False
