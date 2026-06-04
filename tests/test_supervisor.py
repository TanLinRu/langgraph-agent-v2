"""Tests for StateGraph-based Orchestrator — plan parsing, events, node functions."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessageChunk

# ── Helpers ─────────────────────────────────────────────────────


def _make_chunk(content: str | None = None, reasoning: str | None = None):
    """Create a mock AIMessageChunk."""
    chunk = MagicMock(spec=AIMessageChunk)
    chunk.content = content or ""
    chunk.additional_kwargs = {}
    if reasoning:
        chunk.additional_kwargs["reasoning_content"] = reasoning
    return chunk


async def _mock_model_stream(chunks):
    for chunk in chunks:
        yield chunk


# ── Plan Parsing ────────────────────────────────────────────────


class TestParsePlan:
    def test_basic_plan(self):
        from src.agent.orchestrator.core import Orchestrator
        steps = Orchestrator._parse_plan(
            "## Plan\n- coder: write hello world\n- researcher: search for files"
        )
        assert len(steps) == 2
        assert steps[0] == {"agent": "coder", "task": "write hello world"}
        assert steps[1] == {"agent": "researcher", "task": "search for files"}

    def test_bold_agent_name(self):
        from src.agent.orchestrator.core import Orchestrator
        steps = Orchestrator._parse_plan("- **coder**: write code\n- **analyst**: analyze data")
        assert len(steps) == 2
        assert steps[0]["agent"] == "coder"
        assert steps[1]["agent"] == "analyst"

    def test_chinese_colon(self):
        from src.agent.orchestrator.core import Orchestrator
        steps = Orchestrator._parse_plan("- coder：写代码\n- researcher：搜索文件")
        assert len(steps) == 2
        assert steps[0]["agent"] == "coder"
        assert steps[1]["agent"] == "researcher"

    def test_single_agent(self):
        from src.agent.orchestrator.core import Orchestrator
        steps = Orchestrator._parse_plan("- direct: print hello")
        assert len(steps) == 1
        assert steps[0] == {"agent": "direct", "task": "print hello"}

    def test_empty_plan(self):
        from src.agent.orchestrator.core import Orchestrator
        assert Orchestrator._parse_plan("") == []
        assert Orchestrator._parse_plan("no plan here") == []


# ── Planner helpers ─────────────────────────────────────────────


class TestPlannerHelpers:
    def test_build_agent_descriptions(self):
        with patch("src.agent.orchestrator.planner.get_config_manager") as mock_cm:
            mock_cm.return_value.get_agents.return_value = {
                "coder": {"desc": "Writes code", "enabled": True},
                "researcher": {"desc": "Finds info", "enabled": True},
                "direct": {"desc": "Direct reply", "enabled": True},
            }
            from src.agent.orchestrator.planner import build_agent_descriptions
            desc = build_agent_descriptions()
            assert "**coder**" in desc
            assert "**researcher**" in desc
            assert "Writes code" in desc

    def test_convert_history(self):
        from src.agent.orchestrator.planner import _convert_history
        history = [
            {"role": "human", "content": "hello"},
            {"role": "assistant", "content": "hi there", "tool_calls": [{"name": "search", "args": {"q": "test"}}]},
        ]
        converted = _convert_history(history)
        assert len(converted) == 2
        assert converted[0] == {"role": "user", "content": "hello"}
        assert "[Tool calls: search" in converted[1]["content"]


# ── Orchestrator Init ───────────────────────────────────────────


class TestOrchestratorInit:
    def test_init_with_mock_model(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = MagicMock()
            mock_resolve.return_value = mock_model

            from src.agent.config import AgentConfig
            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)
            assert isinstance(orch.sub_agents, dict)
            assert "direct" in orch.sub_agents


# ── Orchestrator Run ────────────────────────────────────────────


class TestOrchestratorRun:
    @pytest.mark.asyncio
    async def test_run_produces_plan_audit_metrics_done(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(reasoning="thinking..."),
                    _make_chunk(content="- coder: write hello"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="All tasks completed successfully."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "hello world written"

                from src.agent.config import AgentConfig
                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("write hello world"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "thinking_start" in types
                assert "plan" in types
                assert "task_update" in types
                assert "message" in types
                assert "audit_summary" in types
                assert "metrics" in types
                assert "done" in types

    @pytest.mark.asyncio
    async def test_events_in_correct_order(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(content="- coder: implement"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="Audit OK."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "implemented"

                from src.agent.config import AgentConfig
                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("implement feature"):
                    events.append(event)

                types = [e["type"] for e in events]
                plan_idx = types.index("plan")
                audit_idx = types.index("audit_summary")
                done_idx = types.index("done")
                assert plan_idx < audit_idx
                assert audit_idx < done_idx

    @pytest.mark.asyncio
    async def test_execute_node_retries_on_error(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(content="- coder: implement"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="Audit OK."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.side_effect = [RuntimeError("fail"), "retry success"]

                from src.agent.config import AgentConfig
                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("implement"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "task_update" in types
                # Should still complete via review node fallback
                assert "done" in types

    @pytest.mark.asyncio
    async def test_execute_node_skips_unknown_agent(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(content="- unknown_agent: do stuff"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="No results to audit."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            from src.agent.config import AgentConfig
            from src.agent.orchestrator import Orchestrator

            config = AgentConfig()
            orch = Orchestrator(config)

            events = []
            async for event in orch.run("do stuff"):
                events.append(event)

            types = [e["type"] for e in events]
            assert "plan" in types
            assert "audit_summary" in types
            assert "done" in types

    @pytest.mark.asyncio
    async def test_audit_summary_contains_results(self):
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(content="- coder: write code"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="Audit: code looks good."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.SubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "def foo(): pass"

                from src.agent.config import AgentConfig
                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("write code"):
                    events.append(event)

                audit_events = [e for e in events if e["type"] == "audit_summary"]
                assert len(audit_events) >= 1
                assert "Audit:" in audit_events[0].get("data", "")

    @pytest.mark.asyncio
    async def test_run_acp_agent_dispatch(self):
        """Orchestrator dispatches to an ACP agent and streams events."""
        with patch("src.agent.models.resolve_model") as mock_resolve:
            mock_model = AsyncMock()
            mock_model.astream = MagicMock(side_effect=[
                _mock_model_stream([
                    _make_chunk(content="- opencode: init project"),
                ]),
                _mock_model_stream([
                    _make_chunk(content="ACP agent audit OK."),
                ]),
            ])
            mock_resolve.return_value = mock_model

            with patch("src.agent.orchestrator.core.ACPSubAgentTool._arun") as mock_tool:
                mock_tool.return_value = "project initialized"

                from src.agent.config import AgentConfig
                from src.agent.orchestrator import Orchestrator

                config = AgentConfig()
                orch = Orchestrator(config)

                events = []
                async for event in orch.run("init project"):
                    events.append(event)

                types = [e["type"] for e in events]
                assert "plan" in types
                assert "task_update" in types
                assert "audit_summary" in types
                assert "done" in types
