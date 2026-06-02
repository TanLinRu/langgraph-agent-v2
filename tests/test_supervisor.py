"""Tests for CustomSupervisor — plan parsing, code extraction, and mock flows."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
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
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        text = "## Plan\n- coder: write hello world\n- researcher: search for files"
        results = []
        for m in _PLAN_RE.finditer(text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        assert len(results) == 2
        assert results[0] == {"agent": "coder", "task": "write hello world"}
        assert results[1] == {"agent": "researcher", "task": "search for files"}

    def test_bold_agent_name(self):
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        text = "- **coder**: write code\n- **analyst**: analyze data"
        results = []
        for m in _PLAN_RE.finditer(text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        assert len(results) == 2
        assert results[0]["agent"] == "coder"
        assert results[1]["agent"] == "analyst"

    def test_chinese_colon(self):
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        text = "- coder：写代码\n- researcher：搜索文件"
        results = []
        for m in _PLAN_RE.finditer(text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        assert len(results) == 2
        assert results[0]["agent"] == "coder"
        assert results[1]["agent"] == "researcher"

    def test_single_agent(self):
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        text = "- direct: print hello"
        results = []
        for m in _PLAN_RE.finditer(text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        assert len(results) == 1
        assert results[0] == {"agent": "direct", "task": "print hello"}

    def test_empty_plan(self):
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        def parse(text):
            results = []
            for m in _PLAN_RE.finditer(text):
                agent_name = m.group(1).lower().strip("*")
                task = m.group(2).strip()
                if agent_name in valid_agents:
                    results.append({"agent": agent_name, "task": task})
            return results

        assert parse("") == []
        assert parse("no plan here") == []

    def test_extra_text_ignored(self):
        import re
        _PLAN_RE = re.compile(r"^\s*-?\s*\**\s*(\w+)\s*\**\s*[:：]\s*(.+)", re.MULTILINE)
        valid_agents = {"coder", "researcher", "analyst", "direct", "opencode", "claude-agent"}

        text = "I will now create a plan:\n## Plan\n- coder: do stuff\nThat's my plan!"
        results = []
        for m in _PLAN_RE.finditer(text):
            agent_name = m.group(1).lower().strip("*")
            task = m.group(2).strip()
            if agent_name in valid_agents:
                results.append({"agent": agent_name, "task": task})
        assert len(results) == 1
        assert results[0]["agent"] == "coder"


# ── Code Extraction ─────────────────────────────────────────────


class TestExtractCode:
    def test_fenced_block(self):
        import re
        def _extract_code(text):
            m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
            if m:
                return m.group(1).strip()
            m = re.search(r"`([^`]+)`", text)
            if m:
                return m.group(1).strip()
            return text.strip()

        text = "Here is the code:\n```python\nprint('hello')\n```"
        assert _extract_code(text) == "print('hello')"

    def test_inline_backticks(self):
        import re
        def _extract_code(text):
            m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
            if m:
                return m.group(1).strip()
            m = re.search(r"`([^`]+)`", text)
            if m:
                return m.group(1).strip()
            return text.strip()

        text = "Run `print('hello')` now"
        assert _extract_code(text) == "print('hello')"

    def test_plain_text(self):
        import re
        def _extract_code(text):
            m = re.search(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
            if m:
                return m.group(1).strip()
            m = re.search(r"`([^`]+)`", text)
            if m:
                return m.group(1).strip()
            return text.strip()

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

                from src.agent.config import AgentConfig
                from src.agent.supervisor import CustomSupervisor

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                # Supervisor now uses config_manager, agents built from JSON config
                assert isinstance(supervisor.agents, dict)
                assert len(supervisor.agents) > 0


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

                from src.agent.config import AgentConfig
                from src.agent.supervisor import CustomSupervisor

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

                from src.agent.config import AgentConfig
                from src.agent.supervisor import CustomSupervisor

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
                assert "message" in types
                assert "metrics" in types
                assert "done" in types
                # Direct-answer shortcut skips plan/summary events
                assert "plan" not in types
                assert "summary" not in types

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

                from src.agent.config import AgentConfig
                from src.agent.supervisor import CustomSupervisor

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

    @pytest.mark.asyncio
    async def test_run_acp_agent_dispatch(self):
        """Supervisor dispatches to an ACP agent (opencode) and streams events."""
        with patch("src.agent.supervisor.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(return_value=_mock_model_stream([
                _make_chunk(content="- opencode: initialize opencode agent"),
            ]))
            mock_resolve.return_value = mock_model

            with patch("src.agent.acp_agent.get_acp_agent") as mock_get_acp:
                mock_acp = AsyncMock()

                async def _mock_acp_run(task, context=""):
                    yield {"type": "thinking", "data": "analyzing project..."}
                    yield {"type": "message", "data": "OpenCode agent initialized"}
                    yield {"type": "thinking_done", "agent_name": "opencode"}

                mock_acp.run = _mock_acp_run
                mock_get_acp.return_value = mock_acp

                from src.agent.config import AgentConfig
                from src.agent.supervisor import CustomSupervisor

                config = AgentConfig()
                supervisor = CustomSupervisor(config)

                events = []
                async for event in supervisor.run("initialize opencode"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "plan" in types
                assert "task_update" in types  # supervisor dispatches opencode as task_update
                assert "message" in types
                assert "done" in types
                # The opencode agent_name should be set on ACP events
                acp_events = [e for e in events if e.get("agent_name") == "opencode"]
                assert len(acp_events) >= 3  # thinking + message + thinking_done
                acp_types = [e["type"] for e in acp_events]
                assert "thinking" in acp_types
                assert "message" in acp_types
                assert "thinking_done" in acp_types

                # Verify the ACP thinking content is preserved
                acp_thinking = [e for e in acp_events if e["type"] == "thinking"]
                assert len(acp_thinking) >= 1
                assert acp_thinking[0]["data"] == "analyzing project..."

                # Verify ACP agent was created with correct cli_id
                mock_get_acp.assert_called_once_with("opencode")
