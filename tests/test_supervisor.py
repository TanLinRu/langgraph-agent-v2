"""Tests for CustomSupervisor — plan parsing, code extraction, and mock flows."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessageChunk


# ── Helpers ─────────────────────────────────────────────────────


def _make_chunk(content=None, reasoning=None):
    """Create a mock AIMessageChunk simulating streaming LLM output."""
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ""
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk


async def _mock_model_stream(chunks):
    """Simulate model.astream() returning a sequence of chunks."""
    for chunk in chunks:
        yield chunk


async def _mock_agent_stream_events(events):
    """Simulate agent_graph.astream_events() returning a sequence of events."""
    for event in events:
        yield event


# ── Plan Parsing ────────────────────────────────────────────────


class TestParsePlan:
    def test_basic_plan(self):
        from src.agent.supervisor import _parse_plan

        text = "## Plan\n- coder: write hello world\n- researcher: search for files"
        result = _parse_plan(text)
        assert len(result) == 2
        assert result[0] == {"agent": "coder", "task": "write hello world"}
        assert result[1] == {"agent": "researcher", "task": "search for files"}

    def test_bold_agent_name(self):
        from src.agent.supervisor import _parse_plan

        text = "- **coder**: write code\n- **analyst**: analyze data"
        result = _parse_plan(text)
        assert len(result) == 2
        assert result[0]["agent"] == "coder"
        assert result[1]["agent"] == "analyst"

    def test_chinese_colon(self):
        from src.agent.supervisor import _parse_plan

        text = "- coder：写代码\n- researcher：搜索文件"
        result = _parse_plan(text)
        assert len(result) == 2
        assert result[0]["agent"] == "coder"
        assert result[1]["agent"] == "researcher"

    def test_single_agent(self):
        from src.agent.supervisor import _parse_plan

        text = "- direct: print hello"
        result = _parse_plan(text)
        assert len(result) == 1
        assert result[0] == {"agent": "direct", "task": "print hello"}

    def test_empty_plan(self):
        from src.agent.supervisor import _parse_plan

        assert _parse_plan("") == []
        assert _parse_plan("no plan here") == []

    def test_extra_text_ignored(self):
        from src.agent.supervisor import _parse_plan

        text = "I will now create a plan:\n## Plan\n- coder: do stuff\nThat's my plan!"
        result = _parse_plan(text)
        assert len(result) == 1
        assert result[0]["agent"] == "coder"


# ── Code Extraction ─────────────────────────────────────────────


class TestExtractCode:
    def test_fenced_block(self):
        from src.agent.supervisor import _extract_code

        text = "Here is the code:\n```python\nprint('hello')\n```"
        assert _extract_code(text) == "print('hello')"

    def test_inline_backticks(self):
        from src.agent.supervisor import _extract_code

        text = "Run `print('hello')` now"
        assert _extract_code(text) == "print('hello')"

    def test_plain_text(self):
        from src.agent.supervisor import _extract_code

        text = "print('hello')"
        assert _extract_code(text) == "print('hello')"


# ── CustomSupervisor Init ───────────────────────────────────────


class TestCustomSupervisorInit:
    def test_init_with_mock_model(self):
        with patch("src.agent.supervisor.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            with patch("src.agent.supervisor.create_agent") as mock_create:
                mock_create.return_value = MagicMock()

                from src.agent.supervisor import CustomSupervisor
                from src.agent.config import AgentConfig

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                assert supervisor.model == mock_model
                assert "coder" in supervisor.agents
                assert "researcher" in supervisor.agents
                assert "analyst" in supervisor.agents


# ── Supervisor Run ──────────────────────────────────────────────


class TestSupervisorRun:
    @pytest.mark.asyncio
    async def test_run_single_agent(self):
        with patch("src.agent.supervisor.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(return_value=_mock_model_stream([
                _make_chunk(reasoning="I need to think..."),
                _make_chunk(content="- coder: write hello world"),
            ]))
            mock_resolve.return_value = mock_model

            with patch("src.agent.supervisor.create_agent") as mock_create:
                mock_agent = AsyncMock()
                mock_agent.astream_events = MagicMock(return_value=_mock_agent_stream_events([
                    {"event": "on_chat_model_stream", "data": {"chunk": _make_chunk(content="hello world")}},
                ]))
                mock_create.return_value = mock_agent

                from src.agent.supervisor import CustomSupervisor
                from src.agent.config import AgentConfig

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                events = []
                async for event in supervisor.run("test task"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "thinking_start" in types
                assert "thinking" in types
                assert "thinking_done" in types
                assert "plan" in types
                assert "message" in types
                assert "done" in types

    @pytest.mark.asyncio
    async def test_run_direct_agent(self):
        with patch("src.agent.supervisor.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(return_value=_mock_model_stream([
                _make_chunk(content="- direct: print hello"),
            ]))
            mock_resolve.return_value = mock_model

            with patch("src.agent.supervisor.create_agent") as mock_create:
                mock_create.return_value = MagicMock()

                from src.agent.supervisor import CustomSupervisor
                from src.agent.config import AgentConfig

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                # Mock execute_code tool
                mock_tool = AsyncMock()
                mock_tool.ainvoke.return_value = "hello"
                supervisor.tool_map["execute_code"] = mock_tool

                events = []
                async for event in supervisor.run("print hello"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "plan" in types
                assert "message" in types
                assert "done" in types

    @pytest.mark.asyncio
    async def test_run_no_plan_fallback(self):
        with patch("src.agent.supervisor.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(return_value=_mock_model_stream([
                _make_chunk(content="I can answer directly: 42"),
            ]))
            mock_resolve.return_value = mock_model

            with patch("src.agent.supervisor.create_agent") as mock_create:
                mock_create.return_value = MagicMock()

                from src.agent.supervisor import CustomSupervisor
                from src.agent.config import AgentConfig

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                events = []
                async for event in supervisor.run("what is 42"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "message" in types
                assert "done" in types
                # No plan event since no valid plan was parsed
                assert "plan" not in types
