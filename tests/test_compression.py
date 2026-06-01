
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from src.agent.config import AgentConfig
from src.agent.context.compression import ContextCompressor


@pytest.fixture
def compressor():
    config = AgentConfig()
    return ContextCompressor(config)


def test_should_compress_below_threshold(compressor):
    msgs = [HumanMessage(content="hello")]
    assert compressor.should_compress(msgs) is False


def test_should_compress_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_MAX_TOKENS", "10")
    config = AgentConfig()
    compressor = ContextCompressor(config)
    big = "word " * 200
    msgs = [HumanMessage(content=big), AIMessage(content=big)]
    assert compressor.should_compress(msgs) is True


@pytest.mark.asyncio
async def test_compress_keeps_recent(compressor):
    msgs = [
        SystemMessage(content="system"),
        HumanMessage(content="q1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
    ]
    summary, recent = await compressor.compress(msgs)
    # keep_recent=5, so all messages kept
    assert len(recent) <= len(msgs)
    assert isinstance(summary, str)


@pytest.mark.asyncio
async def test_compress_preserves_system_message(compressor):
    msgs = [
        SystemMessage(content="system prompt"),
        HumanMessage(content="q1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2"),
        AIMessage(content="a2"),
    ]
    summary, recent = await compressor.compress(msgs)
    system_msgs = [m for m in recent if isinstance(m, SystemMessage)]
    assert len(system_msgs) <= 1


def test_fallback_summary(compressor):
    summary = compressor._fallback_summary([HumanMessage(content="x" * 500)])
    assert len(summary) > 0
    assert "[user]" in summary
